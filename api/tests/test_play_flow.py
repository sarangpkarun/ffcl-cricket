import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import AuditLog, BallEvent, Over
from tests.helpers import BOWL_ALL_EQUAL, live, play, run_toss, setup_match, start


# ---------- toss ----------
async def test_toss_requires_lineups_and_officials(make_user):
    ctx = await setup_match(make_user, lineups=False)
    r = await ctx.ump.req("POST", f"{ctx.url}/toss/open")
    assert r.status_code == 409  # no lineups yet
    ctx = await setup_match(make_user)
    stranger = await make_user("Stranger")
    assert (await stranger.req("POST", f"{ctx.url}/toss/open")).status_code == 403
    assert (await ctx.ump.req("POST", f"{ctx.url}/toss/open")).status_code == 204
    # losing captain cannot choose; winning captain can
    await ctx.ump.req("POST", f"{ctx.url}/toss/winner", json={"winner_team_id": ctx.team_a})
    r = await ctx.b[0].req("POST", f"{ctx.url}/toss/decision", json={"decision": "bat"})
    assert r.status_code == 403
    r = await ctx.a[0].req("POST", f"{ctx.url}/toss/decision", json={"decision": "bowl"})
    assert r.status_code == 204
    assert (await ctx.ump.req("POST", f"{ctx.url}/toss/confirm")).status_code == 204
    data = await live(ctx)
    assert data["match"]["status"] == "ready"
    assert data["toss"] == {"winner_team_id": ctx.team_a, "decision": "bowl"}


async def test_confirm_needs_winner_and_decision(make_user):
    ctx = await setup_match(make_user)
    await ctx.ump.req("POST", f"{ctx.url}/toss/open")
    assert (await ctx.ump.req("POST", f"{ctx.url}/toss/confirm")).status_code == 409


# ---------- full match ----------
async def test_full_match_defended_by_runs(make_user):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    for o in range(1, 8):
        await play(ctx, batters, bowlers, o)  # 21 per over
    d = await live(ctx)
    assert d["match"]["status"] == "break"
    i1 = d["innings"][0]
    assert (i1["runs"], i1["wickets"], i1["overs"], i1["status"]) == (147, 0, "7.0", "completed")
    assert d["innings"][1]["target"] == 148
    await ctx.ump.req("POST", f"{ctx.url}/innings/next")
    # chase: last ball of first over is a wicket (4 vs 4) -> 17 runs that over
    await play(ctx, bowlers, batters, 1, bowl_digits=[6, 5, 2, 1, 4, 4], bat_digits=[5, 6, 1, 2, 3, 4])
    for o in range(2, 8):
        await play(ctx, bowlers, batters, o)
    d = await live(ctx)
    assert d["match"]["status"] == "completed"
    assert d["match"]["result"] == "Pink won by 4 runs"
    assert d["match"]["winner_team_id"] == ctx.team_a
    i2 = d["innings"][1]
    assert (i2["runs"], i2["wickets"]) == (143, 1)
    # individual stats reconcile with team total
    assert sum(b["runs"] for b in i2["batting"]) == i2["runs"]
    assert sum(b["wickets"] for b in i2["bowling"]) == 1
    # a bowler never bowls more than 2 overs
    assert all(float(b["overs"]) <= 2 for b in d["innings"][0]["bowling"])


async def test_all_out_then_chase_ends_mid_over(make_user):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    await play(ctx, batters, bowlers, 1, bowl_digits=BOWL_ALL_EQUAL)  # 6 wickets
    r = await play(ctx, batters, bowlers, 2, bowl_digits=BOWL_ALL_EQUAL)  # 7th wicket on ball 1
    assert r["balls"] == 1 and r["match_status"] == "break"
    d = await live(ctx)
    assert d["innings"][0]["finish_reason"] == "all_out" and d["innings"][0]["runs"] == 0
    assert d["innings"][1]["target"] == 1
    await ctx.ump.req("POST", f"{ctx.url}/innings/next")
    r = await play(ctx, bowlers, batters, 1)  # first ball scores 5 -> chase done
    assert r["balls"] == 1 and r["match_status"] == "completed"
    assert r["result"] == "Green won by 7 wickets"


