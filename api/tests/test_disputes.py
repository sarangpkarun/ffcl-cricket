from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import AuditLog, Dispute, MatchResult, Notification, User
from app.services.disputes import remind_stale_disputes
from tests.helpers import League, make_league, new_match, play_match

BODY = "The second innings was scored wrongly: the last wicket should not have counted."


async def league(make_user) -> League:
    lg = await make_league(make_user, n_teams=4, per_team=4, n_umpires=2)
    for tid in lg.teams:  # every team gets a vice-captain
        await lg.admin.req("PATCH", f"/teams/{tid}", json={"vice_captain_id": lg.players[tid][1].id})
    return lg


async def finished(lg: League, a: int = 0, b: int = 1) -> int:
    mid = await new_match(lg, lg.teams[a], lg.teams[b])
    await play_match(lg, mid, "a")
    return mid


def cap(lg, i):
    return lg.players[lg.teams[i]][0]


def vice(lg, i):
    return lg.players[lg.teams[i]][1]


def plain(lg, i):
    return lg.players[lg.teams[i]][2]


async def raise_it(who, mid, kind="scoring", body=BODY, **extra):
    return await who.req("POST", "/disputes", json={"kind": kind, "body": body, "match_id": mid, **extra})


async def age(db, mid, hours):
    await db.execute(update(MatchResult).where(MatchResult.match_id == mid).values(decided_at=datetime.now(UTC) - timedelta(hours=hours)))
    await db.commit()


async def name(db, actor) -> str:
    return (await db.get(User, actor.id)).name


async def notes(db, title):
    db.expire_all()
    return list(await db.scalars(select(Notification).where(Notification.title == title).order_by(Notification.id)))


# ---------- who may raise one ----------
async def test_who_can_dispute_a_match_and_when(make_user, db):
    lg = await league(make_user)
    mid = await new_match(lg, lg.teams[0], lg.teams[1])
    early = (await cap(lg, 0).req("GET", f"/matches/{mid}/disputes")).json()
    assert early["can_raise"] is False and "once the match has a result" in early["reason"]
    await play_match(lg, mid, "a")

    async def view(user):
        return (await user.req("GET", f"/matches/{mid}/disputes")).json()

    c = await view(cap(lg, 0))
    assert c["can_raise"] and c["role"] == "captain" and c["kinds"] == ["scoring", "eligibility", "umpiring", "other", "conduct"] and c["deadline"]
    assert (await view(vice(lg, 1)))["role"] == "vice_captain" and (await view(vice(lg, 1)))["can_raise"]
    u = await view(lg.umpires[0])
    assert u["can_raise"] and u["role"] == "umpire" and "scoring" in u["kinds"] and "conduct" in u["kinds"]
    p = await view(plain(lg, 0))  # an ordinary player may only report conduct
    assert p["can_raise"] and p["role"] is None and p["kinds"] == ["conduct"]
    third = await view(cap(lg, 2))  # a captain of a team that did not play: not a party to this match
    assert third["role"] is None and third["kinds"] == ["conduct"]
    outsider = await make_user("Fan")
    o = await view(outsider)
    assert o["can_raise"] is False and o["kinds"] == []
    assert (await lg.umpires[1].req("GET", f"/matches/{mid}/disputes")).json()["role"] is None  # another umpire
    # after the window only conduct complaints remain
    await age(db, mid, 49)
    late = await view(cap(lg, 0))
    assert late["kinds"] == ["conduct"] and late["can_raise"]
    r = await raise_it(cap(lg, 0), mid, "scoring")
    assert r.status_code == 409 and "has passed" in r.json()["detail"]
    assert (await raise_it(cap(lg, 0), mid, "conduct")).status_code == 201


