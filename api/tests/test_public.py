import json

import websockets
from sqlalchemy import select

from app.core.config import settings
from app.db.models import Season
from tests.helpers import (
    BAT,
    BOWL_NO_EQUAL,
    League,
    make_league,
    new_match,
    play_match,
    run_toss,
    setup_match,
    start,
)
from tests.ws_helpers import closed_with, recv


async def league(make_user, per_team=4) -> League:
    return await make_league(make_user, n_teams=4, per_team=per_team, n_umpires=2)


async def slug_of(lg: League) -> str:
    return (await lg.admin.req("GET", f"/seasons/{lg.sid}")).json()["slug"]


async def get(client, path, **kw):
    r = await client.get(path, **kw)
    assert r.status_code == 200, (path, r.status_code, r.text)
    return r.json()


# ---------- seasons, slugs, visibility ----------
async def test_season_list_overview_and_slugs(make_user, client):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    slug = await slug_of(lg)
    assert slug.startswith("league")
    await play_match(lg, await new_match(lg, a, b), "a")
    listed = await get(client, "/public/seasons")
    assert [s["slug"] for s in listed] == [slug] and listed[0]["teams"] == 4 and listed[0]["matches"] == 1
    ov = await get(client, f"/public/seasons/{slug}")
    assert ov["season"]["slug"] == slug and ov["live"] == [] and ov["next"] == []
    assert ov["latest"][0]["result"].endswith("won by 21 runs") and ov["latest"][0]["team_a"]["name"] == "Team1"
    assert ov["table"][0]["team"]["name"] == "Team1" and ov["table"][0]["points"] == 2
    assert [r["value"] for r in ov["leaders"]["most_runs"]] == [21]


async def test_draft_and_hidden_seasons_are_not_public(make_user, client):
    lg = await league(make_user)
    slug = await slug_of(lg)
    draft = (await lg.admin.req("POST", "/seasons", json={"name": "Next Year", "status": "draft"})).json()
    assert draft["is_public"] is False and draft["slug"] == "next-year"
    assert (await client.get("/public/seasons/next-year")).status_code == 404
    assert [s["slug"] for s in await get(client, "/public/seasons")] == [slug]
    # going live makes it public; an admin can hide it again
    assert (await lg.admin.req("PATCH", f"/seasons/{draft['id']}", json={"status": "active"})).json()["is_public"] is True
    assert (await client.get("/public/seasons/next-year")).status_code == 200
    assert (await lg.admin.req("PATCH", f"/seasons/{draft['id']}", json={"is_public": False})).json()["is_public"] is False
    assert (await client.get("/public/seasons/next-year")).status_code == 404
    assert (await client.get("/public/seasons/nope")).status_code == 404
    assert (await lg.players[lg.teams[0]][0].req("PATCH", f"/seasons/{lg.sid}", json={"is_public": False})).status_code == 403


async def test_slug_rules(make_user, client):
    lg = await league(make_user)
    one = (await lg.admin.req("POST", "/seasons", json={"name": "FFCL Season 24!", "status": "active"})).json()
    assert one["slug"] == "ffcl-season-24"
    two = (await lg.admin.req("POST", "/seasons", json={"name": "ffcl season 24?", "status": "active"})).json()
    assert two["slug"] == "ffcl-season-24-2"
    hist = (await lg.admin.req("POST", "/seasons", json={"name": "History", "status": "active"})).json()
    assert hist["slug"] == "history-season"  # "history" is a page of its own
    r = await lg.admin.req("PATCH", f"/seasons/{two['id']}", json={"slug": "ffcl-season-24"})
    assert r.status_code == 409
    assert (await lg.admin.req("PATCH", f"/seasons/{two['id']}", json={"slug": "Bad Slug"})).status_code == 422
    assert (await lg.admin.req("PATCH", f"/seasons/{two['id']}", json={"slug": "admin"})).status_code == 422
    ok = await lg.admin.req("PATCH", f"/seasons/{two['id']}", json={"slug": "s24b", "name": "Renamed"})
    assert ok.json()["slug"] == "s24b"
    renamed = await lg.admin.req("PATCH", f"/seasons/{one['id']}", json={"name": "Another name"})
    assert renamed.json()["slug"] == "ffcl-season-24"  # renaming never breaks the address
    assert (await client.get("/public/seasons/s24b")).status_code == 200


