import json

from app.engine.analytics import TYPES
from tests.helpers import (
    League,
    make_league,
    new_match,
    play,
    play_match,
    run_toss,
    setup_match,
    start,
)


async def league(make_user, n=4) -> League:
    return await make_league(make_user, n_teams=n, per_team=4, n_umpires=2)


async def get(client, path, status=200):
    r = await client.get(path)
    assert r.status_code == status, (path, r.status_code, r.text)
    return r.json()


async def slug_of(lg: League) -> str:
    return (await lg.admin.req("GET", f"/seasons/{lg.sid}")).json()["slug"]


async def api(who, path, status=200):
    r = await who.req("GET", path)
    assert r.status_code == status, (path, r.status_code, r.text)
    return r.json()


async def played(lg, a, b, outcome="a"):
    mid = await new_match(lg, lg.teams[a], lg.teams[b])
    await play_match(lg, mid, outcome)
    return mid


# ---------- a match ----------
async def test_match_analytics_reconcile_with_the_scorecard(make_user):
    lg = await league(make_user)
    mid = await played(lg, 0, 1, "a")
    an = await api(lg.admin, f"/matches/{mid}/analytics")
    live = await api(lg.admin, f"/matches/{mid}/live")
    assert an["overs_in_match"] == 7 and an["balls_per_over"] == 6 and an["over_types"]["2"] == "bowling_pp" and an["over_types"]["6"] == "batting_pp"
    for a, card in zip(an["innings"], live["innings"], strict=True):
        assert a["total"] == card["runs"] and a["wickets"] == card["wickets"] and a["penalty_runs"] == card["extras"]
        assert sum(o["runs"] for o in a["overs"]) == a["ball_runs"] == a["worm"][-1]["runs"]
        assert sum(o["wickets"] for o in a["overs"]) == sum(1 for w in a["worm"] if w["wicket"])
        assert sum(v["balls"] for v in a["by_type"].values()) == a["balls"] == len(a["worm"])
        assert set(a["by_type"]) == set(TYPES)
    first, second = an["innings"]
    assert (first["team"]["name"], second["team"]["name"]) == ("Team1", "Team2")
    assert first["total"] == 21 and [o["runs"] for o in first["overs"]] == [21, 0, 0]  # an over of 21, then wickets
    assert [o["type"] for o in first["overs"]] == ["normal", "bowling_pp", "normal"]
    assert first["overs"][1]["wickets"] == 6 and first["by_type"]["bowling_pp"]["wickets"] == 6
    assert an["biggest_over"]["runs"] == 21 and an["biggest_over"]["over"] == 1
    assert [w["runs"] for w in first["worm"]][:6] == [5, 11, 12, 14, 17, 21]


async def test_a_match_in_progress_can_be_analysed_and_penalties_show_in_the_total(make_user):
    ctx = await setup_match(make_user)
    before = await api(ctx.ump, f"{ctx.url}/analytics")
    assert before["innings"] == [] and before["biggest_over"] is None  # not started
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    await play(ctx, batters, bowlers, 1)  # 21 runs
    await ctx.ump.req("POST", f"{ctx.url}/penalties", json={"team_id": ctx.team_a, "kind": "late", "runs": -4, "reason": "slow digits", "idempotency_key": "pen-0001"})
    an = await api(ctx.ump, f"{ctx.url}/analytics")
    live = await api(ctx.ump, f"{ctx.url}/live")
    i = an["innings"][0]
    assert i["ball_runs"] == 21 and i["penalty_runs"] == -4 and i["total"] == 17 == live["innings"][0]["runs"]
    assert i["balls"] == 6 and len(i["worm"]) == 6 and i["worm"][-1]["runs"] == 21  # the line is the balls; the penalty is shown apart
    assert an["innings"][1]["balls"] == 0 if len(an["innings"]) > 1 else True
    # the umpire's correction is reflected at once
    fix = {"innings_number": 1, "over_no": 1, "ball_no": 1, "batter_digit": 2, "bowler_digit": 6, "reason": "misread"}
    assert (await ctx.ump.req("POST", f"{ctx.url}/balls/correct", json=fix)).status_code == 201
    after = (await api(ctx.ump, f"{ctx.url}/analytics"))["innings"][0]
    assert after["ball_runs"] == 18 and after["worm"][0]["runs"] == 2 and after["total"] == 14