async def test_the_window_comes_from_the_rule_set(make_user, db):
    lg = await league(make_user)
    mid = await finished(lg)
    await age(db, mid, 3)
    assert (await cap(lg, 0).req("GET", f"/matches/{mid}/disputes")).json()["kinds"][0] == "scoring"  # 48 hours by default
    rs0 = (await lg.admin.req("GET", f"/seasons/{lg.sid}")).json()["rule_set_id"]
    bad = await lg.admin.req("POST", "/admin/rules", json={"from_id": rs0, "changes": {"dispute_window_hours": 0}, "reason": "no window"})
    assert bad.status_code == 422 and "dispute_window_hours" in bad.json()["detail"]
    new = await lg.admin.req("POST", "/admin/rules", json={"from_id": rs0, "changes": {"dispute_window_hours": 2}, "reason": "two hours only"})
    assert new.status_code == 201
    await lg.admin.req("POST", f"/seasons/{lg.sid}/rules", json={"rule_set_id": new.json()["id"]})
    v = (await cap(lg, 0).req("GET", f"/matches/{mid}/disputes")).json()
    assert v["kinds"] == ["conduct"]  # three hours is now too late


async def test_raising_a_match_dispute(make_user, db):
    lg = await league(make_user)
    mid = await finished(lg)
    c0, c1 = cap(lg, 0), cap(lg, 1)
    assert (await raise_it(c0, mid, body="too short")).status_code == 422
    assert (await raise_it(c0, mid, "bogus")).status_code == 422
    assert (await raise_it(plain(lg, 0), mid, "scoring")).status_code == 403  # an ordinary player cannot
    assert (await c0.req("POST", "/disputes", json={"kind": "scoring", "body": BODY})).status_code == 422  # no match
    assert (await raise_it(c0, 999999)).status_code == 404
    r = await raise_it(c0, mid)
    assert r.status_code == 201 and r.json()["status"] == "open"
    d = (await c0.req("GET", f"/disputes/{r.json()['id']}")).json()
    assert d["kind"] == "scoring" and d["status"] == "open" and d["against"] == "Team2" and d["raised_by"]["as"] == "captain"
    assert d["match"]["match_no"] == 1 and d["match"]["teams"] == "Team1 vs Team2" and d["match_result"].endswith("won by 21 runs")
    # one open dispute per person per match
    again = await raise_it(c0, mid, "umpiring")
    assert again.status_code == 409 and "already have an open dispute" in again.json()["detail"]
    assert (await c0.req("GET", f"/matches/{mid}/disputes")).json()["reason"].startswith("You already have an open dispute")
    assert (await raise_it(c1, mid, "scoring")).status_code == 201  # the other captain may raise their own
    assert (await raise_it(lg.umpires[0], mid, "umpiring")).status_code == 201
    # told: the judges (not the raiser) and the other team's leaders
    admins = await notes(db, "Dispute to look at")
    assert {n.user_id for n in admins} == {lg.admin.id}
    told = await notes(db, "A dispute was raised")
    assert c1.id in {n.user_id for n in told} and vice(lg, 1).id in {n.user_id for n in told}
    log = list(await db.scalars(select(AuditLog.action).where(AuditLog.action == "dispute.raise")))
    assert len(log) == 3