async def test_tie(make_user):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    await play(ctx, batters, bowlers, 1, bowl_digits=BOWL_ALL_EQUAL)
    await play(ctx, batters, bowlers, 2, bowl_digits=BOWL_ALL_EQUAL)  # all out for 0
    await ctx.ump.req("POST", f"{ctx.url}/innings/next")
    for o in range(1, 3):
        await play(ctx, bowlers, batters, o, bowl_digits=BOWL_ALL_EQUAL)
    d = await live(ctx)
    assert d["match"]["status"] == "completed"
    assert d["match"]["result"] == "match tied" and d["match"]["winner_team_id"] is None


# ---------- privacy ----------
async def test_digits_stay_private_until_reveal(make_user):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    bowler, batter = bowlers[0], batters[0]
    spectator = await make_user("Fan")
    u = ctx.ump
    await u.req("POST", f"{ctx.url}/overs/start", json={"bowler_id": bowler.id, "batter_id": batter.id})
    await u.req("POST", f"{ctx.url}/overs/current/signal")
    await bowler.req("POST", f"{ctx.url}/overs/current/submit", json={"digits": "654321"})
    await batter.req("POST", f"{ctx.url}/overs/current/submit", json={"digits": "112233"})

    def blob(d):
        return str(d["over"])

    for who in (batter, spectator, bowlers[1], batters[1]):
        o = (await live(ctx, who))["over"]
        assert o["submitted"] == {"bat": True, "bowl": True} and o["digits"] is None
    # batter sees only their own digits
    o = (await live(ctx, batter))["over"]
    assert o["mine"] == [1, 1, 2, 2, 3, 3] and "6, 5, 4, 3, 2, 1" not in blob(await live(ctx, batter))
    o = (await live(ctx, bowler))["over"]
    assert o["mine"] == [6, 5, 4, 3, 2, 1] and "1, 1, 2, 2, 3, 3" not in blob(await live(ctx, bowler))
    # official sees nothing until the window is locked
    assert (await live(ctx))["over"]["digits"] is None
    await u.req("POST", f"{ctx.url}/overs/current/lock")
    assert (await live(ctx))["over"]["digits"] == {"bat": [1, 1, 2, 2, 3, 3], "bowl": [6, 5, 4, 3, 2, 1]}
    assert (await live(ctx, spectator))["over"]["digits"] is None
    assert (await live(ctx, batter))["over"]["digits"] is None
    await u.req("POST", f"{ctx.url}/overs/current/reveal")
    for who in (batter, spectator):
        assert (await live(ctx, who))["over"]["digits"]["bowl"] == [6, 5, 4, 3, 2, 1]


# ---------- submission validation ----------
async def _open_over(ctx, batters, bowlers, n=1):
    bowler, batter = bowlers[(n - 1) % 4], batters[(n - 1) % 4]
    await ctx.ump.req("POST", f"{ctx.url}/overs/start", json={"bowler_id": bowler.id, "batter_id": batter.id})
    return bowler, batter


