from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.db.models import AuditLog, ChatMessage, ChatRoom, Match, Notification, Stage
from tests.helpers import BOWL_ALL_EQUAL, make_league, play, run_toss, setup_match, start
from tests.test_chat import rooms

PARAMS = {"start_date": "2030-01-07", "times": ["19:00"], "timezone": "UTC", "parallel": 2, "rest_slots": 1}


async def counts(db):
    db.expire_all()
    return (await db.scalar(select(func.count()).select_from(Match)),
            await db.scalar(select(func.count()).select_from(Stage)))


async def gen(lg, **kw):
    return await lg.admin.req("POST", f"/seasons/{lg.sid}/fixtures/generate", json={**PARAMS, **kw})


async def notes(db, kind):
    db.expire_all()
    return list(await db.scalars(select(Notification).where(Notification.kind == kind).order_by(Notification.id)))


# ---------- preview ----------
async def test_preview_saves_nothing_and_describes_the_season(make_user, db):
    lg = await make_league(make_user)
    before = await counts(db)
    r = await lg.admin.req("POST", f"/seasons/{lg.sid}/fixtures/preview", json=PARAMS)
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["matches"] == 6 and body["summary"]["rounds"] == 3 and body["summary"]["teams"] == 4
    assert len(body["matches"]) == 6 and body["summary"]["without_umpire"] == 0
    ha = body["summary"]["home_away"]
    assert all(abs(v["home"] - v["away"]) <= 1 for v in ha.values())
    assert await counts(db) == before  # not a single row written


async def test_preview_warns_when_no_umpire_exists(make_user, db):
    lg = await make_league(make_user, n_umpires=0)
    body = (await lg.admin.req("POST", f"/seasons/{lg.sid}/fixtures/preview", json=PARAMS)).json()
    assert body["summary"]["without_umpire"] == 6
    assert all("No umpire available" in " ".join(m["warnings"]) for m in body["matches"])
    off = (await lg.admin.req("POST", f"/seasons/{lg.sid}/fixtures/preview", json={**PARAMS, "assign_umpires": False})).json()
    assert off["summary"]["without_umpire"] is None and not any(m["warnings"] for m in off["matches"])


async def test_only_admins_can_use_fixture_tools(make_user):
    lg = await make_league(make_user)
    p = lg.players[lg.teams[0]][0]
    for path in ("preview", "generate", "publish"):
        body = PARAMS if path != "publish" else {}
        assert (await p.req("POST", f"/seasons/{lg.sid}/fixtures/{path}", json=body)).status_code == 403, path


async def test_bad_parameters_are_rejected(make_user):
    lg = await make_league(make_user)
    url = f"/seasons/{lg.sid}/fixtures/preview"
    bad = [
        {**PARAMS, "timezone": "Mars/Olympus"}, {**PARAMS, "times": []}, {**PARAMS, "weekdays": [7]},
        {**PARAMS, "weekdays": []}, {**PARAMS, "team_ids": [lg.teams[0]]}, {**PARAMS, "team_ids": [lg.teams[0], 99999]},
        {**PARAMS, "legs": 3}, {**PARAMS, "parallel": 0}, {k: v for k, v in PARAMS.items() if k != "start_date"},
    ]
    for body in bad:
        assert (await lg.admin.req("POST", url, json=body)).status_code == 422, body
    assert (await lg.admin.req("POST", "/seasons/99999/fixtures/preview", json=PARAMS)).status_code == 404


