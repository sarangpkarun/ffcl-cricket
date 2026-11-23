import re
from datetime import UTC, datetime, timedelta

from fastapi.routing import APIRoute
from sqlalchemy import select, update

from app.db.models import Dispute, Notification, RosterChange, User
from app.deps import (
    ANY_ADMIN_MARK,
    GLOBAL_ADMIN_MARK,
    ROLE_MARK,
    SEASON_ADMIN_MARK,
    admin_scope,
    is_admin,
    season_of,
)
from app.main import app
from tests.helpers import League, make_league, new_match, play_match

BODY = "The second innings was scored wrongly: the last wicket should not have counted."


async def two_seasons(make_user):
    """Two seasons, each with its own global admin, and a season admin for the first only."""
    one = await make_league(make_user, n_teams=4, per_team=4, n_umpires=2, name="One")
    two = await make_league(make_user, n_teams=4, per_team=4, n_umpires=2, name="Two")
    sup = await make_user("Super", roles=["super_admin"])
    sa = await make_user("SeasonAdmin")
    r = await sup.req("POST", f"/users/{sa.id}/roles", json={"role": "tournament_admin", "season_id": one.sid})
    assert r.status_code == 204, r.text
    return one, two, sup, sa


async def resources(lg: League, db) -> dict:
    """One of everything a season admin route can be keyed by."""
    mid = await new_match(lg, lg.teams[0], lg.teams[1])
    team = lg.teams[2]
    adj = (await lg.admin.req("POST", f"/seasons/{lg.sid}/adjustments", json={"team_id": team, "points": 1, "reason": "to test"})).json()
    duty = (await lg.admin.req("GET", f"/seasons/{lg.sid}/duties")).json()[0]["id"]
    free = next(iter(lg.players[lg.teams[3]]))
    rc = RosterChange(team_id=team, out_user_id=lg.players[team][1].id, in_user_id=free.id, reason="test", requested_by=lg.players[team][0].id)
    d = Dispute(season_id=lg.sid, match_id=mid, kind="other", raised_by=lg.players[lg.teams[0]][0].id, raised_as="captain", body=BODY)
    db.add_all([rc, d])
    await db.commit()
    from app.db.models import Invite

    inv = Invite(token_hash=f"t{lg.sid}", name="Invited", phone=f"+9188{lg.sid:08d}", team_id=team, season_id=lg.sid, created_by=lg.players[team][0].id,
                 expires_at=datetime.now(UTC) + timedelta(days=1))
    db.add(inv)
    await db.commit()
    return {"season": lg.sid, "match": mid, "team": team, "adjustment": adj["id"], "duty": duty, "roster": rc.id, "dispute": d.id, "invite": inv.id}


PARAM = {"season": "season_id", "match": "match_id", "team": "team_id", "adjustment": "adjustment_id", "duty": "duty_id",
         "roster": "rc_id", "dispute": "dispute_id", "invite": "invite_id"}


def api_routes():
    """Every API route. This FastAPI keeps each included router as one wrapper, so look inside them."""
    for r in app.routes:
        if isinstance(r, APIRoute):
            yield r
        elif hasattr(r, "original_router"):
            yield from (x for x in r.original_router.routes if isinstance(x, APIRoute))


def guards(route: APIRoute) -> list:
    out = []

    def walk(dep):
        for sub in dep.dependencies:
            out.append(sub.call)
            walk(sub)

    walk(route.dependant)
    return out


def classify(route: APIRoute) -> tuple[str, str | None]:
    """("season", by) | ("global", None) | ("any", None) | ("role", roles) | ("open", None)"""
    kinds = []
    for call in guards(route):
        if (by := getattr(call, SEASON_ADMIN_MARK, None)) is not None:
            return "season", by
        if getattr(call, GLOBAL_ADMIN_MARK, False):
            kinds.append(("global", None))
        if getattr(call, ANY_ADMIN_MARK, False):
            kinds.append(("any", None))
        if (roles := getattr(call, ROLE_MARK, None)) is not None:
            kinds.append(("role", ",".join(roles)))
    return kinds[0] if kinds else ("open", None)


def url_for(route: APIRoute, ids: dict, by: str | None) -> str:
    path = route.path

    def sub(m):
        name = m.group(1)
        for kind, param in PARAM.items():
            if param == name:
                return str(ids[kind]) if by is not None or kind == "season" else "1"
        return "1"

    return re.sub(r"\{(\w+)\}", sub, path)


