from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select

from app.db.models import (
    AuditLog,
    ChatMessage,
    ChatRoom,
    Match,
    MatchResult,
    Notification,
    PointAdjustment,
    RuleSet,
    Season,
)
from tests.helpers import make_league, new_match, play_league, play_match

T0 = datetime(2031, 6, 1, 18, 0, tzinfo=UTC)


async def table(who, lg):
    r = await who.req("GET", f"/seasons/{lg.sid}/standings")
    assert r.status_code == 200, r.text
    return r.json()


def rows(t):
    return {r["team"]["id"]: r for r in t["rows"]}


async def league(make_user, **kw):
    return await make_league(make_user, n_teams=kw.pop("n_teams", 4), per_team=3, n_umpires=kw.pop("n_umpires", 3), **kw)


async def ledger(db, mid):
    db.expire_all()
    return await db.scalar(select(MatchResult).where(MatchResult.match_id == mid))


# ---------- the ledger ----------
async def test_a_completed_match_writes_the_ledger_and_the_table(make_user, db):
    lg = await league(make_user)
    a, b, c, _d = lg.teams
    [mid] = await play_league(lg, [(a, b, "a")])
    r = await ledger(db, mid)
    assert (r.result_type, r.winner_team_id) == ("normal", a)
    assert (r.a_runs, r.a_balls, r.a_all_out, r.b_runs, r.b_balls, r.b_all_out) == (21, 13, True, 0, 7, True)
    t = rows(await table(lg.players[a][0], lg))
    # Team 1: 21 runs off the full 7 overs (all out counts the quota) against 0 off 7 overs: +3.000
    assert (t[a]["points"], t[b]["points"], t[a]["nrr"], t[b]["nrr"]) == (2, 0, 3.0, -3.0)
    assert (t[a]["won"], t[b]["lost"], t[a]["form"], t[b]["form"]) == (1, 1, ["W"], ["L"])
    assert t[c]["played"] == 0 and t[c]["points"] == 0  # teams that have not played still appear


async def test_a_one_ball_chase_uses_the_balls_actually_faced(make_user, db):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    [mid] = await play_league(lg, [(a, b, "b")])
    r = await ledger(db, mid)
    assert (r.a_runs, r.a_balls, r.a_all_out) == (0, 7, True) and (r.b_runs, r.b_balls, r.b_all_out) == (5, 1, False)
    t = rows(await table(lg.admin, lg))
    # Team 2: 5 runs off 1 ball = 30 an over; Team 1: 0 off the full quota against 30 an over = -30
    assert (t[b]["nrr"], t[a]["nrr"], t[b]["points"], t[a]["points"]) == (30.0, -30.0, 2, 0)


async def test_a_tie_gives_a_point_each(make_user, db):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    [mid] = await play_league(lg, [(a, b, "tie")])
    assert (await ledger(db, mid)).result_type == "tie"
    t = rows(await table(lg.admin, lg))
    assert (t[a]["points"], t[b]["points"], t[a]["tied"], t[a]["nrr"], t[a]["form"]) == (1, 1, 1, 0.0, ["T"])


async def test_unfinished_matches_are_not_in_the_ledger(make_user, db):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    mid = await new_match(lg, a, b)
    assert await ledger(db, mid) is None
    t = await table(lg.admin, lg)
    assert t["matches_counted"] == 0 and t["pending_matches"] == [1] and t["league_complete"] is False


# ---------- corrections move the table ----------
async def test_a_penalty_can_flip_the_result_and_voiding_it_flips_it_back(make_user, db):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    [mid] = await play_league(lg, [(a, b, "a")])  # A wins 21 to 0
    pen = await lg.admin.req("POST", f"/matches/{mid}/penalties", json={
        "team_id": b, "kind": "rule_breach", "runs": 22, "reason": "late digits", "idempotency_key": "flip-pen-1"})
    assert pen.status_code == 201 and pen.json()["match_status"] == "completed"
    r = await ledger(db, mid)
    assert (r.winner_team_id, r.b_runs) == (b, 22)
    t = rows(await table(lg.admin, lg))
    # 22 v 21 with both sides at the full quota: B +6/42 over, i.e. +0.143
    assert (t[b]["points"], t[a]["points"], t[b]["nrr"], t[a]["nrr"]) == (2, 0, 0.143, -0.143)
    assert (t[b]["form"], t[a]["form"]) == (["W"], ["L"])
    await lg.admin.req("POST", f"/matches/{mid}/penalties/{pen.json()['id']}/void", json={"reason": "wrong team"})
    t = rows(await table(lg.admin, lg))
    assert (t[a]["points"], t[b]["points"], t[a]["nrr"]) == (2, 0, 3.0)
    assert (await ledger(db, mid)).winner_team_id == a