async def test_submission_gating_and_validation(make_user):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    bowler, _ = await _open_over(ctx, batters, bowlers)
    sub = f"{ctx.url}/overs/current/submit"
    # before the umpire signal
    assert (await bowler.req("POST", sub, json={"digits": "123456"})).status_code == 409
    await ctx.ump.req("POST", f"{ctx.url}/overs/current/signal")
    # not part of this over
    assert (await bowlers[1].req("POST", sub, json={"digits": "123456"})).status_code == 403
    assert (await batters[1].req("POST", sub, json={"digits": "123456"})).status_code == 403
    # invalid shapes
    for bad, code in (("12345", "invalid_count"), ("123450", "invalid_digit"),
                      ("111122", "repeat_limit"), ("111222", "repeat_limit")):
        r = await bowler.req("POST", sub, json={"digits": bad})
        assert r.status_code == 422 and code in str(r.json()), (bad, r.text)
    r = await bowler.req("POST", sub, json={"digits": "12ab56"})
    assert r.status_code == 422
    # emoji digits accepted, and idempotent resend of the same digits
    ok = await bowler.req("POST", sub, json={"digits": "1️⃣1️⃣2️⃣2️⃣3️⃣4️⃣"})
    assert ok.status_code == 200 and ok.json()["status"] == "submitted"
    again = await bowler.req("POST", sub, json={"digits": "112234"})
    assert again.status_code == 200 and again.json()["status"] == "already_submitted"
    # a different second submission is rejected: locked after the first
    assert (await bowler.req("POST", sub, json={"digits": "654321"})).status_code == 409
    # lock refuses until the batter has submitted
    assert (await ctx.ump.req("POST", f"{ctx.url}/overs/current/lock")).status_code == 409


async def test_powerplay_rules_enforced_per_side(make_user):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    await play(ctx, batters, bowlers, 1)
    bowler, batter = await _open_over(ctx, batters, bowlers, 2)  # over 2: batter restricted
    await ctx.ump.req("POST", f"{ctx.url}/overs/current/signal")
    sub = f"{ctx.url}/overs/current/submit"
    r = await batter.req("POST", sub, json={"digits": "111111"})
    assert r.status_code == 422 and "pp_requires_5_and_6" in str(r.json())
    assert (await bowler.req("POST", sub, json={"digits": "111111"})).status_code == 422  # repeat cap
    assert (await bowler.req("POST", sub, json={"digits": "123123"})).status_code == 200
    assert (await batter.req("POST", sub, json={"digits": "561111"})).status_code == 200
    await ctx.ump.req("POST", f"{ctx.url}/overs/current/lock")
    await ctx.ump.req("POST", f"{ctx.url}/overs/current/reveal")
    await ctx.ump.req("POST", f"{ctx.url}/overs/current/resolve")
    for o in (3, 4, 5):
        await play(ctx, batters, bowlers, o)
    bowler, batter = await _open_over(ctx, batters, bowlers, 6)  # over 6: bowler restricted
    await ctx.ump.req("POST", f"{ctx.url}/overs/current/signal")
    r = await bowler.req("POST", sub, json={"digits": "123123"})
    assert r.status_code == 422 and "pp_requires_5_and_6" in str(r.json())
    assert (await batter.req("POST", sub, json={"digits": "111111"})).status_code == 200  # batter free


async def test_unverified_phone_cannot_submit(make_user, db):
    from app.db.models import User

    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    bowler, _ = await _open_over(ctx, batters, bowlers)
    await ctx.ump.req("POST", f"{ctx.url}/overs/current/signal")
    (await db.get(User, bowler.id)).phone_verified = False
    await db.commit()
    r = await bowler.req("POST", f"{ctx.url}/overs/current/submit", json={"digits": "123456"})
    assert r.status_code == 403 and "mobile" in r.json()["detail"]