# ---------- the matrix ----------
async def test_a_season_admin_is_refused_on_every_admin_route_of_another_season(make_user, db):
    _one, two, _sup, sa = await two_seasons(make_user)
    other = await resources(two, db)
    checked_season = checked_global = 0
    for route in api_routes():
        kind, by = classify(route)
        if kind == "season":
            for method in route.methods - {"HEAD", "OPTIONS"}:
                r = await sa.req(method, url_for(route, other, by), json={})
                assert r.status_code == 403, (method, route.path, r.status_code, r.text[:100])
            checked_season += 1
        elif kind == "global" or (kind == "role" and by == "super_admin"):
            for method in route.methods - {"HEAD", "OPTIONS"}:
                r = await sa.req(method, url_for(route, other, None), json={})
                assert r.status_code == 403, (method, route.path, r.status_code, r.text[:100])
            checked_global += 1
    assert checked_season >= 25 and checked_global >= 15, (checked_season, checked_global)  # the matrix really covered the routes


async def test_no_admin_route_can_be_added_without_a_guard():
    """Every route under /admin, and every route that takes a season admin, has an explicit guard."""
    unguarded = []
    for route in api_routes():
        if route.path.startswith("/admin") and classify(route)[0] == "open":
            unguarded.append(route.path)
    assert unguarded == []
    kinds = {classify(r)[0] for r in api_routes()}
    assert {"season", "global", "any", "role", "open"} <= kinds


async def test_every_resolver_finds_the_right_season(make_user, db):
    one, two, _sup, _sa = await two_seasons(make_user)
    mine, theirs = await resources(one, db), await resources(two, db)
    for kind, param in PARAM.items():
        assert await season_of(db, kind, {param: mine[kind]}) == one.sid, kind
        assert await season_of(db, kind, {param: theirs[kind]}) == two.sid, kind
        assert await season_of(db, kind, {param: 999999}) is None or kind == "season"


async def test_is_admin_fails_closed_without_a_season(make_user, db):
    one, two, _sup, sa = await two_seasons(make_user)
    user = await db.get(User, sa.id)
    assert await is_admin(db, user) is False  # no season given: only global admins qualify
    assert await is_admin(db, user, one.sid) is True and await is_admin(db, user, two.sid) is False
    glob = await db.get(User, one.admin.id)
    assert await is_admin(db, glob) is True and await is_admin(db, glob, two.sid) is True
    scope = await admin_scope(db, sa.id)
    assert (scope.is_global, set(scope.seasons)) == (False, {one.sid})


# ---------- what a season admin can and cannot do ----------
async def test_me_says_where_someone_is_an_admin(make_user):
    one, two, sup, sa = await two_seasons(make_user)
    both = await make_user("Both")
    for lg in (one, two):
        await sup.req("POST", f"/users/{both.id}/roles", json={"role": "tournament_admin", "season_id": lg.sid})
    assert (await sa.req("GET", "/me")).json()["admin"] == {"is_global": False, "seasons": [one.sid]}
    assert (await both.req("GET", "/me")).json()["admin"] == {"is_global": False, "seasons": sorted([one.sid, two.sid])}
    assert (await one.admin.req("GET", "/me")).json()["admin"] == {"is_global": True, "seasons": []}
    assert (await sup.req("GET", "/me")).json()["admin"]["is_global"] is True
    assert (await one.players[one.teams[0]][0].req("GET", "/me")).json()["admin"] == {"is_global": False, "seasons": []}


