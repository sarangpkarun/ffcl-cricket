"""Admin phone verification, OTP production mode, and bulk invites."""

import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core import otp
from app.core.config import Settings, assert_production_safe, settings
from app.db.models import AuditLog, Invite, Notification, OtpCode, TeamMember, User
from tests.helpers import make_league


async def league(make_user):
    return await make_league(make_user, n_teams=3, per_team=2, n_umpires=1)


@pytest.fixture
def no_sms(monkeypatch):
    monkeypatch.setattr(settings, "otp_provider", "disabled")


# ---------- admin verifies a number ----------
async def test_an_admin_verifies_a_number_with_a_reason_and_it_is_audited(make_user, db):
    lg = await league(make_user)
    newbie = await make_user("New", verified=False)
    await lg.admin.req("POST", f"/teams/{lg.teams[0]}/members", json={"user_id": newbie.id})
    sup = await make_user("Super", roles=["super_admin"])
    assert (await sup.req("POST", f"/admin/users/{newbie.id}/verify-phone", json={"reason": "x"})).status_code == 422
    r = await sup.req("POST", f"/admin/users/{newbie.id}/verify-phone", json={"reason": "Known to the league, checked by call"})
    assert r.status_code == 204, r.text
    me = (await newbie.req("GET", "/me")).json()
    assert me["phone_verified"] is True
    db.expire_all()
    u = await db.get(User, newbie.id)
    assert u.phone_verified_by == sup.id and u.phone_verified_at is not None
    assert await db.scalar(select(AuditLog).where(AuditLog.action == "phone.verify", AuditLog.entity_id == newbie.id, AuditLog.reason.like("Known%")))
    assert await db.scalar(select(Notification.id).where(Notification.user_id == newbie.id, Notification.kind == "phone"))
    assert (await sup.req("POST", f"/admin/users/{newbie.id}/verify-phone", json={"reason": "again please"})).status_code == 409
    listed = (await sup.req("GET", f"/admin/users?q={newbie.player_code if hasattr(newbie, 'player_code') else 'New'}")).json()["users"]
    assert any(x["id"] == newbie.id and x["phone_verified_by_admin"] for x in listed)


async def test_nobody_verifies_their_own_number_and_others_need_a_phone(make_user, db):
    sup = await make_user("Super", roles=["super_admin"], verified=False)
    assert (await sup.req("POST", f"/admin/users/{sup.id}/verify-phone", json={"reason": "myself"})).status_code == 403
    nophone = await make_user("NoPhone", verified=False)
    u = await db.get(User, nophone.id)
    u.phone = None
    await db.commit()
    assert (await sup.req("POST", f"/admin/users/{nophone.id}/verify-phone", json={"reason": "no number"})).status_code == 409
    assert (await sup.req("POST", "/admin/users/999999/verify-phone", json={"reason": "no one"})).status_code == 404
    plain = await make_user("Plain")
    assert (await plain.req("POST", f"/admin/users/{nophone.id}/verify-phone", json={"reason": "not admin"})).status_code == 403


async def test_a_season_admin_verifies_only_members_of_their_season(make_user, db):
    one, two = await league(make_user), await league(make_user)
    sup = await make_user("Super", roles=["super_admin"])
    sa = await make_user("SeasonAdmin")
    await sup.req("POST", f"/users/{sa.id}/roles", json={"role": "tournament_admin", "season_id": one.sid})
    mine, theirs, stranger = await make_user("Mine", verified=False), await make_user("Theirs", verified=False), await make_user("Nobody", verified=False)
    await one.admin.req("POST", f"/teams/{one.teams[0]}/members", json={"user_id": mine.id})
    await two.admin.req("POST", f"/teams/{two.teams[0]}/members", json={"user_id": theirs.id})
    listed = (await sa.req("GET", f"/admin/seasons/{one.sid}/unverified-phones")).json()
    assert [x["id"] for x in listed] == [mine.id]
    assert (await sa.req("GET", f"/admin/seasons/{two.sid}/unverified-phones")).status_code == 403
    for target in (theirs, stranger):
        assert (await sa.req("POST", f"/admin/users/{target.id}/verify-phone", json={"reason": "not mine"})).status_code == 403
    assert (await sa.req("POST", "/admin/users/999999/verify-phone", json={"reason": "no such"})).status_code == 403  # same answer: no probing
    assert (await sa.req("POST", f"/admin/users/{mine.id}/verify-phone", json={"reason": "my player"})).status_code == 204
    # a removed member no longer counts as theirs
    m = await db.scalar(select(TeamMember).where(TeamMember.user_id == theirs.id))
    m.status = "removed"
    await db.commit()
    assert (await sa.req("POST", f"/admin/users/{theirs.id}/verify-phone", json={"reason": "gone"})).status_code == 403