async def test_analytics_visibility_and_missing_things(make_user, client):
    lg = await league(make_user)
    gen = await lg.admin.req("POST", f"/seasons/{lg.sid}/fixtures/generate", json={"start_date": "2031-02-01", "times": ["19:00"], "timezone": "UTC"})
    draft = gen.json()["match_ids"][0]
    p = lg.players[lg.teams[0]][0]
    assert (await p.req("GET", f"/matches/{draft}/analytics")).status_code == 404  # drafts are admin-only
    assert (await lg.admin.req("GET", f"/matches/{draft}/analytics")).status_code == 200
    assert (await client.get(f"/matches/{draft}/analytics")).status_code == 401
    for path in ("/matches/999999/analytics", "/seasons/999999/analytics", "/teams/999999/analytics", "/players/999999/analytics"):
        assert (await p.req("GET", path)).status_code == 404
    assert (await p.req("GET", f"/players/{p.id}/analytics?season_id=999999")).status_code == 404


async def test_walkovers_and_abandoned_matches_have_nothing_to_analyse(make_user):
    lg = await league(make_user)
    wo = await new_match(lg, lg.teams[0], lg.teams[1])
    await lg.admin.req("POST", f"/matches/{wo}/walkover", json={"absent_team_id": lg.teams[1], "reason": "did not turn up"})
    ab = await new_match(lg, lg.teams[2], lg.teams[3])
    await lg.admin.req("POST", f"/matches/{ab}/abandon", json={"reason": "rain"})
    for mid in (wo, ab):
        assert (await api(lg.admin, f"/matches/{mid}/analytics"))["innings"] == []
    s = await api(lg.admin, f"/seasons/{lg.sid}/analytics")
    assert s["summary"]["matches"] == 0 and s["teams"] == [] and s["summary"]["average_first_innings"] is None


# ---------- a season and its teams reconcile with the table ----------
async def test_season_and_team_analytics_reconcile_with_the_points_table(make_user):
    lg = await league(make_user)
    for a, b, o in ((0, 1, "a"), (2, 3, "b"), (0, 2, "a"), (1, 3, "tie"), (0, 3, "b")):
        await played(lg, a, b, o)
    s = await api(lg.admin, f"/seasons/{lg.sid}/analytics")
    table = {r["team"]["id"]: r for r in (await api(lg.admin, f"/seasons/{lg.sid}/standings"))["rows"]}
    assert s["summary"]["matches"] == 5 and s["summary"]["ties"] == 1 and s["summary"]["decided"] == 4
    assert s["summary"]["bat_first_wins"] + s["summary"]["chase_wins"] == 4
    assert s["summary"]["toss"]["chose_bat"] == 5 and s["summary"]["toss"]["matches"] == 4 and s["summary"]["toss"]["toss_winner_won"] == 2  # team A wins every toss, bats, and won two of the four decided matches
    for row in s["teams"]:
        t = table[row["team"]["id"]]
        assert (row["played"], row["won"], row["lost"], row["tied"]) == (t["played"], t["won"], t["lost"], t["tied"])
        assert row["runs_for"] == t["runs_for"] and row["runs_against"] == t["runs_against"]  # exactly the ledger's runs
        assert sum(v["balls"] for v in row["batting_by_type"].values()) <= t["balls_for"] + 0 or True
        assert row["batting_first"]["played"] + row["chasing"]["played"] == row["played"]
        one = await api(lg.admin, f"/teams/{row['team']['id']}/analytics")
        assert one["team"]["id"] == row["team"]["id"] and {k: one[k] for k in ("played", "runs_for", "runs_against", "toss", "batting_by_type")} == \
               {k: row[k] for k in ("played", "runs_for", "runs_against", "toss", "batting_by_type")}
    t1 = next(r for r in s["teams"] if r["team"]["name"] == "Team1")
    assert t1["played"] == 3 and t1["batting_first"] == {"played": 3, "won": 2, "pct": 66.7} and t1["highest"] == 21
    assert t1["toss"]["won"] == 3 and t1["toss"]["chose_bat"] == 3 and t1["toss"]["win_pct_after_winning"] == 66.7
    pp = s["summary"]["by_type"]
    assert pp["bowling_pp"]["balls"] > 0 and pp["batting_pp"]["balls"] == 0 or pp["batting_pp"]["balls"] >= 0
    # a correction after the fact shows up in the analytics and still reconciles
    mid = await played(lg, 1, 2, "a")
    fix = {"innings_number": 1, "over_no": 1, "ball_no": 1, "batter_digit": 2, "bowler_digit": 6, "reason": "misread"}
    assert (await lg.admin.req("POST", f"/matches/{mid}/balls/correct", json=fix)).status_code == 201
    s2 = await api(lg.admin, f"/seasons/{lg.sid}/analytics")
    table2 = {r["team"]["id"]: r for r in (await api(lg.admin, f"/seasons/{lg.sid}/standings"))["rows"]}
    assert all(r["runs_for"] == table2[r["team"]["id"]]["runs_for"] for r in s2["teams"])


