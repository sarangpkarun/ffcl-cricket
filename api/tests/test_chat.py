import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db.models import ChatMessage, ChatRoom
from tests.helpers import setup_match


def cid() -> str:
    return uuid.uuid4().hex


async def rooms(db, ctx):
    out = {}
    for kind, key in (("season", f"season:{ctx.sid}"), ("match", f"match:{ctx.match}"),
                      ("umpire", f"umpire:{ctx.match}")):
        out[kind] = (await db.scalar(select(ChatRoom).where(ChatRoom.scope_key == key))).id
    return out


async def world(make_user, db):
    """Match with lineups + people around it. Returns (ctx, room ids, actors by name)."""
    ctx = await setup_match(make_user)
    bench = await make_user("Bench")  # on team A's roster but not in the lineup
    await ctx.admin.req("POST", f"/teams/{ctx.team_a}/members", json={"user_id": bench.id})
    other_ump = await make_user("OtherUmp", roles=["umpire"])
    outsider = await make_user("Outsider")
    r = await rooms(db, ctx)
    who = {
        "admin": ctx.admin, "umpire": ctx.ump, "other_umpire": other_ump, "captain": ctx.a[0],
        "player": ctx.a[1], "opponent": ctx.b[1], "bench": bench, "outsider": outsider,
    }
    return ctx, r, who


# who may read/post in each room kind
MATRIX = {
    "season": {"admin": 1, "umpire": 1, "other_umpire": 1, "captain": 1, "player": 1, "opponent": 1,
               "bench": 1, "outsider": 0},
    "match": {"admin": 1, "umpire": 1, "other_umpire": 0, "captain": 1, "player": 1, "opponent": 1,
              "bench": 0, "outsider": 0},
    "umpire": {"admin": 1, "umpire": 1, "other_umpire": 0, "captain": 0, "player": 0, "opponent": 0,
               "bench": 0, "outsider": 0},
}


@pytest.mark.parametrize("kind", ["season", "match", "umpire"])
async def test_access_matrix(make_user, db, kind):
    _ctx, r, who = await world(make_user, db)
    room = r[kind]
    for name, allowed in MATRIX[kind].items():
        actor = who[name]
        got = await actor.req("GET", f"/rooms/{room}/messages")
        sent = await actor.req("POST", f"/rooms/{room}/messages", json={"body": f"hi from {name}", "client_id": cid()})
        # strangers get 404 for both read and write so room ids cannot be probed
        assert got.status_code == (200 if allowed else 404), (kind, name, got.text)
        assert sent.status_code == (201 if allowed else 404), (kind, name, sent.text)
    n = await db.scalar(select(func.count()).select_from(ChatMessage).where(ChatMessage.room_id == room))
    assert n == sum(MATRIX[kind].values())  # refused senders stored nothing


async def test_rooms_created_with_season_and_match(make_user, db):
    ctx, r, _ = await world(make_user, db)
    assert len(set(r.values())) == 3
    row = await db.get(ChatRoom, r["match"])
    assert (row.kind, row.match_id, row.season_id) == ("match", ctx.match, ctx.sid)


async def test_match_rooms_endpoint_is_filtered(make_user, db):
    ctx, r, who = await world(make_user, db)
    url = f"/matches/{ctx.match}/rooms"
    ump = (await who["umpire"].req("GET", url)).json()
    assert ump["match"]["room_id"] == r["match"] and ump["umpire"]["room_id"] == r["umpire"]
    player = (await who["player"].req("GET", url)).json()
    assert player["match"]["room_id"] == r["match"] and player["umpire"] is None
    assert (await who["outsider"].req("GET", url)).json() == {"match": None, "umpire": None}


async def test_chat_home_lists_only_readable_seasons(make_user, db):
    _ctx, r, who = await world(make_user, db)
    mine = (await who["player"].req("GET", "/chat/home")).json()
    assert [x["room_id"] for x in mine] == [r["season"]] and mine[0]["title"].endswith("chat")
    assert (await who["outsider"].req("GET", "/chat/home")).json() == []


async def test_removed_member_loses_access(make_user, db):
    ctx, r, who = await world(make_user, db)
    assert (await who["bench"].req("GET", f"/rooms/{r['season']}/messages")).status_code == 200
    await ctx.admin.req("DELETE", f"/teams/{ctx.team_a}/members/{who['bench'].id}")
    assert (await who["bench"].req("GET", f"/rooms/{r['season']}/messages")).status_code == 404