async def test_a_verified_number_is_what_the_lineup_rule_needs(make_user, db):
    lg = await league(make_user)
    newbie = await make_user("New", verified=False)
    tid = lg.teams[0]
    await lg.admin.req("POST", f"/teams/{tid}/members", json={"user_id": newbie.id})
    ids = [p.id for p in lg.players[tid]] + [newbie.id]
    mid = (await lg.admin.req("POST", f"/seasons/{lg.sid}/matches", json={"team_a_id": tid, "team_b_id": lg.teams[1], "umpire_id": lg.umpires[0].id})).json()["id"]
    assert (await lg.admin.req("PUT", f"/matches/{mid}/lineup", json={"team_id": tid, "user_ids": ids})).status_code == 400
    sup = await make_user("Super", roles=["super_admin"])
    await sup.req("POST", f"/admin/users/{newbie.id}/verify-phone", json={"reason": "checked"})
    assert (await lg.admin.req("PUT", f"/matches/{mid}/lineup", json={"team_id": tid, "user_ids": ids})).status_code == 200


# ---------- phone codes in production ----------
async def test_with_codes_disabled_nothing_is_generated_or_logged(make_user, db, no_sms, caplog):
    p = await make_user("P", verified=False)
    with caplog.at_level(logging.DEBUG):
        r = await p.req("POST", "/auth/otp/request", json={"phone": p.phone})
    assert r.status_code == 409 and "organiser" in r.json()["detail"]
    assert await db.scalar(select(func.count()).select_from(OtpCode)) == 0
    assert not [x for x in caplog.records if x.name == "ffcl.otp"]
    assert (await p.req("POST", "/me/phone-change/otp/request")).status_code == 409
    assert not otp.enabled()
    with pytest.raises(RuntimeError):
        otp.get_provider()


async def test_with_codes_disabled_an_approved_phone_change_takes_effect_at_once(make_user, db, no_sms):
    sup = await make_user("Super", roles=["super_admin"])
    p = await make_user("P")
    new = "+919977700001"
    r = await p.req("POST", "/me/phone-change", json={"new_phone": new, "reason": "lost my old SIM"})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert (await sup.req("POST", f"/admin/phone-changes/{rid}/approve")).status_code == 200
    me = (await p.req("GET", "/me")).json()
    assert me["phone"] == new and me["phone_verified"] is True
    db.expire_all()
    assert (await db.get(User, p.id)).phone_verified_by == sup.id


def test_production_never_runs_the_console_provider():
    base = {"environment": "production", "jwt_secret": "k" * 48}
    assert_production_safe(Settings(**base))  # empty means disabled in production
    assert_production_safe(Settings(**base, otp_provider="disabled"))
    with pytest.raises(RuntimeError, match="OTP_PROVIDER"):
        assert_production_safe(Settings(**base, otp_provider="console"))
    with pytest.raises(RuntimeError, match="OTP_PROVIDER"):
        assert_production_safe(Settings(**base, otp_provider="twilio"))


def test_the_default_provider_depends_on_the_environment(monkeypatch):
    monkeypatch.setattr(settings, "otp_provider", "")
    monkeypatch.setattr(settings, "environment", "development")
    assert otp.provider_name() == "console" and otp.enabled()
    monkeypatch.setattr(settings, "environment", "production")
    assert otp.provider_name() == "disabled" and not otp.enabled()


# ---------- bulk import and invites ----------
HEADER = "name,phone,team\n"


def csv_for(lg, rows):
    return HEADER + "\n".join(rows)


async def season_with_room(make_user):
    lg = await make_league(make_user, n_teams=2, per_team=2, n_umpires=1)  # Team1, Team2 each with 2 of 7
    return lg


async def test_the_preview_finds_every_problem_and_writes_nothing(make_user, db):
    lg = await season_with_room(make_user)
    taken = lg.players[lg.teams[0]][0].phone
    text = csv_for(lg, ["Asha Rao,+919811100001,Team1", "Bad Phone,12,Team1", "Nowhere,+919811100002,Ghosts", f"Already,{taken},Team1",
                        "Asha Again,+919811100001,Team2", ",+919811100003,Team1", "Rahul,+91 98111 00004,team2"])
    r = await lg.admin.req("POST", f"/admin/seasons/{lg.sid}/invites/preview", json={"csv": text})
    assert r.status_code == 200, r.text
    body = r.json()
    by = {x["line"]: x for x in body["rows"]}
    assert by[2]["ok"] and by[8]["ok"] and by[8]["phone"] == "+919811100004" and by[8]["team_id"] == lg.teams[1]  # spaces removed, team matched without case
    assert "Phone must be" in by[3]["errors"][0]
    assert "No team" in by[4]["errors"][0]
    assert "already has an account" in by[5]["errors"][0]
    assert "Same number as line 2" in by[6]["errors"][0]
    assert "Name is missing" in by[7]["errors"][0]
    assert (body["ok"], body["errors"]) == (2, 5)
    assert await db.scalar(select(func.count()).select_from(Invite)) == 0