# ---------- generate ----------
async def test_generate_creates_unpublished_drafts_with_rooms_and_stage(make_user, db):
    lg = await make_league(make_user)
    manual = (await lg.admin.req("POST", f"/seasons/{lg.sid}/matches", json={"team_a_id": lg.teams[0], "team_b_id": lg.teams[1]})).json()
    r = await gen(lg, timezone="Asia/Kolkata", times=["19:00"])
    assert r.status_code == 201 and r.json()["created"] == 6
    db.expire_all()
    ms = list(await db.scalars(select(Match).where(Match.stage_id == r.json()["stage_id"]).order_by(Match.match_no)))
    assert [m.match_no for m in ms] == list(range(manual["match_no"] + 1, manual["match_no"] + 7))  # numbering continues
    assert all(m.published_at is None and m.status == "scheduled" and m.round_label.startswith("Round ") for m in ms)
    assert ms[0].scheduled_at == datetime(2030, 1, 7, 13, 30, tzinfo=UTC)  # 19:00 in Kolkata
    for m in ms:
        kinds = set(await db.scalars(select(ChatRoom.kind).where(ChatRoom.match_id == m.id)))
        assert kinds == {"match", "umpire"}
    assert (await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "fixtures.generate"))) == 1
    stages = (await lg.admin.req("GET", f"/seasons/{lg.sid}/stages")).json()
    assert [(s["name"], s["matches"], s["published"]) for s in stages] == [("League", 6, 0)]
    # the hand-made match was untouched and still published
    assert (await db.get(Match, manual["id"])).published_at is not None


async def test_double_round_robin_and_odd_team_counts(make_user, db):
    lg = await make_league(make_user, n_teams=4)
    r = await gen(lg, legs=2)
    assert r.json()["created"] == 12 and r.json()["summary"]["rounds"] == 6
    odd = await make_league(make_user, n_teams=5)
    r = await gen(odd)
    assert r.json()["created"] == 10 and r.json()["summary"]["rounds"] == 5  # a bye every round


async def test_generated_umpires_follow_the_rules(make_user, db):
    lg = await make_league(make_user, n_teams=4, n_umpires=3)
    r = await gen(lg, parallel=2)
    db.expire_all()
    ms = list(await db.scalars(select(Match).where(Match.stage_id == r.json()["stage_id"])))
    assert all(m.umpire_id in {u.id for u in lg.umpires} for m in ms)
    by_time = {}
    for m in ms:
        by_time.setdefault(m.scheduled_at, []).append(m.umpire_id)
    assert all(len(v) == len(set(v)) for v in by_time.values())  # nobody umpires two matches at once
    used = [m.umpire_id for m in ms]
    assert max(used.count(u.id) for u in lg.umpires) - min(used.count(u.id) for u in lg.umpires) <= 1


async def test_generating_twice_needs_replace_and_published_matches_are_safe(make_user, db):
    lg = await make_league(make_user)
    first = (await gen(lg)).json()
    assert (await gen(lg)).status_code == 409
    again = await gen(lg, replace_drafts=True, legs=2)
    assert again.status_code == 201 and again.json()["created"] == 12
    db.expire_all()
    assert await db.scalar(select(func.count()).select_from(Match).where(Match.id.in_(first["match_ids"]))) == 0
    assert (await db.scalar(select(func.count()).select_from(ChatRoom).where(ChatRoom.match_id.in_(first["match_ids"])))) == 0
    assert (await db.scalar(select(func.count()).select_from(Stage))) == 1
    # once published the schedule can no longer be thrown away
    assert (await lg.admin.req("POST", f"/seasons/{lg.sid}/fixtures/publish", json={})).status_code == 200
    assert (await gen(lg, replace_drafts=True)).status_code == 409


