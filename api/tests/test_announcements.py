import pytest
from sqlalchemy import func, select

from app.db.models import BallEvent, ChatMessage, Over
from tests.helpers import (
    BAT,
    BOWL_ALL_EQUAL,
    BOWL_NO_EQUAL,
    live,
    play,
    run_toss,
    setup_match,
    start,
)
from tests.test_chat import rooms
from tests.ws_helpers import connect, next_of, token_of


async def feed(db, room_id, kind="system"):
    """Text of every system message in a room, oldest first."""
    db.expire_all()
    rows = await db.scalars(select(ChatMessage).where(ChatMessage.room_id == room_id, ChatMessage.kind == kind)
                            .order_by(ChatMessage.id))
    return [m.body for m in rows]


async def match_feed(make_user, db):
    ctx = await setup_match(make_user)
    r = await rooms(db, ctx)
    return ctx, r


async def test_full_match_produces_a_readable_feed(make_user, db):
    ctx, r = await match_feed(make_user, db)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    assert await feed(db, r["match"]) == ["🪙 Toss won by Pink.", "🏏 Pink elected to bat first."]
    await start(ctx)
    await play(ctx, batters, bowlers, 1)  # 21 runs, a six on ball 2, no wicket
    names = {p.id: p for p in ctx.a + ctx.b}
    bowler, batter = (await live(ctx))["innings"][0]["bowling"][0]["name"], (await live(ctx))["innings"][0]["batting"][0]["name"]
    msgs = await feed(db, r["match"])
    assert msgs[2] == "🎾 First innings started. Pink are batting."
    assert msgs[3] == f"🔔 Over 1: {bowler} bowls to {batter}. Submissions are open."
    assert msgs[4] == f"🔥 {batter} scored 6 runs (1.2)."
    assert msgs[5] == "📊 Over 1 done: 21 runs, 0 wickets. Pink 21/0 (1.0 ov)."
    assert len(msgs) == 6 and names  # exactly one six, and nothing else
    # over 2 is the bowling powerplay: announced, and a wicket on ball 1 is called out
    await play(ctx, batters, bowlers, 2, bowl_digits=[5, 2, 2, 1, 4, 3])
    msgs = await feed(db, r["match"])
    assert "⚡ Bowling powerplay: the batter must use 5 and 6 once each." in msgs[6]
    assert any(m.startswith("❌") and m.endswith("is OUT (2.1).") for m in msgs)
    assert msgs[-1].startswith("📊 Over 2 done:") and "1 wicket." in msgs[-1]


async def test_all_out_break_second_innings_and_result_lines(make_user, db):
    ctx, r = await match_feed(make_user, db)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    await play(ctx, batters, bowlers, 1, bowl_digits=BOWL_ALL_EQUAL)
    await play(ctx, batters, bowlers, 2, bowl_digits=BOWL_ALL_EQUAL)  # 7th wicket on ball 1
    assert (await feed(db, r["match"]))[-1] == "🏁 Pink finished on 0/7 (1.1 ov). Green need 1 to win."
    await ctx.ump.req("POST", f"{ctx.url}/innings/next")
    assert (await feed(db, r["match"]))[-1] == "🎾 Second innings started. Green need 1 to win."
    await play(ctx, bowlers, batters, 1)  # first ball scores, chase done
    msgs = await feed(db, r["match"])
    assert msgs[-1] == "🏆 Green won by 7 wickets"
    assert "📊 Over 1 done: 5 runs, 0 wickets. Green 5/0 (0.1 ov)." in msgs