async def test_conduct_complaints(make_user, db):
    lg = await league(make_user)
    mid = await finished(lg)
    p = plain(lg, 0)
    r = await p.req("POST", "/disputes", json={"kind": "conduct", "body": "A player abused others in the chat during the match.",
                                                "season_id": lg.sid, "against_team_id": lg.teams[1]})
    assert r.status_code == 201
    did = r.json()["id"]
    # the accused team's captain can read it; a captain of a team that is not involved cannot
    assert (await cap(lg, 1).req("GET", f"/disputes/{did}")).status_code == 200
    assert (await cap(lg, 2).req("GET", f"/disputes/{did}")).status_code == 404
    assert (await cap(lg, 0).req("GET", f"/disputes/{did}")).status_code == 200  # the raiser's own captain: raiser's team is involved
    # not a player in the season: refused. Unknown team: refused. Too many open ones: refused
    assert (await (await make_user("Fan")).req("POST", "/disputes", json={"kind": "conduct", "body": BODY, "season_id": lg.sid})).status_code == 403
    assert (await p.req("POST", "/disputes", json={"kind": "conduct", "body": BODY, "season_id": lg.sid, "against_team_id": 999999})).status_code == 422
    assert (await p.req("POST", "/disputes", json={"kind": "conduct", "body": BODY})).status_code == 422  # which season?
    for _ in range(2):
        assert (await p.req("POST", "/disputes", json={"kind": "conduct", "body": BODY, "season_id": lg.sid})).status_code == 201
    over = await p.req("POST", "/disputes", json={"kind": "conduct", "body": BODY, "season_id": lg.sid})
    assert over.status_code == 409 and "3 open complaints" in over.json()["detail"]
    # a complaint tied to a match is allowed to any player, long after the window
    await age(db, mid, 500)
    assert (await raise_it(plain(lg, 1), mid, "conduct")).status_code == 201


async def test_no_new_disputes_in_an_archived_season(make_user):
    lg = await league(make_user)
    mid = await finished(lg)
    c0 = cap(lg, 0)
    d = (await raise_it(c0, mid)).json()["id"]
    await lg.admin.req("POST", f"/admin/disputes/{d}/dismiss", json={"outcome": "Nothing wrong with the scoring."})
    assert (await lg.admin.req("POST", f"/seasons/{lg.sid}/archive")).status_code == 200
    r = await raise_it(cap(lg, 1), mid)
    assert r.status_code == 409 and "archived" in r.json()["detail"]
    assert (await c0.req("POST", "/disputes", json={"kind": "conduct", "body": BODY, "season_id": lg.sid})).status_code == 409
    assert (await lg.admin.req("POST", f"/admin/disputes/{d}/reopen", json={"reason": "new evidence"})).status_code == 409
    assert (await c0.req("GET", f"/matches/{mid}/disputes")).json()["reason"] == "This season is archived"


# ---------- who can see it ----------
async def test_disputes_are_visible_only_to_those_involved(make_user, client):
    lg = await league(make_user)
    mid = await finished(lg)
    did = (await raise_it(cap(lg, 0), mid)).json()["id"]
    for who in (cap(lg, 0), cap(lg, 1), vice(lg, 1), lg.admin):
        assert (await who.req("GET", f"/disputes/{did}")).status_code == 200
    # everyone else gets the same "not found" as for a dispute that does not exist
    for who in (plain(lg, 0), plain(lg, 1), cap(lg, 2), lg.umpires[0], lg.umpires[1], await make_user("Fan")):
        r = await who.req("GET", f"/disputes/{did}")
        assert r.status_code == 404 and r.json() == (await who.req("GET", "/disputes/999999")).json()
    assert (await client.get(f"/disputes/{did}")).status_code == 401
    assert [x["id"] for x in (await cap(lg, 1).req("GET", "/disputes")).json()] == [did]  # the other captain finds it in their list
    assert (await cap(lg, 2).req("GET", "/disputes")).json() == []
    assert (await plain(lg, 0).req("GET", "/disputes")).json() == []
    assert [x["id"] for x in (await cap(lg, 1).req("GET", f"/matches/{mid}/disputes")).json()["disputes"]] == [did]
    assert (await plain(lg, 1).req("GET", f"/matches/{mid}/disputes")).json()["disputes"] == []
    assert (await cap(lg, 0).req("GET", "/admin/disputes")).status_code == 403


async def test_nothing_about_disputes_is_public(make_user, client):
    lg = await league(make_user)
    mid = await finished(lg)
    await raise_it(cap(lg, 0), mid)
    slug = (await lg.admin.req("GET", f"/seasons/{lg.sid}")).json()["slug"]
    blob = ""
    for p in ("/public/seasons", f"/public/seasons/{slug}", f"/public/matches/{mid}", f"/public/matches/{mid}/live",
              f"/public/seasons/{slug}/fixtures", "/public/sitemap", "/public/history"):
        blob += (await client.get(p)).text.lower()
    assert "dispute" not in blob and BODY.lower() not in blob


