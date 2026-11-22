from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.db.models import (
    AuditLog,
    BallEvent,
    ChatMessage,
    ChatRoom,
    Match,
    MatchDeclaration,
    MatchResult,
    Notification,
)
from tests.helpers import (
    BOWL_ALL_EQUAL,
    Ctx,
    make_league,
    new_match,
    play,
    play_league,
    play_match,
    run_toss,
    start,
)

T0 = datetime(2031, 6, 1, 18, 0, tzinfo=UTC)


async def league(make_user):
    return await make_league(make_user, n_teams=4, per_team=3, n_umpires=3)


async def table(lg):
    r = (await lg.admin.req("GET", f"/seasons/{lg.sid}/standings")).json()
    return r, {x["team"]["id"]: x for x in r["rows"]}


async def ledger(db, mid):
    db.expire_all()
    return await db.scalar(select(MatchResult).where(MatchResult.match_id == mid))


async def lines(db, mid, kind="match"):
    db.expire_all()
    room = await db.scalar(select(ChatRoom.id).where(ChatRoom.match_id == mid, ChatRoom.kind == kind))
    return list(await db.scalars(select(ChatMessage.body).where(ChatMessage.room_id == room, ChatMessage.kind == "system").order_by(ChatMessage.id)))


def walkover(lg, mid, absent, who=None, reason="the team did not show up"):
    return (who or lg.admin).req("POST", f"/matches/{mid}/walkover", json={"absent_team_id": absent, "reason": reason})


def abandon(lg, mid, who=None, reason="heavy rain", **kw):
    return (who or lg.admin).req("POST", f"/matches/{mid}/abandon", json={"reason": reason, **kw})


# ---------- walkover ----------
async def test_a_walkover_awards_the_match_and_changes_the_table(make_user, db):
    lg = await league(make_user)
    a, b, _c, _d = lg.teams
    mid = await new_match(lg, a, b)
    r = await walkover(lg, mid, b)
    assert r.status_code == 200 and r.json()["status"] == "completed" and r.json()["winner_team_id"] == a
    assert r.json()["result"] == "Team1 won by walkover (Team2 did not turn up)"
    row = await ledger(db, mid)
    assert (row.result_type, row.winner_team_id, row.a_runs, row.b_runs, row.a_balls) == ("walkover", a, None, None, None)
    _t, rows = await table(lg)
    assert (rows[a]["points"], rows[b]["points"]) == (2, 0)
    assert (rows[a]["won"], rows[b]["lost"], rows[a]["played"], rows[b]["played"]) == (1, 1, 1, 1)
    assert (rows[a]["nrr"], rows[b]["nrr"], rows[a]["balls_for"]) == (0.0, 0.0, 0)  # net run rate ignores it
    assert (rows[a]["form"], rows[b]["form"]) == (["W"], ["L"])
    assert await db.scalar(select(func.count()).select_from(BallEvent)) == 0  # nothing was "played"
    assert "⚠️ Walkover: Team2 did not turn up. Team1 are awarded the match. Reason: the team did not show up" in await lines(db, mid)
    got = list(await db.scalars(select(Notification).where(Notification.title == "Walkover")))
    assert {n.user_id for n in got} == {p.id for t_ in (a, b) for p in lg.players[t_]} | {lg.umpires[0].id}
    assert (await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "match.walkover"))) == 1
    live = (await lg.players[a][0].req("GET", f"/matches/{mid}/live")).json()
    assert live["match"]["status"] == "completed" and live["match"]["declared"]["kind"] == "walkover"
    assert live["match"]["declared"]["absent_team_id"] == b and live["innings"] == []