async def test_deadline_and_umpire_override_is_audited(make_user, db):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    bowler, batter = await _open_over(ctx, batters, bowlers)
    await ctx.ump.req("POST", f"{ctx.url}/overs/current/signal")
    over = (await db.scalars(select(Over))).one()
    over.deadline_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    r = await batter.req("POST", f"{ctx.url}/overs/current/submit", json={"digits": "561234"})
    assert r.status_code == 409 and "deadline" in r.json()["detail"]
    # umpire enters digits on the late player's behalf, with a reason
    assert (await ctx.ump.req("POST", f"{ctx.url}/overs/current/override",
                              json={"role": "bat", "digits": "561234", "reason": "phone died"})).status_code == 204
    assert (await ctx.ump.req("POST", f"{ctx.url}/overs/current/override",
                              json={"role": "bowl", "digits": "123456", "reason": "late"})).status_code == 204
    # override still validates, and requires a reason
    r = await ctx.ump.req("POST", f"{ctx.url}/overs/current/override",
                          json={"role": "bowl", "digits": "111111", "reason": "x" * 5})
    assert r.status_code == 422
    r = await ctx.ump.req("POST", f"{ctx.url}/overs/current/override",
                          json={"role": "bat", "digits": "561234", "reason": ""})
    assert r.status_code == 422
    assert (await ctx.ump.req("POST", f"{ctx.url}/overs/current/lock")).status_code == 204
    logs = list(await db.scalars(select(AuditLog).where(AuditLog.action == "digits.override")))
    assert len(logs) == 2 and logs[0].reason == "phone died" and logs[0].actor_id == ctx.ump.id
    # players can't use the override
    assert (await bowler.req("POST", f"{ctx.url}/overs/current/override",
                             json={"role": "bat", "digits": "561234", "reason": "cheat"})).status_code == 403


# ---------- over / bowler rules ----------
async def test_third_over_and_overlap_blocked(make_user):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    await _open_over(ctx, batters, bowlers, 1)
    # can't start another over while one is in progress
    r = await ctx.ump.req("POST", f"{ctx.url}/overs/start",
                          json={"bowler_id": bowlers[1].id, "batter_id": batters[0].id})
    assert r.status_code == 409
    await ctx.ump.req("POST", f"{ctx.url}/overs/current/signal")
    for p, d in ((bowlers[0], "123456"), (batters[0], "561234")):
        await p.req("POST", f"{ctx.url}/overs/current/submit", json={"digits": d})
    for step in ("lock", "reveal", "resolve"):
        await ctx.ump.req("POST", f"{ctx.url}/overs/current/{step}")
    await play(ctx, batters, bowlers, 2)
    await play(ctx, batters, bowlers, 3)
    await play(ctx, batters, bowlers, 4)
    await play(ctx, batters, bowlers, 5)  # bowler 0 bowls over 5 (their 2nd)
    await play(ctx, batters, bowlers, 6)
    await play(ctx, batters, bowlers, 7)
    # force a third over for bowlers[0] in a fresh match
    ctx2 = await setup_match(make_user)
    b2, bw2 = await run_toss(ctx2, "a", "bat")
    await start(ctx2)
    for n in (1, 2):
        r = await ctx2.ump.req("POST", f"{ctx2.url}/overs/start",
                               json={"bowler_id": bw2[0].id, "batter_id": b2[0].id})
        assert r.status_code == 201, r.text
        await ctx2.ump.req("POST", f"{ctx2.url}/overs/current/signal")
        await bw2[0].req("POST", f"{ctx2.url}/overs/current/submit", json={"digits": "123456"})
        await b2[0].req("POST", f"{ctx2.url}/overs/current/submit", json={"digits": "561234"})
        for step in ("lock", "reveal", "resolve"):
            await ctx2.ump.req("POST", f"{ctx2.url}/overs/current/{step}")
    r = await ctx2.ump.req("POST", f"{ctx2.url}/overs/start",
                           json={"bowler_id": bw2[0].id, "batter_id": b2[0].id})
    assert r.status_code == 409 and "already bowled" in r.json()["detail"]
    # wrong team's player as bowler
    r = await ctx2.ump.req("POST", f"{ctx2.url}/overs/start",
                           json={"bowler_id": b2[1].id, "batter_id": b2[0].id})
    assert r.status_code == 400