# ---------- same numbers as the signed-in API ----------
async def test_public_numbers_match_the_signed_in_ones(make_user, client):
    lg = await league(make_user)
    a, b, c, d = lg.teams
    for x, y, o in ((a, b, "a"), (c, d, "b"), (a, c, "a")):
        await play_match(lg, await new_match(lg, x, y), o)
    slug = await slug_of(lg)
    assert await get(client, f"/public/seasons/{slug}/standings") == (await lg.admin.req("GET", f"/seasons/{lg.sid}/standings")).json()
    signed = {c_["key"]: c_["rows"] for c_ in (await lg.admin.req("GET", f"/seasons/{lg.sid}/leaderboards")).json()["categories"]}
    pub = {c_["key"]: c_["rows"] for c_ in (await get(client, f"/public/seasons/{slug}/leaderboards"))["categories"]}
    for key, rows in signed.items():
        assert [(r["rank"], r["value"], r["detail"]) for r in pub[key]] == [(r["rank"], r["value"], r["detail"]) for r in rows], key
    assert [m["id"] for m in await get(client, f"/public/seasons/{slug}/fixtures?status=completed")] == \
           [m["id"] for m in (await lg.admin.req("GET", f"/seasons/{lg.sid}/fixtures?status=completed")).json()]
    assert (await get(client, f"/public/seasons/{slug}/bracket"))["matches"] == []
    rules = await get(client, f"/public/seasons/{slug}/rules")
    assert any("7 overs" in i for s in rules["sections"] for i in s["items"])
    assert (await client.get(f"/public/seasons/{slug}/fixtures?status=bogus")).status_code == 422


# ---------- privacy ----------
async def test_players_can_hide_their_name_and_suspended_players_vanish(make_user, client):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    pa, pb = lg.players[a], lg.players[b]
    mid = await new_match(lg, a, b)
    await play_match(lg, mid, "a")
    slug = await slug_of(lg)
    me = (await pa[0].req("GET", "/me")).json()
    assert me["show_publicly"] is True
    assert (await pa[0].req("PATCH", "/me", json={"show_publicly": None})).json()["show_publicly"] is True  # null is ignored
    assert (await pa[0].req("PATCH", "/me", json={"show_publicly": False})).json()["show_publicly"] is False

    top = (await get(client, f"/public/seasons/{slug}/leaderboards"))["categories"][0]["rows"][0]
    assert top["player"]["id"] is None and top["player"]["name"] == me["player_code"] and top["value"] == 21
    assert (await client.get(f"/public/players/{pa[0].id}?season={slug}")).status_code == 404  # no page for them
    live = await get(client, f"/public/matches/{mid}/live")
    bat = live["innings"][0]["batting"]
    assert bat[0]["id"] is None and bat[0]["name"] == me["player_code"]
    assert me["name"] not in json.dumps(live)
    team = await get(client, f"/public/teams/{a}")
    assert all(m["player"]["name"] != me["name"] for m in team["members"]) and any(m["player"]["id"] is None for m in team["members"])

    # a visible player has a page, with a season and a history
    page = await get(client, f"/public/players/{pa[1].id}?season={slug}")
    assert page["player"]["id"] == pa[1].id and page["season"]["slug"] == slug and page["other_seasons"] == []
    assert page["totals"]["matches"] == 1 and page["history"][0]["match_id"] == mid
    assert (await client.get(f"/public/players/{pa[1].id}")).status_code == 422  # a season is required
    assert (await client.get(f"/public/players/999999?season={slug}")).status_code == 404

    # suspended: gone from rankings, rosters and pages
    sa = await make_user("Super", roles=["super_admin"])
    assert (await sa.req("PUT", f"/users/{pb[1].id}/status", json={"status": "suspended"})).status_code == 204
    rows = (await get(client, f"/public/seasons/{slug}/leaderboards"))["categories"][1]["rows"]
    assert pb[1].id not in {r["player"]["id"] for r in rows} and all(r["player"] for r in rows)
    assert (await client.get(f"/public/players/{pb[1].id}?season={slug}")).status_code == 404
    roster = await get(client, f"/public/teams/{b}")
    assert pb[1].id not in {m["player"]["id"] for m in roster["members"]}
    assert pb[1].id not in {p["player"]["id"] for p in roster["players"] if p["player"]}


