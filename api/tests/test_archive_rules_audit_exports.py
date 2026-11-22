import csv
import io
from datetime import UTC, datetime, timedelta

from app.db.models import Match
from tests.helpers import make_league, new_match, play_match


async def league(make_user, per_team=4):
    return await make_league(make_user, n_teams=4, per_team=per_team, n_umpires=2)


async def finished_season(make_user):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    mid = await new_match(lg, a, b)
    await play_match(lg, mid, "a")
    return lg, mid


# ---------- archive ----------
async def test_archive_refuses_unfinished_matches_then_freezes_everything(make_user):
    lg = await league(make_user)
    a, b, c, d = lg.teams
    done = await new_match(lg, a, b)
    await play_match(lg, done, "a")
    open_ = await new_match(lg, c, d)
    r = await lg.admin.req("POST", f"/seasons/{lg.sid}/archive")
    assert r.status_code == 409 and "Finish, abandon or delete" in r.json()["detail"]
    assert (await lg.players[a][0].req("POST", f"/seasons/{lg.sid}/archive")).status_code == 403
    await lg.admin.req("POST", f"/matches/{open_}/abandon", json={"reason": "season is over"})
    assert (await lg.admin.req("POST", f"/seasons/{lg.sid}/archive")).json()["status"] == "archived"
    assert (await lg.admin.req("POST", f"/seasons/{lg.sid}/archive")).status_code == 409

    free = await make_user("Free")
    blocked = [
        ("POST", f"/seasons/{lg.sid}/teams", {"name": "New team"}),
        ("POST", f"/teams/{a}/members", {"user_id": free.id}),
        ("DELETE", f"/teams/{a}/members/{lg.players[a][1].id}", None),
        ("PATCH", f"/teams/{a}", {"color": "#fff"}),
        ("POST", f"/seasons/{lg.sid}/matches", {"team_a_id": a, "team_b_id": c}),
        ("POST", f"/seasons/{lg.sid}/adjustments", {"team_id": a, "points": 1, "reason": "late fix"}),
        ("POST", f"/matches/{done}/result/reverse", {"reason": "try to undo it"}),
        ("POST", f"/matches/{done}/balls/correct", {"innings_number": 1, "over_no": 1, "ball_no": 1, "batter_digit": 2,
                                                    "bowler_digit": 6, "reason": "too late now"}),
        ("PUT", f"/matches/{done}/potm", {"user_id": lg.players[a][0].id}),
        ("POST", f"/seasons/{lg.sid}/fixtures/publish", {}),
        ("POST", f"/seasons/{lg.sid}/knockouts/generate", {"first_at": "2031-01-01T10:00:00Z"}),
        ("POST", f"/teams/{a}/roster-changes", {"out_user_id": lg.players[a][1].id, "in_user_id": free.id, "reason": "a swap"}),
        ("PATCH", f"/seasons/{lg.sid}", {"name": "Renamed"}),
    ]
    for method, url, body in blocked:
        r = await lg.admin.req(method, url, **({"json": body} if body is not None else {}))
        assert r.status_code == 409 and "archived" in r.json()["detail"].lower(), (method, url, r.status_code, r.text)
    # reading still works
    for url in (f"/seasons/{lg.sid}/standings", f"/seasons/{lg.sid}/leaderboards", f"/matches/{done}/live", f"/seasons/{lg.sid}/fixtures"):
        assert (await lg.admin.req("GET", url)).status_code == 200, url
    # unarchive reopens it
    assert (await lg.admin.req("POST", f"/seasons/{lg.sid}/unarchive")).json()["status"] == "completed"
    assert (await lg.admin.req("POST", f"/seasons/{lg.sid}/unarchive")).status_code == 409
    assert (await lg.admin.req("POST", f"/seasons/{lg.sid}/adjustments", json={"team_id": a, "points": 1, "reason": "late fix"})).status_code == 201


async def test_a_season_cannot_be_archived_through_a_plain_patch(make_user):
    lg = await league(make_user)
    r = await lg.admin.req("PATCH", f"/seasons/{lg.sid}", json={"status": "archived"})
    assert r.status_code == 409 and "archive action" in r.json()["detail"]
    assert (await lg.admin.req("POST", "/seasons/999999/archive")).status_code == 404


async def test_history_lists_past_seasons_with_champions_and_leaders(make_user):
    lg, mid = await finished_season(make_user)
    assert (await lg.admin.req("GET", "/history")).json() == []  # an active season is not history yet
    a = lg.teams[0]
    await lg.admin.req("PUT", f"/matches/{mid}/potm", json={"user_id": lg.players[a][0].id})
    await lg.admin.req("PATCH", f"/seasons/{lg.sid}", json={"status": "completed"})
    h = (await lg.players[a][0].req("GET", "/history")).json()
    assert len(h) == 1 and h[0]["season"]["id"] == lg.sid and h[0]["teams"] == 4 and h[0]["matches"] == 1
    assert h[0]["table"][0]["team"] == "Team1" and h[0]["table"][0]["points"] == 2
    assert h[0]["top_batter"]["value"] == 21 and h[0]["top_batter"]["player"]["id"] == lg.players[a][0].id
    assert h[0]["most_awards"]["value"] == 1 and h[0]["champion"] is None
    await lg.admin.req("POST", f"/seasons/{lg.sid}/archive")
    assert [x["season"]["status"] for x in (await lg.admin.req("GET", "/history")).json()] == ["archived"]


