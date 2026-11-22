from sqlalchemy import select

from app.db.models import AuditLog
from tests.helpers import setup_match


async def test_list_search_filter_and_paginate(make_user):
    sa = await make_user("Boss", roles=["super_admin"])
    ump = await make_user("Umpy", roles=["umpire"])
    sus = await make_user("Sus")
    await sa.req("PUT", f"/users/{sus.id}/status", json={"status": "suspended"})
    people = [await make_user("Pat") for _ in range(4)]
    res = (await sa.req("GET", "/admin/users?limit=100")).json()
    assert res["total"] == 7 and len(res["users"]) == 7
    boss = next(u for u in res["users"] if u["id"] == sa.id)
    assert boss["email"].endswith("@t.io") and boss["phone"] == sa.phone and boss["phone_verified"] is True
    assert boss["roles"] == [{"role": "player", "season_id": None}, {"role": "super_admin", "season_id": None}]
    # search by name, email, phone and player code
    for term, expect in (("Umpy", {ump.id}), (f"u{ump.id}@t.io", {ump.id}), (ump.phone.replace("+", "%2B"), {ump.id})):
        got = {u["id"] for u in (await sa.req("GET", f"/admin/users?q={term}")).json()["users"]}
        assert got == expect, term
    code = next(u["player_code"] for u in res["users"] if u["id"] == ump.id)
    assert {u["id"] for u in (await sa.req("GET", f"/admin/users?q={code}")).json()["users"]} == {ump.id}
    # filters
    assert [u["id"] for u in (await sa.req("GET", "/admin/users?role=umpire")).json()["users"]] == [ump.id]
    assert [u["id"] for u in (await sa.req("GET", "/admin/users?status=suspended")).json()["users"]] == [sus.id]
    # pagination is stable and reports the full total
    p1 = (await sa.req("GET", "/admin/users?limit=3&offset=0")).json()
    p2 = (await sa.req("GET", "/admin/users?limit=3&offset=3")).json()
    assert p1["total"] == p2["total"] == 7 and not {u["id"] for u in p1["users"]} & {u["id"] for u in p2["users"]}
    # wildcards are literal, bad filters rejected
    assert (await sa.req("GET", "/admin/users?q=%25")).json()["total"] == 0
    assert (await sa.req("GET", "/admin/users?role=wizard")).status_code == 422
    assert (await sa.req("GET", "/admin/users?limit=500")).status_code == 422
    assert people  # created above


async def test_revoke_rules(make_user, db):
    sa = await make_user("Boss", roles=["super_admin"])
    ta = await make_user("TA", roles=["tournament_admin"])
    p = await make_user("P", roles=["umpire", "tournament_admin"])
    # a tournament admin can take away umpire duty but not admin powers
    assert (await ta.req("DELETE", f"/admin/users/{p.id}/roles/umpire")).status_code == 204
    assert (await ta.req("DELETE", f"/admin/users/{p.id}/roles/umpire")).status_code == 404  # already gone
    assert (await ta.req("DELETE", f"/admin/users/{p.id}/roles/tournament_admin")).status_code == 403
    assert (await sa.req("DELETE", f"/admin/users/{p.id}/roles/tournament_admin")).status_code == 204
    assert (await sa.req("DELETE", f"/admin/users/{p.id}/roles/wizard")).status_code == 422
    assert (await sa.req("DELETE", "/admin/users/99999/roles/umpire")).status_code == 404
    # nobody can lock themselves out, and the last super admin is protected
    assert (await sa.req("DELETE", f"/admin/users/{sa.id}/roles/super_admin")).status_code == 400
    other = await make_user("Other", roles=["super_admin"])
    assert (await other.req("DELETE", f"/admin/users/{sa.id}/roles/super_admin")).status_code == 204
    assert (await other.req("DELETE", f"/admin/users/{other.id}/roles/super_admin")).status_code == 400
    actions = set(await db.scalars(select(AuditLog.action)))
    assert "role.revoke" in actions