async def test_send_list_and_pagination(make_user, db):
    _ctx, r, who = await world(make_user, db)
    room, p = r["match"], who["player"]
    ids = []
    for i in range(7):
        m = await p.req("POST", f"/rooms/{room}/messages", json={"body": f"msg {i}", "client_id": cid()})
        ids.append(m.json()["id"])
    page = (await p.req("GET", f"/rooms/{room}/messages?limit=3")).json()
    assert [m["body"] for m in page["messages"]] == ["msg 4", "msg 5", "msg 6"] and page["has_more"]
    older = (await p.req("GET", f"/rooms/{room}/messages?limit=3&before={page['messages'][0]['id']}")).json()
    assert [m["body"] for m in older["messages"]] == ["msg 1", "msg 2", "msg 3"] and older["has_more"]
    oldest = (await p.req("GET", f"/rooms/{room}/messages?limit=3&before={older['messages'][0]['id']}")).json()
    assert [m["body"] for m in oldest["messages"]] == ["msg 0"] and not oldest["has_more"]
    # reconnect resync: everything after the last id I saw, oldest first
    newer = (await p.req("GET", f"/rooms/{room}/messages?after={ids[4]}")).json()
    assert [m["body"] for m in newer["messages"]] == ["msg 5", "msg 6"] and not newer["has_more"]
    assert newer["messages"][0]["sender"]["id"] == p.id


async def test_retry_with_same_client_id_does_not_duplicate(make_user, db):
    _ctx, r, who = await world(make_user, db)
    room, c = r["match"], cid()
    a = await who["player"].req("POST", f"/rooms/{room}/messages", json={"body": "once", "client_id": c})
    b = await who["player"].req("POST", f"/rooms/{room}/messages", json={"body": "once", "client_id": c})
    assert a.json()["id"] == b.json()["id"]
    assert await db.scalar(select(func.count()).select_from(ChatMessage).where(ChatMessage.room_id == room)) == 1
    # the same client id from someone else is a different message
    other = await who["opponent"].req("POST", f"/rooms/{room}/messages", json={"body": "once", "client_id": c})
    assert other.json()["id"] != a.json()["id"]


async def test_message_validation(make_user, db):
    _ctx, r, who = await world(make_user, db)
    url, p = f"/rooms/{r['match']}/messages", who["player"]
    for body in ("", "   \n  ", "x" * 2001):
        assert (await p.req("POST", url, json={"body": body, "client_id": cid()})).status_code == 422, body
    assert (await p.req("POST", url, json={"body": "ok", "client_id": "short"})).status_code == 422
    assert (await p.req("POST", url, json={"body": "x" * 2000, "client_id": cid()})).status_code == 201
    trimmed = await p.req("POST", url, json={"body": "  hello  ", "client_id": cid()})
    assert trimmed.json()["body"] == "hello"
    # markup is stored as plain text, never interpreted by the server
    raw = await p.req("POST", url, json={"body": "<script>alert(1)</script>", "client_id": cid()})
    assert raw.json()["body"] == "<script>alert(1)</script>"
    assert (await p.req("POST", url, json={"body": "hi"})).status_code == 422  # client_id required


async def test_edit_rules(make_user, db):
    _ctx, r, who = await world(make_user, db)
    room, p = r["match"], who["player"]
    m = (await p.req("POST", f"/rooms/{room}/messages", json={"body": "typo", "client_id": cid()})).json()
    url = f"/rooms/{room}/messages/{m['id']}"
    ok = await p.req("PATCH", url, json={"body": "fixed"})
    assert ok.status_code == 200 and ok.json()["body"] == "fixed" and ok.json()["edited_at"]
    assert (await who["opponent"].req("PATCH", url, json={"body": "hax"})).status_code == 403
    assert (await who["admin"].req("PATCH", url, json={"body": "hax"})).status_code == 403  # admins delete, never rewrite
    assert (await p.req("PATCH", url, json={"body": "  "})).status_code == 422
    # after 15 minutes the window closes
    row = await db.get(ChatMessage, m["id"])
    row.created_at = datetime.now(UTC) - timedelta(minutes=16)
    await db.commit()
    assert (await p.req("PATCH", url, json={"body": "too late"})).status_code == 409
    # a deleted message cannot be edited
    fresh = (await p.req("POST", f"/rooms/{room}/messages", json={"body": "bye", "client_id": cid()})).json()
    await p.req("DELETE", f"/rooms/{room}/messages/{fresh['id']}")
    assert (await p.req("PATCH", f"/rooms/{room}/messages/{fresh['id']}", json={"body": "back"})).status_code == 409