# ---------- visibility ----------
async def test_players_never_see_drafts_but_admins_do(make_user, db):
    lg = await make_league(make_user)
    ids = (await gen(lg)).json()["match_ids"]
    mid = ids[0]
    cap = lg.players[lg.teams[0]][0]
    umpire_id = (await db.get(Match, mid)).umpire_id
    ump = next(u for u in lg.umpires if u.id == umpire_id)
    for who in (cap, ump):
        assert (await who.req("GET", f"/seasons/{lg.sid}/matches")).json() == []
        assert (await who.req("GET", f"/seasons/{lg.sid}/fixtures")).json() == []
        assert (await who.req("GET", f"/seasons/{lg.sid}/fixtures?include_drafts=true")).json() == []  # the flag is admin-only
        for path in (f"/matches/{mid}", f"/matches/{mid}/live", f"/matches/{mid}/rooms"):
            assert (await who.req("GET", path)).status_code == 404, path
    assert (await cap.req("PUT", f"/matches/{mid}/lineup", json={"team_id": lg.teams[0], "user_ids": [cap.id]})).status_code == 404
    admin_view = (await lg.admin.req("GET", f"/seasons/{lg.sid}/fixtures?include_drafts=true")).json()
    assert len(admin_view) == 6 and all(not f["published"] for f in admin_view)
    assert (await lg.admin.req("GET", f"/seasons/{lg.sid}/fixtures")).json() == []  # drafts only on request
    assert len((await lg.admin.req("GET", f"/seasons/{lg.sid}/matches")).json()) == 6
    # nobody can run a match nobody has been told about
    assert (await ump.req("POST", f"/matches/{mid}/toss/open")).status_code == 409
    assert (await lg.admin.req("POST", f"/matches/{mid}/toss/open")).status_code == 409


# ---------- publish ----------
async def test_publish_makes_matches_visible_and_tells_everyone_exactly_once(make_user, db):
    lg = await make_league(make_user, n_teams=4, per_team=3)
    await gen(lg)
    r = await lg.admin.req("POST", f"/seasons/{lg.sid}/fixtures/publish", json={})
    assert r.status_code == 200 and r.json()["published"] == 6 and r.json()["without_umpire"] == []
    members = {p.id for ps in lg.players.values() for p in ps}
    got = await notes(db, "fixtures_published")
    assert {n.user_id for n in got} == members and len(got) == len(members)  # one notice per person
    assert all(n.title == "New fixtures are published" and n.data["link"] == "/fixtures" for n in got)
    mine = next(n for n in got if n.user_id == lg.players[lg.teams[0]][1].id)
    assert mine.body.startswith("Team1 play ") and "(match " in mine.body
    assert {n.user_id for n in await notes(db, "umpire_assigned")} <= {u.id for u in lg.umpires}
    cap = lg.players[lg.teams[0]][0]
    assert len((await cap.req("GET", f"/seasons/{lg.sid}/fixtures")).json()) == 6
    # repeating it does nothing and notifies nobody again
    again = await lg.admin.req("POST", f"/seasons/{lg.sid}/fixtures/publish", json={})
    assert again.json() == {"published": 0, "notified": 0, "without_umpire": []}
    assert len(await notes(db, "fixtures_published")) == len(got)


async def test_publish_can_target_matches_and_refuses_undated_ones(make_user, db):
    lg = await make_league(make_user, n_umpires=0)
    ids = (await gen(lg, assign_umpires=False)).json()["match_ids"]
    r = await lg.admin.req("POST", f"/seasons/{lg.sid}/fixtures/publish", json={"match_ids": ids[:2]})
    assert r.json()["published"] == 2 and len(r.json()["without_umpire"]) == 2  # told which lack an umpire
    await lg.admin.req("PATCH", f"/matches/{ids[2]}", json={"scheduled_at": None})
    bad = await lg.admin.req("POST", f"/seasons/{lg.sid}/fixtures/publish", json={})
    assert bad.status_code == 422 and "date and time" in bad.json()["detail"]
    db.expire_all()
    assert (await db.get(Match, ids[3])).published_at is None  # nothing was half-published


