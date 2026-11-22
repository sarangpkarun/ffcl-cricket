import asyncio
import json
import uuid

import pytest

from app.routers import ws_rooms
from tests.test_chat import world
from tests.ws_helpers import closed_with, connect, next_of, recv, token_of


def send(actor, room, body="hello"):
    return actor.req("POST", f"/rooms/{room}/messages", json={"body": body, "client_id": uuid.uuid4().hex})


async def test_socket_access(make_user, db, ws_url):
    _ctx, r, who = await world(make_user, db)
    url = lambda room: f"{ws_url}/ws/rooms/{room}"
    assert await closed_with(url(r["match"]), token="garbage") == 4401
    assert await closed_with(url(r["match"]), first_message="nonsense") == 4401
    assert await closed_with(url(r["match"])) == 4401  # silent socket: no token within the timeout
    assert await closed_with(url(r["match"]), token=token_of(who["outsider"])) == 4403
    assert await closed_with(url(r["umpire"]), token=token_of(who["player"])) == 4403
    assert await closed_with(url(r["umpire"]), token=token_of(who["captain"])) == 4403
    assert await closed_with(url(999999), token=token_of(who["player"])) == 4403  # same as "not yours"
    # a token in the query string is not accepted
    assert await closed_with(f"{url(r['match'])}?token={token_of(who['player'])}") == 4401


@pytest.fixture(autouse=True)
def _fast_auth(monkeypatch):
    from app.routers import ws

    monkeypatch.setattr(ws, "AUTH_TIMEOUT_SECONDS", 0.5)


async def test_members_receive_messages_nonmembers_and_other_rooms_do_not(make_user, db, ws_url):
    _ctx, r, who = await world(make_user, db)
    m_url, s_url = f"{ws_url}/ws/rooms/{r['match']}", f"{ws_url}/ws/rooms/{r['season']}"
    w_opp = await connect(m_url, token_of(who["opponent"]))
    w_self = await connect(m_url, token_of(who["player"]))
    w_season = await connect(s_url, token_of(who["bench"]))  # bench: season room only
    w_ump = await connect(f"{ws_url}/ws/rooms/{r['umpire']}", token_of(who["umpire"]))
    async with w_opp, w_self, w_season, w_ump:
        for w in (w_opp, w_self, w_season, w_ump):
            await next_of(w, "hello")
        res = await send(who["player"], r["match"], "good over 🔥")
        sent = res.json()
        for w in (w_opp, w_self):
            ev = await next_of(w, "message")
            assert ev["message"]["id"] == sent["id"] and ev["message"]["body"] == "good over 🔥"
            assert ev["message"]["sender"]["id"] == who["player"].id
        # nothing from the match room reaches the season or umpire sockets
        for w in (w_season, w_ump):
            with pytest.raises(TimeoutError):
                await next_of(w, "message", timeout=0.7)
        # and a season message does not reach the match sockets
        await send(who["bench"], r["season"], "bench says hi")
        assert (await next_of(w_season, "message"))["message"]["body"] == "bench says hi"
        with pytest.raises(TimeoutError):
            await next_of(w_opp, "message", timeout=0.7)


async def test_edit_and_delete_are_broadcast(make_user, db, ws_url):
    _ctx, r, who = await world(make_user, db)
    url = f"{ws_url}/ws/rooms/{r['match']}"
    m = (await send(who["player"], r["match"], "teh")).json()
    async with await connect(url, token_of(who["opponent"])) as w:
        await next_of(w, "hello")
        await who["player"].req("PATCH", f"/rooms/{r['match']}/messages/{m['id']}", json={"body": "the"})
        ev = await next_of(w, "edited")
        assert ev["message"]["body"] == "the" and ev["message"]["edited_at"]
        await who["umpire"].req("DELETE", f"/rooms/{r['match']}/messages/{m['id']}")
        assert (await next_of(w, "deleted"))["id"] == m["id"]


