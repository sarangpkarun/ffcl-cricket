import asyncio
import logging

from sqlalchemy import select

from app.db.models import AuditLog, Notification, User
from tests.helpers import make_league, new_match


async def league(make_user):
    return await make_league(make_user, n_teams=3, per_team=4, n_umpires=2)


def swap(out, inn, reason="needs to move away"):
    return {"out_user_id": out.id, "in_user_id": inn.id, "reason": reason}


async def members(lg, tid):
    t = (await lg.admin.req("GET", f"/teams/{tid}")).json()
    return {m["user_id"]: m["status"] for m in t["members"]}


# ---------- roster changes ----------
async def test_roster_change_happy_path(make_user, db):
    lg = await league(make_user)
    a, b, _ = lg.teams
    cap, out = lg.players[a][0], lg.players[a][1]
    free = await make_user("Free")
    r = await cap.req("POST", f"/teams/{a}/roster-changes", json=swap(out, free))
    assert r.status_code == 201, r.text
    rc = r.json()
    assert rc["status"] == "pending" and rc["out"]["id"] == out.id and rc["in"]["id"] == free.id
    got = list(await db.scalars(select(Notification).where(Notification.title == "Roster change to approve")))
    assert {n.user_id for n in got} == {lg.admin.id}
    # who can see it
    assert [x["id"] for x in (await lg.admin.req("GET", "/roster-changes?status=pending")).json()] == [rc["id"]]
    assert [x["id"] for x in (await cap.req("GET", "/roster-changes")).json()] == [rc["id"]]
    assert [x["id"] for x in (await free.req("GET", "/roster-changes")).json()] == [rc["id"]]  # people it is about
    assert (await lg.players[b][1].req("GET", "/roster-changes")).json() == []
    assert (await cap.req("POST", f"/roster-changes/{rc['id']}/approve")).status_code == 403  # admins decide

    ok = await lg.admin.req("POST", f"/roster-changes/{rc['id']}/approve")
    assert ok.status_code == 200 and ok.json()["status"] == "approved" and ok.json()["decided_by"]["id"] == lg.admin.id
    m = await members(lg, a)
    assert m.get(free.id) == "approved" and out.id not in m  # the outgoing player is gone from the roster
    assert (await lg.admin.req("POST", f"/roster-changes/{rc['id']}/approve")).status_code == 409
    told = list(await db.scalars(select(Notification).where(Notification.title == "Roster change approved")))
    assert {out.id, free.id, cap.id} <= {n.user_id for n in told}
    db.expire_all()
    log = list(await db.scalars(select(AuditLog.action).where(AuditLog.entity == "roster_change")))
    assert log == ["roster.request", "roster.approve"]


async def test_roster_change_blockers(make_user, db):
    lg = await league(make_user)
    a, b, _c = lg.teams
    cap, p1, p2 = lg.players[a][0], lg.players[a][1], lg.players[a][2]
    free = await make_user("Free")
    unverified = await make_user("Raw", verified=False)
    url = f"/teams/{a}/roster-changes"
    assert (await lg.players[a][3].req("POST", url, json=swap(p1, free))).status_code == 403  # not the captain
    assert (await cap.req("POST", url, json=swap(p1, p1))).status_code == 409
    r = await cap.req("POST", url, json=swap(cap, free))
    assert r.status_code == 409 and "captain" in r.json()["detail"]
    r = await cap.req("POST", url, json=swap(lg.players[b][1], free))
    assert r.status_code == 409 and "not an approved member" in r.json()["detail"]
    r = await cap.req("POST", url, json=swap(p1, lg.players[b][1]))
    assert r.status_code == 409 and "already in a team" in r.json()["detail"]
    r = await cap.req("POST", url, json=swap(p1, unverified))
    assert r.status_code == 409 and "verified phone" in r.json()["detail"]
    await lg.admin.req("POST", f"/users/{free.id}/status", json={"status": "suspended"})
    # a player in an unfinished match's lineup cannot leave
    mid = await new_match(lg, a, b)
    await lg.admin.req("PUT", f"/matches/{mid}/lineup", json={"team_id": a, "user_ids": [p.id for p in lg.players[a]]})
    other = await make_user("Other")
    r = await cap.req("POST", url, json=swap(p2, other))
    assert r.status_code == 409 and "lineup of an unfinished match" in r.json()["detail"]
    # a second request about the same player is refused while one is pending
    await lg.admin.req("PUT", f"/matches/{mid}/lineup", json={"team_id": a, "user_ids": [cap.id]})
    assert (await cap.req("POST", url, json=swap(p2, other))).status_code == 201
    assert (await cap.req("POST", url, json=swap(p2, await make_user("Another")))).status_code == 409