async def test_walkover_rules(make_user, db):
    lg = await league(make_user)
    a, b, c, d = lg.teams
    mid = await new_match(lg, a, b)
    assert (await walkover(lg, mid, c)).status_code == 422  # not one of the two teams
    assert (await walkover(lg, mid, b, who=lg.players[a][0])).status_code == 403  # a captain cannot hand themselves a win
    assert (await walkover(lg, mid, b, reason="no")).status_code == 422
    assert (await walkover(lg, mid, b, who=lg.umpires[0])).status_code == 200  # the match umpire can
    again = await walkover(lg, mid, a)
    assert again.status_code == 409 and "before the match starts" in again.json()["detail"]
    assert (await abandon(lg, mid)).status_code == 409  # already finished
    # a match under way can only be abandoned, not walked over
    live = await new_match(lg, c, d)
    ctx = Ctx(lg.admin, lg.admin, lg.players[c], lg.players[d], c, d, live, lg.sid)
    for t in (c, d):
        await lg.admin.req("PUT", f"/matches/{live}/lineup", json={"team_id": t, "user_ids": [p.id for p in lg.players[t]]})
    await run_toss(ctx, "a", "bat")
    assert (await walkover(lg, live, d)).status_code == 200  # still only at the toss: allowed
    started = await new_match(lg, a, c)
    for t in (a, c):
        await lg.admin.req("PUT", f"/matches/{started}/lineup", json={"team_id": t, "user_ids": [p.id for p in lg.players[t]]})
    ctx2 = Ctx(lg.admin, lg.admin, lg.players[a], lg.players[c], a, c, started, lg.sid)
    await run_toss(ctx2, "a", "bat")
    await start(ctx2)
    r = await walkover(lg, started, c)
    assert r.status_code == 409 and "abandon it instead" in r.json()["detail"]


async def test_a_walkover_can_be_reversed_and_the_match_played_after_all(make_user, db):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    mid = await new_match(lg, a, b)
    await walkover(lg, mid, b)
    assert (await lg.players[a][0].req("POST", f"/matches/{mid}/result/reverse", json={"reason": "they did come"})).status_code == 403
    assert (await lg.umpires[0].req("POST", f"/matches/{mid}/result/reverse", json={"reason": "they did come"})).status_code == 403  # admins only
    r = await lg.admin.req("POST", f"/matches/{mid}/result/reverse", json={"reason": "they did come after all"})
    assert r.status_code == 200 and r.json()["status"] == "scheduled"
    assert await ledger(db, mid) is None
    t, rows = await table(lg)
    assert t["matches_counted"] == 0 and rows[a]["points"] == 0 and rows[a]["played"] == 0
    assert "🛠 An admin reversed the walkover. Reason: they did come after all" in await lines(db, mid)
    assert (await lg.admin.req("POST", f"/matches/{mid}/result/reverse", json={"reason": "again"})).status_code == 409
    detail = (await lg.players[a][0].req("GET", f"/matches/{mid}/live")).json()["match"]
    assert detail["status"] == "scheduled" and detail["declared"] is None and detail["result"] is None
    await play_match(lg, mid, "a")  # and it can be played normally
    assert (await ledger(db, mid)).result_type == "normal"
    assert (await table(lg))[1][a]["points"] == 2
    decls = list(await db.scalars(select(MatchDeclaration).where(MatchDeclaration.match_id == mid)))
    assert len(decls) == 1 and decls[0].reversed_at is not None and decls[0].reverse_reason  # history is kept


async def test_a_draft_match_cannot_be_declared(make_user, db):
    lg = await league(make_user)
    r = await lg.admin.req("POST", f"/seasons/{lg.sid}/fixtures/generate", json={"start_date": "2031-02-01", "times": ["19:00"], "timezone": "UTC"})
    mid = r.json()["match_ids"][0]
    assert (await walkover(lg, mid, lg.teams[0])).status_code == 409
    assert (await abandon(lg, mid)).status_code == 409


# ---------- abandonment ----------
async def test_abandoning_before_the_start_gives_each_team_a_point(make_user, db):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    mid = await new_match(lg, a, b)
    r = await abandon(lg, mid, reason="ground waterlogged")
    assert r.status_code == 200 and r.json()["status"] == "abandoned" and r.json()["replay_match_id"] is None
    assert r.json()["result"] == "Match abandoned: ground waterlogged"
    assert (await ledger(db, mid)).result_type == "abandoned"
    t, rows = await table(lg)
    assert (rows[a]["points"], rows[b]["points"], rows[a]["played"], rows[a]["no_result"], rows[a]["nrr"], rows[a]["form"]) == (1, 1, 0, 1, 0.0, ["N"])
    assert t["league_complete"] is True and t["pending_matches"] == []  # an abandoned match no longer holds the league up
    assert "⛔ Match abandoned: ground waterlogged." in await lines(db, mid)
    done = (await lg.admin.req("GET", f"/seasons/{lg.sid}/fixtures?status=completed")).json()
    assert [f["id"] for f in done] == [mid] and done[0]["status"] == "abandoned"
    assert (await lg.admin.req("POST", f"/matches/{mid}/toss/open")).status_code == 409  # nothing more can happen
    assert (await abandon(lg, mid)).status_code == 409
    assert (await abandon(lg, await new_match(lg, a, b), who=lg.players[a][0])).status_code == 403


