import asyncio
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid02
from pywebpush import WebPushException
from sqlalchemy import select

from app.core.config import Settings, assert_production_safe, settings
from app.db.models import Notification, NotificationPref, PushSubscription
from app.make_vapid import b64url, make
from app.realtime import client as redis_client
from app.services import delivery
from app.services import push as push_svc
from app.services.notify import KINDS, notify
from app.services.outbox import flush as flush_outbox
from tests.helpers import make_league
from tests.ws_helpers import connect, recv, token_of


def keys():
    pub = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"p256dh": b64url(pub), "auth": b64url(secrets.token_bytes(16))}


FCM = "https://fcm.googleapis.com/fcm/send/"
MOZ = "https://updates.push.services.mozilla.com/wpush/v2/"
APPLE = "https://web.push.apple.com/"


def sub_body(endpoint=None):
    return {"endpoint": endpoint or FCM + secrets.token_urlsafe(40), "keys": keys()}


@pytest.fixture(autouse=True)
def push_on(monkeypatch):
    pub, priv = make()
    monkeypatch.setattr(settings, "push_enabled", True)
    monkeypatch.setattr(settings, "vapid_public_key", pub)
    monkeypatch.setattr(settings, "vapid_private_key", priv)


class Sender:
    """Stands in for the push services: records every push and can answer with a refusal."""

    def __init__(self):
        self.sent: list[tuple[str, dict]] = []
        self.fail: dict[str, int] = {}  # endpoint -> HTTP status to refuse with

    def __call__(self, sub, payload):
        status = self.fail.get(sub.endpoint)
        if status:
            raise WebPushException("refused", response=type("R", (), {"status_code": status})())
        self.sent.append((sub.endpoint, payload))
        return 201


@pytest.fixture
def sender(monkeypatch):
    s = Sender()
    monkeypatch.setattr(push_svc, "send_one", s)
    return s