# ---------- the conversation ----------
async def test_messages_and_private_notes(make_user, db):
    lg = await league(make_user)
    mid = await finished(lg)
    c0, c1 = cap(lg, 0), cap(lg, 1)
    did = (await raise_it(c0, mid)).json()["id"]
    assert (await c1.req("POST", f"/disputes/{did}/messages", json={"body": "We disagree: the umpire scored it correctly."})).status_code == 201
    assert (await c1.req("POST", f"/disputes/{did}/messages", json={"body": "secret", "internal": True})).status_code == 403  # parties cannot keep notes
    assert (await plain(lg, 0).req("POST", f"/disputes/{did}/messages", json={"body": "let me in"})).status_code == 404
    assert (await c0.req("POST", f"/disputes/{did}/messages", json={"body": ""})).status_code == 422
    assert (await lg.admin.req("POST", f"/disputes/{did}/messages", json={"body": "Checking the ball events now."})).status_code == 201
    note = await lg.admin.req("POST", f"/disputes/{did}/messages", json={"body": "Captain 1 has complained before.", "internal": True})
    assert note.status_code == 201
    as_admin = (await lg.admin.req("GET", f"/disputes/{did}")).json()
    assert [m["internal"] for m in as_admin["messages"]] == [False, False, True]
    assert as_admin["viewer"]["level"] == "admin"
    for who in (c0, c1, vice(lg, 1)):
        d = (await who.req("GET", f"/disputes/{did}")).json()
        assert [m["body"] for m in d["messages"]] == ["We disagree: the umpire scored it correctly.", "Checking the ball events now."]
        assert d["viewer"]["level"] == "party" and not d["viewer"]["can_decide"] and "Captain 1" not in str(d)
    # who heard about what: public messages go to the others, private notes to nobody
    msgs = await notes(db, "New message on a dispute")
    n0, n1, na = await name(db, c0), await name(db, c1), await name(db, lg.admin)
    got = {(n.user_id, n.body.split(":")[0]) for n in msgs}
    assert (c0.id, n1) in got and (c1.id, na) in got and not any("Captain 1 has" in (n.body or "") for n in msgs)
    assert all(n.user_id != lg.admin.id or n.body.startswith(n0) or n.body.startswith(n1) for n in msgs)