async def test_nothing_private_in_any_public_response(make_user, client):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    mid = await new_match(lg, a, b)
    await play_match(lg, mid, "a")
    await lg.admin.req("PUT", f"/matches/{mid}/potm", json={"user_id": lg.players[a][0].id})
    await lg.admin.req("POST", f"/matches/{await new_match(lg, lg.teams[2], lg.teams[3])}/abandon", json={"reason": "somebody's injury details"})
    slug = await slug_of(lg)
    await lg.admin.req("PATCH", f"/seasons/{lg.sid}", json={"status": "completed"})
    paths = ["/public/seasons", f"/public/seasons/{slug}", f"/public/seasons/{slug}/fixtures", f"/public/seasons/{slug}/standings",
             f"/public/seasons/{slug}/bracket", f"/public/seasons/{slug}/leaderboards", f"/public/seasons/{slug}/rules",
             "/public/history", f"/public/teams/{a}", f"/public/players/{lg.players[a][1].id}?season={slug}",
             f"/public/matches/{mid}", f"/public/matches/{mid}/live", "/public/sitemap"]
    forbidden_keys = {"email", "phone", "phone_verified", "password", "password_hash", "token", "access_token",
                      "refresh_token", "mine", "avatar_url", "umpire_id", "created_by"}
    blob = ""
    for p in paths:
        data = await get(client, p)
        text = json.dumps(data)
        blob += text

        def walk(x, path=p):
            if isinstance(x, dict):
                leaked = {k for k in x if k in forbidden_keys and x[k] is not None}
                assert not leaked, (path, leaked)
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)

        walk(data)
    assert "@t.io" not in blob and "+9199000" not in blob  # no emails or phone numbers in any form
    assert "injury" not in blob  # free-text reasons stay inside the league


# ---------- live view ----------
async def test_digits_stay_hidden_until_the_reveal(make_user, client):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    u = ctx.ump
    r = await u.req("POST", f"{ctx.url}/overs/start", json={"bowler_id": bowlers[0].id, "batter_id": batters[0].id})
    assert r.status_code == 201
    await u.req("POST", f"{ctx.url}/overs/current/signal")
    await bowlers[0].req("POST", f"{ctx.url}/overs/current/submit", json={"digits": BOWL_NO_EQUAL})

    async def public_over():
        live = await get(client, f"/public/matches/{ctx.match}/live")
        assert live["you"] == {"official": False} and live["match"]["umpire_id"] is None
        return live["over"]

    o = await public_over()
    assert o["state"] == "submissions_open" and o["submitted"] == {"bat": False, "bowl": True}
    assert o["digits"] is None and "mine" not in o and o["bowler_id"] is None and o["bowler"] and o["batter"]
    await batters[0].req("POST", f"{ctx.url}/overs/current/submit", json={"digits": BAT})
    await u.req("POST", f"{ctx.url}/overs/current/lock")
    o = await public_over()
    assert o["state"] == "locked" and o["digits"] is None  # even locked: the umpire sees them, the public does not
    assert (await u.req("GET", f"{ctx.url}/live")).json()["over"]["digits"] is not None
    await u.req("POST", f"{ctx.url}/overs/current/reveal")
    o = await public_over()
    assert o["state"] == "revealed" and o["digits"] == {"bat": BAT, "bowl": BOWL_NO_EQUAL}  # the same as any spectator


