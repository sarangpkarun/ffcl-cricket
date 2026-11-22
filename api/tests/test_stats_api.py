from sqlalchemy import select

from app.db.models import ChatMessage, Notification
from tests.helpers import make_league, new_match, play_match


async def league(make_user):
    return await make_league(make_user, n_teams=4, per_team=4, n_umpires=3)


async def board(lg, who=None, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    r = await (who or lg.admin).req("GET", f"/seasons/{lg.sid}/leaderboards?{qs}")
    assert r.status_code == 200, r.text
    return {c["key"]: c["rows"] for c in r.json()["categories"]}


async def played(lg, a, b, outcome="a"):
    mid = await new_match(lg, a, b)
    await play_match(lg, mid, outcome)
    return mid


async def test_leaderboards_after_one_match(make_user):
    lg = await league(make_user)
    a, b, _c, _d = lg.teams
    pa, pb = lg.players[a], lg.players[b]
    await played(lg, a, b)
    bd = await board(lg)
    # the first batter hit 21 off 6 balls: one four, one six
    assert [(r["player"]["id"], r["value"]) for r in bd["most_runs"]] == [(pa[0].id, 21)]
    assert bd["highest_score"][0]["detail"] == "off 6 balls"
    assert [(r["player"]["id"], r["value"]) for r in bd["most_sixes"]] == [(pa[0].id, 1)]
    assert [(r["player"]["id"], r["value"]) for r in bd["most_fours"]] == [(pa[0].id, 1)]
    # wickets: Team1's first two bowlers took 6 and 1 in the chase; Team2's took 6 and 1 before that
    wk = {r["player"]["id"]: r["value"] for r in bd["most_wickets"]}
    assert wk == {pb[1].id: 6, pa[0].id: 6, pb[2].id: 1, pa[1].id: 1}
    assert {r["rank"] for r in bd["most_wickets"] if r["value"] == 6} == {1}
    # nobody has faced the 12 balls needed for the rate boards yet
    assert bd["best_strike_rate"] == [] and bd["best_economy"] == []
    assert bd["most_potm"] == []
    # win percentage: Team1 won its only match
    pct = {r["team"]["id"]: r["value"] for r in bd["best_win_pct"]}
    assert pct == {a: 100.0, b: 0.0}
    assert bd["most_runs"][0]["team"]["id"] == a


async def test_rate_boards_need_the_minimum_balls(make_user):
    lg = await league(make_user)
    a, b, c, _d = lg.teams
    pa = lg.players[a]
    await played(lg, a, b)
    await played(lg, a, c)
    bd = await board(lg)
    sr = bd["best_strike_rate"]
    assert sr[0]["player"]["id"] == pa[0].id and sr[0]["value"] == 350.0  # 42 off 12
    assert sr[0]["detail"] == "42 off 12"
    eco = {r["player"]["id"]: r["value"] for r in bd["best_economy"]}
    assert eco[pa[0].id] == 0.0  # 12 balls, no runs
    bad = await lg.admin.req("GET", f"/seasons/{lg.sid}/leaderboards?limit=0")
    assert bad.status_code == 422


async def test_team_filter_and_walkovers_and_abandoned_do_not_count(make_user):
    lg = await league(make_user)
    a, b, c, d = lg.teams
    await played(lg, a, b)
    wo = await new_match(lg, c, d)
    await lg.admin.req("POST", f"/matches/{wo}/walkover", json={"absent_team_id": d, "reason": "did not turn up"})
    ab = await new_match(lg, c, d)
    await lg.admin.req("POST", f"/matches/{ab}/abandon", json={"reason": "rain"})
    only_b = await board(lg, team_id=b)
    assert {r["player"]["id"] for r in only_b["most_wickets"]} == {lg.players[b][1].id, lg.players[b][2].id}
    assert only_b["most_runs"] == []  # Team2 scored nothing
    assert [r["team"]["id"] for r in only_b["best_win_pct"]] == [b]
    nobody = await board(lg, team_id=c)
    assert all(rows == [] for k, rows in nobody.items() if k != "best_win_pct")
    assert nobody["best_win_pct"][0]["value"] == 100.0 or nobody["best_win_pct"] == []  # a walkover is a played win


async def test_player_stats_reconcile_with_the_scorecard_including_penalties_and_corrections(make_user):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    pa, _pb = lg.players[a], lg.players[b]
    mid = await played(lg, a, b)
    url = f"/matches/{mid}"
    await lg.admin.req("POST", f"{url}/penalties", json={"team_id": a, "kind": "late_submission", "runs": -4, "reason": "slow digits", "idempotency_key": "pen-0001"})

    async def check(expected_first):
        live = (await lg.admin.req("GET", f"{url}/live")).json()
        for inn in live["innings"]:
            team = inn["batting_team_id"]
            ids = {p.id for p in lg.players[team]}
            runs = 0
            for pid in ids:
                s = (await lg.admin.req("GET", f"/players/{pid}/stats")).json()
                h = next(x for x in s["history"] if x["match_id"] == mid)
                runs += h["runs"]
            assert runs == inn["runs"] - (inn["extras"] or 0), (inn["number"], runs, inn["runs"], inn["extras"])
            assert runs == sum(x["runs"] for x in inn["batting"])
        assert live["innings"][0]["runs"] == expected_first

    await check(17)  # 21 - 4 penalty; players still hold their own 21
    r = await lg.admin.req("POST", f"{url}/balls/correct", json={"innings_number": 1, "over_no": 1, "ball_no": 1,
                           "batter_digit": 2, "bowler_digit": 6, "reason": "misread"})
    assert r.status_code == 201, r.text
    await check(14)  # 18 off the bat - 4
    bd = await board(lg)
    assert [(r["player"]["id"], r["value"]) for r in bd["most_runs"]] == [(pa[0].id, 18)]  # leaderboard follows the correction
    st = (await lg.admin.req("GET", f"/players/{pa[0].id}/stats")).json()["totals"]
    assert (st["runs"], st["balls"], st["outs"], st["highest"], st["fours"], st["sixes"]) == (18, 6, 0, 18, 1, 1)


async def test_player_page_season_and_career(make_user):
    lg = await league(make_user)
    a, b, c, _d = lg.teams
    p0 = lg.players[a][0]
    m1 = await played(lg, a, b)
    m2 = await played(lg, a, c, "b")
    other = (await lg.admin.req("POST", "/seasons", json={"name": "Other", "status": "active"})).json()["id"]
    r = await lg.admin.req("GET", f"/players/{p0.id}/stats")
    assert r.status_code == 200
    s = r.json()
    assert s["player"]["id"] == p0.id and s["totals"]["matches"] == 2 and s["totals"]["runs"] == 21
    assert [h["match_id"] for h in s["history"]] == [m2, m1]  # newest first
    assert s["history"][1]["against"] == "Team2" and s["history"][1]["won"] is True and s["history"][0]["won"] is False
    assert len(s["seasons"]) == 1 and s["seasons"][0]["season"]["id"] == lg.sid and s["seasons"][0]["runs"] == 21
    scoped = (await lg.admin.req("GET", f"/players/{p0.id}/stats?season_id={lg.sid}")).json()
    assert scoped["totals"] == s["totals"] and scoped["seasons"] == []
    empty = (await lg.admin.req("GET", f"/players/{p0.id}/stats?season_id={other}")).json()
    assert empty["totals"]["matches"] == 0 and empty["history"] == []
    assert (await lg.admin.req("GET", "/players/999999/stats")).status_code == 404
    assert (await lg.admin.req("GET", "/players/1/stats?season_id=999999")).status_code == 404


async def test_team_stats(make_user):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    await played(lg, a, b)
    s = (await lg.admin.req("GET", f"/teams/{a}/stats")).json()
    assert s["team"]["id"] == a and s["table"]["won"] == 1 and s["win_pct"] == 100.0
    assert s["best"]["most_runs"]["value"] == 21 and s["best"]["most_runs"]["player"]["id"] == lg.players[a][0].id
    assert s["players"][0]["player"]["id"] == lg.players[a][0].id and s["players"][0]["runs"] == 21
    assert {p["player"]["id"] for p in s["players"]} <= {p.id for p in lg.players[a]}
    assert (await lg.admin.req("GET", "/teams/999999/stats")).status_code == 404


# ---------- player of the match ----------
async def test_potm_flow(make_user, db):
    lg = await league(make_user)
    a, b, c, _d = lg.teams
    pa, pb = lg.players[a], lg.players[b]
    mid = await new_match(lg, a, b)
    before = await lg.admin.req("GET", f"/matches/{mid}/potm")
    assert before.json()["eligible"] is False and before.json()["can_choose"] is False
    assert (await lg.admin.req("PUT", f"/matches/{mid}/potm", json={"user_id": pa[0].id})).status_code == 409  # not finished
    await play_match(lg, mid, "a")

    g = (await lg.admin.req("GET", f"/matches/{mid}/potm")).json()
    assert g["eligible"] and g["can_choose"] and g["award"] is None
    assert g["suggestion"]["player"]["id"] == pa[0].id and g["suggestion"]["score"] == 81  # 21 runs + 6 wickets
    assert len(g["candidates"]) == 8
    fan = (await pa[1].req("GET", f"/matches/{mid}/potm")).json()
    assert fan["can_choose"] is False and fan["candidates"] == [] and fan["suggestion"] is None  # only officials see the shortlist

    assert (await pa[0].req("PUT", f"/matches/{mid}/potm", json={"user_id": pa[0].id})).status_code == 403  # captains cannot
    outsider = lg.players[c][0]
    assert (await lg.admin.req("PUT", f"/matches/{mid}/potm", json={"user_id": outsider.id})).status_code == 422
    ok = await lg.admin.req("PUT", f"/matches/{mid}/potm", json={"user_id": pb[1].id})
    assert ok.status_code == 200 and ok.json()["changed"] is True
    assert (await lg.admin.req("PUT", f"/matches/{mid}/potm", json={"user_id": pb[1].id})).json()["changed"] is False

    after = (await pa[1].req("GET", f"/matches/{mid}/potm")).json()
    assert after["award"]["player"]["id"] == pb[1].id and after["award"]["wickets"] == 6
    live = (await pa[1].req("GET", f"/matches/{mid}/live")).json()
    assert live["match"]["potm"]["id"] == pb[1].id
    db.expire_all()
    texts = list(await db.scalars(select(ChatMessage.body).where(ChatMessage.kind == "system")))
    assert any(t and t.startswith("⭐ Player of the match:") for t in texts)
    got = list(await db.scalars(select(Notification).where(Notification.title == "Player of the match")))
    assert [n.user_id for n in got] == [pb[1].id]

    bd = await board(lg)
    assert [(r["player"]["id"], r["value"]) for r in bd["most_potm"]] == [(pb[1].id, 1)]
    st = (await lg.admin.req("GET", f"/players/{pb[1].id}/stats")).json()
    assert st["totals"]["potm"] == 1 and st["history"][0]["potm"] is True

    # the choice can be changed; the old winner loses the award, the new one is told
    assert (await lg.admin.req("PUT", f"/matches/{mid}/potm", json={"user_id": pa[0].id})).json()["changed"] is True
    bd = await board(lg)
    assert [(r["player"]["id"], r["value"]) for r in bd["most_potm"]] == [(pa[0].id, 1)]
    umpire_ok = await lg.umpires[0].req("PUT", f"/matches/{mid}/potm", json={"user_id": pb[1].id})
    assert umpire_ok.status_code == 200  # the match umpire may choose too


async def test_potm_not_for_walkover(make_user):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    mid = await new_match(lg, a, b)
    await lg.admin.req("POST", f"/matches/{mid}/walkover", json={"absent_team_id": b, "reason": "no show today"})
    assert (await lg.admin.req("GET", f"/matches/{mid}/potm")).json()["eligible"] is False
    assert (await lg.admin.req("PUT", f"/matches/{mid}/potm", json={"user_id": lg.players[a][0].id})).status_code == 409