# ---------- deciding ----------
async def test_take_resolve_and_the_follow_up(make_user, db):
    lg = await league(make_user)
    mid = await finished(lg)
    c0 = cap(lg, 0)
    did = (await raise_it(c0, mid)).json()["id"]
    assert (await c0.req("POST", f"/admin/disputes/{did}/take")).status_code == 403
    assert (await lg.admin.req("POST", f"/admin/disputes/{did}/take")).status_code == 204
    d = (await lg.admin.req("GET", f"/disputes/{did}")).json()
    assert d["status"] == "in_review" and d["assigned_to"] == await name(db, lg.admin)
    assert (await notes(db, "Your dispute is being looked at"))[0].user_id == c0.id

    adj = (await lg.admin.req("POST", f"/seasons/{lg.sid}/adjustments", json={"team_id": lg.teams[0], "points": 1, "reason": "dispute upheld"})).json()
    other = await make_league(make_user, n_teams=2, per_team=2, n_umpires=1, name="Other")
    foreign = (await other.admin.req("POST", f"/seasons/{other.sid}/adjustments", json={"team_id": other.teams[0], "points": 1, "reason": "unrelated"})).json()
    ok = {"outcome": "The last wicket was counted twice. A point was added to make it right."}
    assert (await lg.admin.req("POST", f"/admin/disputes/{did}/resolve", json={**ok, "outcome": "short"})).status_code == 422
    assert (await lg.admin.req("POST", f"/admin/disputes/{did}/resolve", json={**ok, "action": "magic"})).status_code == 422
    assert (await lg.admin.req("POST", f"/admin/disputes/{did}/resolve", json={**ok, "action": "points_adjusted"})).status_code == 422  # which one?
    assert (await lg.admin.req("POST", f"/admin/disputes/{did}/resolve", json={**ok, "action": "points_adjusted", "adjustment_id": foreign["id"]})).status_code == 422
    assert (await lg.admin.req("POST", f"/admin/disputes/{did}/resolve", json={**ok, "action": "points_adjusted", "adjustment_id": 999999})).status_code == 422
    assert (await c0.req("POST", f"/admin/disputes/{did}/resolve", json=ok)).status_code == 403
    r = await lg.admin.req("POST", f"/admin/disputes/{did}/resolve", json={**ok, "action": "points_adjusted", "adjustment_id": adj["id"]})
    assert r.status_code == 204
    d = (await c0.req("GET", f"/disputes/{did}")).json()
    assert d["status"] == "resolved" and d["outcome"] == ok["outcome"] and d["resolution"] == {"action": "points_adjusted", "adjustment_id": adj["id"]}
    assert d["resolved_by"] == await name(db, lg.admin) and d["resolved_at"] and d["viewer"]["can_decide"] is False
    told = await notes(db, "Dispute resolved")
    assert {n.user_id for n in told} == {c0.id, vice(lg, 0).id, cap(lg, 1).id, vice(lg, 1).id}  # both teams' leaders hear the outcome
    # closed: parties cannot add to it, nobody can decide it again; the match page shows the outcome
    assert (await c0.req("POST", f"/disputes/{did}/messages", json={"body": "one more thing"})).status_code == 409
    assert (await lg.admin.req("POST", f"/admin/disputes/{did}/dismiss", json=ok)).status_code == 409
    assert (await lg.admin.req("POST", f"/admin/disputes/{did}/take")).status_code == 409
    assert (await c0.req("POST", f"/disputes/{did}/withdraw")).status_code == 409
    # an admin can reopen it with a reason
    assert (await c0.req("POST", f"/admin/disputes/{did}/reopen", json={"reason": "new evidence"})).status_code == 403
    assert (await lg.admin.req("POST", f"/admin/disputes/{did}/reopen", json={"reason": "x"})).status_code == 422
    assert (await lg.admin.req("POST", f"/admin/disputes/{did}/reopen", json={"reason": "New evidence from the scorer"})).status_code == 204
    d = (await c0.req("GET", f"/disputes/{did}")).json()
    assert d["status"] == "in_review" and d["outcome"] is None and d["resolution"] is None
    assert d["messages"][-1]["body"] == "Reopened: New evidence from the scorer"
    assert (await lg.admin.req("POST", f"/admin/disputes/{did}/reopen", json={"reason": "again please"})).status_code == 409
    actions = [a for a in await db.scalars(select(AuditLog.action).where(AuditLog.entity == "dispute", AuditLog.entity_id == did).order_by(AuditLog.id))]
    assert actions == ["dispute.raise", "dispute.take", "dispute.resolved", "dispute.reopen"]


async def test_dismiss_and_withdraw(make_user, db):
    lg = await league(make_user)
    mid = await finished(lg)
    a = (await raise_it(cap(lg, 0), mid)).json()["id"]
    b = (await raise_it(cap(lg, 1), mid)).json()["id"]
    r = await lg.admin.req("POST", f"/admin/disputes/{a}/dismiss", json={"outcome": "The scoring matches the ball events.", "action": "points_adjusted"})
    assert r.status_code == 204  # a dismissal never records an action
    d = (await cap(lg, 0).req("GET", f"/disputes/{a}")).json()
    assert d["status"] == "dismissed" and d["resolution"] == {"action": "none"}
    assert (await cap(lg, 0).req("POST", f"/disputes/{b}/withdraw")).status_code == 403  # they can see it, but it is not theirs to withdraw
    assert (await cap(lg, 1).req("POST", f"/disputes/{b}/withdraw")).status_code == 204
    assert (await lg.admin.req("GET", f"/disputes/{b}")).json()["status"] == "withdrawn"
    assert (await lg.admin.req("POST", f"/admin/disputes/{b}/dismiss", json={"outcome": "It was withdrawn anyway."})).status_code == 409
    assert (await cap(lg, 0).req("POST", f"/disputes/{a}/withdraw")).status_code == 409