async def test_presence_online_list_and_events(make_user, db, ws_url):
    _ctx, r, who = await world(make_user, db)
    url = f"{ws_url}/ws/rooms/{r['match']}"
    w1 = await connect(url, token_of(who["player"]))
    async with w1:
        assert (await next_of(w1, "hello"))["online"] == [who["player"].id]
        w2 = await connect(url, token_of(who["opponent"]))
        async with w2:
            ev = await next_of(w1, "presence")
            while ev["user"]["id"] != who["opponent"].id:  # a socket also hears its own arrival
                ev = await next_of(w1, "presence")
            assert ev["online"] is True
            assert set((await next_of(w2, "hello"))["online"]) == {who["player"].id, who["opponent"].id}
            online = (await who["umpire"].req("GET", f"/rooms/{r['match']}/online")).json()
            assert {u["id"] for u in online} == {who["player"].id, who["opponent"].id}
            assert (await who["outsider"].req("GET", f"/rooms/{r['match']}/online")).status_code == 404
        ev = await next_of(w1, "presence")
        assert ev["online"] is False and ev["user"]["id"] == who["opponent"].id
    await asyncio.sleep(0.3)
    assert (await who["umpire"].req("GET", f"/rooms/{r['match']}/online")).json() == []


async def test_heartbeat_message_is_accepted(make_user, db, ws_url):
    _ctx, r, who = await world(make_user, db)
    async with await connect(f"{ws_url}/ws/rooms/{r['match']}", token_of(who["player"])) as w:
        await next_of(w, "hello")
        await w.send(json.dumps({"type": "ping"}))
        await w.send("garbage that is not json")  # must not kill the socket
        await send(who["opponent"], r["match"], "still here?")
        assert (await next_of(w, "message"))["message"]["body"] == "still here?"


async def test_socket_dropped_when_access_is_revoked(make_user, db, ws_url, monkeypatch):
    monkeypatch.setattr(ws_rooms, "RECHECK_SECONDS", 0.4)
    ctx, r, who = await world(make_user, db)
    bench = who["bench"]
    async with await connect(f"{ws_url}/ws/rooms/{r['season']}", token_of(bench)) as w:
        await next_of(w, "hello")
        await ctx.admin.req("DELETE", f"/teams/{ctx.team_a}/members/{bench.id}")  # leaves the team
        with pytest.raises(Exception) as e:  # connection closes with 4403 at the next re-check
            for _ in range(10):
                await recv(w, timeout=1.5)
        assert getattr(e.value, "rcvd", None) and e.value.rcvd.code == 4403


async def test_socket_dropped_when_logged_out_everywhere(make_user, db, ws_url, monkeypatch):
    monkeypatch.setattr(ws_rooms, "RECHECK_SECONDS", 0.4)
    _ctx, r, who = await world(make_user, db)
    p = who["player"]
    async with await connect(f"{ws_url}/ws/rooms/{r['match']}", token_of(p)) as w:
        await next_of(w, "hello")
        await p.req("POST", "/auth/logout-all")
        with pytest.raises(Exception) as e:
            for _ in range(10):
                await recv(w, timeout=1.5)
        assert getattr(e.value, "rcvd", None) and e.value.rcvd.code == 4403


async def test_socket_survives_access_token_expiry(make_user, db, ws_url, monkeypatch):
    """The 15-minute access token only gates the handshake; a live session keeps its socket."""
    monkeypatch.setattr(ws_rooms, "RECHECK_SECONDS", 0.3)
    _ctx, r, who = await world(make_user, db)
    async with await connect(f"{ws_url}/ws/rooms/{r['match']}", token_of(who["player"])) as w:
        await next_of(w, "hello")
        await asyncio.sleep(1.0)  # several re-check cycles pass
        await send(who["opponent"], r["match"], "alive")
        assert (await next_of(w, "message"))["message"]["body"] == "alive"


# ---------- Sprint 6 events ----------
async def _room_sockets(ws_url, room, *actors):
    socks = [await connect(f"{ws_url}/ws/rooms/{room}", token_of(a)) for a in actors]
    for w in socks:
        await next_of(w, "hello")
    return socks


