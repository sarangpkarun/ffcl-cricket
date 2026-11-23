"""Every route that costs something or can be abused has a limit; each is checked here (limits are off in other tests)."""

import pytest

from app.core.config import settings
from tests.helpers import make_league


@pytest.fixture(autouse=True)
def limits_on(monkeypatch):
    monkeypatch.setattr(settings, "auth_rate_limits_enabled", True)


async def until_429(call, budget, ok=lambda r: r.status_code != 429):
    """The first `budget` calls are answered, the next one is refused."""
    for i in range(budget):
        r = await call()
        assert ok(r), (i, r.status_code, r.text[:120])
    assert (await call()).status_code == 429


async def test_downloading_your_data_is_limited(make_user):
    p = await make_user("P")
    await until_429(lambda: p.req("GET", "/me/data"), 3)


async def test_deleting_an_account_is_limited_so_the_password_cannot_be_guessed(make_user):
    p = await make_user("P")
    await until_429(lambda: p.req("POST", "/me/delete", json={"password": "not-it"}), 5, ok=lambda r: r.status_code == 403)
    assert (await p.req("GET", "/me")).status_code == 200  # still there


async def test_invite_creation_lookup_and_acceptance_are_limited(make_user, client):
    lg = await make_league(make_user, n_teams=2, per_team=2, n_umpires=1)
    await until_429(lambda: lg.admin.req("POST", f"/admin/seasons/{lg.sid}/invites", json={"csv": ""}), 20, ok=lambda r: r.status_code == 422)
    await until_429(lambda: client.post("/invites/nope/accept", json={"email": "a@t.io", "password": "a-long-password"}), 10, ok=lambda r: r.status_code == 404)
    await until_429(lambda: client.get("/invites/nope"), 60, ok=lambda r: r.status_code == 404)


async def test_disputes_push_and_reports_are_limited(make_user, monkeypatch):
    monkeypatch.setattr(settings, "push_enabled", True)
    lg = await make_league(make_user, n_teams=2, per_team=2, n_umpires=1)
    cap = lg.players[lg.teams[0]][0]
    await until_429(lambda: cap.req("POST", "/me/push/test"), 5, ok=lambda r: r.status_code == 409)  # no device: refused, but counted
    body = {"kind": "conduct", "body": "A message that is long enough to be a complaint", "season_id": lg.sid}
    await until_429(lambda: cap.req("POST", "/disputes", json=body), 5, ok=lambda r: r.status_code in (200, 201, 409, 422))


async def test_chat_sends_are_limited_per_room(make_user):
    lg = await make_league(make_user, n_teams=2, per_team=2, n_umpires=1)
    p = lg.players[lg.teams[0]][1]
    rooms = (await p.req("GET", "/chat/home")).json()
    rid = rooms[0]["room_id"]  # the season room
    n = {"i": 0}

    def send():
        n["i"] += 1
        return p.req("POST", f"/rooms/{rid}/messages", json={"body": "hello", "client_id": f"client-{n['i']:04d}"})

    await until_429(send, 10, ok=lambda r: r.status_code == 201)