async def test_abandoning_a_match_under_way_keeps_what_was_played_and_can_be_undone(make_user, db):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    mid = await new_match(lg, a, b)
    ctx = Ctx(lg.admin, lg.admin, lg.players[a], lg.players[b], a, b, mid, lg.sid)
    for t in (a, b):
        await lg.admin.req("PUT", f"/matches/{mid}/lineup", json={"team_id": t, "user_ids": [p.id for p in lg.players[t]]})
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    await play(ctx, batters, bowlers, 1)  # 21 runs
    r = await abandon(lg, mid, reason="floodlights failed")
    assert r.status_code == 200
    row = await ledger(db, mid)
    assert row.result_type == "no_result" and row.a_runs is None  # points only: the partial innings is not a result
    assert await db.scalar(select(func.count()).select_from(BallEvent)) == 6  # what was bowled is kept
    t, rows = await table(lg)
    assert (rows[a]["points"], rows[b]["points"], rows[a]["nrr"]) == (1, 1, 0.0)
    # reversing puts the match back where it was, paused so the umpire resumes on purpose
    assert (await lg.admin.req("POST", f"/matches/{mid}/result/reverse", json={"reason": "lights fixed"})).status_code == 200
    live = (await lg.admin.req("GET", f"/matches/{mid}/live")).json()
    assert live["match"]["status"] == "innings1" and live["match"]["paused"] is True and live["innings"][0]["runs"] == 21
    assert await ledger(db, mid) is None
    assert (await lg.admin.req("POST", f"/matches/{mid}/resume")).status_code == 204
    await play(ctx, batters, bowlers, 2, bowl_digits=BOWL_ALL_EQUAL)
    await play(ctx, batters, bowlers, 3, bowl_digits=BOWL_ALL_EQUAL)  # innings 1 ends all out on 21
    await lg.admin.req("POST", f"{ctx.url}/innings/next")
    await play(ctx, bowlers, batters, 1, bowl_digits=BOWL_ALL_EQUAL)
    await play(ctx, bowlers, batters, 2, bowl_digits=BOWL_ALL_EQUAL)
    assert (await ledger(db, mid)).result_type == "normal"
    assert (await table(lg))[1][a]["points"] == 2


async def test_a_replay_is_a_draft_that_must_be_scheduled_and_published(make_user, db):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    mid = await new_match(lg, a, b)
    r = await abandon(lg, mid, replay=True, replay_at=(T0 + timedelta(days=3)).isoformat())
    rid = r.json()["replay_match_id"]
    assert rid and "A replay will be arranged." in (await lines(db, mid))[-1]
    db.expire_all()
    again = await db.get(Match, rid)
    assert (again.team_a_id, again.team_b_id, again.round_label, again.published_at) == (a, b, f"Replay of match {(await db.get(Match, mid)).match_no}", None)
    assert again.scheduled_at == T0 + timedelta(days=3) and again.umpire_id == lg.umpires[0].id
    assert (await lg.players[a][0].req("GET", f"/matches/{rid}")).status_code == 404  # invisible until published
    t, _ = await table(lg)
    assert t["league_complete"] is False and t["pending_matches"] == [again.match_no]  # the replay still has to be played
    await lg.admin.req("POST", f"/seasons/{lg.sid}/fixtures/publish", json={"match_ids": [rid]})
    assert (await lg.players[a][0].req("GET", f"/matches/{rid}")).status_code == 200
    # reversing the abandonment would leave two copies of one match, so it is refused once the replay is public
    r2 = await lg.admin.req("POST", f"/matches/{mid}/result/reverse", json={"reason": "play on"})
    assert r2.status_code == 409 and "replay" in r2.json()["detail"]