async def test_hidden_digits_never_reach_the_feed(make_user, db):
    ctx, r = await match_feed(make_user, db)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    bowler, batter = bowlers[0], batters[0]
    await ctx.ump.req("POST", f"{ctx.url}/overs/start", json={"bowler_id": bowler.id, "batter_id": batter.id})
    await ctx.ump.req("POST", f"{ctx.url}/overs/current/signal")
    await bowler.req("POST", f"{ctx.url}/overs/current/submit", json={"digits": "652143"})
    await batter.req("POST", f"{ctx.url}/overs/current/submit", json={"digits": "561234"})
    before = await feed(db, r["match"])
    assert before[-1].startswith("🔔 Over 1")  # nothing about the over's outcome while digits are hidden
    await ctx.ump.req("POST", f"{ctx.url}/overs/current/lock")
    await ctx.ump.req("POST", f"{ctx.url}/overs/current/reveal")
    assert await feed(db, r["match"]) == before  # still nothing between signal and resolve
    await ctx.ump.req("POST", f"{ctx.url}/overs/current/resolve")
    for text in await feed(db, r["match"]):
        assert "652143" not in text and "561234" not in text and not any(c in text for c in ("6️⃣", "5️⃣"))


async def test_umpire_channel_gets_the_details_players_never_see(make_user, db):
    ctx, r = await match_feed(make_user, db)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    bowler, batter = bowlers[0], batters[0]
    await ctx.ump.req("POST", f"{ctx.url}/overs/start", json={"bowler_id": bowler.id, "batter_id": batter.id})
    await ctx.ump.req("POST", f"{ctx.url}/overs/current/signal")
    await bowler.req("POST", f"{ctx.url}/overs/current/submit", json={"digits": "123456"})
    await ctx.ump.req("POST", f"{ctx.url}/overs/current/override",
                      json={"role": "bat", "digits": "561234", "reason": "batter's phone died"})
    for step in ("lock", "reveal", "resolve"):
        await ctx.ump.req("POST", f"{ctx.url}/overs/current/{step}")
    pen = await ctx.ump.req("POST", f"{ctx.url}/penalties", json={
        "team_id": ctx.team_a, "kind": "late_submission", "runs": 6, "reason": "digits sent late", "idempotency_key": "p-feed-1"})
    await ctx.ump.req("POST", f"{ctx.url}/balls/correct", json={
        "innings_number": 1, "over_no": 1, "ball_no": 1, "batter_digit": 5, "bowler_digit": 5, "reason": "misread"})
    await ctx.ump.req("POST", f"{ctx.url}/penalties/{pen.json()['id']}/void", json={"reason": "wrong team"})
    umpire = await feed(db, r["umpire"])
    assert any("entered the batter's digits for over 1 on their behalf. Reason: batter's phone died" in m for m in umpire)
    assert any("applied penalty 'late_submission' to Pink (runs +6, wickets 0). Reason: digits sent late" in m for m in umpire)
    assert any("corrected innings 1, over 1, ball 1: 5 run(s) → 0 run(s) (wicket). Reason: misread" in m for m in umpire)
    assert any("cancelled penalty" in m and "Reason: wrong team" in m for m in umpire)
    match_msgs = await feed(db, r["match"])
    # players see the outcome of these decisions but not the umpire's internal reasons
    assert "📢 6 penalty runs awarded to Pink: digits sent late." in match_msgs
    assert "📢 A penalty against Pink was cancelled by the umpire." in match_msgs
    assert "🛠 The umpire corrected a ball (innings 1, over 1.1)." in match_msgs
    assert not any("phone died" in m or "misread" in m or "wrong team" in m for m in match_msgs)
    assert (await ctx.a[1].req("GET", f"/rooms/{r['umpire']}/messages")).status_code == 404
    assert (await ctx.ump.req("GET", f"/rooms/{r['umpire']}/messages")).status_code == 200


async def test_penalty_wording_and_pause_lines(make_user, db):
    ctx, r = await match_feed(make_user, db)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    await play(ctx, batters, bowlers, 1)
    await ctx.ump.req("POST", f"{ctx.url}/pause")
    await ctx.ump.req("POST", f"{ctx.url}/resume")
    for i, body in enumerate(({"runs": -2, "reason": "slow over rate"}, {"wickets": 1, "reason": "no batter"},
                              {"runs": 1, "reason": "wide"}, {"runs": 3, "wickets": 2, "reason": "both"})):
        await ctx.ump.req("POST", f"{ctx.url}/penalties", json={
            "team_id": ctx.team_a, "kind": "rule_breach", "idempotency_key": f"pen-wording-{i}", **body})
    msgs = await feed(db, r["match"])
    assert "⏸ The match is paused by the umpire." in msgs and "▶ The match has resumed." in msgs
    assert "📢 2 penalty runs deducted from Pink: slow over rate." in msgs
    assert "📢 1 penalty wicket charged to Pink: no batter." in msgs
    assert "📢 1 penalty run awarded to Pink: wide." in msgs
    assert "📢 3 penalty runs awarded to Pink and 2 penalty wickets charged to Pink: both." in msgs


