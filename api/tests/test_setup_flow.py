async def mk_season(admin, name="S24"):
    r = await admin.req("POST", "/seasons", json={"name": name, "status": "active"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def mk_team(admin, season_id, name):
    r = await admin.req("POST", f"/seasons/{season_id}/teams", json={"name": name, "color": "#ff69b4"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_players_cannot_create_seasons(make_user):
    p = await make_user("P")
    assert (await p.req("POST", "/seasons", json={"name": "X"})).status_code == 403


async def test_season_crud_and_duplicate(make_user):
    admin = await make_user("A", roles=["tournament_admin"])
    sid = await mk_season(admin)
    assert (await admin.req("POST", "/seasons", json={"name": "S24"})).status_code == 409
    r = await admin.req("PATCH", f"/seasons/{sid}", json={"status": "completed"})
    assert r.json()["status"] == "completed"
    assert len((await admin.req("GET", "/seasons")).json()) == 1


async def test_roster_flow_and_cap(make_user):
    admin = await make_user("A", roles=["tournament_admin"])
    sid = await mk_season(admin)
    tid = await mk_team(admin, sid, "Pink")
    players = [await make_user("P") for _ in range(8)]
    for p in players[:7]:
        assert (await admin.req("POST", f"/teams/{tid}/members", json={"user_id": p.id})).status_code == 201
    r = await admin.req("POST", f"/teams/{tid}/members", json={"user_id": players[7].id})
    assert r.status_code == 409  # 8th player rejected
    # self-request lands as pending and cannot be approved over the cap
    r = await players[7].req("POST", f"/teams/{tid}/members", json={})
    assert r.status_code == 201 and r.json()["status"] == "pending"
    r = await admin.req("POST", f"/teams/{tid}/members/{players[7].id}/approve")
    assert r.status_code == 409
    await admin.req("DELETE", f"/teams/{tid}/members/{players[0].id}")
    r = await admin.req("POST", f"/teams/{tid}/members/{players[7].id}/approve")
    assert r.status_code == 200


async def test_player_in_one_team_per_season(make_user):
    admin = await make_user("A", roles=["tournament_admin"])
    sid = await mk_season(admin)
    t1, t2 = await mk_team(admin, sid, "Pink"), await mk_team(admin, sid, "Green")
    p = await make_user("P")
    assert (await admin.req("POST", f"/teams/{t1}/members", json={"user_id": p.id})).status_code == 201
    assert (await admin.req("POST", f"/teams/{t2}/members", json={"user_id": p.id})).status_code == 409


async def test_captain_manages_own_team_only(make_user):
    admin = await make_user("A", roles=["tournament_admin"])
    sid = await mk_season(admin)
    t1, t2 = await mk_team(admin, sid, "Pink"), await mk_team(admin, sid, "Green")
    cap, p, q = await make_user("C"), await make_user("P"), await make_user("Q")
    await admin.req("POST", f"/teams/{t1}/members", json={"user_id": cap.id})
    r = await admin.req("PATCH", f"/teams/{t1}", json={"captain_id": cap.id})
    assert r.status_code == 200
    assert "captain" in (await cap.req("GET", "/me")).json()["roles"]
    assert (await cap.req("POST", f"/teams/{t1}/members", json={"user_id": p.id})).status_code == 201
    assert (await cap.req("POST", f"/teams/{t2}/members", json={"user_id": q.id})).status_code == 403
    # captain cannot reassign captaincy
    r = await cap.req("PATCH", f"/teams/{t1}", json={"captain_id": p.id})
    assert r.status_code == 403
    # captain must be an approved member
    r = await admin.req("PATCH", f"/teams/{t1}", json={"captain_id": q.id})
    assert r.status_code == 400


async def test_match_creation_rules(make_user):
    admin = await make_user("A", roles=["tournament_admin"])
    sid = await mk_season(admin)
    t1, t2 = await mk_team(admin, sid, "Pink"), await mk_team(admin, sid, "Green")
    ump, p = await make_user("U", roles=["umpire"]), await make_user("P")
    await admin.req("POST", f"/teams/{t1}/members", json={"user_id": ump.id})
    body = {"team_a_id": t1, "team_b_id": t2}
    assert (await admin.req("POST", f"/seasons/{sid}/matches", json={**body, "team_b_id": t1})).status_code == 400
    # non-umpire rejected
    r = await admin.req("POST", f"/seasons/{sid}/matches", json={**body, "umpire_id": p.id})
    assert r.status_code == 400
    # umpire who plays for a team in this match rejected
    r = await admin.req("POST", f"/seasons/{sid}/matches", json={**body, "umpire_id": ump.id})
    assert r.status_code == 400
    await admin.req("DELETE", f"/teams/{t1}/members/{ump.id}")
    r = await admin.req("POST", f"/seasons/{sid}/matches", json={**body, "umpire_id": ump.id})
    assert r.status_code == 201 and r.json()["match_no"] == 1
    r = await admin.req("POST", f"/seasons/{sid}/matches", json=body)
    assert r.json()["match_no"] == 2


async def test_lineup_rules(make_user):
    admin = await make_user("A", roles=["tournament_admin"])
    sid = await mk_season(admin)
    t1, t2 = await mk_team(admin, sid, "Pink"), await mk_team(admin, sid, "Green")
    cap = await make_user("C")
    ok1, unverified, outsider = await make_user("P"), await make_user("U", verified=False), await make_user("O")
    for p in (cap, ok1, unverified):
        await admin.req("POST", f"/teams/{t1}/members", json={"user_id": p.id})
    await admin.req("PATCH", f"/teams/{t1}", json={"captain_id": cap.id})
    m = (await admin.req("POST", f"/seasons/{sid}/matches", json={"team_a_id": t1, "team_b_id": t2})).json()
    url = f"/matches/{m['id']}/lineup"
    # unverified phone blocked
    r = await cap.req("PUT", url, json={"team_id": t1, "user_ids": [cap.id, unverified.id]})
    assert r.status_code == 400 and "verified" in r.json()["detail"]
    # non-member blocked
    r = await cap.req("PUT", url, json={"team_id": t1, "user_ids": [cap.id, outsider.id]})
    assert r.status_code == 400
    # duplicates blocked
    r = await cap.req("PUT", url, json={"team_id": t1, "user_ids": [cap.id, cap.id]})
    assert r.status_code == 400
    # other team's captain/random player blocked
    r = await outsider.req("PUT", url, json={"team_id": t1, "user_ids": [cap.id]})
    assert r.status_code == 403
    # valid, and replacing is allowed
    r = await cap.req("PUT", url, json={"team_id": t1, "user_ids": [cap.id, ok1.id]})
    assert r.status_code == 200 and [p["user_id"] for p in r.json()["lineup"]] == [cap.id, ok1.id]
    r = await cap.req("PUT", url, json={"team_id": t1, "user_ids": [ok1.id]})
    assert len(r.json()["lineup"]) == 1