# ---------- pause ----------
async def test_pause_blocks_play_and_resumes(make_user):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    bowler, _ = await _open_over(ctx, batters, bowlers)
    await ctx.ump.req("POST", f"{ctx.url}/overs/current/signal")
    assert (await ctx.ump.req("POST", f"{ctx.url}/pause")).status_code == 204
    r = await bowler.req("POST", f"{ctx.url}/overs/current/submit", json={"digits": "123456"})
    assert r.status_code == 409 and "paused" in r.json()["detail"]
    assert (await live(ctx))["match"]["paused"] is True
    await ctx.ump.req("POST", f"{ctx.url}/resume")
    r = await bowler.req("POST", f"{ctx.url}/overs/current/submit", json={"digits": "123456"})
    assert r.status_code == 200


# ---------- concurrency / duplicates ----------
async def test_double_resolve_never_duplicates_balls(make_user, db):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    bowler, batter = await _open_over(ctx, batters, bowlers)
    await ctx.ump.req("POST", f"{ctx.url}/overs/current/signal")
    await bowler.req("POST", f"{ctx.url}/overs/current/submit", json={"digits": "623541"})
    await batter.req("POST", f"{ctx.url}/overs/current/submit", json={"digits": "561234"})
    for step in ("lock", "reveal"):
        await ctx.ump.req("POST", f"{ctx.url}/overs/current/{step}")
    rs = await asyncio.gather(*[ctx.ump.req("POST", f"{ctx.url}/overs/current/resolve") for _ in range(4)])
    assert sorted(r.status_code for r in rs).count(200) == 1
    assert len(list(await db.scalars(select(BallEvent)))) == 6


async def test_simultaneous_submissions_both_accepted_once(make_user, db):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    bowler, batter = await _open_over(ctx, batters, bowlers)
    await ctx.ump.req("POST", f"{ctx.url}/overs/current/signal")
    url = f"{ctx.url}/overs/current/submit"
    rs = await asyncio.gather(
        bowler.req("POST", url, json={"digits": "123456"}),
        batter.req("POST", url, json={"digits": "561234"}),
        bowler.req("POST", url, json={"digits": "123456"}),
    )
    assert [r.status_code for r in rs] == [200, 200, 200]
    d = await live(ctx)
    assert d["over"]["submitted"] == {"bat": True, "bowl": True}
    from app.db.models import DigitSubmission

    assert len(list(await db.scalars(select(DigitSubmission)))) == 2


# ---------- penalties ----------
async def test_penalty_is_idempotent_and_excluded_from_player_stats(make_user):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    await play(ctx, batters, bowlers, 1)  # 21
    body = {"team_id": ctx.team_a, "kind": "late_submission", "runs": 6, "reason": "late digits",
            "idempotency_key": "pen-0001"}
    r1 = await ctx.ump.req("POST", f"{ctx.url}/penalties", json=body)
    r2 = await ctx.ump.req("POST", f"{ctx.url}/penalties", json=body)  # retry: no second penalty
    assert r1.status_code == 201 and r2.json()["duplicate"] is True
    d = await live(ctx)
    i = d["innings"][0]
    assert i["runs"] == 27 and i["extras"] == 6
    assert sum(b["runs"] for b in i["batting"]) == 21  # player stats unaffected
    assert sum(b["runs"] for b in i["bowling"]) == 21
    assert len(i["penalties"]) == 1
    pid = r1.json()["id"]
    assert (await ctx.ump.req("POST", f"{ctx.url}/penalties/{pid}/void", json={"reason": "wrong team"})).status_code == 204
    assert (await live(ctx))["innings"][0]["runs"] == 21
    # players cannot apply penalties; zero penalty rejected
    assert (await ctx.a[0].req("POST", f"{ctx.url}/penalties", json={**body, "idempotency_key": "pen-0002"})).status_code == 403
    r = await ctx.ump.req("POST", f"{ctx.url}/penalties", json={**body, "runs": 0, "idempotency_key": "pen-0003"})
    assert r.status_code == 400


