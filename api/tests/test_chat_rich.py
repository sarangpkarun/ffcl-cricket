import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import AuditLog, ChatMessage, ChatMute, ChatRead
from app.services import chat as svc
from tests.test_chat import MATRIX, cid, world


def post(actor, room, body="hello", **extra):
    return actor.req("POST", f"/rooms/{room}/messages", json={"body": body, "client_id": cid(), **extra})


# ---------- replies ----------
async def test_replies(make_user, db):
    _ctx, r, who = await world(make_user, db)
    room = r["match"]
    base = (await post(who["player"], room, "original text")).json()
    rep = (await post(who["opponent"], room, "agreed", reply_to_id=base["id"])).json()
    assert rep["reply_to"] == {"id": base["id"], "sender_name": base["sender"]["name"],
                               "snippet": "original text", "deleted": False}
    # the reply keeps working after the original is deleted, but the quote no longer leaks the text
    await who["player"].req("DELETE", f"/rooms/{room}/messages/{base['id']}")
    listed = (await who["opponent"].req("GET", f"/rooms/{room}/messages")).json()["messages"]
    quote = next(m for m in listed if m["id"] == rep["id"])["reply_to"]
    assert quote["deleted"] is True and quote["snippet"] is None and "original text" not in str(listed)
    # cannot reply across rooms or to nothing
    other = (await post(who["player"], r["season"], "season msg")).json()
    assert (await post(who["opponent"], room, "x", reply_to_id=other["id"])).status_code == 422
    assert (await post(who["opponent"], room, "x", reply_to_id=999999)).status_code == 422


# ---------- mentions + members ----------
async def test_mentions(make_user, db):
    _ctx, r, who = await world(make_user, db)
    room = r["match"]
    ok = await post(who["player"], room, "nice one", mentions=[who["opponent"].id])
    assert ok.status_code == 201 and ok.json()["meta"]["mentions"][0]["id"] == who["opponent"].id
    # the bench player and the outsider are not in the match room
    assert (await post(who["player"], room, "x", mentions=[who["bench"].id])).status_code == 422
    assert (await post(who["player"], room, "x", mentions=[who["outsider"].id])).status_code == 422
    assert (await post(who["player"], room, "x", mentions=list(range(1, 12)))).status_code == 422
    # the picker lists room members only, never yourself, and filters by name
    people = (await who["player"].req("GET", f"/rooms/{room}/members")).json()
    ids = {p["id"] for p in people}
    assert who["player"].id not in ids and who["opponent"].id in ids and who["outsider"].id not in ids
    filtered = (await who["player"].req("GET", f"/rooms/{room}/members?q=zzzz")).json()
    assert filtered == []
    assert (await who["outsider"].req("GET", f"/rooms/{room}/members")).status_code == 404


async def test_member_list_and_search_scope_agree_with_can_read(make_user, db):
    """member_ids() and readable_room_ids() are optimised copies of can_read: they must never drift."""
    _ctx, r, who = await world(make_user, db)
    from app.db.models import ChatRoom, User

    for kind in ("season", "match", "umpire"):
        room = await db.get(ChatRoom, r[kind])
        members = await svc.member_ids(db, room)
        for name, actor in who.items():
            user = await db.get(User, actor.id)
            assert (actor.id in members) == bool(MATRIX[kind][name]) == await svc.can_read(db, room, user), (kind, name)
    for name, actor in who.items():
        user = await db.get(User, actor.id)
        expected = {r[k] for k in ("season", "match", "umpire") if MATRIX[k][name]}
        assert await svc.readable_room_ids(db, user) == expected, name