async def test_a_tie_can_become_a_win_through_a_penalty(make_user, db):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    [mid] = await play_league(lg, [(a, b, "tie")])
    await lg.admin.req("POST", f"/matches/{mid}/penalties", json={
        "team_id": b, "kind": "rule_breach", "runs": 1, "reason": "a run penalty", "idempotency_key": "tie-pen-1"})
    r = await ledger(db, mid)
    assert (r.result_type, r.winner_team_id) == ("normal", b)
    t = rows(await table(lg.admin, lg))
    assert (t[b]["points"], t[a]["points"], t[b]["tied"]) == (2, 0, 0)


async def test_a_withdrawn_result_leaves_no_trace_and_replaying_restores_it(make_user, db):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    [mid] = await play_league(lg, [(a, b, "a")])
    assert (await ledger(db, mid)) is not None
    # turn the chase's deciding 7th wicket (innings 2, over 2, ball 1) into 5 runs: the innings is alive again
    fix = {"innings_number": 2, "over_no": 2, "ball_no": 1, "batter_digit": 5, "bowler_digit": 6, "reason": "misread"}
    assert (await lg.admin.req("POST", f"/matches/{mid}/balls/correct", json=fix)).status_code == 201
    assert (await ledger(db, mid)) is None
    t = await table(lg.admin, lg)
    assert t["matches_counted"] == 0 and all(r["points"] == 0 and r["played"] == 0 for r in t["rows"])
    assert (await lg.admin.req("GET", f"/matches/{mid}")).json()["status"] == "innings2"
    # play on: the next over finishes the chase (another wicket) and the result comes back, with new figures
    ump = lg.admin
    from tests.helpers import BOWL_ALL_EQUAL, Ctx, play

    ctx = Ctx(lg.admin, ump, lg.players[a], lg.players[b], a, b, mid, lg.sid)
    await play(ctx, lg.players[b], lg.players[a], 3, bowl_digits=BOWL_ALL_EQUAL)
    r = await ledger(db, mid)
    assert r is not None and (r.winner_team_id, r.b_runs) == (a, 5)
    assert rows(await table(lg.admin, lg))[a]["points"] == 2


async def test_the_table_equals_the_table_rebuilt_from_scratch(make_user, db):
    lg = await league(make_user)
    a, b, c, d = lg.teams
    ids = await play_league(lg, [(a, b, "a"), (c, d, "tie"), (a, c, "b"), (b, d, "a")])
    await lg.admin.req("POST", f"/matches/{ids[0]}/penalties", json={
        "team_id": b, "kind": "rule_breach", "runs": 22, "reason": "late digits", "idempotency_key": "scratch-pen"})
    db.add(PointAdjustment(season_id=lg.sid, team_id=d, points=-1, kind="manual", reason="x", created_by=lg.admin.id))
    await db.commit()
    before = await table(lg.admin, lg)
    await db.execute(delete(MatchResult))  # throw the whole ledger away...
    await db.commit()
    assert (await table(lg.admin, lg))["matches_counted"] == 0
    r = await lg.admin.req("POST", "/admin/results/rebuild", json={"season_id": lg.sid})  # ...and rebuild it from the ball events
    assert r.status_code == 200 and r.json()["rebuilt"] == 4
    after = await table(lg.admin, lg)
    assert after["rows"] == before["rows"]
    assert (await lg.admin.req("POST", "/admin/results/rebuild", json={})).json()["rebuilt"] == 4  # repeatable
    assert (await table(lg.admin, lg))["rows"] == before["rows"]
    assert (await lg.players[a][0].req("POST", "/admin/results/rebuild", json={})).status_code == 403