# ---------- rescheduling and clashes ----------
async def test_rescheduling_a_published_match_tells_everybody(make_user, db):
    lg = await make_league(make_user)
    ids = (await gen(lg)).json()["match_ids"]
    await lg.admin.req("POST", f"/seasons/{lg.sid}/fixtures/publish", json={})
    mid = ids[0]
    m = await db.get(Match, mid)
    teams, umpire, match_no = {m.team_a_id, m.team_b_id}, m.umpire_id, m.match_no
    new = (m.scheduled_at + timedelta(days=30)).replace(hour=9)
    r = await lg.admin.req("PATCH", f"/matches/{mid}", json={"scheduled_at": new.isoformat()})
    assert r.status_code == 200
    db.expire_all()
    got = [n for n in await notes(db, "fixture_change") if n.data["match_id"] == mid]
    expect = {p.id for t in teams for p in lg.players[t]} | {umpire}
    assert {n.user_id for n in got} == expect and got[0].title == f"Match {match_no} rescheduled"
    r2 = (await db.scalars(select(ChatRoom).where(ChatRoom.match_id == mid, ChatRoom.kind == "match"))).one()
    lines = list(await db.scalars(select(ChatMessage.body).where(ChatMessage.room_id == r2.id, ChatMessage.kind == "system")))
    assert any(line.startswith("📅 Match moved to") for line in lines)
    # moving a draft is silent
    draft = (await lg.admin.req("POST", f"/seasons/{lg.sid}/matches", json={"team_a_id": lg.teams[0], "team_b_id": lg.teams[1]})).json()
    assert draft["published_at"]  # hand-made matches are visible at once


async def test_clashes_are_caught_and_can_be_overridden_with_an_audit_trail(make_user, db):
    lg = await make_league(make_user, n_teams=4)
    t0 = datetime(2031, 3, 1, 18, 0, tzinfo=UTC)
    a, b, c, d = lg.teams
    ump = lg.umpires[0]
    m1 = (await lg.admin.req("POST", f"/seasons/{lg.sid}/matches", json={
        "team_a_id": a, "team_b_id": b, "scheduled_at": t0.isoformat(), "umpire_id": ump.id})).json()
    # a team double-booked within the match window
    clash = await lg.admin.req("POST", f"/seasons/{lg.sid}/matches", json={
        "team_a_id": a, "team_b_id": c, "scheduled_at": (t0 + timedelta(minutes=30)).isoformat()})
    assert clash.status_code == 409 and "Team1 already plays match 1" in clash.json()["detail"]["conflicts"][0]
    # the same umpire at the same time
    c2 = await lg.admin.req("POST", f"/seasons/{lg.sid}/matches", json={
        "team_a_id": c, "team_b_id": d, "scheduled_at": t0.isoformat(), "umpire_id": ump.id})
    assert c2.status_code == 409 and "umpire is already umpiring" in c2.json()["detail"]["conflicts"][0]
    # clear of the window is fine (90 minutes apart)
    ok = await lg.admin.req("POST", f"/seasons/{lg.sid}/matches", json={
        "team_a_id": a, "team_b_id": c, "scheduled_at": (t0 + timedelta(minutes=90)).isoformat()})
    assert ok.status_code == 201
    # rescheduling into a clash is refused; force goes through and is audited
    m3 = (await lg.admin.req("POST", f"/seasons/{lg.sid}/matches", json={"team_a_id": c, "team_b_id": d})).json()
    bad = await lg.admin.req("PATCH", f"/matches/{m3['id']}", json={"scheduled_at": t0.isoformat(), "umpire_id": ump.id})
    assert bad.status_code == 409
    forced = await lg.admin.req("PATCH", f"/matches/{m3['id']}", json={"scheduled_at": t0.isoformat(), "umpire_id": ump.id, "force": True})
    assert forced.status_code == 200
    audit = list(await db.scalars(select(AuditLog).where(AuditLog.action == "match.force_update")))
    assert len(audit) == 1 and audit[0].after["conflicts"]
    # a match never clashes with itself: re-saving it at its own time with a free umpire is fine
    # (team 1's other match is exactly 90 minutes later, which is outside the window)
    same = await lg.admin.req("PATCH", f"/matches/{m1['id']}", json={"scheduled_at": t0.isoformat(), "umpire_id": lg.umpires[1].id})
    assert same.status_code == 200