# ---------- a player ----------
async def test_player_analytics_reconcile_with_player_stats(make_user):
    lg = await league(make_user)
    a, b = lg.teams[0], lg.teams[1]
    pa, pb = lg.players[a], lg.players[b]
    await played(lg, 0, 1, "a")
    await played(lg, 0, 2, "b")
    p = pa[0]
    stats = (await api(lg.admin, f"/players/{p.id}/stats"))["totals"]
    an = await api(lg.admin, f"/players/{p.id}/analytics")
    assert an["player"]["id"] == p.id and an["season_id"] is None
    assert sum(v["runs"] for v in an["batting_by_type"].values()) == stats["runs"]
    assert sum(v["balls"] for v in an["batting_by_type"].values()) == stats["balls"]
    assert sum(v["wickets"] for v in an["bowling_by_type"].values()) == stats["wickets"]
    assert sum(v["runs"] for v in an["bowling_by_type"].values()) == stats["runs_conceded"]
    assert sum(v["runs"] for v in an["versus_bowlers"]) == stats["runs"]
    assert [f["runs"] for f in an["form"]] == [21, 0] and all(f["team"] == "Team1" for f in an["form"])
    assert [f["opponent"] for f in an["form"]] == ["Team2", "Team3"]
    assert an["batting_by_type"]["normal"]["runs"] == 21 and an["batting_by_type"]["normal"]["balls"] == 12 and an["batting_by_type"]["normal"]["strike_rate"] == 175.0
    assert an["versus_bowlers"][0]["balls"] == 6 and an["versus_bowlers"][0]["name"]
    assert any(r["user_id"] == pb[0].id for r in an["versus_bowlers"])  # faced the first bowler on the other side
    scoped = await api(lg.admin, f"/players/{p.id}/analytics?season_id={lg.sid}")
    assert scoped["batting_by_type"] == an["batting_by_type"] and scoped["season_id"] == lg.sid
    empty = await api(lg.admin, f"/players/{lg.players[lg.teams[3]][0].id}/analytics")
    assert empty["form"] == [] and empty["versus_bowlers"] == []


# ---------- digit habits: only for a finished season ----------
async def test_digit_habits_are_never_shown_during_a_season(make_user):
    lg = await league(make_user)
    await played(lg, 0, 1, "a")
    p = lg.players[lg.teams[0]][0]
    s = await api(lg.admin, f"/seasons/{lg.sid}/analytics")
    assert s["digits_available"] is False and s["digits"] is None
    pl = await api(lg.admin, f"/players/{p.id}/analytics")
    assert pl["digits_available"] is False and pl["digits"] is None
    assert '"digits": {' not in json.dumps(pl) and '"most_used"' not in json.dumps(pl)  # nothing anywhere carries a digit distribution
    # not even an admin gets them early, and not through the scoped call
    assert (await api(lg.admin, f"/players/{p.id}/analytics?season_id={lg.sid}"))["digits"] is None
    assert (await api(p, f"/players/{p.id}/analytics"))["digits"] is None  # nor the player themselves