async def test_unreadable_files_are_refused(make_user):
    lg = await season_with_room(make_user)

    async def prev(text):
        return await lg.admin.req("POST", f"/admin/seasons/{lg.sid}/invites/preview", json={"csv": text})

    assert (await prev("")).status_code == 422
    assert (await prev("name,phone\nA,+919800000001")).status_code == 422  # no team column
    assert (await prev(HEADER)).status_code == 422  # no players
    big = HEADER + "\n".join(f"P{i},+9198000{i:05d},Team1" for i in range(501))
    r = await prev(big)
    assert r.status_code == 422 and "Too many rows" in r.json()["detail"]
    assert (await prev("name,phone,team\n" + "A" * 300_000)).status_code == 422
    assert (await prev(HEADER + chr(0x202E) + "Evil,+919800000001,Team1")).json()["rows"][0]["errors"][0].startswith("Name contains")


async def test_formula_looking_names_are_stored_as_text_and_exports_defuse_them(make_user, db):
    lg = await season_with_room(make_user)
    r = await lg.admin.req("POST", f"/admin/seasons/{lg.sid}/invites", json={"csv": csv_for(lg, ['"=HYPERLINK(""http://x"")",+919822200001,Team1'])})
    assert r.status_code == 201 and len(r.json()["invites"]) == 1
    from app.routers.exports import cell

    assert cell(r.json()["invites"][0]["name"]).startswith("'=")


async def test_a_team_cannot_be_over_filled(make_user):
    lg = await season_with_room(make_user)  # 2 of 7 taken
    rows = [f"P{i},+9198333{i:05d},Team1" for i in range(6)]
    r = await lg.admin.req("POST", f"/admin/seasons/{lg.sid}/invites/preview", json={"csv": csv_for(lg, rows)})
    assert (r.json()["ok"], r.json()["errors"]) == (5, 1) and "more than 7" in r.json()["rows"][5]["errors"][0]


async def import_one(lg, name="Asha Rao", phone="+919844400001", team="Team1"):
    r = await lg.admin.req("POST", f"/admin/seasons/{lg.sid}/invites", json={"csv": csv_for(lg, [f"{name},{phone},{team}"])})
    assert r.status_code == 201, r.text
    return r.json()["invites"][0]


async def test_an_invite_makes_a_verified_player_on_the_team(make_user, db, client):
    lg = await season_with_room(make_user)
    inv = await import_one(lg)
    db.expire_all()
    row = await db.get(Invite, inv["id"])
    assert row.token_hash != inv["token"] and len(row.token_hash) == 64  # only a hash is stored
    look = await client.get(f"/invites/{inv['token']}")
    assert look.status_code == 200 and look.json() == {"name": "Asha Rao", "team": "Team1", "season": f"League{lg.admin.id}", "phone_ending": "01"}
    r = await client.post(f"/invites/{inv['token']}/accept", json={"email": "Asha@Example.com", "password": "a-long-password"})
    assert r.status_code == 201, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = (await client.get("/me", headers=h)).json()
    assert (me["name"], me["email"], me["phone"], me["phone_verified"]) == ("Asha Rao", "asha@example.com", "+919844400001", True)
    team = (await client.get(f"/teams/{lg.teams[0]}", headers=h)).json()
    assert any(m["user_id"] == me["id"] and m["status"] == "approved" for m in team["members"])
    db.expire_all()
    u = await db.get(User, me["id"])
    assert u.phone_verified_by == lg.admin.id
    assert (await client.post("/auth/login", json={"email": "asha@example.com", "password": "a-long-password"})).status_code == 200
    # the link is single use
    assert (await client.get(f"/invites/{inv['token']}")).status_code == 404
    again = await client.post(f"/invites/{inv['token']}/accept", json={"email": "other@example.com", "password": "a-long-password"})
    assert again.status_code == 404
    listed = (await lg.admin.req("GET", f"/admin/seasons/{lg.sid}/invites")).json()
    assert listed[0]["state"] == "used" and "token" not in listed[0]
    assert await db.scalar(select(AuditLog.id).where(AuditLog.action == "invite.accept"))


