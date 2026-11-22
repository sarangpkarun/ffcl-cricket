import json

from sqlalchemy import func, select

from app.db.models import Notification
from app.services.notify import KINDS, notify
from tests.helpers import BOWL_ALL_EQUAL, play, run_toss, setup_match, start
from tests.test_chat import cid, rooms
from tests.ws_helpers import closed_with, connect, next_of, recv, token_of


async def inbox(actor, kind=None):
    rows = (await actor.req("GET", "/notifications")).json()["notifications"]
    return [n for n in rows if kind is None or n["kind"] == kind]


async def counts(db, ctx, kind):
    """kind -> how many notifications each person got, by role label."""
    rows = list(await db.scalars(select(Notification).where(Notification.kind == kind)))
    got = {}
    for n in rows:
        got[n.user_id] = got.get(n.user_id, 0) + 1
    return got


async def test_umpire_assignment_notifies_once(make_user, db):
    ctx = await setup_match(make_user)
    first = await inbox(ctx.ump, "umpire_assigned")
    assert len(first) == 1 and first[0]["title"] == "You are the umpire for Match 1"
    assert first[0]["body"] == "Pink vs Green" and first[0]["data"]["link"] == f"/matches/{ctx.match}"
    other = await make_user("Ump2", roles=["umpire"])
    await ctx.admin.req("PATCH", f"/matches/{ctx.match}", json={"umpire_id": other.id})
    await ctx.admin.req("PATCH", f"/matches/{ctx.match}", json={"umpire_id": other.id})  # same again: nothing new
    assert len(await inbox(other, "umpire_assigned")) == 1
    assert len(await inbox(ctx.ump, "umpire_assigned")) == 1  # the replaced umpire is not pinged again


async def test_toss_and_over_notifications_reach_the_right_people(make_user, db):
    ctx = await setup_match(make_user)
    await ctx.ump.req("POST", f"{ctx.url}/toss/open")
    got = await counts(db, ctx, "toss_ready")
    assert got == {ctx.a[0].id: 1, ctx.b[0].id: 1}  # both captains, nobody else
    await ctx.ump.req("POST", f"{ctx.url}/toss/winner", json={"winner_team_id": ctx.team_a})
    await ctx.a[0].req("POST", f"{ctx.url}/toss/decision", json={"decision": "bat"})
    await ctx.ump.req("POST", f"{ctx.url}/toss/confirm")
    await start(ctx)
    bowler, batter = ctx.b[0], ctx.a[0]
    await ctx.ump.req("POST", f"{ctx.url}/overs/start", json={"bowler_id": bowler.id, "batter_id": batter.id})
    assert await counts(db, ctx, "your_over") == {}  # nothing until the umpire signals
    await ctx.ump.req("POST", f"{ctx.url}/overs/current/signal")
    got = await counts(db, ctx, "your_over")
    assert got == {bowler.id: 1, batter.id: 1}
    n = (await inbox(bowler, "your_over"))[0]
    assert n["title"] == "Over 1: submit your digits now" and n["data"]["link"] == f"/matches/{ctx.match}" and not n["read"]


async def test_wicket_penalty_over_and_result_notifications(make_user, db):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    await play(ctx, batters, bowlers, 1, bowl_digits=BOWL_ALL_EQUAL)  # six wickets
    pink = {p.id for p in ctx.a}
    green = {p.id for p in ctx.b}
    got = await counts(db, ctx, "wicket")
    assert set(got) == pink and all(v == 1 for v in got.values())  # the batting team only
    assert not set(got) & green
    # "every over" notifications are off by default
    assert await counts(db, ctx, "over_complete") == {}
    # a penalty tells the penalised team
    await ctx.ump.req("POST", f"{ctx.url}/penalties", json={
        "team_id": ctx.team_b, "kind": "x_breach", "runs": 0, "wickets": 0, "reason": "ignored", "idempotency_key": "n-0"})
    await play(ctx, batters, bowlers, 2, bowl_digits=BOWL_ALL_EQUAL)
    await ctx.ump.req("POST", f"{ctx.url}/innings/next")
    await play(ctx, bowlers, batters, 1)  # chase done on ball 1
    got = await counts(db, ctx, "result")
    assert set(got) == pink | green | {ctx.ump.id} and all(v == 1 for v in got.values())
    assert (await inbox(ctx.a[1], "result"))[0]["body"] == "Green won by 7 wickets"
    pen = await ctx.ump.req("POST", f"{ctx.url}/penalties", json={
        "team_id": ctx.team_a, "kind": "late_submission", "runs": 4, "reason": "slow", "idempotency_key": "n-pen-1"})
    await ctx.ump.req("POST", f"{ctx.url}/penalties", json={
        "team_id": ctx.team_a, "kind": "late_submission", "runs": 4, "reason": "slow", "idempotency_key": "n-pen-1"})
    assert pen.status_code == 201
    got = await counts(db, ctx, "penalty")
    assert set(got) == pink and all(v == 1 for v in got.values())  # a retried penalty notifies once


