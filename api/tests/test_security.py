"""Regression tests for the Sprint 8 security review (see docs/SECURITY.md)."""

import pytest

from app.core.config import Settings, assert_production_safe
from app.core.config import settings as app_settings
from tests.helpers import run_toss, setup_match, start


@pytest.fixture
def limits_on(monkeypatch):
    monkeypatch.setattr(app_settings, "auth_rate_limits_enabled", True)


# ---------- privacy ----------
async def test_user_search_never_exposes_contact_details(make_user):
    me, other = await make_user("Me"), await make_user("Other")
    rows = (await me.req("GET", "/users?q=Other")).json()
    assert [r["id"] for r in rows] == [other.id]
    assert set(rows[0]) == {"id", "name", "player_code"}  # no email, phone or status
    assert "@" not in str(rows) and other.phone not in str(rows)


async def test_team_and_match_views_do_not_expose_contact_details(make_user):
    ctx = await setup_match(make_user)
    team = (await ctx.a[1].req("GET", f"/teams/{ctx.team_a}")).json()
    match = (await ctx.a[1].req("GET", f"/matches/{ctx.match}")).json()
    live = (await ctx.a[1].req("GET", f"/matches/{ctx.match}/live")).json()
    for payload in (team, match, live):
        text = str(payload)
        assert "@t.io" not in text and "+9199" not in text  # emails and phones from the test fixtures


# ---------- privilege ----------
async def test_only_a_super_admin_can_hand_out_admin_roles(make_user):
    ta = await make_user("TA", roles=["tournament_admin"])
    sa = await make_user("SA", roles=["super_admin"])
    p = await make_user("P")
    for role in ("tournament_admin", "super_admin"):
        r = await ta.req("POST", f"/users/{p.id}/roles", json={"role": role})
        assert r.status_code == 403, role
    assert (await ta.req("POST", f"/users/{p.id}/roles", json={"role": "umpire"})).status_code == 204
    assert (await sa.req("POST", f"/users/{p.id}/roles", json={"role": "tournament_admin"})).status_code == 204
    assert "tournament_admin" in (await p.req("GET", "/me")).json()["roles"]


async def test_players_cannot_use_admin_endpoints(make_user):
    p = await make_user("P")
    for method, url in (("GET", "/admin/users"), ("GET", "/admin/reports"), ("GET", "/admin/mutes")):
        assert (await p.req(method, url)).status_code == 403, url
    assert (await p.req("POST", f"/users/{p.id}/roles", json={"role": "tournament_admin"})).status_code == 403
    assert (await p.req("PUT", f"/users/{p.id}/status", json={"status": "active"})).status_code == 403


# ---------- brute force ----------
async def test_login_is_rate_limited_per_account_and_per_address(make_user, client, limits_on):
    u = await make_user("Victim")
    email = f"u{u.id}@t.io"  # make_user's naming scheme
    bad = {"email": email, "password": "wrong-password"}
    codes = [(await client.post("/auth/login", json=bad)).status_code for _ in range(12)]
    assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]
    # once locked, even the right password is refused until the window passes
    assert (await client.post("/auth/login", json={"email": email, "password": "password123"})).status_code == 429
    # a different account from the same address is still allowed
    other = await make_user("Other")
    assert (await client.post("/auth/login", json={"email": f"u{other.id}@t.io", "password": "password123"})).status_code == 200


async def test_registration_and_otp_requests_are_rate_limited(make_user, client, monkeypatch):
    me = await make_user("Texter")  # registered while the limits are still off
    monkeypatch.setattr(app_settings, "auth_rate_limits_enabled", True)
    codes = []
    for i in range(14):
        r = await client.post("/auth/register", json={
            "name": f"R{i}", "email": f"burst{i}@t.io", "password": "password123", "phone": f"+9188000{i:05d}"})
        codes.append(r.status_code)
    assert codes.count(201) == 10 and codes[-1] == 429
    codes = [(await me.req("POST", "/auth/otp/request", json={"phone": me.phone})).status_code for _ in range(5)]
    assert codes[:3] == [204, 204, 204] and codes[3:] == [429, 429]


async def test_unknown_email_costs_the_same_work_as_a_known_one(client, monkeypatch):
    """Otherwise response time reveals which emails have accounts."""
    calls = []
    from app.routers import auth

    real = auth.verify_password_async

    async def spy(pw, hashed):
        calls.append(hashed)
        return await real(pw, hashed)

    monkeypatch.setattr(auth, "verify_password_async", spy)
    r = await client.post("/auth/login", json={"email": "nobody@t.io", "password": "whatever123"})
    assert r.status_code == 401 and len(calls) == 1


# ---------- input limits ----------
async def test_free_text_and_digit_fields_are_bounded(make_user):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    await ctx.ump.req("POST", f"{ctx.url}/overs/start", json={"bowler_id": bowlers[0].id, "batter_id": batters[0].id})
    await ctx.ump.req("POST", f"{ctx.url}/overs/current/signal")
    long = "x" * 501
    sub = f"{ctx.url}/overs/current/submit"
    assert (await bowlers[0].req("POST", sub, json={"digits": list(range(1, 7)) * 5000})).status_code == 422
    assert (await bowlers[0].req("POST", sub, json={"digits": "1" * 5000})).status_code == 422
    assert (await ctx.ump.req("POST", f"{ctx.url}/penalties", json={
        "team_id": ctx.team_a, "kind": "k_breach", "runs": 1, "reason": long, "idempotency_key": "long-reason-1"})).status_code == 422
    assert (await ctx.ump.req("POST", f"{ctx.url}/overs/current/override", json={
        "role": "bat", "digits": "561234", "reason": long})).status_code == 422
    assert (await ctx.ump.req("POST", f"{ctx.url}/balls/correct", json={
        "innings_number": 1, "over_no": 1, "ball_no": 1, "batter_digit": 1, "bowler_digit": 2, "reason": long})).status_code == 422
    assert (await ctx.ump.req("POST", f"{ctx.url}/penalties/1/void", json={"reason": long})).status_code == 422
    # emoji digits still fit comfortably
    assert (await bowlers[0].req("POST", sub, json={"digits": "1️⃣1️⃣2️⃣2️⃣3️⃣4️⃣"})).status_code == 200


async def test_avatar_must_be_a_web_url(make_user):
    p = await make_user("P")
    for bad in ("javascript:alert(1)", "data:text/html;base64,AAAA", "ftp://x/y.png", "//evil.test/x.png"):
        assert (await p.req("PATCH", "/me", json={"avatar_url": bad})).status_code == 422, bad
    ok = await p.req("PATCH", "/me", json={"avatar_url": "https://cdn.example.com/me.png"})
    assert ok.status_code == 200 and ok.json()["avatar_url"] == "https://cdn.example.com/me.png"


# ---------- deployment ----------
def test_production_refuses_the_development_secret():
    dev = Settings(environment="production")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        assert_production_safe(dev)
    assert_production_safe(Settings(environment="production", jwt_secret="k" * 48, auth_rate_limits_enabled=True))
    assert_production_safe(Settings(environment="development"))  # the dev default is fine in development
    with pytest.raises(RuntimeError, match="rate limits"):
        assert_production_safe(Settings(environment="production", jwt_secret="k" * 48, auth_rate_limits_enabled=False))