async def test_abandoned_reason_stays_private(make_user, client):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    mid = await new_match(lg, a, b)
    await lg.admin.req("POST", f"/matches/{mid}/abandon", json={"reason": "a player was hurt"})
    live = await get(client, f"/public/matches/{mid}/live")
    assert live["match"]["result"] == "Match abandoned" and live["match"]["declared"]["reason"] is None
    signed = (await lg.admin.req("GET", f"/matches/{mid}/live")).json()["match"]
    assert "a player was hurt" in signed["result"] and signed["declared"]["reason"] == "a player was hurt"
    slug = await slug_of(lg)
    fx = await get(client, f"/public/seasons/{slug}/fixtures?status=completed")
    assert fx[0]["result"] == "Match abandoned"


async def test_drafts_and_unknown_matches_are_hidden(make_user, client):
    lg = await league(make_user)
    slug = await slug_of(lg)
    gen = await lg.admin.req("POST", f"/seasons/{lg.sid}/fixtures/generate",
                             json={"start_date": "2031-02-01", "times": ["19:00"], "timezone": "UTC"})
    draft = gen.json()["match_ids"][0]
    for path in (f"/public/matches/{draft}", f"/public/matches/{draft}/live", "/public/matches/999999"):
        assert (await client.get(path)).status_code == 404
    assert await get(client, f"/public/seasons/{slug}/fixtures") == []
    assert (await get(client, "/public/sitemap"))["matches"] == []
    await lg.admin.req("POST", f"/seasons/{lg.sid}/fixtures/publish", json={})
    assert len(await get(client, f"/public/seasons/{slug}/fixtures")) == 6
    assert (await client.get(f"/public/matches/{draft}")).status_code == 200
    await lg.admin.req("PATCH", f"/seasons/{lg.sid}", json={"is_public": False})  # hiding the season hides its matches
    assert (await client.get(f"/public/matches/{draft}")).status_code == 404


async def test_signed_in_users_can_use_the_public_api_too(make_user, client):
    lg = await league(make_user)
    r = await lg.players[lg.teams[0]][0].req("GET", "/public/seasons")
    assert r.status_code == 200 and len(r.json()) == 1
    assert (await client.get("/seasons")).status_code == 401  # the signed-in API still needs a login


# ---------- sitemap ----------
async def test_sitemap(make_user, client):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    mid = await new_match(lg, a, b)
    await play_match(lg, mid, "a")
    await lg.players[a][0].req("PATCH", "/me", json={"show_publicly": False})
    sa = await make_user("Super", roles=["super_admin"])
    assert (await sa.req("PUT", f"/users/{lg.players[b][0].id}/status", json={"status": "suspended"})).status_code == 204
    sm = await get(client, "/public/sitemap")
    slug = await slug_of(lg)
    assert sm["seasons"] == [slug] and {t["id"] for t in sm["teams"]} == set(lg.teams) and sm["matches"] == [{"id": mid, "season": slug}]
    ids = {p["id"] for p in sm["players"]}
    assert lg.players[a][1].id in ids and lg.players[a][0].id not in ids and lg.players[b][0].id not in ids


# ---------- abuse protection ----------
async def test_rate_limit_and_cache_headers(make_user, client, monkeypatch):
    lg = await league(make_user)
    slug = await slug_of(lg)
    monkeypatch.setattr(settings, "public_rate_limit_per_minute", 4)
    for _ in range(4):
        r = await client.get(f"/public/seasons/{slug}/standings")
        assert r.status_code == 200
    assert "max-age=10" in r.headers["cache-control"] and "public" in r.headers["cache-control"]
    assert (await client.get(f"/public/seasons/{slug}/standings")).status_code == 429
    monkeypatch.setattr(settings, "public_rate_limit_per_minute", 0)
    mid = await new_match(lg, lg.teams[0], lg.teams[1])
    assert "max-age=2" in (await client.get(f"/public/matches/{mid}/live")).headers["cache-control"]