# ---------- reactions ----------
async def test_reactions_toggle(make_user, db):
    _ctx, r, who = await world(make_user, db)
    room = r["match"]
    m = (await post(who["player"], room, "six!")).json()
    url = f"/rooms/{room}/messages/{m['id']}/reactions"
    a = await who["opponent"].req("POST", url, json={"emoji": "🔥"})
    assert a.json()["reactions"] == {"🔥": [who["opponent"].id]}
    b = await who["player"].req("POST", url, json={"emoji": "🔥"})
    assert b.json()["reactions"]["🔥"] == [who["opponent"].id, who["player"].id]
    again = await who["opponent"].req("POST", url, json={"emoji": "🔥"})  # second tap removes it
    assert again.json()["reactions"] == {"🔥": [who["player"].id]}
    assert (await who["player"].req("POST", url, json={"emoji": "💩"})).status_code == 422
    assert (await who["outsider"].req("POST", url, json={"emoji": "🔥"})).status_code == 404
    listed = (await who["player"].req("GET", f"/rooms/{room}/messages")).json()["messages"][0]
    assert listed["reactions"] == {"🔥": [who["player"].id]}
    await who["player"].req("DELETE", f"/rooms/{room}/messages/{m['id']}")
    assert (await who["player"].req("POST", url, json={"emoji": "👍"})).status_code == 409


# ---------- pins + announcements ----------
async def test_pins_and_announcements(make_user, db):
    _ctx, r, who = await world(make_user, db)
    room, season = r["match"], r["season"]
    m = (await post(who["player"], room, "rules: be nice")).json()
    pin = f"/rooms/{room}/messages/{m['id']}/pin"
    assert (await who["player"].req("POST", pin)).status_code == 403
    assert (await who["umpire"].req("POST", pin)).json()["pinned"] is True  # match umpire moderates their match
    assert [p["id"] for p in (await who["opponent"].req("GET", f"/rooms/{room}/pinned")).json()] == [m["id"]]
    s_msg = (await post(who["player"], season, "season msg")).json()
    assert (await who["umpire"].req("POST", f"/rooms/{season}/messages/{s_msg['id']}/pin")).status_code == 403
    assert (await who["admin"].req("POST", f"/rooms/{season}/messages/{s_msg['id']}/pin")).status_code == 200
    assert (await who["umpire"].req("DELETE", pin)).json()["pinned"] is False
    assert (await who["opponent"].req("GET", f"/rooms/{room}/pinned")).json() == []
    # announcements
    assert (await who["player"].req("POST", f"/rooms/{season}/announcements", json={"body": "free biryani"})).status_code == 403
    a = await who["admin"].req("POST", f"/rooms/{season}/announcements", json={"body": "Final on Sunday"})
    assert a.status_code == 201 and a.json()["kind"] == "announcement" and a.json()["pinned"] is True
    assert a.json()["sender"]["id"] == who["admin"].id
    assert (await who["admin"].req("POST", f"/rooms/{season}/announcements", json={"body": "  "})).status_code == 422
    # a deleted message drops out of the pinned list
    await who["admin"].req("DELETE", f"/rooms/{season}/messages/{a.json()['id']}")
    pinned = (await who["player"].req("GET", f"/rooms/{season}/pinned")).json()
    assert [p["id"] for p in pinned] == [s_msg["id"]]


# ---------- reaction set ----------
async def test_reaction_set(make_user, db):
    _ctx, _r, who = await world(make_user, db)
    got = (await who["player"].req("GET", "/chat/reactions")).json()
    assert "🔥" in got["reactions"] and len(got["reactions"]) == 8


