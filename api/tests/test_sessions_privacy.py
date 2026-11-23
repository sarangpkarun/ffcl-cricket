"""Sign-in families and replay detection, the list of devices, socket origins, leaving the league, and the data download."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import websockets
from sqlalchemy import func, select

from app.core.config import Settings, assert_production_safe
from app.db.models import AuditLog, Notification, PushSubscription, Session, User
from tests.helpers import make_league, play_match

PW = "a-long-password"


async def signup(client, n, name="Person"):
    r = await client.post("/auth/register", json={"name": f"{name}{n}", "email": f"s{n}@t.io", "password": PW, "phone": f"+9188{n:08d}"})
    assert r.status_code == 201, r.text
    return r.json()


async def login(client, n, agent):
    r = await client.post("/auth/login", json={"email": f"s{n}@t.io", "password": PW}, headers={"User-Agent": agent})
    assert r.status_code == 200
    return r.json()


def bearer(t):
    return {"Authorization": f"Bearer {t['access_token']}"}


async def age_replaced(db, seconds):
    """Pretend the swap happened `seconds` ago."""
    for s in await db.scalars(select(Session).where(Session.replaced_at.is_not(None))):
        s.replaced_at = datetime.now(UTC) - timedelta(seconds=seconds)
    await db.commit()


# ---------- refresh families ----------
async def test_a_refresh_continues_the_same_sign_in(client, db):
    t = await signup(client, 1)
    r = await client.post("/auth/refresh", json={"refresh_token": t["refresh_token"]})
    assert r.status_code == 200
    rows = list(await db.scalars(select(Session).order_by(Session.id)))
    assert len(rows) == 2 and rows[0].family_id == rows[1].family_id and rows[0].replaced_at is not None and rows[1].replaced_at is None
    assert (await client.get("/me", headers=bearer(r.json()))).status_code == 200


async def test_replaying_a_spent_token_later_signs_the_device_out_and_tells_the_person(client, db):
    t = await signup(client, 1)
    new = (await client.post("/auth/refresh", json={"refresh_token": t["refresh_token"]})).json()
    await age_replaced(db, 60)
    thief = await client.post("/auth/refresh", json={"refresh_token": t["refresh_token"]})
    assert thief.status_code == 401
    # the real owner's newer token and access token are dead too: the whole sign-in ended
    assert (await client.post("/auth/refresh", json={"refresh_token": new["refresh_token"]})).status_code == 401
    assert (await client.get("/me", headers=bearer(new))).status_code == 401
    db.expire_all()
    assert await db.scalar(select(Notification.id).where(Notification.kind == "security"))
    assert await db.scalar(select(AuditLog.id).where(AuditLog.action == "session.replay"))
    # signing in again works
    assert (await client.post("/auth/login", json={"email": "s1@t.io", "password": PW})).status_code == 200


async def test_a_second_tab_racing_the_same_token_is_not_an_attack(client, db):
    t = await signup(client, 1)
    a, b = await asyncio.gather(*(client.post("/auth/refresh", json={"refresh_token": t["refresh_token"]}) for _ in range(2)))
    assert sorted([a.status_code, b.status_code]) == [200, 401]
    winner = a if a.status_code == 200 else b
    assert (await client.get("/me", headers=bearer(winner.json()))).status_code == 200  # nobody was signed out
    assert (await client.post("/auth/refresh", json={"refresh_token": winner.json()["refresh_token"]})).status_code == 200
    assert not await db.scalar(select(AuditLog.id).where(AuditLog.action == "session.replay"))


async def test_a_replay_only_ends_its_own_device(client, db):
    t = await signup(client, 1)
    other = await login(client, 1, "Other phone")
    new = (await client.post("/auth/refresh", json={"refresh_token": t["refresh_token"]})).json()
    await age_replaced(db, 60)
    await client.post("/auth/refresh", json={"refresh_token": t["refresh_token"]})
    assert (await client.get("/me", headers=bearer(new))).status_code == 401
    assert (await client.get("/me", headers=bearer(other))).status_code == 200


async def test_logout_is_a_plain_end_not_a_replay(client, db):
    t = await signup(client, 1)
    await client.post("/auth/logout", json={"refresh_token": t["refresh_token"]}, headers=bearer(t))
    await age_replaced(db, 60)
    assert (await client.post("/auth/refresh", json={"refresh_token": t["refresh_token"]})).status_code == 401
    assert not await db.scalar(select(Notification.id).where(Notification.kind == "security"))


async def test_the_access_token_is_short_lived():
    assert Settings().access_ttl_minutes <= 10


# ---------- the list of devices ----------
async def test_you_can_see_and_end_your_devices(client, db):
    t = await signup(client, 1)
    phone = await login(client, 1, "Pixel 9")
    other = await signup(client, 2)
    rows = (await client.get("/me/sessions", headers=bearer(phone))).json()
    assert len(rows) == 2 and [r["current"] for r in rows].count(True) == 1
    cur = next(r for r in rows if r["current"])
    assert cur["device"] == "Pixel 9"
    first = next(r for r in rows if not r["current"])
    assert (await client.delete(f"/me/sessions/{first['id']}", headers=bearer(phone))).status_code == 204
    assert (await client.get("/me", headers=bearer(t))).status_code == 401  # that device is signed out
    assert (await client.get("/me", headers=bearer(phone))).status_code == 200  # this one stays
    assert len((await client.get("/me/sessions", headers=bearer(phone))).json()) == 1
    # someone else's session id looks like it does not exist
    theirs = (await client.get("/me/sessions", headers=bearer(other))).json()[0]["id"]
    assert (await client.delete(f"/me/sessions/{theirs}", headers=bearer(phone))).status_code == 404
    assert (await client.get("/me", headers=bearer(other))).status_code == 200


# ---------- sockets and origins ----------
async def test_every_socket_refuses_a_page_from_another_site(make_user, ws_url):
    lg = await make_league(make_user, n_teams=2, per_team=2, n_umpires=1)
    mid = (await lg.admin.req("POST", f"/seasons/{lg.sid}/matches", json={"team_a_id": lg.teams[0], "team_b_id": lg.teams[1], "umpire_id": lg.umpires[0].id})).json()["id"]
    urls = [f"{ws_url}/ws/me", f"{ws_url}/ws/matches/{mid}", f"{ws_url}/ws/rooms/1", f"{ws_url}/ws/public/matches/{mid}"]
    for url in urls:
        with pytest.raises(websockets.exceptions.InvalidStatus) as e:
            await websockets.connect(url, origin="https://evil.example")
        assert e.value.response.status_code == 403, url
        ok = await websockets.connect(url, origin="http://localhost:3100")  # our own site gets as far as the sign-in step
        await ok.close()
        none = await websockets.connect(url)  # and so does a client that is not a browser
        await none.close()


def test_production_wants_exact_https_origins():
    base = {"environment": "production", "jwt_secret": "k" * 48}
    assert_production_safe(Settings(**base, cors_origins="https://ffcl.example"))
    for bad in ("*", "", "http://ffcl.example", "https://ffcl.example,*", "http://localhost:3100,http://localhost:3000"):
        with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
            assert_production_safe(Settings(**base, cors_origins=bad))


async def test_cors_answers_only_for_our_sites(client):
    ok = await client.options("/health", headers={"Origin": "http://localhost:3100", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3100"
    bad = await client.options("/health", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers


# ---------- text that hides itself ----------
async def test_names_and_messages_cannot_hide_characters(client, make_user):
    for name in ("Evil" + chr(0x202E) + "name", "Zero" + chr(0x200B) + "width", "Line\nbreak", "Bell" + chr(7)):
        r = await client.post("/auth/register", json={"name": name, "email": "x@t.io", "password": PW, "phone": "+919800000099"})
        assert r.status_code == 422, repr(name)
    p = await make_user("P")
    assert (await p.req("PATCH", "/me", json={"name": "Ok" + chr(0x2066) + "x"})).status_code == 422
    assert (await p.req("PATCH", "/me", json={"name": "Asha Rao"})).status_code == 200
    admin = await make_user("Admin", roles=["tournament_admin"])
    sid = (await admin.req("POST", "/seasons", json={"name": "S", "status": "active"})).json()["id"]
    assert (await admin.req("POST", f"/seasons/{sid}/teams", json={"name": "Pink" + chr(0x202E)})).status_code == 422
    room = (await admin.req("GET", "/chat/home")).json()
    rid = room["rooms"][0]["room_id"] if isinstance(room, dict) and room.get("rooms") else None
    if rid:
        bad = await admin.req("POST", f"/rooms/{rid}/messages", json={"body": "hi" + chr(0x202E) + "there", "client_id": "abcdefgh1"})
        assert bad.status_code == 422
        good = await admin.req("POST", f"/rooms/{rid}/messages", json={"body": "two\nlines are fine", "client_id": "abcdefgh2"})
        assert good.status_code == 201


# ---------- leaving the league ----------
async def test_leaving_keeps_the_leagues_numbers_and_blanks_the_person(make_user, db, client):
    lg = await make_league(make_user, n_teams=4, per_team=3, n_umpires=2)
    a, b, _c, _d = lg.teams
    mid = (await lg.admin.req("POST", f"/seasons/{lg.sid}/matches", json={"team_a_id": a, "team_b_id": b, "umpire_id": lg.umpires[0].id})).json()["id"]
    await play_match(lg, mid, "a")
    await lg.admin.req("PATCH", f"/seasons/{lg.sid}", json={"status": "completed"})
    table_before = (await lg.admin.req("GET", f"/seasons/{lg.sid}/standings")).json()["rows"]
    stats_before = (await lg.admin.req("GET", f"/seasons/{lg.sid}/leaderboards")).json()
    leaver = lg.players[b][1]  # played, is not captain
    await leaver.req("POST", "/push/subscriptions", json={"endpoint": "https://fcm.googleapis.com/fcm/send/x", "keys": {"p256dh": "a" * 87, "auth": "b" * 22}})
    check = (await leaver.req("GET", "/me/delete-check")).json()
    assert check == {"can_delete": True, "blockers": []}
    assert (await leaver.req("POST", "/me/delete", json={"password": "wrong-password"})).status_code == 403
    assert (await leaver.req("POST", "/me/delete", json={"password": "password123"})).status_code == 204
    # they are gone: no sign-in, no access, no personal details
    assert (await leaver.req("GET", "/me")).status_code == 401
    assert (await client.post("/auth/login", json={"email": f"u{leaver.id}@t.io", "password": "password123"})).status_code == 401
    db.expire_all()
    u = await db.get(User, leaver.id)
    assert (u.name, u.phone, u.status) == ("Former player", None, "deleted") and u.email.endswith("@deleted.invalid") and u.deleted_at
    assert await db.scalar(select(func.count()).select_from(PushSubscription).where(PushSubscription.user_id == leaver.id)) == 0
    # and the league did not change
    assert (await lg.admin.req("GET", f"/seasons/{lg.sid}/standings")).json()["rows"] == table_before
    after = (await lg.admin.req("GET", f"/seasons/{lg.sid}/leaderboards")).json()
    def figures(board):  # every row's rank, player id, and numbers: everything except the name
        return [(c["key"], sorted((r["rank"], (r["player"] or {}).get("id") or 0, r["value"]) for r in c["rows"])) for c in board["categories"]]

    assert figures(after) == figures(stats_before)  # the same figures, whoever they are credited to
    shown = {r["player"]["name"] for c in after["categories"] for r in c["rows"] if (r["player"] or {}).get("id") == leaver.id}
    assert shown <= {"Former player"}
    team = (await lg.admin.req("GET", f"/teams/{b}")).json()
    assert any(m["name"] == "Former player" for m in team["members"])
    # the public site shows them as a former player, with no page, no code and no details
    slug = (await lg.admin.req("GET", f"/seasons/{lg.sid}")).json()["slug"]
    await lg.admin.req("PATCH", f"/seasons/{lg.sid}", json={"is_public": True})
    public_match = (await client.get(f"/public/matches/{mid}")).text
    assert "Former player" in public_match
    for secret in (f"u{leaver.id}@t.io", leaver.phone, f"FFP{leaver.id:05d}"):
        assert secret not in public_match
    assert (await client.get(f"/public/players/{leaver.id}?season={slug}")).status_code == 404
    assert await db.scalar(select(AuditLog.id).where(AuditLog.action == "account.delete", AuditLog.entity_id == leaver.id))


async def test_some_people_must_hand_over_first(make_user, db):
    lg = await make_league(make_user, n_teams=2, per_team=3, n_umpires=1)
    a, b = lg.teams
    captain, ump = lg.players[a][0], lg.umpires[0]
    r = await captain.req("POST", "/me/delete", json={"password": "password123"})
    assert r.status_code == 409 and "captain" in r.json()["detail"]
    mid = (await lg.admin.req("POST", f"/seasons/{lg.sid}/matches", json={"team_a_id": a, "team_b_id": b, "umpire_id": ump.id})).json()["id"]
    r = await ump.req("POST", "/me/delete", json={"password": "password123"})
    assert r.status_code == 409 and "umpire" in r.json()["detail"]
    assert (await lg.admin.req("POST", "/me/delete", json={"password": "password123"})).status_code == 409  # an admin
    member = lg.players[b][1]
    await lg.admin.req("PUT", f"/matches/{mid}/lineup", json={"team_id": b, "user_ids": [p.id for p in lg.players[b]]})
    r = await member.req("POST", "/me/delete", json={"password": "password123"})
    assert r.status_code == 409 and "lineup" in r.json()["detail"]
    assert (await member.req("GET", "/me")).status_code == 200  # still here


async def test_a_deleted_person_stays_out_of_lists_and_pending_things_are_cancelled(make_user, db):
    lg = await make_league(make_user, n_teams=2, per_team=3, n_umpires=1)
    a, _b = lg.teams
    free = await make_user("Free", verified=True)
    rc = await lg.players[a][0].req("POST", f"/teams/{a}/roster-changes", json={"out_user_id": lg.players[a][2].id, "in_user_id": free.id, "reason": "swap"})
    assert rc.status_code == 201, rc.text
    assert (await free.req("POST", "/me/delete", json={"password": "password123"})).status_code == 204
    pending = (await lg.admin.req("GET", "/roster-changes?status=pending")).json()
    assert pending == []
    team = (await lg.admin.req("GET", f"/teams/{a}")).json()
    assert not any(m["user_id"] == free.id and m["status"] == "approved" for m in team["members"])


# ---------- download my data ----------
async def test_the_download_has_what_is_held_and_nothing_of_others(make_user, db):
    lg = await make_league(make_user, n_teams=2, per_team=3, n_umpires=1)
    a, b = lg.teams
    mid = (await lg.admin.req("POST", f"/seasons/{lg.sid}/matches", json={"team_a_id": a, "team_b_id": b, "umpire_id": lg.umpires[0].id})).json()["id"]
    await play_match(lg, mid, "a")
    me = lg.players[a][1]
    r = await me.req("GET", "/me/data")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"] and r.headers["cache-control"] == "no-store"
    d = r.json()
    assert d["profile"]["email"] == f"u{me.id}@t.io" and d["profile"]["phone"] == me.phone
    assert d["teams"][0]["team"] == "Team1" and d["matches_played"][0]["match_id"] == mid
    assert any(x["role"] == "player" for x in d["roles"])
    text = r.text
    other = lg.players[b][1]
    assert f"u{other.id}@t.io" not in text and other.phone not in text
    assert "password" not in text.lower() and "refresh" not in text.lower()
    for _ in range(2):
        assert (await me.req("GET", "/me/data")).status_code == 200


async def test_a_large_history_downloads(make_user, db):
    lg = await make_league(make_user, n_teams=2, per_team=3, n_umpires=1)
    from app.db.models import Notification

    me = lg.players[lg.teams[0]][1]
    db.add_all([Notification(user_id=me.id, kind="result", title=f"t{i}", body="b", data={}, dedupe_key=f"k{i}") for i in range(1500)])
    await db.commit()
    d = (await me.req("GET", "/me/data")).json()
    assert len(d["notifications"]) == 1000  # the most recent thousand


# ---------- housekeeping ----------
async def test_old_codes_sign_ins_invites_and_audit_entries_are_dropped(client, db, engine, monkeypatch):
    from app.core.config import settings
    from app.db.models import OtpCode
    from app.services.retention import purge_stale

    t = await signup(client, 1)
    await client.post("/auth/refresh", json={"refresh_token": t["refresh_token"]})
    now = datetime.now(UTC)
    old, recent = now - timedelta(days=100), now - timedelta(hours=12)
    user = await db.scalar(select(User))
    db.add_all([OtpCode(phone="+91", code_hash="x", expires_at=old), OtpCode(phone="+92", code_hash="y", expires_at=now - timedelta(hours=1)),
                OtpCode(phone="+94", code_hash="z", expires_at=recent)])
    db.add(AuditLog(actor_id=user.id, action="old.thing", entity="x"))
    await db.flush()
    (await db.scalar(select(AuditLog).where(AuditLog.action == "old.thing"))).created_at = now - timedelta(days=800)
    sessions = list(await db.scalars(select(Session).order_by(Session.id)))
    sessions[0].expires_at = now - timedelta(days=8)  # expired a week ago
    await db.commit()
    monkeypatch.setattr(settings, "audit_retention_days", 730)

    from sqlalchemy.ext.asyncio import async_sessionmaker

    ctx = {"session_factory": async_sessionmaker(engine, expire_on_commit=False)}
    out = await purge_stale(ctx)
    assert out["otp_codes"] == 1 and out["sessions"] == 1 and out["audit"] == 1
    db.expire_all()
    assert await db.scalar(select(func.count()).select_from(Session)) == 1
    assert await db.scalar(select(func.count()).select_from(OtpCode)) == 2  # the recent ones stay
    monkeypatch.setattr(settings, "audit_retention_days", 0)
    assert "audit" not in await purge_stale(ctx)