# ---------- the table API ----------
async def test_table_flags_qualifiers_adjustments_and_scope(make_user, db):
    lg = await league(make_user)
    a, b, c, d = lg.teams
    await play_league(lg, [(a, b, "a"), (c, d, "a"), (a, c, "a")])
    db.add(PointAdjustment(season_id=lg.sid, team_id=a, points=-1, kind="umpire_duty", reason="no umpire", created_by=lg.admin.id))
    db.add(PointAdjustment(season_id=lg.sid, team_id=b, points=-5, kind="manual", reason="void", created_by=lg.admin.id,
                           voided_at=datetime.now(UTC)))  # a voided adjustment is ignored
    await db.commit()
    t = await table(lg.players[d][0], lg)
    assert t["qualifiers"] == 4 and t["points"]["win"] == 2 and t["tiebreakers"][:2] == ["points", "nrr"]
    r = rows(t)
    assert (r[a]["match_points"], r[a]["adjustments"], r[a]["points"]) == (4, -1, 3)
    assert r[b]["points"] == 0  # not -5
    assert [x["position"] for x in t["rows"]] == [1, 2, 3, 4]
    assert t["rows"][0]["team"]["id"] == a  # Team1: 4 match points - 1 adjustment = 3, ahead of Team3 on 2
    assert (await lg.players[a][0].req("GET", "/seasons/99999/standings")).status_code == 404


async def test_hand_made_matches_count_but_drafts_do_not_matter(make_user, db):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    await play_league(lg, [(a, b, "a")])  # created by hand: no stage, still counts
    await lg.admin.req("POST", f"/seasons/{lg.sid}/fixtures/generate", json={
        "start_date": "2031-02-01", "times": ["19:00"], "timezone": "UTC"})
    t = await table(lg.admin, lg)
    assert t["matches_counted"] == 1 and rows(t)[a]["points"] == 2
    assert t["league_complete"] is False and len(t["pending_matches"]) == 6  # the drafts are still to be played


async def test_champion_is_none_until_a_final_is_won(make_user, db):
    lg = await league(make_user)
    t = await table(lg.admin, lg)
    assert t["season"]["champion"] is None and t["league_complete"] is False
    assert (await lg.admin.req("GET", f"/seasons/{lg.sid}/bracket")).json() == {"stage": None, "matches": [], "champion": None}


# ---------- knockouts ----------
async def play_round_robin(lg):
    """A beats everyone, B beats C and D, C beats D: final order Team1 > Team2 > Team3 > Team4."""
    a, b, c, d = lg.teams
    await play_league(lg, [(a, b, "a"), (a, c, "a"), (a, d, "a"), (b, c, "a"), (b, d, "a"), (c, d, "a")])


async def generate(lg, **kw):
    return await lg.admin.req("POST", f"/seasons/{lg.sid}/knockouts/generate", json={
        "first_at": T0.isoformat(), "second_at": (T0 + timedelta(hours=3)).isoformat(), **kw})


async def stage_matches(lg):
    b = (await lg.admin.req("GET", f"/seasons/{lg.sid}/bracket")).json()
    return b, {m["round_label"]: m for m in b["matches"]}


async def notes(db, kind, title=None):
    db.expire_all()
    q = select(Notification).where(Notification.kind == kind)
    if title:
        q = q.where(Notification.title == title)
    return list(await db.scalars(q))


async def season_lines(db, sid):
    db.expire_all()
    room = await db.scalar(select(ChatRoom.id).where(ChatRoom.season_id == sid, ChatRoom.kind == "season"))
    return list(await db.scalars(select(ChatMessage.body).where(ChatMessage.room_id == room, ChatMessage.kind == "system").order_by(ChatMessage.id)))


async def test_knockouts_wait_for_the_league_to_finish(make_user, db):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    assert (await generate(lg)).status_code == 409  # nothing played
    await play_league(lg, [(a, b, "a")])
    await new_match(lg, lg.teams[2], lg.teams[3])  # an unplayed league match
    r = await generate(lg)
    assert r.status_code == 409 and "still to be finished" in r.json()["detail"]
    assert (await lg.players[a][0].req("POST", f"/seasons/{lg.sid}/knockouts/generate", json={"first_at": T0.isoformat()})).status_code == 403


