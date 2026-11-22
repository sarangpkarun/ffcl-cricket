from sqlalchemy import func, select

from app.db.models import BallEvent
from tests.helpers import BOWL_ALL_EQUAL, live, play, run_toss, setup_match, start


async def post(actor, ctx, path, **kw):
    return await actor.req("POST", f"{ctx.url}/{path}", **kw)


async def test_actions_out_of_order_are_rejected(make_user):
    ctx = await setup_match(make_user)
    u = ctx.ump
    # nothing works before the toss
    for path in ("start", "toss/confirm", "innings/next", "pause"):
        assert (await post(u, ctx, path)).status_code == 409, path
    assert (await post(u, ctx, "overs/start", json={"bowler_id": ctx.b[0].id, "batter_id": ctx.a[0].id})).status_code == 409
    assert (await post(u, ctx, "toss/open")).status_code == 204
    assert (await post(u, ctx, "toss/open")).status_code == 409  # twice
    batters, bowlers = await run_toss_after_open(ctx)
    assert (await post(u, ctx, "toss/open")).status_code == 409
    assert (await post(u, ctx, "innings/next")).status_code == 409  # not in a break
    await start(ctx)
    assert (await post(u, ctx, "start")).status_code == 409  # twice
    # inside an over: each step must follow the previous one
    await post(u, ctx, "overs/start", json={"bowler_id": bowlers[0].id, "batter_id": batters[0].id})
    assert (await post(u, ctx, "overs/current/lock")).status_code == 409  # before signal
    assert (await post(u, ctx, "overs/current/reveal")).status_code == 409
    assert (await post(u, ctx, "overs/current/resolve")).status_code == 409
    assert (await post(u, ctx, "overs/current/signal")).status_code == 204
    assert (await post(u, ctx, "overs/current/signal")).status_code == 409  # twice
    assert (await post(u, ctx, "overs/current/reveal")).status_code == 409  # before lock
    assert (await post(u, ctx, "overs/current/resolve")).status_code == 409  # before reveal
    # a resolved over leaves nothing to submit to
    await bowlers[0].req("POST", f"{ctx.url}/overs/current/submit", json={"digits": "123456"})
    await batters[0].req("POST", f"{ctx.url}/overs/current/submit", json={"digits": "561234"})
    for step in ("lock", "reveal", "resolve"):
        await post(u, ctx, f"overs/current/{step}")
    r = await bowlers[0].req("POST", f"{ctx.url}/overs/current/submit", json={"digits": "123456"})
    assert r.status_code == 409


async def run_toss_after_open(ctx):
    """Finish a toss that was already opened by the test."""
    await ctx.ump.req("POST", f"{ctx.url}/toss/winner", json={"winner_team_id": ctx.team_a})
    await ctx.a[0].req("POST", f"{ctx.url}/toss/decision", json={"decision": "bat"})
    assert (await ctx.ump.req("POST", f"{ctx.url}/toss/confirm")).status_code == 204
    return ctx.a, ctx.b


async def test_correction_cannot_reopen_innings_after_chase_started(make_user, db):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    await play(ctx, batters, bowlers, 1, bowl_digits=BOWL_ALL_EQUAL)
    await play(ctx, batters, bowlers, 2, bowl_digits=BOWL_ALL_EQUAL)  # all out for 0
    await post(ctx.ump, ctx, "innings/next")
    await play(ctx, bowlers, batters, 1)
    before = (await db.scalar(select(func.count()).select_from(BallEvent)))
    # un-wicketing innings 1's last wicket would reopen it while innings 2 has balls
    fix = {"innings_number": 1, "over_no": 2, "ball_no": 1, "batter_digit": 5, "bowler_digit": 4, "reason": "misread"}
    r = await post(ctx.ump, ctx, "balls/correct", json=fix)
    assert r.status_code == 409 and "reopen" in r.json()["detail"]
    assert (await db.scalar(select(func.count()).select_from(BallEvent))) == before  # nothing stored
    d = await live(ctx)
    assert d["innings"][0]["status"] == "completed" and d["innings"][0]["wickets"] == 7


async def test_penalty_needs_a_started_innings(make_user):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    await play(ctx, batters, bowlers, 1)
    body = {"team_id": ctx.team_b, "kind": "late_submission", "runs": 5, "reason": "not batting yet",
            "idempotency_key": "early-1"}
    assert (await post(ctx.ump, ctx, "penalties", json=body)).status_code == 409


async def test_admin_can_take_over_when_umpire_drops_mid_over(make_user):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    await post(ctx.ump, ctx, "overs/start", json={"bowler_id": bowlers[0].id, "batter_id": batters[0].id})
    await post(ctx.ump, ctx, "overs/current/signal")
    await bowlers[0].req("POST", f"{ctx.url}/overs/current/submit", json={"digits": "123456"})
    # the umpire vanishes here; the admin picks the over up from persisted state
    await batters[0].req("POST", f"{ctx.url}/overs/current/submit", json={"digits": "561234"})
    for step in ("lock", "reveal"):
        assert (await post(ctx.admin, ctx, f"overs/current/{step}")).status_code == 204
    r = await post(ctx.admin, ctx, "overs/current/resolve")
    assert r.status_code == 200 and r.json()["balls"] == 6
    # a random player still cannot drive the match
    assert (await post(batters[1], ctx, "overs/current/resolve")).status_code in (403, 409)
    assert (await post(batters[1], ctx, "pause")).status_code == 403


async def test_innings_break_blocks_play_until_resumed_and_started(make_user):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    for o in (1, 2):
        await play(ctx, batters, bowlers, o, bowl_digits=BOWL_ALL_EQUAL)
    d = await live(ctx)
    assert d["match"]["status"] == "break" and d["innings"][1]["status"] == "pending"
    r = await post(ctx.ump, ctx, "overs/start", json={"bowler_id": batters[0].id, "batter_id": bowlers[0].id})
    assert r.status_code == 409  # no innings in progress during the break
    assert (await post(ctx.ump, ctx, "pause")).status_code == 204
    assert (await post(ctx.ump, ctx, "innings/next")).status_code == 409  # paused
    await post(ctx.ump, ctx, "resume")
    assert (await post(ctx.ump, ctx, "innings/next")).status_code == 204


async def test_live_endpoint_is_cheap_and_complete(make_user, db):
    """Names are loaded only for players who appear on the scorecard."""
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    await play(ctx, batters, bowlers, 1)
    d = await live(ctx)
    inn = d["innings"][0]
    assert inn["batting"][0]["name"] and inn["bowling"][0]["name"]
    assert inn["timeline"][0]["over"] == 1 and len(inn["timeline"][0]["balls"]) == 6