async def test_penalty_wicket_counts_for_team_only(make_user):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    await play(ctx, batters, bowlers, 1)
    body = {"team_id": ctx.team_a, "kind": "no_batter", "wickets": 1, "reason": "missing batter",
            "idempotency_key": "pen-wkt-1"}
    assert (await ctx.ump.req("POST", f"{ctx.url}/penalties", json=body)).status_code == 201
    i = (await live(ctx))["innings"][0]
    assert i["wickets"] == 1 and sum(b["wickets"] for b in i["bowling"]) == 0


async def test_penalty_can_decide_the_match(make_user):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    await play(ctx, batters, bowlers, 1, bowl_digits=BOWL_ALL_EQUAL)
    await play(ctx, batters, bowlers, 2, bowl_digits=BOWL_ALL_EQUAL)  # innings 1: 0 all out
    await ctx.ump.req("POST", f"{ctx.url}/innings/next")
    await play(ctx, bowlers, batters, 1, bowl_digits=BOWL_ALL_EQUAL)  # 6 wickets, 0 runs
    # penalty of 1 run to Green (chasing team) reaches target 1 -> match ends
    r = await ctx.ump.req("POST", f"{ctx.url}/penalties", json={
        "team_id": ctx.team_b, "kind": "rule_breach", "runs": 1, "reason": "rule breach", "idempotency_key": "pen-win-1"})
    assert r.status_code == 201 and r.json()["match_status"] == "completed"
    assert (await live(ctx))["match"]["result"].startswith("Green won")


# ---------- corrections ----------
async def test_correction_recomputes_and_audits(make_user, db):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    await play(ctx, batters, bowlers, 1)  # ball 1: bat 5 vs bowl 6 = 5 runs
    fix = {"innings_number": 1, "over_no": 1, "ball_no": 1, "batter_digit": 5, "bowler_digit": 5,
           "reason": "bowler digit misread"}
    r = await ctx.ump.req("POST", f"{ctx.url}/balls/correct", json=fix)
    assert r.status_code == 201 and r.json()["revision"] == 2
    i = (await live(ctx))["innings"][0]
    assert i["runs"] == 16 and i["wickets"] == 1  # 5 runs removed, wicket added
    assert i["timeline"][0]["balls"][0]["wicket"] is True
    log = (await db.scalars(select(AuditLog).where(AuditLog.action == "ball.correct"))).one()
    assert log.reason == "bowler digit misread" and log.before["runs"] == 5 and log.after["runs"] == 0
    # original ball event is preserved (append-only)
    assert len(list(await db.scalars(select(BallEvent)))) == 7
    # unknown ball, bad reason, and non-officials rejected
    assert (await ctx.ump.req("POST", f"{ctx.url}/balls/correct", json={**fix, "over_no": 5})).status_code == 404
    assert (await ctx.ump.req("POST", f"{ctx.url}/balls/correct", json={**fix, "reason": ""})).status_code == 422
    assert (await ctx.a[0].req("POST", f"{ctx.url}/balls/correct", json=fix)).status_code == 403


async def test_correction_flips_completed_result(make_user):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    await play(ctx, batters, bowlers, 1, bowl_digits=BOWL_ALL_EQUAL)
    await play(ctx, batters, bowlers, 2, bowl_digits=BOWL_ALL_EQUAL)
    await ctx.ump.req("POST", f"{ctx.url}/innings/next")
    await play(ctx, bowlers, batters, 1)  # chase done on ball 1 with 5 runs
    assert (await live(ctx))["match"]["status"] == "completed"
    # umpire fixes ball 1 of the chase to a wicket: chase is no longer won
    fix = {"innings_number": 2, "over_no": 1, "ball_no": 1, "batter_digit": 5, "bowler_digit": 5, "reason": "misread"}
    assert (await ctx.ump.req("POST", f"{ctx.url}/balls/correct", json=fix)).status_code == 201
    d = await live(ctx)
    assert d["match"]["status"] == "innings2" and d["match"]["result"] is None
