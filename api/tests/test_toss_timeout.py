"""A captain who never answers the toss: the umpire can declare a walkover once the waiting time is over."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import AuditLog, Match, MatchResult
from tests.helpers import Ctx, make_league, new_match, run_toss


async def league(make_user):
    return await make_league(make_user, n_teams=4, per_team=3, n_umpires=3)


async def at(db, mid, minutes_ago):
    m = await db.get(Match, mid)
    m.scheduled_at = datetime.now(UTC) - timedelta(minutes=minutes_ago) if minutes_ago is not None else None
    await db.commit()


def absent(who, mid, team):
    return who.req("POST", f"/matches/{mid}/toss/absent", json={"team_id": team})


async def test_the_umpire_may_declare_a_walkover_after_the_wait(make_user, db):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    mid = await new_match(lg, a, b)
    await at(db, mid, 16)  # 15 minutes is the default wait
    r = await absent(lg.umpires[0], mid, b)
    assert r.status_code == 200, r.text
    assert r.json()["winner_team_id"] == a and "walkover" in r.json()["result"]
    db.expire_all()
    row = await db.scalar(select(MatchResult).where(MatchResult.match_id == mid))
    assert (row.result_type, row.winner_team_id) == ("walkover", a)
    audit = await db.scalar(select(AuditLog).where(AuditLog.action == "match.walkover", AuditLog.entity_id == mid))
    assert audit and "toss" in audit.reason
    # and an admin can still put it right
    assert (await lg.admin.req("POST", f"/matches/{mid}/result/reverse", json={"reason": "captain was stuck in traffic"})).status_code == 200


async def test_too_early_or_without_a_time_is_refused(make_user, db):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    mid = await new_match(lg, a, b)
    await at(db, mid, 14)  # one minute early
    r = await absent(lg.umpires[0], mid, b)
    assert r.status_code == 409 and "Wait until" in r.json()["detail"]
    await at(db, mid, None)
    r = await absent(lg.umpires[0], mid, b)
    assert r.status_code == 409 and "no scheduled start" in r.json()["detail"]
    live = (await lg.umpires[0].req("GET", f"/matches/{mid}/live")).json()
    assert live["you"]["toss_absent_from"] is None


async def test_only_officials_and_only_the_two_teams(make_user, db):
    lg = await league(make_user)
    a, b, c, _ = lg.teams
    mid = await new_match(lg, a, b)
    await at(db, mid, 30)
    assert (await absent(lg.players[a][0], mid, b)).status_code == 403  # a captain cannot hand themselves a win
    assert (await absent(lg.umpires[1], mid, b)).status_code == 403  # another match's umpire
    assert (await absent(lg.umpires[0], mid, c)).status_code == 422
    assert (await absent(lg.admin, mid, a)).status_code == 200  # an admin may


async def test_not_after_the_toss_is_settled(make_user, db):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    mid = await new_match(lg, a, b)
    for t in (a, b):
        await lg.admin.req("PUT", f"/matches/{mid}/lineup", json={"team_id": t, "user_ids": [p.id for p in lg.players[t]]})
    ctx = Ctx(lg.admin, lg.umpires[0], lg.players[a], lg.players[b], a, b, mid, lg.sid)
    await run_toss(ctx, "a", "bat")
    await at(db, mid, 60)
    r = await absent(lg.umpires[0], mid, b)
    assert r.status_code == 409 and "already been settled" in r.json()["detail"]


async def test_the_umpire_sees_when_the_button_unlocks_and_nobody_else_does(make_user, db):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    mid = await new_match(lg, a, b)
    await at(db, mid, 5)
    live = (await lg.umpires[0].req("GET", f"/matches/{mid}/live")).json()
    due = datetime.fromisoformat(live["you"]["toss_absent_from"])
    assert abs((due - (datetime.now(UTC) + timedelta(minutes=10))).total_seconds()) < 5
    other = (await lg.players[a][0].req("GET", f"/matches/{mid}/live")).json()
    assert other["you"]["toss_absent_from"] is None


async def test_the_wait_is_a_validated_rule_and_in_the_rulebook(make_user, db):
    lg = await league(make_user)
    rs0 = (await lg.admin.req("GET", f"/seasons/{lg.sid}")).json()["rule_set_id"]
    for bad in (0, 241, "ten"):
        r = await lg.admin.req("POST", "/admin/rules", json={"from_id": rs0, "changes": {"toss_timeout_minutes": bad}, "reason": "try"})
        assert r.status_code == 422 and "toss_timeout_minutes" in r.json()["detail"]
    r = await lg.admin.req("POST", "/admin/rules", json={"from_id": rs0, "changes": {"toss_timeout_minutes": 5}, "reason": "shorter wait"})
    assert r.status_code == 201, r.text
    from app.engine.rules_text import summarize

    text = " ".join(i for sec in summarize({"toss_timeout_minutes": 5}) for i in sec["items"])
    assert "5 minutes after the scheduled start" in text
    assert "15 minutes after the scheduled start" in " ".join(i for sec in summarize(None) for i in sec["items"])