async def test_roster_change_is_rechecked_at_approval(make_user):
    lg = await league(make_user)
    a, b, _ = lg.teams
    cap, out = lg.players[a][0], lg.players[a][1]
    free = await make_user("Free")
    rc = (await cap.req("POST", f"/teams/{a}/roster-changes", json=swap(out, free))).json()
    # meanwhile the incoming player joins another team
    assert (await lg.admin.req("POST", f"/teams/{b}/members", json={"user_id": free.id})).status_code == 201
    r = await lg.admin.req("POST", f"/roster-changes/{rc['id']}/approve")
    assert r.status_code == 409 and "already in a team" in r.json()["detail"]
    assert (await members(lg, a)).get(out.id) == "approved"  # nothing changed
    # and a lineup being set after the request also blocks it
    assert (await cap.req("POST", f"/roster-changes/{rc['id']}/cancel")).status_code == 200
    free2 = await make_user("Free2")
    rc2 = (await cap.req("POST", f"/teams/{a}/roster-changes", json=swap(out, free2))).json()
    mid = await new_match(lg, a, b)
    await lg.admin.req("PUT", f"/matches/{mid}/lineup", json={"team_id": a, "user_ids": [out.id]})
    assert (await lg.admin.req("POST", f"/roster-changes/{rc2['id']}/approve")).status_code == 409


async def test_two_admins_approving_at_once_only_one_wins(make_user):
    lg = await league(make_user)
    a = lg.teams[0]
    second = await make_user("Admin2", roles=["tournament_admin"])
    free = await make_user("Free")
    rc = (await lg.players[a][0].req("POST", f"/teams/{a}/roster-changes", json=swap(lg.players[a][1], free))).json()
    r1, r2 = await asyncio.gather(lg.admin.req("POST", f"/roster-changes/{rc['id']}/approve"),
                                  second.req("POST", f"/roster-changes/{rc['id']}/approve"))
    assert sorted([r1.status_code, r2.status_code]) == [200, 409]
    roster = await members(lg, a)
    assert list(roster.values()).count("approved") == 4 and roster[free.id] == "approved"  # still a full, valid roster


async def test_reject_and_cancel(make_user, db):
    lg = await league(make_user)
    a = lg.teams[0]
    cap = lg.players[a][0]
    free = await make_user("Free")
    rc = (await cap.req("POST", f"/teams/{a}/roster-changes", json=swap(lg.players[a][1], free))).json()
    assert (await lg.admin.req("POST", f"/roster-changes/{rc['id']}/reject", json={"note": "no"})).status_code == 422
    assert (await lg.players[a][2].req("POST", f"/roster-changes/{rc['id']}/cancel")).status_code == 403
    r = await lg.admin.req("POST", f"/roster-changes/{rc['id']}/reject", json={"note": "season is too far along"})
    assert r.status_code == 200 and r.json()["status"] == "rejected" and r.json()["decision_note"] == "season is too far along"
    got = list(await db.scalars(select(Notification).where(Notification.title == "Roster change rejected")))
    assert [n.user_id for n in got] == [cap.id]
    assert (await lg.admin.req("POST", f"/roster-changes/{rc['id']}/approve")).status_code == 409
    rc2 = (await cap.req("POST", f"/teams/{a}/roster-changes", json=swap(lg.players[a][1], free))).json()
    assert (await cap.req("POST", f"/roster-changes/{rc2['id']}/cancel")).json()["status"] == "cancelled"
    assert (await cap.req("POST", f"/roster-changes/{rc2['id']}/cancel")).status_code == 409


# ---------- phone changes ----------
NEW = "+919888800001"


async def code_for(actor, caplog):
    with caplog.at_level(logging.WARNING, logger="ffcl.otp"):
        r = await actor.req("POST", "/me/phone-change/otp/request")
    assert r.status_code == 204, r.text
    return caplog.records[-1].args[1]