async def test_shared_cache_serves_repeat_reads_and_live_follows_the_sequence(make_user, client, monkeypatch):
    monkeypatch.setattr(settings, "public_cache_enabled", True)
    lg = await league(make_user)
    a, b, c, d = lg.teams
    slug = await slug_of(lg)
    await play_match(lg, await new_match(lg, a, b), "a")
    first = await get(client, f"/public/seasons/{slug}")
    await play_match(lg, await new_match(lg, c, d), "a")
    assert (await get(client, f"/public/seasons/{slug}")) == first  # still the cached copy
    # the live view is keyed by the match's sequence number, so a change shows at once
    mid = await new_match(lg, a, c)
    for t in (a, c):
        await lg.admin.req("PUT", f"/matches/{mid}/lineup", json={"team_id": t, "user_ids": [p.id for p in lg.players[t]]})
    before = (await get(client, f"/public/matches/{mid}/live"))["match"]
    assert (await lg.admin.req("POST", f"/matches/{mid}/toss/open")).status_code == 204
    after = (await get(client, f"/public/matches/{mid}/live"))["match"]
    assert after["seq"] > before["seq"] and after["status"] == "toss"


async def test_history_is_public_only_and_respects_privacy(make_user, client):
    lg = await league(make_user)
    a, b, *_ = lg.teams
    await play_match(lg, await new_match(lg, a, b), "a")
    await lg.admin.req("PATCH", f"/seasons/{lg.sid}", json={"status": "completed"})
    await lg.players[a][0].req("PATCH", "/me", json={"show_publicly": False})
    h = await get(client, "/public/history")
    assert len(h) == 1 and h[0]["table"][0]["team"] == "Team1"
    assert h[0]["top_batter"]["player"]["id"] is None  # shown by player code only
    assert h[0]["season"]["slug"] == await slug_of(lg)
    await lg.admin.req("PATCH", f"/seasons/{lg.sid}", json={"is_public": False})
    assert await get(client, "/public/history") == []


# ---------- anonymous live socket ----------
async def test_public_socket_streams_only_sequence_numbers(make_user, ws_url):
    ctx = await setup_match(make_user)
    ws = await websockets.connect(f"{ws_url}/ws/public/matches/{ctx.match}")  # no token, no first message
    hello = await recv(ws)
    assert hello["type"] == "hello" and isinstance(hello["seq"], int)
    await ctx.ump.req("POST", f"{ctx.url}/toss/open")
    while True:
        msg = await recv(ws)
        if msg["type"] == "changed":
            break
    assert set(msg) == {"type", "seq"} and msg["seq"] > hello["seq"]
    await ws.close()


async def test_public_socket_refuses_drafts_and_caps_each_address(make_user, ws_url, monkeypatch):
    lg = await league(make_user)
    gen = await lg.admin.req("POST", f"/seasons/{lg.sid}/fixtures/generate",
                             json={"start_date": "2031-02-01", "times": ["19:00"], "timezone": "UTC"})
    draft = gen.json()["match_ids"][0]
    assert await closed_with(f"{ws_url}/ws/public/matches/{draft}") == 4404
    assert await closed_with(f"{ws_url}/ws/public/matches/999999") == 4404
    await lg.admin.req("POST", f"/seasons/{lg.sid}/fixtures/publish", json={})
    monkeypatch.setattr(settings, "public_ws_per_ip", 2)
    first = await websockets.connect(f"{ws_url}/ws/public/matches/{draft}")
    second = await websockets.connect(f"{ws_url}/ws/public/matches/{draft}")
    assert (await recv(first))["type"] == "hello" and (await recv(second))["type"] == "hello"
    assert await closed_with(f"{ws_url}/ws/public/matches/{draft}") == 4429  # the third from this address
    await first.close()
    import asyncio
    await asyncio.sleep(0.3)  # the slot is released when the socket closes
    third = await websockets.connect(f"{ws_url}/ws/public/matches/{draft}")
    assert (await recv(third))["type"] == "hello"
    await second.close()
    await third.close()


async def test_seasons_table_has_slug_for_every_row(db):
    rows = list(await db.scalars(select(Season.slug)))
    assert all(rows)