async def test_a_season_admin_runs_their_own_season(make_user, db):
    one, two, _sup, sa = await two_seasons(make_user)
    # build the season: teams, a schedule, publish it
    t = await sa.req("POST", f"/seasons/{one.sid}/teams", json={"name": "Extra"})
    assert t.status_code == 201
    params = {"start_date": "2031-02-01", "times": ["19:00"], "timezone": "UTC", "team_ids": one.teams}
    assert (await sa.req("POST", f"/seasons/{one.sid}/fixtures/preview", json=params)).status_code == 200
    gen = await sa.req("POST", f"/seasons/{one.sid}/fixtures/generate", json=params)
    assert gen.status_code == 201, gen.text
    draft = gen.json()["match_ids"][0]
    assert any(f["id"] == draft for f in (await sa.req("GET", f"/seasons/{one.sid}/fixtures?include_drafts=true")).json())
    assert (await sa.req("GET", f"/matches/{draft}")).status_code == 200  # drafts are visible to the season's admin
    assert (await sa.req("POST", f"/seasons/{one.sid}/fixtures/publish", json={})).status_code == 200
    m = await sa.req("POST", f"/seasons/{one.sid}/matches", json={"team_a_id": one.teams[0], "team_b_id": one.teams[1]})
    assert m.status_code == 201
    assert (await sa.req("PATCH", f"/matches/{m.json()['id']}", json={"scheduled_at": "2031-03-01T10:00:00Z"})).status_code == 200
    # points, exports, rules, and the season itself
    adj = await sa.req("POST", f"/seasons/{one.sid}/adjustments", json={"team_id": one.teams[0], "points": -1, "reason": "late arrival"})
    assert adj.status_code == 201
    assert len((await sa.req("GET", f"/seasons/{one.sid}/adjustments")).json()) == 1
    assert (await sa.req("POST", f"/adjustments/{adj.json()['id']}/void", json={"reason": "mistake made"})).status_code == 200
    for kind in ("fixtures", "table", "players"):
        assert (await sa.req("GET", f"/seasons/{one.sid}/export/{kind}.csv")).status_code == 200
    assert (await sa.req("GET", f"/seasons/{one.sid}/duties")).status_code == 200
    assert (await sa.req("PATCH", f"/seasons/{one.sid}", json={"name": "Renamed by a season admin"})).status_code == 200
    # …and the other season stays out of reach, even through ids inside this season's routes
    bad = await sa.req("POST", f"/seasons/{one.sid}/matches", json={"team_a_id": one.teams[0], "team_b_id": two.teams[0]})
    assert bad.status_code == 400 and "must belong to this season" in bad.json()["detail"]
    assert (await sa.req("GET", f"/seasons/{two.sid}/adjustments")).status_code == 403
    assert (await sa.req("PATCH", f"/seasons/{two.sid}", json={"name": "Hijacked"})).status_code == 403


async def test_a_season_admin_can_play_archive_and_decide_in_their_season_only(make_user, db):
    one, two, _sup, sa = await two_seasons(make_user)
    mine = await new_match(one, one.teams[0], one.teams[1])
    theirs = await new_match(two, two.teams[0], two.teams[1])
    for lg, mid in ((one, mine), (two, theirs)):
        for t in lg.teams[:2]:
            await lg.admin.req("PUT", f"/matches/{mid}/lineup", json={"team_id": t, "user_ids": [p.id for p in lg.players[t]]})
    assert (await sa.req("POST", f"/matches/{mid_of(theirs)}/toss/open")).status_code == 403  # not the official of that season's match
    assert (await sa.req("POST", f"/matches/{mine}/toss/open")).status_code == 204  # but is for their own
    assert (await sa.req("GET", f"/matches/{theirs}")).status_code == 200  # published matches are readable by anyone
    # a draft of the other season is simply not there for them
    gen = await two.admin.req("POST", f"/seasons/{two.sid}/fixtures/generate", json={"start_date": "2031-02-01", "times": ["19:00"], "timezone": "UTC", "team_ids": two.teams, "replace_drafts": False})
    draft = gen.json()["match_ids"][0]
    assert (await sa.req("GET", f"/matches/{draft}")).status_code == 404
    assert all(f["id"] != draft for f in (await sa.req("GET", f"/seasons/{two.sid}/fixtures?include_drafts=true")).json())
    # finish a match in each season, then archive: only their own
    await play_match(one, await new_match(one, one.teams[2], one.teams[3]), "a")
    await one.admin.req("POST", f"/matches/{mine}/abandon", json={"reason": "rain"})
    assert (await sa.req("POST", f"/seasons/{one.sid}/archive")).status_code == 200
    assert (await sa.req("POST", f"/seasons/{one.sid}/unarchive")).status_code == 200
    assert (await sa.req("POST", f"/seasons/{two.sid}/archive")).status_code == 403


def mid_of(x):
    return x