# ---------- admins who are involved ----------
async def test_an_admin_on_the_disputed_team_cannot_judge_it(make_user, db):
    lg = await league(make_user)
    insider = await make_user("InsiderAdmin", roles=["tournament_admin"])  # plays for Team1 as well
    assert (await lg.admin.req("POST", f"/teams/{lg.teams[0]}/members", json={"user_id": insider.id})).status_code == 201
    mid = await finished(lg)
    did = (await raise_it(cap(lg, 1), mid)).json()["id"]  # Team2's captain disputes the Team1 v Team2 result
    # the insider is not asked, cannot see it, cannot decide it
    assert {n.user_id for n in await notes(db, "Dispute to look at")} == {lg.admin.id}
    for path in (f"/disputes/{did}",):
        assert (await insider.req("GET", path)).status_code == 404
    for action in ("take", "resolve", "dismiss", "reopen"):
        r = await insider.req("POST", f"/admin/disputes/{did}/{action}", json={"outcome": "I would like to decide this one.", "reason": "abc"})
        assert r.status_code == 404, action
    assert [x["id"] for x in (await insider.req("GET", "/admin/disputes")).json()] == []
    assert (await insider.req("GET", "/admin/disputes/summary")).json() == {"open": 0, "in_review": 0, "stale": 0, "mine": 0}
    assert (await insider.req("POST", f"/disputes/{did}/messages", json={"body": "hello"})).status_code == 404
    assert [x["id"] for x in (await lg.admin.req("GET", "/admin/disputes")).json()] == [did]


async def test_an_admin_who_is_a_captain_is_a_party_not_a_judge(make_user, db):
    lg = await league(make_user)
    boss = await make_user("CaptainAdmin", roles=["tournament_admin"])
    assert (await lg.admin.req("POST", f"/teams/{lg.teams[1]}/members", json={"user_id": boss.id})).status_code == 201
    assert (await lg.admin.req("PATCH", f"/teams/{lg.teams[1]}", json={"captain_id": boss.id})).status_code == 200
    mid = await finished(lg)
    did = (await raise_it(cap(lg, 0), mid)).json()["id"]
    d = (await boss.req("GET", f"/disputes/{did}")).json()  # they lead Team2, so they may read and reply as a party
    assert d["viewer"]["level"] == "party" and not d["viewer"]["can_decide"]
    assert (await boss.req("POST", f"/admin/disputes/{did}/resolve", json={"outcome": "I resolve my own case, thanks."})).status_code == 403
    assert (await boss.req("POST", f"/admin/disputes/{did}/take")).status_code == 403
    assert (await boss.req("POST", f"/disputes/{did}/messages", json={"body": "internal?", "internal": True})).status_code == 403
    assert (await boss.req("GET", "/admin/disputes")).json() == []
    # an admin raising a dispute themselves cannot decide it either
    own = (await raise_it(boss, mid, "conduct")).json()["id"]
    assert (await boss.req("POST", f"/admin/disputes/{own}/dismiss", json={"outcome": "Not a problem at all really."})).status_code == 403
    assert (await lg.admin.req("POST", f"/admin/disputes/{own}/dismiss", json={"outcome": "Looked into it and found nothing."})).status_code == 204