async def test_invites_expire_and_can_be_revoked_or_reissued(make_user, db, client):
    lg = await season_with_room(make_user)
    a, b, c = await import_one(lg, "A", "+919855500001"), await import_one(lg, "B", "+919855500002"), await import_one(lg, "C", "+919855500003")
    row = await db.get(Invite, a["id"])
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db.commit()
    body = {"email": "x@example.com", "password": "a-long-password"}
    assert (await client.post(f"/invites/{a['token']}/accept", json=body)).status_code == 404  # expired
    assert (await lg.admin.req("POST", f"/admin/invites/{b['id']}/revoke")).status_code == 204
    assert (await client.post(f"/invites/{b['token']}/accept", json=body)).status_code == 404  # revoked
    new = (await lg.admin.req("POST", f"/admin/invites/{a['id']}/reissue")).json()
    assert new["token"] != a["token"] and new["id"] != a["id"]
    assert (await client.post(f"/invites/{new['token']}/accept", json=body)).status_code == 201
    assert (await lg.admin.req("POST", f"/admin/invites/{new['id']}/revoke")).status_code == 409  # already used
    assert (await client.get("/invites/not-a-real-token")).status_code == 404
    states = {i["id"]: i["state"] for i in (await lg.admin.req("GET", f"/admin/seasons/{lg.sid}/invites")).json()}
    assert states[a["id"]] == "revoked" and states[b["id"]] == "revoked" and states[c["id"]] == "open" and states[new["id"]] == "used"
    # an invite cannot be reissued once its number has registered
    p = await client.post("/auth/register", json={"name": "C", "email": "c@example.com", "password": "a-long-password", "phone": "+919855500003"})
    assert p.status_code == 201
    assert (await lg.admin.req("POST", f"/admin/invites/{c['id']}/reissue")).status_code == 409


async def test_a_number_that_registered_meanwhile_or_an_email_in_use_is_refused_without_burning_the_link(make_user, db, client):
    lg = await season_with_room(make_user)
    inv = await import_one(lg)
    taken_email = lg.players[lg.teams[0]][0]
    r = await client.post(f"/invites/{inv['token']}/accept", json={"email": f"u{taken_email.id}@t.io", "password": "a-long-password"})
    assert r.status_code == 409
    assert (await client.get(f"/invites/{inv['token']}")).status_code == 200  # still usable
    await client.post("/auth/register", json={"name": "Someone", "email": "s@example.com", "password": "a-long-password", "phone": "+919844400001"})
    r = await client.post(f"/invites/{inv['token']}/accept", json={"email": "fresh@example.com", "password": "a-long-password"})
    assert r.status_code == 409


async def test_two_people_racing_for_one_link_only_one_gets_in(make_user, db, client):
    import asyncio

    lg = await season_with_room(make_user)
    inv = await import_one(lg)
    results = await asyncio.gather(*(client.post(f"/invites/{inv['token']}/accept", json={"email": f"r{i}@example.com", "password": "a-long-password"}) for i in range(4)))
    assert sorted(r.status_code for r in results).count(201) == 1


async def test_who_may_manage_invites(make_user, db):
    one, two = await season_with_room(make_user), await season_with_room(make_user)
    sup = await make_user("Super", roles=["super_admin"])
    sa = await make_user("SeasonAdmin")
    await sup.req("POST", f"/users/{sa.id}/roles", json={"role": "tournament_admin", "season_id": one.sid})
    inv = await import_one(two)
    csv = csv_for(one, ["Z,+919866600001,Team1"])
    assert (await sa.req("POST", f"/admin/seasons/{one.sid}/invites", json={"csv": csv})).status_code == 201
    for method, path, body in (("POST", f"/admin/seasons/{two.sid}/invites", {"csv": csv}), ("POST", f"/admin/seasons/{two.sid}/invites/preview", {"csv": csv}),
                               ("GET", f"/admin/seasons/{two.sid}/invites", None), ("POST", f"/admin/invites/{inv['id']}/revoke", None),
                               ("POST", f"/admin/invites/{inv['id']}/reissue", None)):
        assert (await sa.req(method, path, json=body)).status_code == 403, path
    plain = await make_user("Plain")
    assert (await plain.req("POST", f"/admin/seasons/{one.sid}/invites/preview", json={"csv": csv})).status_code == 403


async def test_nothing_can_be_imported_into_an_archived_season(make_user, db):
    lg = await season_with_room(make_user)
    r = await lg.admin.req("POST", f"/admin/seasons/{lg.sid}/archive", json={"reason": "season over"})
    if r.status_code in (200, 204):
        resp = await lg.admin.req("POST", f"/admin/seasons/{lg.sid}/invites/preview", json={"csv": csv_for(lg, ["A,+919877700001,Team1"])})
        assert resp.status_code == 409