async def test_a_season_admin_decides_rosters_and_disputes_of_their_season(make_user, db):
    one, two, _sup, sa = await two_seasons(make_user)
    mine, theirs = await resources(one, db), await resources(two, db)
    # roster requests: they see and decide their own season's, nobody else's
    listed = (await sa.req("GET", "/roster-changes")).json()
    assert [r["id"] for r in listed] == [mine["roster"]]
    assert (await sa.req("GET", f"/seasons/{one.sid}/roster-changes/summary")).json() == {"pending": 1}
    assert (await sa.req("GET", f"/seasons/{two.sid}/roster-changes/summary")).status_code == 403
    assert (await sa.req("POST", f"/roster-changes/{theirs['roster']}/reject", json={"note": "not yours to decide"})).status_code == 403
    assert (await sa.req("POST", f"/roster-changes/{mine['roster']}/reject", json={"note": "season is too far along"})).status_code == 200
    # disputes: the queue shows only their season; deciding works only there
    for lg, d in ((one, mine["dispute"]), (two, theirs["dispute"])):
        await db.execute(update(Dispute).where(Dispute.id == d).values(status="open"))
    await db.commit()
    queue = (await sa.req("GET", "/admin/disputes")).json()
    assert [q["id"] for q in queue] == [mine["dispute"]]
    assert (await sa.req("GET", "/admin/disputes/summary")).json()["open"] == 1
    assert (await sa.req("POST", f"/admin/disputes/{theirs['dispute']}/take")).status_code == 403
    assert (await sa.req("GET", f"/disputes/{theirs['dispute']}")).status_code == 404  # not even visible
    assert (await sa.req("POST", f"/admin/disputes/{mine['dispute']}/take")).status_code == 204
    done = await sa.req("POST", f"/admin/disputes/{mine['dispute']}/dismiss", json={"outcome": "The scoring matches the ball events."})
    assert done.status_code == 204
    plain = await make_user("Plain")
    assert (await plain.req("GET", "/admin/disputes")).status_code == 403  # a non-admin is refused by the shared guard


async def test_people_in_a_season_are_told_about_that_season_only(make_user, db):
    one, two, _sup, sa = await two_seasons(make_user)
    free = await make_user("Free")
    for lg in (one, two):
        cap = lg.players[lg.teams[0]][0]
        r = await cap.req("POST", f"/teams/{lg.teams[0]}/roster-changes", json={"out_user_id": lg.players[lg.teams[0]][1].id, "in_user_id": free.id, "reason": "needs to move away"})
        assert r.status_code == 201, r.text
    db.expire_all()
    got = list(await db.scalars(select(Notification).where(Notification.title == "Roster change to approve")))
    by_user = {n.user_id for n in got}
    assert sa.id in by_user and one.admin.id in by_user and two.admin.id in by_user  # global admins hear about both
    assert sum(n.user_id == sa.id for n in got) == 1  # the season admin hears about their own season only
    # disputes: judges of a season are its admins, not another season's admin
    mid = await new_match(one, one.teams[0], one.teams[1])
    await play_match(one, mid, "a")
    d = await one.players[one.teams[0]][0].req("POST", "/disputes", json={"kind": "scoring", "body": BODY, "match_id": mid})
    assert d.status_code == 201
    db.expire_all()
    heard = {n.user_id for n in await db.scalars(select(Notification).where(Notification.title == "Dispute to look at"))}
    assert sa.id in heard and one.admin.id in heard and two.admin.id in heard


async def test_chat_rooms_follow_the_same_boundary(make_user, db):
    one, two, _sup, sa = await two_seasons(make_user)
    m1, m2 = await new_match(one, one.teams[0], one.teams[1]), await new_match(two, two.teams[0], two.teams[1])
    mine = (await sa.req("GET", f"/matches/{m1}/rooms")).json()
    assert mine["match"] is not None and mine["umpire"] is not None  # an admin of that season reads both rooms
    theirs = (await sa.req("GET", f"/matches/{m2}/rooms")).json()
    assert theirs == {"match": None, "umpire": None}  # nothing readable in the other season
    glob = (await two.admin.req("GET", f"/matches/{m2}/rooms")).json()
    assert glob["match"] is not None  # their own season's admin can
    assert (await sa.req("GET", f"/rooms/{glob['match']['room_id']}")).status_code == 404  # unreadable rooms look the same as missing ones
    assert (await sa.req("GET", f"/rooms/{mine['match']['room_id']}")).json()["moderator"] is True  # and they moderate their own