# ---------- the admin queue ----------
async def test_admin_queue_filters_and_summary(make_user, db):
    lg = await league(make_user)
    m1, m2 = await finished(lg, 0, 1), await finished(lg, 2, 3)
    a = (await raise_it(cap(lg, 0), m1, "scoring")).json()["id"]
    b = (await raise_it(cap(lg, 2), m2, "umpiring")).json()["id"]
    c = (await raise_it(plain(lg, 1), m1, "conduct")).json()["id"]
    q = lambda **kw: lg.admin.req("GET", "/admin/disputes?" + "&".join(f"{k}={v}" for k, v in kw.items()))
    assert [x["id"] for x in (await q()).json()] == [a, b, c]  # oldest first
    assert [x["id"] for x in (await q(kind="umpiring")).json()] == [b]
    assert [x["id"] for x in (await q(season_id=lg.sid)).json()] == [a, b, c]
    assert (await q(season_id=999999)).json() == []
    assert [x["id"] for x in (await q(assigned="nobody")).json()] == [a, b, c]
    await lg.admin.req("POST", f"/admin/disputes/{a}/take")
    assert [x["id"] for x in (await q(assigned="me")).json()] == [a]
    assert [x["id"] for x in (await q(assigned="nobody")).json()] == [b, c]
    row = (await q(assigned="me")).json()[0]
    assert row["raised_by"]["as"] == "captain" and row["match"]["teams"] == "Team1 vs Team2" and row["against"] == "Team2" and row["assigned_to"] == await name(db, lg.admin)
    await lg.admin.req("POST", f"/admin/disputes/{c}/dismiss", json={"outcome": "No evidence of a problem was found."})
    assert [x["id"] for x in (await q(status="closed")).json()] == [c]
    assert {x["id"] for x in (await q(status="all")).json()} == {a, b, c}
    assert (await q(status="bogus")).status_code == 422 and (await q(assigned="you")).status_code == 422
    await db.execute(update(Dispute).where(Dispute.id == b).values(created_at=datetime.now(UTC) - timedelta(days=4)))
    await db.commit()
    assert (await lg.admin.req("GET", "/admin/disputes/summary")).json() == {"open": 1, "in_review": 1, "stale": 1, "mine": 1}


# ---------- reminders ----------
async def test_old_disputes_are_flagged_to_the_admins_who_may_decide(make_user, db, engine):
    lg = await league(make_user)
    insider = await make_user("InsiderAdmin", roles=["tournament_admin"])
    await lg.admin.req("POST", f"/teams/{lg.teams[0]}/members", json={"user_id": insider.id})
    mid = await finished(lg)
    stale = (await raise_it(cap(lg, 1), mid)).json()["id"]
    fresh = (await raise_it(cap(lg, 0), mid)).json()["id"]
    closed = (await raise_it(cap(lg, 2), await finished(lg, 2, 3))).json()["id"]
    await lg.admin.req("POST", f"/admin/disputes/{closed}/dismiss", json={"outcome": "Nothing to see here, really."})
    old = datetime.now(UTC) - timedelta(days=4)
    await db.execute(update(Dispute).where(Dispute.id.in_([stale, closed])).values(created_at=old))
    await db.commit()
    ctx = {"session_factory": async_sessionmaker(engine, expire_on_commit=False)}
    assert await remind_stale_disputes(ctx) == 1  # only the open dispute that has waited 72 hours
    got = await notes(db, "Dispute waiting 4 days")
    assert [(n.user_id, n.data["link"]) for n in got] == [(lg.admin.id, f"/disputes/{stale}")]
    assert await remind_stale_disputes(ctx) == 0  # once a day, not on every run
    later = datetime.now(UTC) + timedelta(days=1, minutes=1)
    assert await remind_stale_disputes(ctx, now=later) == 1  # the next day it is mentioned again; the fresh one has only waited a day
    assert fresh and (await notes(db, "Dispute waiting 5 days"))


def test_the_worker_runs_the_reminder_daily():
    from app.worker import WorkerSettings

    assert "cron:remind_stale_disputes" in {j.name for j in WorkerSettings.cron_jobs}
    assert "remind_stale_disputes" in {f.__name__ for f in WorkerSettings.functions}