async def test_over_complete_can_be_switched_on(make_user, db):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    watcher = ctx.b[2]
    await watcher.req("PUT", "/notifications/prefs", json={"kind": "over_complete", "in_app": True})
    await play(ctx, batters, bowlers, 1)
    got = await counts(db, ctx, "over_complete")
    assert set(got) == {watcher.id}
    assert (await inbox(watcher, "over_complete"))[0]["body"].startswith("Over 1 done: 21 runs")


async def test_announcement_reaches_members_but_not_the_author_or_strangers(make_user, db):
    ctx = await setup_match(make_user)
    r = await rooms(db, ctx)
    outsider = await make_user("Fan")
    res = await ctx.admin.req("POST", f"/rooms/{r['season']}/announcements", json={"body": "Final is on Sunday"})
    assert res.status_code == 201
    got = await counts(db, ctx, "announcement")
    members = {p.id for p in ctx.a + ctx.b} | {ctx.ump.id}
    assert set(got) == members and ctx.admin.id not in got and outsider.id not in got
    n = (await inbox(ctx.a[1], "announcement"))[0]
    assert n["body"] == "Final is on Sunday" and n["data"]["link"] == "/chat"


async def test_mentions_and_replies(make_user, db):
    ctx = await setup_match(make_user)
    r = await rooms(db, ctx)
    room, me, you, third = r["match"], ctx.a[1], ctx.b[1], ctx.b[2]

    def post(actor, body, **extra):
        return actor.req("POST", f"/rooms/{room}/messages", json={"body": body, "client_id": cid(), **extra})

    base = (await post(you, "first message")).json()
    await post(me, "hello there", mentions=[you.id])
    n = (await inbox(you, "mention"))[0]
    assert n["title"] == f"{(await me.req('GET', '/me')).json()['name']} mentioned you" and n["body"] == "hello there"
    assert n["data"]["link"] == f"/matches/{ctx.match}"
    await post(me, "agree", reply_to_id=base["id"])
    assert len(await inbox(you, "reply")) == 1
    # mentioning and replying to the same person pings them once, as a mention
    await post(me, "both", reply_to_id=base["id"], mentions=[you.id])
    assert len(await inbox(you, "reply")) == 1 and len(await inbox(you, "mention")) == 2
    # replying to yourself and mentioning yourself notify nobody
    mine = (await post(me, "note to self")).json()
    await post(me, "again", reply_to_id=mine["id"], mentions=[me.id])
    assert await inbox(me) == []
    # a person who turned mentions off hears nothing
    await third.req("PUT", "/notifications/prefs", json={"kind": "mention", "in_app": False})
    await post(me, "psst", mentions=[third.id])
    assert await inbox(third, "mention") == []
    # editing a message never re-notifies
    msg = (await post(me, "edit me", mentions=[you.id])).json()
    before = len(await inbox(you, "mention"))
    await me.req("PATCH", f"/rooms/{room}/messages/{msg['id']}", json={"body": "edited"})
    assert len(await inbox(you, "mention")) == before


