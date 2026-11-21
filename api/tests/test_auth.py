import logging

from app.core.security import sha256


async def reg(client, email="a@t.io", phone="+919900000001"):
    return await client.post(
        "/auth/register",
        json={"name": "A", "email": email, "password": "password123", "phone": phone},
    )


async def test_register_login_me(client):
    r = await reg(client)
    assert r.status_code == 201
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = (await client.get("/me", headers=h)).json()
    assert me["player_code"].startswith("FFP") and me["roles"] == ["player"]
    assert me["phone_verified"] is False
    r = await client.post("/auth/login", json={"email": "A@T.io", "password": "password123"})
    assert r.status_code == 200


async def test_duplicate_email_and_phone(client):
    await reg(client)
    assert (await reg(client, phone="+919900000002")).status_code == 409
    assert (await reg(client, email="b@t.io")).status_code == 409


async def test_bad_credentials_and_missing_token(client):
    await reg(client)
    r = await client.post("/auth/login", json={"email": "a@t.io", "password": "wrongpass1"})
    assert r.status_code == 401
    assert (await client.get("/me")).status_code == 401


async def test_refresh_rotates_and_old_token_dies(client):
    tok = (await reg(client)).json()
    r = await client.post("/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert r.status_code == 200
    again = await client.post("/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert again.status_code == 401


async def test_logout_all_kills_every_session(client):
    t1 = (await reg(client)).json()
    t2 = (await client.post("/auth/login", json={"email": "a@t.io", "password": "password123"})).json()
    h1 = {"Authorization": f"Bearer {t1['access_token']}"}
    h2 = {"Authorization": f"Bearer {t2['access_token']}"}
    assert (await client.post("/auth/logout-all", headers=h1)).status_code == 204
    assert (await client.get("/me", headers=h1)).status_code == 401
    assert (await client.get("/me", headers=h2)).status_code == 401


async def test_otp_flow(client, caplog):
    tok = (await reg(client)).json()
    h = {"Authorization": f"Bearer {tok['access_token']}"}
    with caplog.at_level(logging.WARNING, logger="ffcl.otp"):
        r = await client.post("/auth/otp/request", json={"phone": "+919900000001"}, headers=h)
    assert r.status_code == 204
    code = caplog.records[-1].args[1]
    bad = await client.post("/auth/otp/verify", json={"phone": "+919900000001", "code": "000000" if code != "000000" else "111111"}, headers=h)
    assert bad.status_code == 400
    ok = await client.post("/auth/otp/verify", json={"phone": "+919900000001", "code": code}, headers=h)
    assert ok.status_code == 204
    assert (await client.get("/me", headers=h)).json()["phone_verified"] is True


async def test_otp_rejects_other_number(client):
    tok = (await reg(client)).json()
    h = {"Authorization": f"Bearer {tok['access_token']}"}
    r = await client.post("/auth/otp/request", json={"phone": "+919911111111"}, headers=h)
    assert r.status_code == 400


async def test_otp_lockout_after_max_attempts(client, caplog):
    tok = (await reg(client)).json()
    h = {"Authorization": f"Bearer {tok['access_token']}"}
    with caplog.at_level(logging.WARNING, logger="ffcl.otp"):
        await client.post("/auth/otp/request", json={"phone": "+919900000001"}, headers=h)
    code = caplog.records[-1].args[1]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        await client.post("/auth/otp/verify", json={"phone": "+919900000001", "code": wrong}, headers=h)
    r = await client.post("/auth/otp/verify", json={"phone": "+919900000001", "code": code}, headers=h)
    assert r.status_code == 400  # locked out even with the right code


async def test_suspended_user_is_locked_out(client, make_user):
    admin = await make_user("Root", roles=["super_admin"])
    victim = await make_user("Vic")
    r = await admin.req("PUT", f"/users/{victim.id}/status", json={"status": "suspended"})
    assert r.status_code == 204
    assert (await client.get("/me", headers=victim.h)).status_code == 401
    r = await client.post("/auth/login", json={"email": "u2@t.io", "password": "password123"})
    assert r.status_code == 403


async def test_only_super_admin_grants_super_admin(make_user):
    ta = await make_user("TA", roles=["tournament_admin"])
    p = await make_user("P")
    r = await ta.req("POST", f"/users/{p.id}/roles", json={"role": "super_admin"})
    assert r.status_code == 403
    r = await ta.req("POST", f"/users/{p.id}/roles", json={"role": "umpire"})
    assert r.status_code == 204
    r = await ta.req("POST", f"/users/{p.id}/roles", json={"role": "umpire"})  # idempotent
    assert r.status_code == 204
    me = (await p.req("GET", "/me")).json()
    assert me["roles"].count("umpire") == 1
    assert sha256("x")  # keep import used