async def test_phone_change_full_flow(make_user, db, caplog):
    admin = await make_user("Admin", roles=["tournament_admin"])
    p = await make_user("Player")
    old = p.phone
    r = await p.req("POST", "/me/phone-change", json={"new_phone": NEW, "reason": "lost my old sim"})
    assert r.status_code == 201 and r.json()["status"] == "pending" and "*" in r.json()["new_phone"]
    assert (await p.req("POST", "/me/phone-change/otp/request")).status_code == 409  # not approved yet
    assert (await p.req("POST", "/me/phone-change/verify", json={"code": "123456"})).status_code == 409
    queue = (await admin.req("GET", "/admin/phone-changes?status=pending")).json()
    assert len(queue) == 1 and queue[0]["new_phone"] == NEW and queue[0]["current_phone"] != old and "*" in queue[0]["current_phone"]
    assert (await p.req("GET", "/admin/phone-changes")).status_code == 403
    assert (await p.req("POST", f"/admin/phone-changes/{queue[0]['id']}/approve")).status_code == 403
    assert (await admin.req("POST", f"/admin/phone-changes/{queue[0]['id']}/approve")).json()["status"] == "approved"

    code = await code_for(p, caplog)
    wrong = "000000" if code != "000000" else "111111"
    assert (await p.req("POST", "/me/phone-change/verify", json={"code": wrong})).status_code == 400
    ok = await p.req("POST", "/me/phone-change/verify", json={"code": code})
    assert ok.status_code == 200 and ok.json()["phone"] == NEW
    db.expire_all()
    u = await db.get(User, p.id)
    assert u.phone == NEW and u.phone_verified is True
    assert (await p.req("GET", "/me/phone-change")).json()["status"] == "completed"
    # the old number is free again
    assert (await admin.req("POST", "/me/phone-change", json={"new_phone": old, "reason": "swap numbers around"})).status_code == 201
    log = list(await db.scalars(select(AuditLog).where(AuditLog.entity == "phone_change", AuditLog.action == "phone.complete")))
    assert len(log) == 1 and "*" in log[0].after["phone"] and NEW not in str(log[0].after) and old not in str(log[0].before)
    assert (await p.req("POST", "/me/phone-change/verify", json={"code": code})).status_code == 409  # nothing open any more


async def test_phone_change_rules(make_user, db):
    admin = await make_user("Admin", roles=["tournament_admin"])
    p, q = await make_user("P"), await make_user("Q")
    body = {"new_phone": NEW, "reason": "lost my old sim"}
    assert (await p.req("POST", "/me/phone-change", json={**body, "new_phone": p.phone})).status_code == 409
    taken = await p.req("POST", "/me/phone-change", json={**body, "new_phone": q.phone})
    assert taken.status_code == 409 and q.phone not in taken.text  # does not say who owns it
    assert (await p.req("POST", "/me/phone-change", json={**body, "new_phone": "12"})).status_code == 422
    assert (await p.req("POST", "/me/phone-change", json={**body, "reason": "x"})).status_code == 422
    r = await p.req("POST", "/me/phone-change", json=body)
    assert r.status_code == 201
    assert (await p.req("POST", "/me/phone-change", json={**body, "new_phone": "+919888800002"})).status_code == 409  # one at a time
    assert (await q.req("POST", "/me/phone-change", json=body)).status_code == 409  # same number as someone's open request
    # reject keeps the old number and records the reason
    rid = r.json()["id"]
    assert (await admin.req("POST", f"/admin/phone-changes/{rid}/reject", json={"note": "x"})).status_code == 422
    assert (await admin.req("POST", f"/admin/phone-changes/{rid}/reject", json={"note": "please call the organiser"})).json()["status"] == "rejected"
    assert (await admin.req("POST", f"/admin/phone-changes/{rid}/approve")).status_code == 409
    mine = (await p.req("GET", "/me/phone-change")).json()
    assert mine["status"] == "rejected" and mine["decision_note"] == "please call the organiser"
    # cancel an open one, and the number becomes available to others again
    await p.req("POST", "/me/phone-change", json=body)
    assert (await p.req("DELETE", "/me/phone-change")).status_code == 204
    assert (await p.req("DELETE", "/me/phone-change")).status_code == 404
    assert (await q.req("POST", "/me/phone-change", json=body)).status_code == 201


async def test_number_registered_meanwhile_blocks_the_change(make_user, caplog, client):
    admin = await make_user("Admin", roles=["tournament_admin"])
    p = await make_user("P")
    rid = (await p.req("POST", "/me/phone-change", json={"new_phone": NEW, "reason": "lost my old sim"})).json()["id"]
    await admin.req("POST", f"/admin/phone-changes/{rid}/approve")
    code = await code_for(p, caplog)
    reg = await client.post("/auth/register", json={"name": "Late", "email": "late@t.io", "password": "password123", "phone": NEW})
    assert reg.status_code == 201  # registration does not know about the pending change
    r = await p.req("POST", "/me/phone-change/verify", json={"code": code})
    assert r.status_code == 409 and NEW not in r.text