# ---------- rule versions ----------
async def test_rule_versions_diff_and_apply(make_user, db):
    lg = await league(make_user)
    a, b, c, d = lg.teams
    sid = lg.sid
    rs0 = (await lg.admin.req("GET", f"/seasons/{sid}")).json()["rule_set_id"]
    assert (await lg.players[a][0].req("GET", "/admin/rules")).status_code == 403
    listed = (await lg.admin.req("GET", "/admin/rules")).json()
    assert any(r["id"] == rs0 and r["seasons"] and r["seasons"][0]["id"] == sid for r in listed)

    played = await new_match(lg, a, b)
    await play_match(lg, played, "a")  # finished under the old rules
    future = await new_match(lg, c, d)  # not started yet
    new = await lg.admin.req("POST", "/admin/rules", json={"from_id": rs0, "changes": {"points": {"win": 3}}, "reason": "three for a win"})
    assert new.status_code == 201 and new.json()["changes"] == [{"path": "points.win", "from": 2, "to": 3}]
    rs1 = new.json()["id"]
    assert new.json()["version"] > (await lg.admin.req("GET", f"/admin/rules/{rs0}")).json()["version"]
    detail = (await lg.admin.req("GET", f"/admin/rules/{rs1}")).json()
    assert detail["previous"]["id"] == rs0 and detail["changes"] == [{"path": "points.win", "from": 2, "to": 3}]
    assert detail["config"]["points"]["win"] == 3

    # bad edits are refused with the reasons
    bad = await lg.admin.req("POST", "/admin/rules", json={"from_id": rs0, "changes": {"overs": 0}, "reason": "oops overs"})
    assert bad.status_code == 422 and "overs" in bad.json()["detail"]
    assert (await lg.admin.req("POST", "/admin/rules", json={"from_id": rs0, "changes": {}, "reason": "no change"})).status_code == 422
    assert (await lg.admin.req("POST", "/admin/rules", json={"from_id": rs0, "changes": {"overs": 5}, "reason": "x"})).status_code == 422
    assert (await lg.admin.req("POST", "/admin/rules", json={"from_id": 999999, "changes": {"overs": 5}, "reason": "no such one"})).status_code == 404

    # until applied, the table still uses the old points
    assert (await lg.admin.req("GET", f"/seasons/{sid}/standings")).json()["rows"][0]["points"] == 2
    r = await lg.admin.req("POST", f"/seasons/{sid}/rules", json={"rule_set_id": rs1})
    assert r.status_code == 200 and r.json()["repinned_matches"] == 1 and r.json()["kept_matches"] == 1
    assert (await lg.admin.req("GET", f"/seasons/{sid}/standings")).json()["rows"][0]["points"] == 3
    assert (await lg.admin.req("POST", f"/seasons/{sid}/rules", json={"rule_set_id": rs1})).status_code == 409
    assert (await lg.players[a][0].req("POST", f"/seasons/{sid}/rules", json={"rule_set_id": rs0})).status_code == 403
    db.expire_all()
    assert (await db.get(Match, future)).rule_set_id == rs1 and (await db.get(Match, played)).rule_set_id == rs0  # started matches keep their version
    counts = {x["id"]: x["matches"] for x in (await lg.admin.req("GET", "/admin/rules")).json()}
    assert counts[rs0] == 1 and counts[rs1] == 1