async def test_delete_rules_and_removed_content_is_hidden(make_user, db):
    ctx, r, who = await world(make_user, db)
    m_room, s_room = r["match"], r["season"]
    mine = (await who["player"].req("POST", f"/rooms/{m_room}/messages", json={"body": "secret rant", "client_id": cid()})).json()
    assert (await who["opponent"].req("DELETE", f"/rooms/{m_room}/messages/{mine['id']}")).status_code == 403
    # the match umpire moderates their match room
    assert (await who["umpire"].req("DELETE", f"/rooms/{m_room}/messages/{mine['id']}")).status_code == 204
    assert (await who["umpire"].req("DELETE", f"/rooms/{m_room}/messages/{mine['id']}")).status_code == 204  # idempotent
    listed = (await who["opponent"].req("GET", f"/rooms/{m_room}/messages")).json()["messages"][0]
    assert listed["deleted"] is True and listed["body"] is None and "secret rant" not in str(listed)
    row = await db.get(ChatMessage, mine["id"])
    assert row.body == "secret rant" and row.deleted_by == ctx.ump.id  # kept for moderation
    # the umpire is not a moderator of the season room; admins are
    s_msg = (await who["player"].req("POST", f"/rooms/{s_room}/messages", json={"body": "season hi", "client_id": cid()})).json()
    assert (await who["umpire"].req("DELETE", f"/rooms/{s_room}/messages/{s_msg['id']}")).status_code == 403
    assert (await who["admin"].req("DELETE", f"/rooms/{s_room}/messages/{s_msg['id']}")).status_code == 204
    # a message from another room is not reachable through this room's url
    assert (await who["player"].req("DELETE", f"/rooms/{m_room}/messages/{s_msg['id']}")).status_code == 404


async def test_rate_limit_is_per_user_per_room(make_user, db):
    _ctx, r, who = await world(make_user, db)
    p, room = who["player"], r["match"]
    codes = [(await p.req("POST", f"/rooms/{room}/messages", json={"body": f"m{i}", "client_id": cid()})).status_code
             for i in range(12)]
    assert codes == [201] * 10 + [429, 429]
    # another room and another user are unaffected
    assert (await p.req("POST", f"/rooms/{r['season']}/messages", json={"body": "x", "client_id": cid()})).status_code == 201
    assert (await who["opponent"].req("POST", f"/rooms/{room}/messages", json={"body": "x", "client_id": cid()})).status_code == 201
    # a retry of an already stored message is not rate limited
    again = await p.req("GET", f"/rooms/{room}/messages?limit=1")
    assert again.status_code == 200


async def test_room_info(make_user, db):
    _ctx, r, who = await world(make_user, db)
    info = (await who["umpire"].req("GET", f"/rooms/{r['match']}")).json()
    assert info["kind"] == "match" and info["moderator"] is True and info["can_post"] is True
    assert (await who["player"].req("GET", f"/rooms/{r['match']}")).json()["moderator"] is False
    assert (await who["player"].req("GET", f"/rooms/{r['umpire']}")).status_code == 404
    assert (await who["player"].req("GET", "/rooms/999999")).status_code == 404


async def test_simultaneous_identical_sends_collapse_to_one_message(make_user, db):
    """A double tap or client retry arrives twice at once: both succeed with the same message."""
    import asyncio

    _ctx, r, who = await world(make_user, db)
    room, c = r["match"], cid()
    rs = await asyncio.gather(*[
        who["player"].req("POST", f"/rooms/{room}/messages", json={"body": "tap tap", "client_id": c}) for _ in range(8)])
    assert [x.status_code for x in rs] == [201] * 8
    assert len({x.json()["id"] for x in rs}) == 1
    assert await db.scalar(select(func.count()).select_from(ChatMessage).where(ChatMessage.room_id == room)) == 1


async def test_simultaneous_reaction_taps_never_error(make_user, db):
    import asyncio

    _ctx, r, who = await world(make_user, db)
    m = (await who["player"].req("POST", f"/rooms/{r['match']}/messages", json={"body": "nice", "client_id": cid()})).json()
    rs = await asyncio.gather(*[
        who["opponent"].req("POST", f"/rooms/{r['match']}/messages/{m['id']}/reactions", json={"emoji": "🔥"}) for _ in range(6)])
    assert all(x.status_code == 200 for x in rs)  # some add, some remove, none crash
    final = (await who["player"].req("GET", f"/rooms/{r['match']}/messages")).json()["messages"][0]["reactions"]
    assert final in ({}, {"🔥": [who["opponent"].id]})