# ---------- granting and revoking ----------
async def test_granting_and_revoking_season_admins(make_user, db):
    one, two, sup, sa = await two_seasons(make_user)
    other = await make_user("Other")
    assert (await sup.req("POST", f"/users/{other.id}/roles", json={"role": "tournament_admin", "season_id": 999999})).status_code == 404
    assert (await sup.req("POST", f"/users/{other.id}/roles", json={"role": "super_admin", "season_id": one.sid})).status_code == 422
    assert (await one.admin.req("POST", f"/users/{other.id}/roles", json={"role": "tournament_admin", "season_id": one.sid})).status_code == 403  # only a super admin
    assert (await sa.req("POST", f"/users/{other.id}/roles", json={"role": "tournament_admin", "season_id": one.sid})).status_code == 403  # nor a season admin
    assert (await sup.req("POST", f"/users/{other.id}/roles", json={"role": "tournament_admin", "season_id": two.sid})).status_code == 204
    assert (await other.req("GET", f"/seasons/{two.sid}/adjustments")).status_code == 200
    assert (await other.req("GET", f"/seasons/{one.sid}/adjustments")).status_code == 403
    # revoking takes effect at once, and only for that season
    gone = await sup.req("DELETE", f"/admin/users/{sa.id}/roles/tournament_admin?season_id={one.sid}")
    assert gone.status_code == 204, gone.text
    assert (await sa.req("GET", f"/seasons/{one.sid}/adjustments")).status_code == 403
    assert (await sa.req("GET", "/me")).json()["admin"] == {"is_global": False, "seasons": []}
    assert (await sup.req("DELETE", f"/admin/users/{other.id}/roles/tournament_admin")).status_code == 404  # that is the global role, which they do not have
    # a season admin cannot manage people, rules, moderation or the audit log
    sa2 = await make_user("SeasonAdmin2")
    await sup.req("POST", f"/users/{sa2.id}/roles", json={"role": "tournament_admin", "season_id": one.sid})
    for method, path in (("GET", "/admin/users"), ("GET", "/admin/audit"), ("GET", "/admin/rules"), ("GET", "/admin/reports"),
                         ("GET", "/admin/phone-changes"), ("POST", "/seasons"), ("POST", "/admin/results/rebuild")):
        r = await sa2.req(method, path, json={"name": "x", "status": "draft"} if method == "POST" else None) if method == "POST" else await sa2.req(method, path)
        assert r.status_code == 403, (method, path, r.status_code)


async def test_a_missing_id_does_not_reveal_anything_to_a_season_admin(make_user, db):
    one, _two, _sup, sa = await two_seasons(make_user)
    for path in ("/matches/999999", "/duties/999999/reverse", "/adjustments/999999/void", "/admin/disputes/999999/take", "/roster-changes/999999/approve"):
        method = "PATCH" if path.startswith("/matches") else "POST"
        assert (await sa.req(method, path, json={})).status_code == 403, path  # no 404, so ids cannot be probed
    assert (await one.admin.req("PATCH", "/matches/999999", json={})).status_code == 404  # a global admin does get the 404


async def test_season_admin_results_unchanged_for_global_admins(make_user, db):
    """A global admin keeps working everywhere, including routes that now look at the season."""
    one, two, _sup, _sa = await two_seasons(make_user)
    r = await resources(two, db)
    assert (await one.admin.req("GET", f"/seasons/{two.sid}/adjustments")).status_code == 200  # another season's admin, but global
    assert (await one.admin.req("GET", f"/seasons/{two.sid}/export/table.csv")).status_code == 200
    assert (await one.admin.req("POST", f"/adjustments/{r['adjustment']}/void", json={"reason": "global admin acting"})).status_code == 200