async def test_prefs_api(make_user, db):
    ctx = await setup_match(make_user)
    p = ctx.a[1]
    prefs = {x["kind"]: x for x in (await p.req("GET", "/notifications/prefs")).json()}
    assert set(prefs) == set(KINDS) and prefs["over_complete"]["in_app"] is False and prefs["result"]["in_app"] is True
    assert (await p.req("PUT", "/notifications/prefs", json={"kind": "result", "in_app": False})).status_code == 204
    assert (await p.req("PUT", "/notifications/prefs", json={"kind": "result", "in_app": False})).status_code == 204  # idempotent
    assert (await p.req("PUT", "/notifications/prefs", json={"kind": "nonsense", "in_app": True})).status_code == 422
    after = {x["kind"]: x["in_app"] for x in (await p.req("GET", "/notifications/prefs")).json()}
    assert after["result"] is False
    # other people's choices are untouched
    other = {x["kind"]: x["in_app"] for x in (await ctx.b[1].req("GET", "/notifications/prefs")).json()}
    assert other["result"] is True


async def test_inbox_read_state_pagination_and_isolation(make_user, db):
    ctx = await setup_match(make_user)
    r = await rooms(db, ctx)
    for i in range(5):
        await ctx.admin.req("POST", f"/rooms/{r['season']}/announcements", json={"body": f"news {i}"})
    me = ctx.a[1]
    page = (await me.req("GET", "/notifications?limit=2")).json()
    assert [n["body"] for n in page["notifications"]] == ["news 4", "news 3"] and page["has_more"] and page["unread"] == 5
    older = (await me.req("GET", f"/notifications?limit=2&before={page['notifications'][-1]['id']}")).json()
    assert [n["body"] for n in older["notifications"]] == ["news 2", "news 1"]
    assert (await me.req("GET", "/notifications/unread-count")).json() == {"unread": 5}
    first = page["notifications"][0]["id"]
    assert (await me.req("POST", f"/notifications/{first}/read")).status_code == 204
    assert (await me.req("POST", f"/notifications/{first}/read")).status_code == 204  # idempotent
    assert (await me.req("GET", "/notifications/unread-count")).json() == {"unread": 4}
    # you cannot touch somebody else's notification, and it looks like it does not exist
    assert (await ctx.b[1].req("POST", f"/notifications/{first}/read")).status_code == 404
    assert (await ctx.b[1].req("GET", "/notifications/unread-count")).json() == {"unread": 5}
    assert all(n["id"] != first for n in (await ctx.b[1].req("GET", "/notifications")).json()["notifications"])
    assert (await me.req("POST", "/notifications/read-all")).status_code == 204
    assert (await me.req("GET", "/notifications/unread-count")).json() == {"unread": 0}
    assert (await ctx.b[1].req("GET", "/notifications/unread-count")).json() == {"unread": 5}  # not affected


async def test_notify_is_idempotent_per_key(make_user, db):
    ctx = await setup_match(make_user)
    me = ctx.a[1]
    for _ in range(3):  # a retried job asks again with the same key
        await notify(db, {me.id}, "result", "t", "b", {}, "job-1")
        await db.commit()
    assert await db.scalar(select(func.count()).select_from(Notification).where(Notification.dedupe_key == "job-1")) == 1
    await notify(db, {me.id}, "result", "t", "b", {}, "job-2")
    await db.commit()
    assert await db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id == me.id,
                                                                              Notification.kind == "result")) == 2


async def test_user_socket_delivers_only_your_notifications(make_user, db, ws_url):
    ctx = await setup_match(make_user)
    url = f"{ws_url}/ws/me"
    assert await closed_with(url, token="garbage") == 4401
    assert await closed_with(url) == 4401
    async with await connect(url, token_of(ctx.a[0])) as cap_a, await connect(url, token_of(ctx.a[1])) as other:
        hello = await next_of(cap_a, "hello")
        assert hello["unread"] == 0
        await next_of(other, "hello")
        await ctx.ump.req("POST", f"{ctx.url}/toss/open")  # notifies both captains
        ev = await next_of(cap_a, "notification")
        assert ev["notification"]["kind"] == "toss_ready" and ev["notification"]["read"] is False
        assert ev["notification"]["data"]["link"] == f"/matches/{ctx.match}"
        try:
            await recv(other, timeout=0.8)
            raise AssertionError("a non-captain received the captains' notification")
        except TimeoutError:
            pass
    # reconnecting later reports the unread count
    async with await connect(url, token_of(ctx.a[0])) as again:
        assert (await next_of(again, "hello"))["unread"] >= 1
    _ = json