# ---------- reports + moderation ----------
async def test_report_flow_and_actions(make_user, db):
    _ctx, r, who = await world(make_user, db)
    room = r["match"]
    bad = (await post(who["opponent"], room, "you lot are rubbish")).json()
    url = f"/rooms/{room}/messages/{bad['id']}/report"
    a = await who["player"].req("POST", url, json={"reason": "abusive"})
    assert a.status_code == 201 and a.json()["duplicate"] is False
    assert (await who["player"].req("POST", url, json={"reason": "abusive"})).json()["duplicate"] is True
    assert (await who["captain"].req("POST", url, json={"reason": "rude to us"})).status_code == 201
    assert (await who["opponent"].req("POST", url, json={"reason": "my own words"})).status_code == 400  # own message
    assert (await who["outsider"].req("POST", url, json={"reason": "spy"})).status_code == 404
    assert (await who["player"].req("POST", url, json={"reason": "x"})).status_code == 422  # reason too short
    # only admins see the queue; the report shows both reporters and the text
    assert (await who["player"].req("GET", "/admin/reports")).status_code == 403
    queue = (await who["admin"].req("GET", "/admin/reports")).json()
    assert len(queue) == 1 and queue[0]["count"] == 2 and queue[0]["message"]["body"] == "you lot are rubbish"
    # delete + mute for 2 hours
    rid = queue[0]["reports"][0]["id"]
    res = await who["admin"].req("POST", f"/admin/reports/{rid}/resolve", json={"action": "delete_and_mute", "mute_hours": 2})
    assert res.status_code == 200 and res.json()["resolved"] == 2 and res.json()["muted_until"]
    assert (await who["admin"].req("GET", "/admin/reports")).json() == []
    listed = (await who["player"].req("GET", f"/rooms/{room}/messages")).json()["messages"][0]
    assert listed["deleted"] and listed["body"] is None
    assert (await who["admin"].req("POST", f"/admin/reports/{rid}/resolve", json={"action": "dismiss"})).status_code == 409
    # the muted player can still read but not post or react - in every room of that season
    for rm in (room, r["season"]):
        got = await post(who["opponent"], rm, "sorry")
        assert got.status_code == 403 and "muted until" in got.json()["detail"]
        assert (await who["opponent"].req("GET", f"/rooms/{rm}/messages")).status_code == 200
    info = (await who["opponent"].req("GET", f"/rooms/{room}")).json()
    assert info["can_post"] is False and "muted" in info["blocked_reason"]
    audit = list(await db.scalars(select(AuditLog.action).where(AuditLog.action.in_(["report.delete_and_mute", "chat.mute"]))))
    assert sorted(audit) == ["chat.mute", "report.delete_and_mute"]


async def test_dismiss_leaves_message_and_user_alone(make_user, db):
    _ctx, r, who = await world(make_user, db)
    m = (await post(who["opponent"], r["match"], "banter")).json()
    await who["player"].req("POST", f"/rooms/{r['match']}/messages/{m['id']}/report", json={"reason": "meh whatever"})
    rid = (await who["admin"].req("GET", "/admin/reports")).json()[0]["reports"][0]["id"]
    assert (await who["admin"].req("POST", f"/admin/reports/{rid}/resolve", json={"action": "dismiss"})).status_code == 200
    assert (await post(who["opponent"], r["match"], "still fine")).status_code == 201
    assert len((await who["player"].req("GET", f"/rooms/{r['match']}/messages")).json()["messages"]) == 2
    assert (await who["admin"].req("GET", "/admin/reports?status=dismissed")).json()[0]["count"] == 1


async def test_mutes_manage_lift_and_expire(make_user, db):
    ctx, r, who = await world(make_user, db)
    opp, admin = who["opponent"], who["admin"]
    body = {"user_id": opp.id, "season_id": ctx.sid, "hours": 5, "reason": "spamming"}
    assert (await who["player"].req("POST", "/admin/mutes", json=body)).status_code == 403
    assert (await admin.req("POST", "/admin/mutes", json={**body, "user_id": admin.id})).status_code == 400  # admins are immune
    assert (await admin.req("POST", "/admin/mutes", json={**body, "hours": 0})).status_code == 422
    mid = (await admin.req("POST", "/admin/mutes", json=body)).json()["id"]
    assert (await post(opp, r["match"])).status_code == 403
    listed = (await admin.req("GET", "/admin/mutes")).json()
    assert [m["user"]["id"] for m in listed] == [opp.id]
    assert (await admin.req("DELETE", f"/admin/mutes/{mid}")).status_code == 204
    assert (await post(opp, r["match"])).status_code == 201 and (await admin.req("GET", "/admin/mutes")).json() == []
    # an expired mute no longer applies
    row = ChatMute(user_id=opp.id, season_id=ctx.sid, until=datetime.now(UTC) - timedelta(minutes=1),
                   reason="old", created_by=admin.id)
    db.add(row)
    await db.commit()
    assert (await post(opp, r["match"])).status_code == 201
    actions = set(await db.scalars(select(AuditLog.action).where(AuditLog.entity == "user")))
    assert {"chat.mute", "chat.unmute"} <= actions