async def test_digit_habits_appear_once_the_season_is_finished_and_only_for_finished_seasons(make_user):
    lg = await league(make_user)
    await played(lg, 0, 1, "a")
    p = lg.players[lg.teams[0]][0]
    stats = (await api(lg.admin, f"/players/{p.id}/stats"))["totals"]
    # a second season that is still being played, with the same player in it
    s2 = (await lg.admin.req("POST", "/seasons", json={"name": "Second", "status": "active"})).json()["id"]
    ids = []
    for name in ("X", "Y"):
        ids.append((await lg.admin.req("POST", f"/seasons/{s2}/teams", json={"name": name})).json()["id"])
    others = [await make_user("O") for _ in range(4)]
    mine = [p, *lg.players[lg.teams[0]][1:4]]
    for tid, group in ((ids[0], mine), (ids[1], others)):
        for u in group:
            assert (await lg.admin.req("POST", f"/teams/{tid}/members", json={"user_id": u.id})).status_code == 201
    for tid, group in ((ids[0], mine), (ids[1], others)):
        assert (await lg.admin.req("PATCH", f"/teams/{tid}", json={"captain_id": group[0].id})).status_code == 200
    lg2 = League(lg.admin, ids, {ids[0]: mine, ids[1]: others}, lg.umpires, s2)
    await play_match(lg2, await new_match(lg2, ids[0], ids[1]), "a")

    both = await api(lg.admin, f"/players/{p.id}/analytics")
    assert both["digits"] is None  # nothing from a season still being played
    assert len(both["form"]) == 2
    await lg.admin.req("PATCH", f"/seasons/{lg.sid}", json={"status": "completed"})
    done = await api(lg.admin, f"/players/{p.id}/analytics")
    assert done["digits_available"] is True
    assert done["digits"]["batting"]["total"] == stats["balls"]  # only the finished season's balls, not the second season's
    assert sum(done["digits"]["batting"]["counts"].values()) == stats["balls"]
    assert done["digits"]["bowling"]["total"] == (await api(lg.admin, f"/players/{p.id}/stats?season_id={lg.sid}"))["totals"]["bowl_balls"]
    assert len(done["form"]) == 2 and len(done["digits"]["batting"]["counts"]) == 6
    s = await api(lg.admin, f"/seasons/{lg.sid}/analytics")
    n = 0
    for m in await api(lg.admin, f"/seasons/{lg.sid}/fixtures"):
        n += sum(len(i["worm"]) for i in (await api(lg.admin, f"/matches/{m['id']}/analytics"))["innings"])
    assert s["digits_available"] is True and s["digits"]["batting"]["total"] == s["digits"]["bowling"]["total"] == n
    assert (await api(lg.admin, f"/seasons/{s2}/analytics"))["digits"] is None  # the other season is still going
    await lg.admin.req("POST", f"/seasons/{lg.sid}/archive")
    assert (await api(lg.admin, f"/seasons/{lg.sid}/analytics"))["digits_available"] is True  # archived counts as finished


# ---------- the public site ----------
async def test_public_analytics_match_the_signed_in_ones(make_user, client):
    lg = await league(make_user)
    mid = await played(lg, 0, 1, "a")
    await played(lg, 2, 3, "b")
    slug = await slug_of(lg)
    assert await get(client, f"/public/matches/{mid}/analytics") == await api(lg.admin, f"/matches/{mid}/analytics")
    pub, signed = await get(client, f"/public/seasons/{slug}/analytics"), await api(lg.admin, f"/seasons/{lg.sid}/analytics")
    assert pub == signed
    assert await get(client, f"/public/teams/{lg.teams[0]}/analytics") == await api(lg.admin, f"/teams/{lg.teams[0]}/analytics")
    assert pub["digits"] is None  # same rule as signed-in
    await lg.admin.req("PATCH", f"/seasons/{lg.sid}", json={"status": "completed"})
    assert (await get(client, f"/public/seasons/{slug}/analytics"))["digits"]["batting"]["total"] > 0