# ---------- audit viewer ----------
async def test_audit_log_filters_and_paging(make_user):
    lg = await league(make_user)
    a, b, c, d = lg.teams
    m1 = await new_match(lg, a, b)
    await lg.admin.req("POST", f"/matches/{m1}/walkover", json={"absent_team_id": b, "reason": "100% no show_today"})
    m2 = await new_match(lg, c, d)
    await lg.admin.req("POST", f"/matches/{m2}/abandon", json={"reason": "rain"})
    await lg.admin.req("POST", f"/seasons/{lg.sid}/adjustments", json={"team_id": a, "points": -1, "reason": "late arrival"})
    assert (await lg.players[a][0].req("GET", "/admin/audit")).status_code == 403
    allr = (await lg.admin.req("GET", "/admin/audit")).json()
    actions = [e["action"] for e in allr["entries"]]
    assert actions[:3] == ["adjustment.add", "match.abandon", "match.walkover"] and allr["next_before_id"] is None  # newest first
    assert allr["entries"][0]["actor"]["id"] == lg.admin.id and allr["entries"][0]["actor"]["name"]
    m = (await lg.admin.req("GET", "/admin/audit?action=match")).json()["entries"]
    assert {e["action"] for e in m} == {"match.walkover", "match.abandon"}
    assert [e["entity_id"] for e in (await lg.admin.req("GET", f"/admin/audit?entity=match&entity_id={m1}")).json()["entries"]] == [m1]
    assert (await lg.admin.req("GET", f"/admin/audit?actor_id={lg.players[a][0].id}")).json()["entries"] == []
    # a literal % or _ in the search text is not a wildcard
    assert len((await lg.admin.req("GET", "/admin/audit?q=100%25")).json()["entries"]) == 1
    assert (await lg.admin.req("GET", "/admin/audit?q=%25")).json()["entries"][0]["reason"] == "100% no show_today"
    assert (await lg.admin.req("GET", "/admin/audit?q=no%20show_t")).json()["entries"][0]["action"] == "match.walkover"
    assert (await lg.admin.req("GET", "/admin/audit?q=zzz")).json()["entries"] == []
    now = datetime.now(UTC)
    future = (now + timedelta(days=1)).isoformat().replace("+", "%2B")
    past = (now - timedelta(days=1)).isoformat().replace("+", "%2B")
    assert (await lg.admin.req("GET", f"/admin/audit?since={future}")).json()["entries"] == []
    assert len((await lg.admin.req("GET", f"/admin/audit?since={past}")).json()["entries"]) == len(actions)
    assert (await lg.admin.req("GET", f"/admin/audit?until={past}")).json()["entries"] == []
    # cursor paging walks the whole log exactly once
    seen, before = [], None
    while True:
        page = (await lg.admin.req("GET", f"/admin/audit?limit=2{'&before_id=' + str(before) if before else ''}")).json()
        seen += [e["id"] for e in page["entries"]]
        before = page["next_before_id"]
        if not before:
            break
    assert seen == sorted(set(seen), reverse=True) and len(seen) == len(actions)
    assert (await lg.admin.req("GET", "/admin/audit?limit=0")).status_code == 422
    assert (await lg.admin.req("GET", "/admin/audit?limit=999")).status_code == 422
    assert "match.walkover" in (await lg.admin.req("GET", "/admin/audit/actions")).json()


# ---------- CSV exports ----------
def rows(resp):
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/csv")
    return list(csv.reader(io.StringIO(resp.text)))


async def test_exports(make_user):
    lg, _mid = await finished_season(make_user)
    a = lg.teams[0]
    fx = await lg.admin.req("GET", f"/seasons/{lg.sid}/export/fixtures.csv")
    assert "attachment" in fx.headers["content-disposition"] and fx.headers["content-disposition"].endswith('-fixtures.csv"')
    r = rows(fx)
    assert r[0][:8] == ["match", "round", "date_utc", "time_utc", "team_a", "team_b", "umpire", "status"]
    assert r[1][0] == "1" and r[1][4:6] == ["Team1", "Team2"] and r[1][7] == "completed" and "won by" in r[1][9]
    t = rows(await lg.admin.req("GET", f"/seasons/{lg.sid}/export/table.csv"))
    assert t[0][:3] == ["position", "team", "played"] and t[1][1] == "Team1" and t[1][7] == "2" and len(t) == 5
    p = rows(await lg.admin.req("GET", f"/seasons/{lg.sid}/export/players.csv"))
    head = p[0]
    top = dict(zip(head, p[1], strict=True))
    assert top["runs"] == "21" and top["fours"] == "1" and top["sixes"] == "1" and top["team"] == "Team1"
    assert top["player"].startswith("T1P")
    assert (await lg.players[a][0].req("GET", f"/seasons/{lg.sid}/export/table.csv")).status_code == 403
    assert (await lg.admin.req("GET", "/seasons/999999/export/table.csv")).status_code == 404


async def test_exports_neutralise_formulas(make_user):
    lg = await league(make_user)
    evil = '=HYPERLINK("http://x.test","click")'
    await lg.admin.req("POST", f"/seasons/{lg.sid}/teams", json={"name": evil})
    await lg.admin.req("POST", f"/seasons/{lg.sid}/teams", json={"name": "+SUM(1)"})
    await lg.admin.req("POST", f"/seasons/{lg.sid}/teams", json={"name": "@cmd"})
    table = rows(await lg.admin.req("GET", f"/seasons/{lg.sid}/export/table.csv"))
    names = {r[1] for r in table[1:]}
    assert "'" + evil in names and "'+SUM(1)" in names and "'@cmd" in names
    assert not any(n.startswith(("=", "+", "@", "-")) for n in names)


async def test_new_version_from_an_older_partial_rule_set(make_user, db):
    from app.db.models import RuleSet

    lg = await league(make_user)
    old = RuleSet(name="Legacy", version=1, config={"overs": 7, "wickets": 7})  # as stored by early versions
    db.add(old)
    await db.commit()
    r = await lg.admin.req("POST", "/admin/rules", json={"from_id": old.id, "changes": {"points": {"win": 3}}, "reason": "move to three"})
    assert r.status_code == 201, r.text
    assert r.json()["changes"] == [{"path": "points.win", "from": 2, "to": 3}]  # defaults fill the gaps
    full = (await lg.admin.req("GET", f"/admin/rules/{r.json()['id']}")).json()
    assert full["config"]["points"]["win"] == 3 and full["config"]["tiebreakers"] and full["previous"]["id"] == old.id
    assert full["changes"] == [{"path": "points.win", "from": 2, "to": 3}]