async def test_semi_finals_are_seeded_one_v_four_and_two_v_three(make_user, db):
    lg = await league(make_user)
    a, b, c, d = lg.teams
    await play_round_robin(lg)
    t = await table(lg.admin, lg)
    assert [r["team"]["id"] for r in t["rows"]] == [a, b, c, d] and t["league_complete"] is True
    r = await generate(lg)
    assert r.status_code == 201 and r.json()["seeds"] == [a, b, c, d]
    bracket, ms = await stage_matches(lg)
    assert set(ms) == {"Semi-final 1", "Semi-final 2"}
    assert (ms["Semi-final 1"]["team_a"]["id"], ms["Semi-final 1"]["team_b"]["id"]) == (a, d)
    assert (ms["Semi-final 2"]["team_a"]["id"], ms["Semi-final 2"]["team_b"]["id"]) == (b, c)
    assert [s["team"]["id"] for s in bracket["stage"]["seeds"]] == [a, b, c, d]
    db.expire_all()
    for m in ms.values():  # published at once, with rooms, and the umpire is not playing
        row = await db.get(Match, m["id"])
        assert row.published_at is not None and row.umpire_id in {u.id for u in lg.umpires}
    assert ms["Semi-final 1"]["scheduled_at"] != ms["Semi-final 2"]["scheduled_at"]
    assert len(await notes(db, "fixtures_published", "The knockouts are set")) == 12  # 4 teams x 3 people, once each
    assert any(line.startswith("🏆 The knockouts are set.") for line in await season_lines(db, lg.sid))
    assert (await generate(lg)).status_code == 409  # only once
    # knockout results never count towards the league table
    assert (await table(lg.admin, lg))["matches_counted"] == 6


async def test_the_final_appears_by_itself_exactly_once(make_user, db):
    lg = await league(make_user)
    a, b, _c, _d = lg.teams
    await play_round_robin(lg)
    await generate(lg)
    _, ms = await stage_matches(lg)
    await play_match(lg, ms["Semi-final 1"]["id"], "a")  # Team1 beat Team4
    assert "Final" not in (await stage_matches(lg))[1]  # one semi is not enough
    await play_match(lg, ms["Semi-final 2"]["id"], "a")  # Team2 beat Team3
    _bracket, ms = await stage_matches(lg)
    final = ms["Final"]
    assert (final["team_a"]["id"], final["team_b"]["id"]) == (a, b)
    db.expire_all()
    row = await db.get(Match, final["id"])
    assert row.published_at is not None and row.status == "scheduled" and row.umpire_id in {u.id for u in lg.umpires}
    assert row.scheduled_at == T0 + timedelta(hours=3) + timedelta(days=1)  # the day after the last semi
    assert len(await notes(db, "fixtures_published", "The final is set")) >= 2
    assert "🏏 The final is set: Team1 vs Team2." in await season_lines(db, lg.sid)
    # repeating the sync (rebuild) must not create a second final or tell people again
    before = len(await notes(db, "fixtures_published", "The final is set"))
    await lg.admin.req("POST", "/admin/results/rebuild", json={"season_id": lg.sid})
    assert sum(1 for m in (await stage_matches(lg))[0]["matches"] if m["round_label"] == "Final") == 1
    assert len(await notes(db, "fixtures_published", "The final is set")) == before


async def test_a_tied_knockout_goes_to_the_higher_league_seed(make_user, db):
    lg = await league(make_user)
    a, b, _c, _d = lg.teams
    await play_round_robin(lg)
    await generate(lg)
    _, ms = await stage_matches(lg)
    await play_match(lg, ms["Semi-final 1"]["id"], "tie")  # Team1 (seed 1) v Team4 (seed 4)
    await play_match(lg, ms["Semi-final 2"]["id"], "tie")  # Team2 (seed 2) v Team3 (seed 3)
    _bracket, ms = await stage_matches(lg)
    sf1, sf2 = ms["Semi-final 1"], ms["Semi-final 2"]
    assert (sf1["winner_team_id"], sf2["winner_team_id"]) == (a, b)
    assert sf1["result"] == "Match tied. Team1 go through as the higher league seed"
    assert (ms["Final"]["team_a"]["id"], ms["Final"]["team_b"]["id"]) == (a, b)
    db.expire_all()
    assert (await ledger(db, sf1["id"])).result_type == "tie"  # recorded honestly as a tie
    assert (await table(lg.admin, lg))["matches_counted"] == 6  # and not in the league table