# ---------- read receipts ----------
async def test_read_cursor(make_user, db):
    _ctx, r, who = await world(make_user, db)
    room = r["match"]
    ids = [(await post(who["player"], room, f"m{i}")).json()["id"] for i in range(3)]
    url = f"/rooms/{room}/read"
    assert (await who["opponent"].req("POST", url, json={"last_id": ids[1]})).status_code == 204
    assert (await who["opponent"].req("POST", url, json={"last_id": ids[0]})).status_code == 204  # backwards: ignored
    await who["umpire"].req("POST", url, json={"last_id": 10**9})  # clamped to the newest message
    reads = {x["user_id"]: x["last_read_id"] for x in (await who["player"].req("GET", f"/rooms/{room}/reads")).json()}
    assert reads == {who["opponent"].id: ids[1], who["umpire"].id: ids[2]}
    row = await db.scalar(select(ChatRead).where(ChatRead.user_id == who["opponent"].id))
    assert row.last_read_id == ids[1]
    assert (await who["outsider"].req("POST", url, json={"last_id": 1})).status_code == 404
    assert (await who["outsider"].req("GET", f"/rooms/{room}/reads")).status_code == 404
    assert (await who["player"].req("POST", url, json={"last_id": 0})).status_code == 422


# ---------- search ----------
async def test_search_is_scoped_and_literal(make_user, db):
    _ctx, r, who = await world(make_user, db)
    await post(who["player"], r["match"], "great Yorker at the death")
    await post(who["player"], r["match"], "scored 100% today")
    await post(who["bench"], r["season"], "yorker practice on sunday")
    await post(who["umpire"], r["umpire"], "yorker was a no ball, officials only")
    gone = (await post(who["player"], r["match"], "deleted yorker")).json()
    await who["player"].req("DELETE", f"/rooms/{r['match']}/messages/{gone['id']}")

    def bodies(res):
        return sorted(m["body"] for m in res.json())

    p = await who["player"].req("GET", "/chat/search?q=yorker")  # case-insensitive substring, own rooms only
    assert bodies(p) == ["great Yorker at the death", "yorker practice on sunday"]
    assert {m["room"]["kind"] for m in p.json()} == {"match", "season"}
    u = await who["umpire"].req("GET", "/chat/search?q=yorker")
    assert "yorker was a no ball, officials only" in bodies(u)
    a = await who["admin"].req("GET", "/chat/search?q=yorker")
    assert len(a.json()) == 3  # admin sees every room; deleted messages never appear
    assert (await who["outsider"].req("GET", "/chat/search?q=yorker")).json() == []
    # wildcard characters are matched literally
    assert bodies(await who["player"].req("GET", "/chat/search?q=100%25")) == ["scored 100% today"]
    assert (await who["player"].req("GET", "/chat/search?q=%25%25")).json() == []
    assert (await who["player"].req("GET", "/chat/search?q=_____")).json() == []
    # scoping to one room, and to a room you cannot read
    one = await who["player"].req("GET", f"/chat/search?q=yorker&room_id={r['season']}")
    assert bodies(one) == ["yorker practice on sunday"]
    assert (await who["player"].req("GET", f"/chat/search?q=yorker&room_id={r['umpire']}")).status_code == 404
    assert (await who["player"].req("GET", "/chat/search?q=y")).status_code == 422  # too short


async def test_unique_helper_ids():
    assert uuid.uuid4().hex != uuid.uuid4().hex  # cid() relies on this
    assert ChatMessage.__tablename__ == "chat_messages"
