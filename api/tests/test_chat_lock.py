from tests.helpers import play, run_toss, setup_match, start
from tests.test_chat import cid, rooms
from tests.ws_helpers import connect, next_of, token_of


def say(actor, room, text="hi"):
    return actor.req("POST", f"/rooms/{room}/messages", json={"body": text, "client_id": cid()})


async def open_over(ctx, batters, bowlers):
    await ctx.ump.req("POST", f"{ctx.url}/overs/start", json={"bowler_id": bowlers[0].id, "batter_id": batters[0].id})
    await ctx.ump.req("POST", f"{ctx.url}/overs/current/signal")
    return bowlers[0], batters[0]


async def test_pair_is_locked_out_only_while_submissions_are_open(make_user, db):
    ctx = await setup_match(make_user)
    r = await rooms(db, ctx)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    bowler, batter = bowlers[0], batters[0]
    mate, rival = batters[1], bowlers[1]
    earlier = (await say(batter, r["match"], "good luck")).json()
    await ctx.ump.req("POST", f"{ctx.url}/overs/start", json={"bowler_id": bowler.id, "batter_id": batter.id})
    # the over exists but has not been signalled: chat is open for everybody
    assert (await say(bowler, r["match"], "before the signal")).status_code == 201
    await ctx.ump.req("POST", f"{ctx.url}/overs/current/signal")
    # now the bowler and the batter are blocked from posting, reacting and editing
    for p in (bowler, batter):
        blocked = await say(p, r["match"], "psst")
        assert blocked.status_code == 403 and "Chat is paused for you" in blocked.json()["detail"]
        info = (await p.req("GET", f"/rooms/{r['match']}")).json()
        assert info["can_post"] is False and "paused" in info["blocked_reason"]
    assert (await batter.req("POST", f"/rooms/{r['match']}/messages/{earlier['id']}/reactions", json={"emoji": "🔥"})).status_code == 403
    assert (await batter.req("PATCH", f"/rooms/{r['match']}/messages/{earlier['id']}", json={"body": "edited"})).status_code == 403
    # reading is not blocked, and neither is the season chat
    assert (await bowler.req("GET", f"/rooms/{r['match']}/messages")).status_code == 200
    assert (await say(bowler, r["season"], "season chat is fine")).status_code == 201
    # everyone else, including the umpire and the admin, chats normally
    for p in (mate, rival, ctx.ump, ctx.admin):
        assert (await say(p, r["match"], "go on lads")).status_code == 201
    assert (await mate.req("GET", f"/rooms/{r['match']}")).json()["can_post"] is True
    # submissions close: the pair can talk again
    for p, d in ((bowler, "652143"), (batter, "561234")):
        await p.req("POST", f"{ctx.url}/overs/current/submit", json={"digits": d})
    await ctx.ump.req("POST", f"{ctx.url}/overs/current/lock")
    assert (await say(batter, r["match"], "done")).status_code == 201
    assert (await batter.req("GET", f"/rooms/{r['match']}")).json()["can_post"] is True


async def test_lock_is_per_over_not_per_match(make_user, db):
    ctx = await setup_match(make_user)
    r = await rooms(db, ctx)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    await play(ctx, batters, bowlers, 1)
    # over 1 is finished; over 2 uses a different pair, so over 1's pair is free
    await ctx.ump.req("POST", f"{ctx.url}/overs/start", json={"bowler_id": bowlers[1].id, "batter_id": batters[1].id})
    await ctx.ump.req("POST", f"{ctx.url}/overs/current/signal")
    assert (await say(bowlers[0], r["match"], "I bowled the last one")).status_code == 201
    assert (await say(batters[0], r["match"], "so did I bat")).status_code == 201
    assert (await say(bowlers[1], r["match"], "my turn")).status_code == 403
    assert (await say(batters[1], r["match"], "my turn")).status_code == 403


async def test_lock_changes_are_pushed_so_the_composer_updates(make_user, db, ws_url):
    ctx = await setup_match(make_user)
    r = await rooms(db, ctx)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    async with await connect(f"{ws_url}/ws/rooms/{r['match']}", token_of(batters[0])) as w:
        await next_of(w, "hello")
        bowler, batter = await open_over(ctx, batters, bowlers)
        assert (await next_of(w, "room_state"))["type"] == "room_state"  # the lock switched on
        for p, d in ((bowler, "652143"), (batter, "561234")):
            await p.req("POST", f"{ctx.url}/overs/current/submit", json={"digits": d})
        await ctx.ump.req("POST", f"{ctx.url}/overs/current/lock")
        assert (await next_of(w, "room_state"))["type"] == "room_state"  # and off again