async def test_cannot_revoke_umpire_or_captain_while_in_use(make_user):
    ctx = await setup_match(make_user)  # umpire assigned to an unfinished match; a[0] and b[0] are captains
    sa = await make_user("Boss", roles=["super_admin"])
    r = await sa.req("DELETE", f"/admin/users/{ctx.ump.id}/roles/umpire")
    assert r.status_code == 409 and "unfinished" in r.json()["detail"]
    await ctx.admin.req("PATCH", f"/matches/{ctx.match}", json={"umpire_id": None})
    assert (await sa.req("DELETE", f"/admin/users/{ctx.ump.id}/roles/umpire")).status_code == 204
    r = await sa.req("DELETE", f"/admin/users/{ctx.a[0].id}/roles/captain?season_id={ctx.sid}")
    assert r.status_code == 409 and "captain of Pink" in r.json()["detail"]
    await ctx.admin.req("PATCH", f"/teams/{ctx.team_a}", json={"captain_id": ctx.a[1].id})
    assert (await sa.req("DELETE", f"/admin/users/{ctx.a[0].id}/roles/captain?season_id={ctx.sid}")).status_code == 204


async def test_season_scoped_role_revoke_only_touches_that_season(make_user, db):
    from app.db.models import UserRole

    sa = await make_user("Boss", roles=["super_admin"])
    p = await make_user("P")
    ctx = await setup_match(make_user)
    db.add_all([UserRole(user_id=p.id, role="umpire", season_id=None), UserRole(user_id=p.id, role="umpire", season_id=ctx.sid)])
    await db.commit()
    assert (await sa.req("DELETE", f"/admin/users/{p.id}/roles/umpire?season_id={ctx.sid}")).status_code == 204
    left = (await sa.req("GET", f"/admin/users?q={p.phone.replace('+', '%2B')}")).json()["users"][0]["roles"]
    assert {"role": "umpire", "season_id": None} in left and {"role": "umpire", "season_id": ctx.sid} not in left


async def test_suspend_reactivate_and_audit(make_user, client, db):
    sa = await make_user("Boss", roles=["super_admin"])
    ta = await make_user("TA", roles=["tournament_admin"])
    p = await make_user("P")
    creds = {"email": f"u{p.id}@t.io", "password": "password123"}
    assert (await ta.req("PUT", f"/users/{p.id}/status", json={"status": "suspended"})).status_code == 403
    assert (await sa.req("PUT", f"/users/{sa.id}/status", json={"status": "suspended"})).status_code == 400  # no self-lockout
    assert (await sa.req("PUT", f"/users/{p.id}/status", json={"status": "suspended"})).status_code == 204
    assert (await p.req("GET", "/me")).status_code == 401  # their sessions were ended
    assert (await client.post("/auth/login", json=creds)).status_code == 403
    assert (await sa.req("PUT", f"/users/{p.id}/status", json={"status": "active"})).status_code == 204
    assert (await client.post("/auth/login", json=creds)).status_code == 200
    assert (await sa.req("PUT", f"/users/{p.id}/status", json={"status": "exiled"})).status_code == 422
    rows = list(await db.scalars(select(AuditLog).where(AuditLog.action == "user.status").order_by(AuditLog.id)))
    assert [(r.before["status"], r.after["status"]) for r in rows] == [("active", "suspended"), ("suspended", "active")]
    assert all(r.actor_id == sa.id and r.entity_id == p.id for r in rows)


async def test_granting_is_audited(make_user, db):
    sa = await make_user("Boss", roles=["super_admin"])
    p = await make_user("P")
    await sa.req("POST", f"/users/{p.id}/roles", json={"role": "umpire"})
    await sa.req("POST", f"/users/{p.id}/roles", json={"role": "umpire"})  # idempotent: one audit row
    rows = list(await db.scalars(select(AuditLog).where(AuditLog.action == "role.grant")))
    assert len(rows) == 1 and rows[0].after == {"role": "umpire", "season_id": None} and rows[0].actor_id == sa.id