async def test_reversing_an_abandonment_removes_an_unpublished_replay(make_user, db):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    mid = await new_match(lg, a, b)
    rid = (await abandon(lg, mid, replay=True)).json()["replay_match_id"]
    assert (await lg.admin.req("POST", f"/matches/{mid}/result/reverse", json={"reason": "weather cleared"})).status_code == 200
    db.expire_all()
    assert await db.get(Match, rid) is None and (await db.get(Match, mid)).status == "scheduled"


# ---------- knockouts ----------
async def knockouts(lg):
    a, b, c, d = lg.teams
    await play_league(lg, [(a, b, "a"), (a, c, "a"), (a, d, "a"), (b, c, "a"), (b, d, "a"), (c, d, "a")])
    r = await lg.admin.req("POST", f"/seasons/{lg.sid}/knockouts/generate", json={
        "first_at": T0.isoformat(), "second_at": (T0 + timedelta(hours=3)).isoformat()})
    assert r.status_code == 201, r.text
    b_ = (await lg.admin.req("GET", f"/seasons/{lg.sid}/bracket")).json()
    return {m["round_label"]: m for m in b_["matches"]}


async def bracket(lg):
    return {m["round_label"]: m for m in (await lg.admin.req("GET", f"/seasons/{lg.sid}/bracket")).json()["matches"]}


async def test_a_walkover_in_a_semi_final_sends_the_other_team_through(make_user, db):
    lg = await league(make_user)
    a, b, _c, d = lg.teams
    ms = await knockouts(lg)
    assert (await walkover(lg, ms["Semi-final 1"]["id"], d)).status_code == 200  # Team4 do not turn up
    assert "Final" not in await bracket(lg)
    await play_match(lg, ms["Semi-final 2"]["id"], "a")
    ms = await bracket(lg)
    assert (ms["Final"]["team_a"]["id"], ms["Final"]["team_b"]["id"]) == (a, b)
    assert (await table(lg))[0]["matches_counted"] == 6  # knockout results are not in the league table
    # reversing it while the final is only scheduled puts the final on hold
    assert (await lg.admin.req("POST", f"/matches/{ms['Semi-final 1']['id']}/result/reverse", json={"reason": "they arrived"})).status_code == 200
    assert "Final" not in await bracket(lg)


async def test_a_walkover_cannot_be_reversed_once_the_final_has_started(make_user, db):
    lg = await league(make_user)
    a, b, _c, d = lg.teams
    ms = await knockouts(lg)
    await walkover(lg, ms["Semi-final 1"]["id"], d)
    await play_match(lg, ms["Semi-final 2"]["id"], "a")
    fid = (await bracket(lg))["Final"]["id"]
    for t in (a, b):
        await lg.admin.req("PUT", f"/matches/{fid}/lineup", json={"team_id": t, "user_ids": [p.id for p in lg.players[t]]})
    assert (await lg.admin.req("POST", f"/matches/{fid}/toss/open")).status_code == 204
    r = await lg.admin.req("POST", f"/matches/{ms['Semi-final 1']['id']}/result/reverse", json={"reason": "too late"})
    assert r.status_code == 409 and "final has started" in r.json()["detail"]
    assert (await bracket(lg))["Semi-final 1"]["winner_team_id"] == a  # nothing changed


async def test_an_abandoned_semi_final_is_replayed_in_its_place(make_user, db):
    lg = await league(make_user)
    a, b, _c, _d = lg.teams
    ms = await knockouts(lg)
    r = await abandon(lg, ms["Semi-final 1"]["id"], replay=True, replay_at=(T0 + timedelta(days=1)).isoformat())
    rid = r.json()["replay_match_id"]
    await play_match(lg, ms["Semi-final 2"]["id"], "a")
    assert "Final" not in await bracket(lg)  # still waiting for the first semi-final
    await lg.admin.req("POST", f"/seasons/{lg.sid}/fixtures/publish", json={"match_ids": [rid]})
    db.expire_all()
    assert (await db.get(Match, rid)).round_label == "Semi-final 1"  # it keeps its place in the bracket
    await play_match(lg, rid, "a")
    ms = await bracket(lg)
    assert (ms["Final"]["team_a"]["id"], ms["Final"]["team_b"]["id"]) == (a, b)
    assert sum(1 for m in (await lg.admin.req("GET", f"/seasons/{lg.sid}/bracket")).json()["matches"] if m["round_label"] == "Final") == 1