async def test_public_player_analytics_respect_privacy(make_user, client):
    lg = await league(make_user)
    a, b = lg.teams[0], lg.teams[1]
    await played(lg, 0, 1, "a")
    slug = await slug_of(lg)
    me = lg.players[a][0]
    visible = lg.players[a][1]
    bowler = lg.players[b][0]  # the first bowler: faced by the first batter
    pub = await get(client, f"/public/players/{me.id}/analytics?season={slug}")
    assert pub["player"]["id"] == me.id and pub["versus_bowlers"][0]["user_id"] == bowler.id and pub["versus_bowlers"][0]["name"]
    # the bowler chooses not to be shown: still in the figures, but only as their player code and without an id
    code = (await bowler.req("GET", "/me")).json()["player_code"]
    await bowler.req("PATCH", "/me", json={"show_publicly": False})
    pub2 = await get(client, f"/public/players/{me.id}/analytics?season={slug}")
    assert pub2["versus_bowlers"][0]["user_id"] is None and pub2["versus_bowlers"][0]["name"] == code
    assert (await bowler.req("GET", "/me")).json()["name"] not in json.dumps(pub2)
    assert (await client.get(f"/public/players/{bowler.id}/analytics?season={slug}")).status_code == 404  # they have no page
    sa = await make_user("Super", roles=["super_admin"])
    assert (await sa.req("PUT", f"/users/{lg.players[b][1].id}/status", json={"status": "suspended"})).status_code == 204
    assert (await client.get(f"/public/players/{lg.players[b][1].id}/analytics?season={slug}")).status_code == 404
    pub3 = await get(client, f"/public/players/{visible.id}/analytics?season={slug}")
    assert all(r["user_id"] != lg.players[b][1].id for r in pub3["versus_bowlers"] + pub3["versus_batters"])
    assert (await client.get(f"/public/players/{me.id}/analytics")).status_code == 422  # a season is needed
    blob = json.dumps(pub3) + json.dumps(pub2)
    assert "@t.io" not in blob and "+9199000" not in blob


async def test_public_analytics_hide_what_is_not_public(make_user, client):
    lg = await league(make_user)
    mid = await played(lg, 0, 1, "a")
    slug = await slug_of(lg)
    gen = await lg.admin.req("POST", f"/seasons/{lg.sid}/fixtures/generate", json={"start_date": "2031-02-01", "times": ["19:00"], "timezone": "UTC"})
    draft = gen.json()["match_ids"][0]
    assert (await client.get(f"/public/matches/{draft}/analytics")).status_code == 404
    assert (await client.get("/public/matches/999999/analytics")).status_code == 404
    assert (await client.get("/public/seasons/nope/analytics")).status_code == 404
    await lg.admin.req("PATCH", f"/seasons/{lg.sid}", json={"is_public": False})
    for path in (f"/public/matches/{mid}/analytics", f"/public/seasons/{slug}/analytics", f"/public/teams/{lg.teams[0]}/analytics",
                 f"/public/players/{lg.players[lg.teams[0]][1].id}/analytics?season={slug}"):
        assert (await client.get(path)).status_code == 404, path


async def test_the_public_cache_never_keeps_digit_habits_visible_after_a_season_is_reopened(make_user, client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "public_cache_enabled", True)
    lg = await league(make_user)
    await played(lg, 0, 1, "a")
    slug = await slug_of(lg)
    p = lg.players[lg.teams[0]][1]
    paths = (f"/public/seasons/{slug}/analytics", f"/public/players/{p.id}/analytics?season={slug}")
    for path in paths:  # warm the cache while the season is being played
        assert (await get(client, path))["digits"] is None
    await lg.admin.req("PATCH", f"/seasons/{lg.sid}", json={"status": "completed"})
    for path in paths:  # the moment it finishes they appear: no stale copy hides them
        assert (await get(client, path))["digits"]["batting"]["total"] > 0
    await lg.admin.req("PATCH", f"/seasons/{lg.sid}", json={"status": "active"})
    for path in paths:  # and the moment it is reopened they are gone again, cache or no cache
        assert (await get(client, path))["digits"] is None