@pytest.fixture
def inline_jobs(monkeypatch, engine):
    """Run queued jobs straight away instead of through a worker."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    calls = []

    async def run(job, *args):
        calls.append((job, args))
        assert job == "send_push"
        await push_svc.send_push({"session_factory": async_sessionmaker(engine, expire_on_commit=False)}, *args)

    monkeypatch.setattr(delivery, "enqueue", run)
    return calls


async def add_device(user, endpoint=None):
    r = await user.req("POST", "/me/push/subscriptions", json=sub_body(endpoint))
    assert r.status_code == 201, r.text
    return r.json()


async def announce(db, user_id, kind="result", title="Match 1 has a result", body="Pink won", link="/matches/1", key="k1"):
    await notify(db, [user_id], kind, title, body, {"link": link}, key)
    await db.commit()
    await flush_outbox(db)


# ---------- endpoint and key safety ----------
@pytest.mark.parametrize("endpoint", [FCM + "abc", MOZ + "abc", APPLE + "abc", "https://wns2-par02p.notify.windows.com/w/?token=x",
                                      "https://fcm.googleapis.com:443/fcm/send/abc", "https://web.push.apple.com/Q1..."])
def test_real_push_services_are_accepted(endpoint):
    assert push_svc.endpoint_problem(endpoint) is None


@pytest.mark.parametrize("endpoint", [
    "http://fcm.googleapis.com/fcm/send/abc",  # not https
    "https://127.0.0.1/x", "https://10.0.0.5/x", "https://[::1]/x", "https://169.254.169.254/latest/meta-data",
    "https://localhost/x", "https://internal.corp/x", "https://example.com/x",
    "https://fcm.googleapis.com.evil.io/x", "https://evilfcm.googleapis.com.attacker.net/x",
    "https://notfcm.googleapis.com/x", "https://push.apple.com.evil.test/x", "https://xpush.apple.com/x",
    "https://user:pw@fcm.googleapis.com/x", "https://fcm.googleapis.com:8443/x", "https://fcm.googleapis.com/x#frag",
    "ftp://fcm.googleapis.com/x", "javascript:alert(1)", "//fcm.googleapis.com/x", "", "https://", "https://" + "a" * 1100,
    "https://fcm.googleapis.com\\@evil.io/x",
])
def test_everything_else_is_refused(endpoint):
    assert push_svc.endpoint_problem(endpoint)


def test_key_checks():
    k = keys()
    assert push_svc.keys_problem(k["p256dh"], k["auth"]) is None
    assert push_svc.keys_problem("short", k["auth"]) and push_svc.keys_problem(k["p256dh"], "x")
    assert push_svc.keys_problem(k["p256dh"], "not base64url!!!!!!!!!!")
    assert push_svc.keys_problem("$" * 87, k["auth"])


def test_links_never_leave_the_site():
    assert push_svc.safe_link("/matches/5") == "/matches/5"
    for bad in ("https://evil.test/x", "//evil.test/x", "javascript:alert(1)", "/\\evil", "/x\ny", "", None, 5, "/" + "a" * 300):
        assert push_svc.safe_link(bad) == "/notifications", bad


def test_every_kind_makes_a_small_payload_with_nothing_else_in_it():
    for kind in KINDS:
        n = Notification(id=7, user_id=1, kind=kind, title="T" * 500, body="B" * 500, data={"link": "https://evil.test", "digits": [1, 2, 3, 4, 5, 6], "match_id": 9})
        p = push_svc.payload_for(n)
        assert set(p) == {"id", "kind", "title", "body", "link"}, kind
        assert len(p["title"]) == 100 and len(p["body"]) == 200 and p["link"] == "/notifications"
        assert "digits" not in json.dumps(p)


def test_push_defaults():
    assert all(push_svc.push_default(k) for k in KINDS if k not in {"wicket", "over_complete", "mention", "reply"})
    assert not any(push_svc.push_default(k) for k in ("wicket", "over_complete", "mention", "reply"))
    assert {"your_over", "toss_ready", "result", "fixtures_published", "adjustment", "approval"} <= {k for k in KINDS if push_svc.push_default(k)}


# ---------- registering devices ----------
async def test_push_key_endpoint(client, monkeypatch):
    r = (await client.get("/push/key")).json()
    assert r["enabled"] is True and r["key"] == settings.vapid_public_key
    monkeypatch.setattr(settings, "push_enabled", False)
    assert (await client.get("/push/key")).json() == {"enabled": False, "key": None}


async def test_registering_a_device(make_user, client, monkeypatch):
    u = await make_user("P")
    assert (await client.post("/me/push/subscriptions", json=sub_body())).status_code == 401
    body = sub_body()
    r = await client.post("/me/push/subscriptions", json=body, headers={**u.h, "User-Agent": "Mozilla/5.0 Test"})
    assert r.status_code == 201 and r.json()["user_agent"] == "Mozilla/5.0 Test" and r.json()["service"] == "fcm.googleapis.com" and r.json()["failures"] == 0
    assert "endpoint" not in r.json() and "p256dh" not in r.json()  # the address and keys never come back out
    again = await u.req("POST", "/me/push/subscriptions", json=body)  # the same browser asking twice
    assert again.status_code == 201 and again.json()["id"] == r.json()["id"]
    assert len((await u.req("GET", "/me/push/subscriptions")).json()) == 1
    monkeypatch.setattr(settings, "push_enabled", False)
    off = await u.req("POST", "/me/push/subscriptions", json=sub_body())
    assert off.status_code == 409


async def test_bad_registrations_are_refused(make_user):
    u = await make_user("P")
    for endpoint in ("http://fcm.googleapis.com/x", "https://169.254.169.254/x", "https://evil.example/x", "https://fcm.googleapis.com.evil.io/x"):
        r = await u.req("POST", "/me/push/subscriptions", json=sub_body(endpoint))
        assert r.status_code == 422, endpoint
    r = await u.req("POST", "/me/push/subscriptions", json={"endpoint": FCM + "x", "keys": {"p256dh": "bad", "auth": "bad"}})
    assert r.status_code == 422 and r.json()["detail"] == "Invalid push keys"
    assert (await u.req("POST", "/me/push/subscriptions", json={"endpoint": FCM + "x"})).status_code == 422
    assert (await u.req("GET", "/me/push/subscriptions")).json() == []


async def test_device_limit_and_removal(make_user, monkeypatch):
    monkeypatch.setattr(settings, "push_max_devices_per_user", 2)
    u, other = await make_user("P"), await make_user("Q")
    first = await add_device(u)
    second_endpoint = FCM + secrets.token_urlsafe(30)
    await add_device(u, second_endpoint)
    assert (await u.req("POST", "/me/push/subscriptions", json=sub_body())).status_code == 409  # the third
    assert (await u.req("POST", "/me/push/subscriptions", json=sub_body(second_endpoint))).status_code == 201  # known one is fine
    # nobody can remove someone else's device
    assert (await other.req("DELETE", f"/me/push/subscriptions/{first['id']}")).status_code == 404
    await other.req("POST", "/me/push/subscriptions/remove", json={"endpoint": second_endpoint})
    assert len((await u.req("GET", "/me/push/subscriptions")).json()) == 2
    assert (await u.req("DELETE", f"/me/push/subscriptions/{first['id']}")).status_code == 204
    assert (await u.req("POST", "/me/push/subscriptions/remove", json={"endpoint": second_endpoint})).status_code == 204
    assert (await u.req("POST", "/me/push/subscriptions/remove", json={"endpoint": second_endpoint})).status_code == 204  # already gone
    assert (await u.req("GET", "/me/push/subscriptions")).json() == []


async def test_a_shared_device_belongs_to_whoever_is_signed_in(make_user, db):
    a, b = await make_user("A"), await make_user("B")
    body = sub_body()
    await a.req("POST", "/me/push/subscriptions", json=body)
    await b.req("POST", "/me/push/subscriptions", json=body)
    assert (await a.req("GET", "/me/push/subscriptions")).json() == []
    assert len((await b.req("GET", "/me/push/subscriptions")).json()) == 1
    assert len(list(await db.scalars(select(PushSubscription)))) == 1


# ---------- who is pushed what ----------
async def test_important_kinds_are_pushed_and_noisy_ones_are_not(make_user, db, sender, inline_jobs):
    u = await make_user("P")
    await add_device(u)
    await announce(db, u.id, "result", "Match 1 has a result", "Pink won", "/matches/1", "a")
    await announce(db, u.id, "wicket", "Wicket", "Out!", "/matches/1", "b")
    await announce(db, u.id, "mention", "Someone mentioned you", "hi", "/chat", "c")
    assert [p["kind"] for _, p in sender.sent] == ["result"]
    p = sender.sent[0][1]
    assert p["title"] == "Match 1 has a result" and p["body"] == "Pink won" and p["link"] == "/matches/1"
    assert [c[0] for c in inline_jobs] == ["send_push"] * 3  # all were queued; the job decides


async def test_personal_choices_override_the_defaults(make_user, db, sender, inline_jobs):
    u = await make_user("P")
    await add_device(u)
    assert (await u.req("PUT", "/notifications/prefs", json={"kind": "wicket", "push": True})).status_code == 204
    assert (await u.req("PUT", "/notifications/prefs", json={"kind": "result", "push": False})).status_code == 204
    await announce(db, u.id, "wicket", key="a")
    await announce(db, u.id, "result", key="b")
    assert [p["kind"] for _, p in sender.sent] == ["wicket"]
    prefs = {p["kind"]: p for p in (await u.req("GET", "/notifications/prefs")).json()}
    assert prefs["wicket"]["push"] is True and prefs["result"]["push"] is False and prefs["your_over"]["push"] is True
    assert prefs["mention"]["push"] is False and prefs["wicket"]["in_app"] is True  # in-app choice untouched
    # turning a kind off in the app stops the notification itself (and so the push)
    await u.req("PUT", "/notifications/prefs", json={"kind": "your_over", "in_app": False})
    sender.sent.clear()
    await announce(db, u.id, "your_over", key="c")
    assert sender.sent == []
    prefs = {p["kind"]: p for p in (await u.req("GET", "/notifications/prefs")).json()}
    assert prefs["your_over"] == {"kind": "your_over", "label": KINDS["your_over"][0], "in_app": False, "push": True}
    assert (await u.req("PUT", "/notifications/prefs", json={"kind": "result"})).status_code == 422
    assert (await u.req("PUT", "/notifications/prefs", json={"kind": "nope", "push": True})).status_code == 422
    rows = list(await db.scalars(select(NotificationPref).where(NotificationPref.user_id == u.id)))
    assert len(rows) == 3


async def test_nobody_is_pushed_while_looking_at_the_app(make_user, db, sender, inline_jobs):
    u = await make_user("P")
    await add_device(u)
    await redis_client().set(f"fg:{u.id}", "1", ex=45)
    await announce(db, u.id, key="a")
    assert sender.sent == []
    await redis_client().delete(f"fg:{u.id}")
    await announce(db, u.id, key="b")
    assert len(sender.sent) == 1
    n = list(await db.scalars(select(Notification).where(Notification.user_id == u.id)))
    assert len(n) == 2  # the in-app notification exists either way


async def test_every_device_gets_it_and_people_without_devices_cost_nothing(make_user, db, sender, inline_jobs):
    a, b, none = await make_user("A"), await make_user("B"), await make_user("N")
    await add_device(a)
    await add_device(a)
    await add_device(b)
    await notify(db, [a.id, b.id, none.id], "fixtures_published", "New fixtures", "see them", {"link": "/fixtures"}, "k")
    await db.commit()
    await flush_outbox(db)
    assert len(sender.sent) == 3
    assert {p["link"] for _, p in sender.sent} == {"/fixtures"}


async def test_nothing_is_queued_when_push_is_off(make_user, db, sender, inline_jobs, monkeypatch):
    u = await make_user("P")
    await add_device(u)
    monkeypatch.setattr(settings, "push_enabled", False)
    await announce(db, u.id, key="a")
    assert inline_jobs == [] and sender.sent == []


async def test_a_queueing_failure_never_breaks_the_request(make_user, db, monkeypatch):
    async def boom(*_a):
        raise RuntimeError("redis is down")

    monkeypatch.setattr(delivery, "enqueue", boom)
    u = await make_user("P")
    await announce(db, u.id, key="a")  # no exception
    assert len(list(await db.scalars(select(Notification)))) == 1


# ---------- looking after devices ----------
async def test_gone_devices_are_forgotten_and_others_still_get_it(make_user, db, sender, inline_jobs):
    u = await make_user("P")
    dead, ok = FCM + "dead", MOZ + "ok"
    await add_device(u, dead)
    await add_device(u, ok)
    sender.fail[dead] = 410
    await announce(db, u.id, key="a")
    assert [e for e, _ in sender.sent] == [ok]
    db.expire_all()
    left = list(await db.scalars(select(PushSubscription.endpoint)))
    assert left == [ok]
    row = await db.scalar(select(PushSubscription))
    assert row.last_success_at is not None and row.failures == 0


async def test_a_flaky_device_is_dropped_after_repeated_failures(make_user, db, sender, inline_jobs):
    u = await make_user("P")
    flaky = FCM + "flaky"
    await add_device(u, flaky)
    sender.fail[flaky] = 500
    for i in range(push_svc.MAX_FAILURES - 1):
        await announce(db, u.id, key=f"a{i}")
        db.expire_all()
        assert (await db.scalar(select(PushSubscription.failures))) == i + 1
    sender.fail.clear()  # it recovers: the count resets
    await announce(db, u.id, key="ok")
    db.expire_all()
    assert (await db.scalar(select(PushSubscription.failures))) == 0
    sender.fail[flaky] = 500
    for i in range(push_svc.MAX_FAILURES):
        await announce(db, u.id, key=f"b{i}")
    db.expire_all()
    assert await db.scalar(select(PushSubscription.id)) is None


async def test_one_crashing_device_does_not_stop_the_rest(make_user, db, monkeypatch, inline_jobs):
    u = await make_user("P")
    await add_device(u, FCM + "boom")
    await add_device(u, MOZ + "fine")
    got = []

    def send(sub, payload):
        if sub.endpoint.endswith("boom"):
            raise OSError("network down")
        got.append(sub.endpoint)

    monkeypatch.setattr(push_svc, "send_one", send)
    await announce(db, u.id, key="a")
    assert got == [MOZ + "fine"]
    db.expire_all()
    assert sorted((s.endpoint.rsplit("/", 1)[1], s.failures) for s in await db.scalars(select(PushSubscription))) == [("boom", 1), ("fine", 0)]


async def test_test_push_button(make_user, db, sender):
    u = await make_user("P")
    assert (await u.req("POST", "/me/push/test")).status_code == 409  # no device yet
    await add_device(u)
    await add_device(u)
    r = await u.req("POST", "/me/push/test")
    assert r.status_code == 200 and r.json() == {"sent": 2, "removed": 0, "failed": 0}
    assert sender.sent[0][1]["title"] == "FFCL test notification" and sender.sent[0][1]["link"] == "/notifications"
    sender.fail[sender.sent[0][0]] = 410
    assert (await u.req("POST", "/me/push/test")).json() == {"sent": 1, "removed": 1, "failed": 0}
    assert (await db.scalar(select(PushSubscription.id).where(PushSubscription.user_id == u.id))) is not None


async def test_purge_forgets_long_dead_devices(make_user, db, engine):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy.ext.asyncio import async_sessionmaker

    u = await make_user("P")
    old, new = datetime.now(UTC) - timedelta(days=90), datetime.now(UTC)
    rows = [PushSubscription(user_id=u.id, endpoint=FCM + n, p256dh="x" * 87, auth="y" * 22, failures=f, created_at=c, last_success_at=s)
            for n, f, c, s in (("never-worked", 2, old, None), ("stopped", 3, old, old), ("fine-but-failed-once", 1, new, new),
                               ("old-but-fine", 0, old, new), ("new-never-worked", 1, new, None))]
    db.add_all(rows)
    await db.commit()
    n = await push_svc.purge_dead_subscriptions({"session_factory": async_sessionmaker(engine, expire_on_commit=False)})
    assert n == 2
    db.expire_all()
    assert sorted(e.rsplit("/", 1)[1] for e in await db.scalars(select(PushSubscription.endpoint))) == ["fine-but-failed-once", "new-never-worked", "old-but-fine"]


# ---------- sending ----------
async def test_the_sender_signs_with_our_key_and_never_follows_redirects(monkeypatch):
    seen = {}

    class Resp:
        status_code = 201

    def fake_webpush(**kw):
        seen.update(kw)
        return Resp()

    monkeypatch.setattr(push_svc, "webpush", fake_webpush)
    sub = PushSubscription(user_id=1, endpoint=FCM + "abc", p256dh="p" * 87, auth="a" * 22)
    assert push_svc.send_one(sub, {"title": "x"}) == 201
    assert seen["subscription_info"] == {"endpoint": FCM + "abc", "keys": {"p256dh": "p" * 87, "auth": "a" * 22}}
    assert json.loads(seen["data"]) == {"title": "x"} and seen["vapid_private_key"] == settings.vapid_private_key
    assert seen["vapid_claims"] == {"sub": settings.vapid_subject} and seen["ttl"] == push_svc.TTL_SECONDS
    assert isinstance(seen["requests_session"], push_svc.NoRedirectSession)


def test_a_redirect_from_a_push_endpoint_is_not_followed():
    hits: list[str] = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            hits.append(self.path)
            self.send_response(307 if self.path == "/push" else 200)
            self.send_header("Location", "/internal-admin")
            self.end_headers()

        def log_message(self, *_a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        r = push_svc.NoRedirectSession().post(f"http://127.0.0.1:{srv.server_port}/push", data=b"x")
        assert r.status_code == 307 and hits == ["/push"]  # the Location was ignored
    finally:
        srv.shutdown()


def test_generated_vapid_keys_work():
    pub, priv = make()
    v = Vapid02.from_string(priv)
    raw = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    assert b64url(raw) == pub and len(raw) == 65
    claims = v.sign({"sub": "mailto:a@b.test", "aud": "https://fcm.googleapis.com", "exp": 4102444800})
    assert "vapid" in claims["Authorization"].lower() or claims["Authorization"].startswith(("vapid", "WebPush"))


def test_production_refuses_push_without_keys():
    base = {"environment": "production", "jwt_secret": "x" * 40, "auth_rate_limits_enabled": True, "cors_origins": "https://ffcl.example"}
    assert_production_safe(Settings(**base, push_enabled=False))
    assert_production_safe(Settings(**base, push_enabled=True, vapid_public_key="a", vapid_private_key="b"))
    with pytest.raises(RuntimeError, match="VAPID"):
        assert_production_safe(Settings(**base, push_enabled=True))
    with pytest.raises(RuntimeError, match="VAPID"):
        assert_production_safe(Settings(**base, push_enabled=True, vapid_public_key="a"))


# ---------- the "I am looking at the app" heartbeat ----------
async def test_the_notification_socket_reports_whether_the_app_is_in_front(make_user, ws_url):
    u = await make_user("P")
    ws = await connect(f"{ws_url}/ws/me", token_of(u))
    assert (await recv(ws))["type"] == "hello"
    r = redis_client()
    assert not await r.exists(f"fg:{u.id}")
    await ws.send(json.dumps({"type": "fg"}))
    for _ in range(40):
        if await r.exists(f"fg:{u.id}"):
            break
        await asyncio.sleep(0.05)
    assert await r.exists(f"fg:{u.id}") and 0 < await r.ttl(f"fg:{u.id}") <= push_svc.FG_SECONDS
    await ws.send("not json at all")  # ignored, the socket stays up
    await ws.send(json.dumps({"type": "bg"}))
    for _ in range(40):
        if not await r.exists(f"fg:{u.id}"):
            break
        await asyncio.sleep(0.05)
    assert not await r.exists(f"fg:{u.id}")
    await ws.send(json.dumps({"type": "fg"}))
    await asyncio.sleep(0.3)
    await ws.close()
    for _ in range(40):
        if not await r.exists(f"fg:{u.id}"):
            break
        await asyncio.sleep(0.05)
    assert not await r.exists(f"fg:{u.id}")  # closing the page clears it


async def test_a_league_notification_reaches_a_registered_phone(make_user, sender, inline_jobs):
    """End to end: a real league event (an umpire is assigned) becomes a push."""
    lg = await make_league(make_user, n_teams=2, per_team=4, n_umpires=2)
    ump = lg.umpires[0]
    await add_device(ump)
    r = await lg.admin.req("POST", f"/seasons/{lg.sid}/matches", json={"team_a_id": lg.teams[0], "team_b_id": lg.teams[1], "umpire_id": ump.id})
    assert r.status_code == 201
    assert len(sender.sent) == 1
    p = sender.sent[0][1]
    assert p["kind"] == "umpire_assigned" and p["link"].startswith("/matches/") and "digit" not in json.dumps(p).lower()


def test_dry_run_logs_instead_of_sending(monkeypatch, caplog):
    import logging

    monkeypatch.setattr(settings, "push_dry_run", True)
    monkeypatch.setattr(push_svc, "webpush", lambda **_k: pytest.fail("a dry run must not call the push service"))
    sub = PushSubscription(user_id=3, endpoint=FCM + "abc", p256dh="p" * 87, auth="a" * 22)
    with caplog.at_level(logging.WARNING, logger="ffcl.push"):
        assert push_svc.send_one(sub, {"title": "Hello", "link": "/x"}) == 201
    assert "PUSH DRY RUN user=3" in caplog.text and '"title": "Hello"' in caplog.text