async def test_a_correction_can_change_the_final_while_it_has_not_started(make_user, db):
    lg = await league(make_user)
    a, b, c, _d = lg.teams
    await play_round_robin(lg)
    await generate(lg)
    _, ms = await stage_matches(lg)
    await play_match(lg, ms["Semi-final 1"]["id"], "a")
    await play_match(lg, ms["Semi-final 2"]["id"], "a")  # Team2 beat Team3
    _, ms = await stage_matches(lg)
    final_id = ms["Final"]["id"]
    # the umpire's penalty gives Team3 the semi-final: the final becomes Team1 v Team3, lineups cleared
    await lg.admin.req("PUT", f"/matches/{final_id}/lineup", json={"team_id": a, "user_ids": [lg.players[a][0].id]})
    pen = await lg.admin.req("POST", f"/matches/{ms['Semi-final 2']['id']}/penalties", json={
        "team_id": c, "kind": "rule_breach", "runs": 22, "reason": "late digits", "idempotency_key": "ko-flip-1"})
    assert pen.status_code == 201
    _, ms = await stage_matches(lg)
    assert ms["Final"]["id"] == final_id and (ms["Final"]["team_a"]["id"], ms["Final"]["team_b"]["id"]) == (a, c)
    detail = (await lg.admin.req("GET", f"/matches/{final_id}")).json()
    assert detail["lineup"] == []
    db.expire_all()
    assert (await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "knockout.final_updated"))) == 1
    assert any(n.title == "The final line-up changed" for n in await notes(db, "fixture_change"))
    assert "🛠 The final is now Team1 vs Team3." in await season_lines(db, lg.sid)
    await lg.admin.req("POST", f"/matches/{ms['Semi-final 2']['id']}/penalties/{pen.json()['id']}/void", json={"reason": "wrong team"})
    _, ms = await stage_matches(lg)
    assert (ms["Final"]["team_a"]["id"], ms["Final"]["team_b"]["id"]) == (a, b)


async def test_a_correction_cannot_change_a_semi_once_the_final_has_started(make_user, db):
    lg = await league(make_user)
    a, b, c, _d = lg.teams
    await play_round_robin(lg)
    await generate(lg)
    _, ms = await stage_matches(lg)
    await play_match(lg, ms["Semi-final 1"]["id"], "a")
    await play_match(lg, ms["Semi-final 2"]["id"], "a")
    _, ms = await stage_matches(lg)
    fid = ms["Final"]["id"]
    for t in (a, b):  # a toss needs both lineups
        await lg.admin.req("PUT", f"/matches/{fid}/lineup", json={"team_id": t, "user_ids": [p.id for p in lg.players[t]]})
    assert (await lg.admin.req("POST", f"/matches/{fid}/toss/open")).status_code == 204  # the final is under way
    pen = await lg.admin.req("POST", f"/matches/{ms['Semi-final 2']['id']}/penalties", json={
        "team_id": c, "kind": "rule_breach", "runs": 22, "reason": "too late", "idempotency_key": "ko-late-1"})
    assert pen.status_code == 409 and "after the final has started" in pen.json()["detail"]
    _, after = await stage_matches(lg)
    assert after["Semi-final 2"]["winner_team_id"] == b  # nothing changed
    db.expire_all()
    assert (await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "penalty.apply"))) == 0