async def test_rich_events_are_broadcast(make_user, db, ws_url):
    _ctx, r, who = await world(make_user, db)
    room = r["match"]
    w_opp, w_ump = await _room_sockets(ws_url, room, who["opponent"], who["umpire"])
    async with w_opp, w_ump:
        m = (await send(who["player"], room, "what a shot")).json()
        await next_of(w_opp, "message")
        await who["opponent"].req("POST", f"/rooms/{room}/messages/{m['id']}/reactions", json={"emoji": "🔥"})
        ev = await next_of(w_ump, "reaction")
        assert ev["message_id"] == m["id"] and ev["reactions"] == {"🔥": [who["opponent"].id]}
        await who["umpire"].req("POST", f"/rooms/{room}/messages/{m['id']}/pin")
        assert (await next_of(w_opp, "pinned"))["message"]["pinned"] is True
        await who["umpire"].req("POST", f"/rooms/{room}/announcements", json={"body": "Toss in 5 minutes"})
        a = await next_of(w_opp, "message")
        while a["message"]["kind"] != "announcement":
            a = await next_of(w_opp, "message")
        assert a["message"]["body"] == "Toss in 5 minutes"
        await who["umpire"].req("DELETE", f"/rooms/{room}/messages/{m['id']}")
        assert (await next_of(w_opp, "deleted"))["id"] == m["id"]


async def test_typing_is_broadcast_and_throttled(make_user, db, ws_url):
    _ctx, r, who = await world(make_user, db)
    w_typer, w_watch = await _room_sockets(ws_url, r["match"], who["player"], who["opponent"])
    async with w_typer, w_watch:
        for _ in range(5):  # a burst of keystrokes
            await w_typer.send(json.dumps({"type": "typing"}))
        ev = await next_of(w_watch, "typing")
        assert ev["user"]["id"] == who["player"].id
        with pytest.raises(TimeoutError):  # the other four were throttled
            await next_of(w_watch, "typing", timeout=0.8)
        await asyncio.sleep(2.1)
        await w_typer.send(json.dumps({"type": "typing"}))
        assert (await next_of(w_watch, "typing"))["user"]["id"] == who["player"].id


async def test_read_receipts_over_socket(make_user, db, ws_url):
    _ctx, r, who = await world(make_user, db)
    room = r["match"]
    m = (await send(who["player"], room, "seen this?")).json()
    w_reader, w_author = await _room_sockets(ws_url, room, who["opponent"], who["player"])
    async with w_reader, w_author:
        await w_reader.send(json.dumps({"type": "read", "last_id": m["id"]}))
        ev = await next_of(w_author, "read")
        assert ev["user"]["id"] == who["opponent"].id and ev["last_id"] == m["id"]
        await w_reader.send(json.dumps({"type": "read", "last_id": m["id"]}))  # no movement: no event
        with pytest.raises(TimeoutError):
            await next_of(w_author, "read", timeout=0.8)
        await w_reader.send(json.dumps({"type": "read", "last_id": "junk"}))  # bad input is ignored
        await send(who["umpire"], room, "still alive")
        assert (await next_of(w_author, "message"))["message"]["body"] == "still alive"
    reads = (await who["player"].req("GET", f"/rooms/{room}/reads")).json()
    assert reads == [{"user_id": who["opponent"].id, "name": reads[0]["name"], "last_read_id": m["id"]}]


async def test_muted_user_keeps_receiving(make_user, db, ws_url):
    ctx, r, who = await world(make_user, db)
    room = r["match"]
    await ctx.admin.req("POST", "/admin/mutes", json={"user_id": who["opponent"].id, "season_id": ctx.sid,
                                                        "hours": 1, "reason": "cooling off"})
    (w,) = await _room_sockets(ws_url, room, who["opponent"])
    async with w:
        await send(who["player"], room, "can you hear me")
        assert (await next_of(w, "message"))["message"]["body"] == "can you hear me"
        assert (await send(who["opponent"], room, "no")).status_code == 403