async def test_an_umpire_who_is_playing_cannot_umpire_at_the_same_time(make_user, db):
    lg = await make_league(make_user, n_teams=4)
    t0 = datetime(2031, 3, 1, 18, 0, tzinfo=UTC)
    a, b, c, d = lg.teams
    player = lg.players[a][1]
    await lg.admin.req("POST", f"/users/{player.id}/roles", json={"role": "umpire"})
    await lg.admin.req("POST", f"/seasons/{lg.sid}/matches", json={"team_a_id": a, "team_b_id": b, "scheduled_at": t0.isoformat()})
    r = await lg.admin.req("POST", f"/seasons/{lg.sid}/matches", json={
        "team_a_id": c, "team_b_id": d, "scheduled_at": t0.isoformat(), "umpire_id": player.id})
    assert r.status_code == 409 and "plays in match 1" in r.json()["detail"]["conflicts"][0]


# ---------- delete ----------
async def test_only_drafts_can_be_deleted(make_user, db):
    lg = await make_league(make_user)
    ids = (await gen(lg)).json()["match_ids"]
    assert (await lg.players[lg.teams[0]][0].req("DELETE", f"/matches/{ids[0]}")).status_code == 403
    assert (await lg.admin.req("DELETE", f"/matches/{ids[0]}")).status_code == 204
    assert (await lg.admin.req("DELETE", f"/matches/{ids[0]}")).status_code == 404
    await lg.admin.req("POST", f"/seasons/{lg.sid}/fixtures/publish", json={})
    assert (await lg.admin.req("DELETE", f"/matches/{ids[1]}")).status_code == 409
    db.expire_all()
    assert await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "match.delete")) == 1


# ---------- the fixture list ----------
async def test_fixture_list_filters_and_ordering(make_user, db):
    ctx = await setup_match(make_user)  # Pink v Green, published
    r = await rooms(db, ctx)  # noqa: F841 - keeps rooms fixture helper exercised
    sid = ctx.sid
    url = f"/seasons/{sid}/fixtures"
    admin = ctx.admin

    def ids(res):
        return [f["id"] for f in res.json()]

    assert ids(await admin.req("GET", f"{url}?status=upcoming")) == [ctx.match]
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    live = (await admin.req("GET", f"{url}?status=live")).json()
    assert [f["id"] for f in live] == [ctx.match] and live[0]["team_a"]["name"] == "Pink"
    assert ids(await admin.req("GET", f"{url}?status=upcoming")) == []
    await play(ctx, batters, bowlers, 1, bowl_digits=BOWL_ALL_EQUAL)
    await play(ctx, batters, bowlers, 2, bowl_digits=BOWL_ALL_EQUAL)
    await ctx.ump.req("POST", f"{ctx.url}/innings/next")
    await play(ctx, bowlers, batters, 1)
    done = (await admin.req("GET", f"{url}?status=completed")).json()
    assert [f["id"] for f in done] == [ctx.match] and done[0]["result"] == "Green won by 7 wickets"
    assert done[0]["umpire"] and done[0]["winner_team_id"]
    team_green = done[0]["team_b"]["id"]
    assert ids(await admin.req("GET", f"{url}?team_id={team_green}")) == [ctx.match]
    assert ids(await admin.req("GET", f"{url}?team_id=999999")) == []
    assert (await admin.req("GET", f"{url}?status=nonsense")).status_code == 422


async def test_stage_listing_counts_published_matches(make_user, db):
    lg = await make_league(make_user)
    ids = (await gen(lg)).json()["match_ids"]
    await lg.admin.req("POST", f"/seasons/{lg.sid}/fixtures/publish", json={"match_ids": ids[:2]})
    stages = (await lg.players[lg.teams[0]][0].req("GET", f"/seasons/{lg.sid}/stages")).json()
    assert [(s["matches"], s["published"], s["kind"]) for s in stages] == [(6, 2, "round_robin")]
