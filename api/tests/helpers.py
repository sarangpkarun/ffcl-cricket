"""Drive a whole match through the HTTP API."""

from dataclasses import dataclass, field

BAT = [5, 6, 1, 2, 3, 4]
BOWL_NO_EQUAL = [6, 5, 2, 1, 4, 3]  # never matches BAT -> 21 runs per over
BOWL_ALL_EQUAL = list(BAT)  # matches every ball -> 6 wickets per over


@dataclass
class Ctx:
    admin: object
    ump: object
    a: list  # team A players (index 0 is captain)
    b: list
    team_a: int
    team_b: int
    match: int
    sid: int
    extra: dict = field(default_factory=dict)

    @property
    def url(self):
        return f"/matches/{self.match}"


async def setup_match(make_user, players_per_team=4, lineups=True) -> Ctx:
    admin = await make_user("Admin", roles=["tournament_admin"])
    ump = await make_user("Ump", roles=["umpire"])
    sid = (await admin.req("POST", "/seasons", json={"name": f"S{ump.id}", "status": "active"})).json()["id"]
    ta = (await admin.req("POST", f"/seasons/{sid}/teams", json={"name": "Pink"})).json()["id"]
    tb = (await admin.req("POST", f"/seasons/{sid}/teams", json={"name": "Green"})).json()["id"]
    a = [await make_user("A") for _ in range(players_per_team)]
    b = [await make_user("B") for _ in range(players_per_team)]
    for tid, pl in ((ta, a), (tb, b)):
        for p in pl:
            r = await admin.req("POST", f"/teams/{tid}/members", json={"user_id": p.id})
            assert r.status_code == 201, r.text
        r = await admin.req("PATCH", f"/teams/{tid}", json={"captain_id": pl[0].id})
        assert r.status_code == 200, r.text
    m = await admin.req("POST", f"/seasons/{sid}/matches",
                        json={"team_a_id": ta, "team_b_id": tb, "umpire_id": ump.id})
    assert m.status_code == 201, m.text
    ctx = Ctx(admin, ump, a, b, ta, tb, m.json()["id"], sid)
    if lineups:
        for tid, pl in ((ta, a), (tb, b)):
            r = await pl[0].req("PUT", f"{ctx.url}/lineup", json={"team_id": tid, "user_ids": [p.id for p in pl]})
            assert r.status_code == 200, r.text
    return ctx


async def run_toss(ctx: Ctx, winner="a", decision="bat"):
    """Team A (Pink) wins the toss by default. Returns (batting_first_players, bowling_first_players)."""
    u = ctx.ump
    assert (await u.req("POST", f"{ctx.url}/toss/open")).status_code == 204
    wt = ctx.team_a if winner == "a" else ctx.team_b
    wc = ctx.a[0] if winner == "a" else ctx.b[0]
    assert (await u.req("POST", f"{ctx.url}/toss/winner", json={"winner_team_id": wt})).status_code == 204
    assert (await wc.req("POST", f"{ctx.url}/toss/decision", json={"decision": decision})).status_code == 204
    assert (await u.req("POST", f"{ctx.url}/toss/confirm")).status_code == 204
    win_players, lose_players = (ctx.a, ctx.b) if winner == "a" else (ctx.b, ctx.a)
    return (win_players, lose_players) if decision == "bat" else (lose_players, win_players)


async def start(ctx: Ctx):
    assert (await ctx.ump.req("POST", f"{ctx.url}/start")).status_code == 204


async def play(ctx: Ctx, batters, bowlers, over_no, bat_digits=BAT, bowl_digits=BOWL_NO_EQUAL, expect=200):
    """Run one full over. Bowler rotates through the bowling lineup."""
    u = ctx.ump
    bowler = bowlers[(over_no - 1) % len(bowlers)]
    batter = batters[(over_no - 1) % len(batters)]
    r = await u.req("POST", f"{ctx.url}/overs/start", json={"bowler_id": bowler.id, "batter_id": batter.id})
    assert r.status_code == 201, r.text
    assert (await u.req("POST", f"{ctx.url}/overs/current/signal")).status_code == 204
    r = await bowler.req("POST", f"{ctx.url}/overs/current/submit", json={"digits": bowl_digits})
    assert r.status_code == 200, r.text
    r = await batter.req("POST", f"{ctx.url}/overs/current/submit", json={"digits": bat_digits})
    assert r.status_code == 200, r.text
    assert (await u.req("POST", f"{ctx.url}/overs/current/lock")).status_code == 204
    assert (await u.req("POST", f"{ctx.url}/overs/current/reveal")).status_code == 204
    r = await u.req("POST", f"{ctx.url}/overs/current/resolve")
    assert r.status_code == expect, r.text
    return r.json()


async def live(ctx: Ctx, who=None):
    return (await (who or ctx.ump).req("GET", f"{ctx.url}/live")).json()