async def test_correction_withdraws_and_restores_a_result(make_user, db):
    ctx, r = await match_feed(make_user, db)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    await play(ctx, batters, bowlers, 1, bowl_digits=BOWL_ALL_EQUAL)
    await play(ctx, batters, bowlers, 2, bowl_digits=BOWL_ALL_EQUAL)
    await ctx.ump.req("POST", f"{ctx.url}/innings/next")
    await play(ctx, bowlers, batters, 1)
    fix = {"innings_number": 2, "over_no": 1, "ball_no": 1, "batter_digit": 5, "bowler_digit": 5, "reason": "misread"}
    await ctx.ump.req("POST", f"{ctx.url}/balls/correct", json=fix)
    msgs = await feed(db, r["match"])
    assert msgs[-1] == "🛠 The result was withdrawn after a correction. The match continues."
    assert sum(1 for m in msgs if m.startswith("🏆")) == 1


async def test_a_failed_request_leaves_no_announcements_behind(make_user, db, monkeypatch):
    """The announcement and the state change commit together or not at all."""
    ctx, r = await match_feed(make_user, db)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    bowler, batter = bowlers[0], batters[0]
    await ctx.ump.req("POST", f"{ctx.url}/overs/start", json={"bowler_id": bowler.id, "batter_id": batter.id})
    await ctx.ump.req("POST", f"{ctx.url}/overs/current/signal")
    await bowler.req("POST", f"{ctx.url}/overs/current/submit", json={"digits": "652143"})
    await batter.req("POST", f"{ctx.url}/overs/current/submit", json={"digits": "561234"})
    for step in ("lock", "reveal"):
        await ctx.ump.req("POST", f"{ctx.url}/overs/current/{step}")
    before = await feed(db, r["match"])

    async def boom(*a, **k):
        raise RuntimeError("database fell over")

    monkeypatch.setattr("app.routers.play.recompute", boom)
    with pytest.raises(RuntimeError):
        await ctx.ump.req("POST", f"{ctx.url}/overs/current/resolve")
    monkeypatch.undo()
    assert await feed(db, r["match"]) == before
    db.expire_all()
    assert await db.scalar(select(func.count()).select_from(BallEvent)) == 0
    assert (await db.scalar(select(Over.state))) == "revealed"
    # and the retry works normally
    assert (await ctx.ump.req("POST", f"{ctx.url}/overs/current/resolve")).status_code == 200
    assert (await feed(db, r["match"]))[-1].startswith("📊 Over 1 done")


async def test_announcements_are_pushed_live_after_commit(make_user, db, ws_url):
    ctx, r = await match_feed(make_user, db)
    fan = ctx.a[1]
    async with await connect(f"{ws_url}/ws/rooms/{r['match']}", token_of(fan)) as w, \
            await connect(f"{ws_url}/ws/rooms/{r['umpire']}", token_of(ctx.ump)) as wu:
        await next_of(w, "hello")
        await next_of(wu, "hello")
        await run_toss(ctx, "a", "bat")
        first = await next_of(w, "message")
        second = await next_of(w, "message")
        assert (first["message"]["kind"], first["message"]["sender"]) == ("system", None)
        assert [first["message"]["body"], second["message"]["body"]] == ["🪙 Toss won by Pink.", "🏏 Pink elected to bat first."]
        assert first["message"]["id"] < second["message"]["id"]
    _ = (BAT, BOWL_NO_EQUAL)