# ---------- starting the next season ----------
async def test_a_new_season_can_start_from_an_old_one(make_user, db):
    one, _two, sup, sa = await two_seasons(make_user)
    mid = await new_match(one, one.teams[0], one.teams[1])
    await play_match(one, mid, "a")
    await one.admin.req("PATCH", f"/seasons/{one.sid}", json={"status": "completed"})
    src = (await one.admin.req("GET", f"/seasons/{one.sid}")).json()
    # only a global admin can create a season
    assert (await sa.req("POST", f"/seasons/{one.sid}/clone", json={"name": "Next"})).status_code == 403
    assert (await one.players[one.teams[0]][0].req("POST", f"/seasons/{one.sid}/clone", json={"name": "Next"})).status_code == 403
    # teams only
    r = await one.admin.req("POST", f"/seasons/{one.sid}/clone", json={"name": "Next Year", "copy_teams": True})
    assert r.status_code == 201, r.text
    new = r.json()
    assert (new["teams"], new["players"], new["status"], new["slug"]) == (4, 0, "draft", "next-year") and new["rule_set_id"] == src["rule_set_id"]
    got = (await one.admin.req("GET", f"/seasons/{new['id']}")).json()
    assert got["is_public"] is False and got["status"] == "draft"  # hidden until the organisers say so
    teams = (await one.admin.req("GET", f"/seasons/{new['id']}/teams")).json()
    assert sorted(t["name"] for t in teams) == ["Team1", "Team2", "Team3", "Team4"]
    assert (await one.admin.req("GET", f"/seasons/{new['id']}/fixtures")).json() == []  # no matches, results or adjustments carry over
    assert (await one.admin.req("GET", f"/seasons/{new['id']}/standings")).json()["matches_counted"] == 0
    assert (await one.admin.req("GET", f"/seasons/{new['id']}/adjustments")).json() == []
    for t in teams:  # empty rosters
        assert (await one.admin.req("GET", f"/teams/{t['id']}")).json()["members"] == []
    # with rosters: approved players, captains and vice-captains come across; a suspended player does not
    gone = one.players[one.teams[1]][3]
    await sup.req("PUT", f"/users/{gone.id}/status", json={"status": "suspended"})
    r2 = await one.admin.req("POST", f"/seasons/{one.sid}/clone", json={"name": "Next Year", "copy_rosters": True})
    assert r2.status_code == 409  # the name is taken
    r2 = await one.admin.req("POST", f"/seasons/{one.sid}/clone", json={"name": "Next Year!", "copy_rosters": True})
    assert r2.status_code == 201 and r2.json()["slug"] == "next-year-2" and r2.json()["teams"] == 4 and r2.json()["players"] == 15
    new2 = r2.json()["id"]
    by_name = {t["name"]: t for t in (await one.admin.req("GET", f"/seasons/{new2}/teams")).json()}
    t1 = (await one.admin.req("GET", f"/teams/{by_name['Team1']['id']}")).json()
    assert {m["user_id"] for m in t1["members"]} == {p.id for p in one.players[one.teams[0]]}
    assert t1["captain_id"] == one.players[one.teams[0]][0].id and t1["vice_captain_id"] is None  # no vice-captain was set in the old season
    t2 = (await one.admin.req("GET", f"/teams/{by_name['Team2']['id']}")).json()
    assert gone.id not in {m["user_id"] for m in t2["members"]} and len(t2["members"]) == 3
    # the new season is a normal one: the players are free to be placed, the old one is untouched
    assert (await one.admin.req("GET", f"/seasons/{one.sid}/standings")).json()["matches_counted"] == 1
    assert (await one.admin.req("POST", "/seasons/999999/clone", json={"name": "Nope"})).status_code == 404
    assert (await one.admin.req("POST", f"/seasons/{one.sid}/clone", json={"name": ""})).status_code == 422


# ---------- one season at a glance ----------
async def test_the_season_dashboard(make_user, db):
    one, two, _sup, sa = await two_seasons(make_user)
    mid = await new_match(one, one.teams[0], one.teams[1])
    await play_match(one, mid, "a")
    live = await new_match(one, one.teams[2], one.teams[3])
    await one.admin.req("POST", f"/matches/{live}/abandon", json={"reason": "rain"})
    await new_match(one, one.teams[0], one.teams[2])
    await one.admin.req("POST", f"/seasons/{one.sid}/adjustments", json={"team_id": one.teams[0], "points": 1, "reason": "to test"})
    await one.admin.req("POST", f"/seasons/{one.sid}/fixtures/generate", json={"start_date": "2031-02-01", "times": ["19:00"], "timezone": "UTC", "team_ids": one.teams[:2]})
    d = (await one.players[one.teams[0]][0].req("POST", "/disputes", json={"kind": "scoring", "body": BODY, "match_id": mid})).json()["id"]
    assert d
    for who in (sa, one.admin):
        r = await who.req("GET", f"/admin/seasons/{one.sid}/dashboard")
        assert r.status_code == 200, r.text
        dash = r.json()
        assert dash["season"]["slug"] and dash["season"]["is_public"] is True and dash["teams"] == 4 and dash["players"] == 16
        assert dash["matches"] == {"drafts": 1, "upcoming": 1, "live": 0, "finished": 2}
        assert dash["waiting"] == {"roster_changes": 0, "disputes": 1, "missed_duties": 0} and dash["adjustments"] == 1
        assert dash["rules"]["name"] and len(dash["next"]) == 1 and "vs" in dash["next"][0]["teams"]
    assert (await sa.req("GET", f"/admin/seasons/{two.sid}/dashboard")).status_code == 403
    assert (await one.players[one.teams[0]][0].req("GET", f"/admin/seasons/{one.sid}/dashboard")).status_code == 403
    assert (await one.admin.req("GET", "/admin/seasons/999999/dashboard")).status_code == 404