async def test_withdrawing_a_semi_result_puts_the_final_on_hold_then_it_returns(make_user, db):
    lg = await league(make_user)
    a, b, c, _d = lg.teams
    await play_round_robin(lg)
    await generate(lg)
    _, ms = await stage_matches(lg)
    await play_match(lg, ms["Semi-final 1"]["id"], "a")
    await play_match(lg, ms["Semi-final 2"]["id"], "a")
    _, ms = await stage_matches(lg)
    old_final = ms["Final"]["id"]
    fix = {"innings_number": 2, "over_no": 2, "ball_no": 1, "batter_digit": 5, "bowler_digit": 6, "reason": "misread"}
    assert (await lg.admin.req("POST", f"/matches/{ms['Semi-final 2']['id']}/balls/correct", json=fix)).status_code == 201
    _, ms = await stage_matches(lg)
    assert "Final" not in ms  # on hold: nobody knows the second finalist
    assert "🛠 The final is on hold until the semi-final result is settled." in await season_lines(db, lg.sid)
    db.expire_all()
    assert await db.get(Match, old_final) is None
    from tests.helpers import BOWL_ALL_EQUAL, Ctx, play

    sid2 = ms["Semi-final 2"]["id"]
    ctx = Ctx(lg.admin, lg.admin, lg.players[b], lg.players[c], b, c, sid2, lg.sid)
    await play(ctx, lg.players[c], lg.players[b], 3, bowl_digits=BOWL_ALL_EQUAL)  # the chase finishes again
    _, ms = await stage_matches(lg)
    assert (ms["Final"]["team_a"]["id"], ms["Final"]["team_b"]["id"]) == (a, b)
    assert sum(1 for m in (await stage_matches(lg))[0]["matches"] if m["round_label"] == "Final") == 1


async def test_winning_the_final_crowns_the_champion_and_a_correction_can_change_it(make_user, db):
    lg = await league(make_user)
    a, b, _c, _d = lg.teams
    await play_round_robin(lg)
    await generate(lg)
    _, ms = await stage_matches(lg)
    await play_match(lg, ms["Semi-final 1"]["id"], "a")
    await play_match(lg, ms["Semi-final 2"]["id"], "a")
    _, ms = await stage_matches(lg)
    final_id = ms["Final"]["id"]
    await play_match(lg, final_id, "a")  # Team1 win the final
    bracket, _ = await stage_matches(lg)
    assert bracket["champion"]["id"] == a and (await table(lg.admin, lg))["season"]["champion"]["name"] == "Team1"
    assert any(line.startswith("🏆 Team1 are the champions of ") for line in await season_lines(db, lg.sid))
    assert {n.user_id for n in await notes(db, "result", "Team1 are the champions!")} == {p.id for p in lg.players[a]}
    # a penalty hands the title to Team2, and back
    pen = await lg.admin.req("POST", f"/matches/{final_id}/penalties", json={
        "team_id": b, "kind": "rule_breach", "runs": 22, "reason": "late digits", "idempotency_key": "title-flip"})
    assert (await stage_matches(lg))[0]["champion"]["id"] == b
    await lg.admin.req("POST", f"/matches/{final_id}/penalties/{pen.json()['id']}/void", json={"reason": "wrong team"})
    assert (await stage_matches(lg))[0]["champion"]["id"] == a
    # the league table is untouched by all of this
    t = await table(lg.admin, lg)
    assert t["matches_counted"] == 6 and [r["points"] for r in t["rows"]] == [6, 4, 2, 0]


async def test_with_two_qualifiers_the_final_is_played_straight_away(make_user, db):
    lg = await league(make_user)
    a, b, _c, _d = lg.teams
    await play_round_robin(lg)
    season = await db.get(Season, lg.sid)
    rs = RuleSet(name="Top two", version=1, config={"knockout": {"qualifiers": 2, "tie": "higher_seed"}})
    db.add(rs)
    await db.flush()
    season.rule_set_id = rs.id
    await db.commit()
    t = await table(lg.admin, lg)
    assert t["qualifiers"] == 2 and [r["qualified"] for r in t["rows"]] == [True, True, False, False]
    assert (await generate(lg)).status_code == 201
    _, ms = await stage_matches(lg)
    assert list(ms) == ["Final"] and (ms["Final"]["team_a"]["id"], ms["Final"]["team_b"]["id"]) == (a, b)
    await play_match(lg, ms["Final"]["id"], "b")  # Team2 chase it down
    assert (await stage_matches(lg))[0]["champion"]["id"] == b


async def test_unsupported_qualifier_counts_are_refused(make_user, db):
    lg = await league(make_user)
    await play_round_robin(lg)
    season = await db.get(Season, lg.sid)
    rs = RuleSet(name="Odd", version=1, config={"knockout": {"qualifiers": 3}})
    db.add(rs)
    await db.flush()
    season.rule_set_id = rs.id
    await db.commit()
    assert (await generate(lg)).status_code == 422
