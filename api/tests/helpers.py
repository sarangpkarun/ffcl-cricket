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


@dataclass
class League:
    admin: object
    teams: list  # team ids
    players: dict  # team id -> [actors]
    umpires: list  # neutral umpire actors (no team)
    sid: int


async def make_league(make_user, n_teams=4, per_team=2, n_umpires=3, name="League") -> League:
    admin = await make_user("Admin", roles=["tournament_admin"])
    sid = (await admin.req("POST", "/seasons", json={"name": f"{name}{admin.id}", "status": "active"})).json()["id"]
    teams, players = [], {}
    for i in range(n_teams):
        tid = (await admin.req("POST", f"/seasons/{sid}/teams", json={"name": f"Team{i + 1}"})).json()["id"]
        teams.append(tid)
        players[tid] = [await make_user(f"T{i + 1}P") for _ in range(per_team)]
        for p in players[tid]:
            r = await admin.req("POST", f"/teams/{tid}/members", json={"user_id": p.id})
            assert r.status_code == 201, r.text
        await admin.req("PATCH", f"/teams/{tid}", json={"captain_id": players[tid][0].id})
    umpires = [await make_user("Ump", roles=["umpire"]) for _ in range(n_umpires)]
    return League(admin, teams, players, umpires, sid)


async def play_match(lg: League, match_id: int, outcome: str, official=None) -> Ctx:
    """Play an existing match to the end through the API, quickly, with the admin as the official.

    Team A wins the toss and bats first. Outcomes (A = the match's first team, B = the second):
      "a"   A scores 21 then is all out; B is all out for 0          -> A wins by 21 runs
      "b"   A is all out for 0; B scores 5 off the first ball        -> B wins by 7 wickets (chase over in one ball)
      "tie" both sides are all out for 0                              -> tied
    """
    official = official or lg.admin
    m = (await lg.admin.req("GET", f"/matches/{match_id}")).json()
    ta, tb = m["team_a_id"], m["team_b_id"]
    ctx = Ctx(lg.admin, official, lg.players[ta], lg.players[tb], ta, tb, match_id, lg.sid)
    for tid, pl in ((ta, lg.players[ta]), (tb, lg.players[tb])):
        if not any(p["team_id"] == tid for p in m["lineup"]):
            r = await lg.admin.req("PUT", f"/matches/{match_id}/lineup", json={"team_id": tid, "user_ids": [p.id for p in pl]})
            assert r.status_code == 200, r.text
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    if outcome == "a":
        await play(ctx, batters, bowlers, 1)
        await play(ctx, batters, bowlers, 2, bowl_digits=BOWL_ALL_EQUAL)
        await play(ctx, batters, bowlers, 3, bowl_digits=BOWL_ALL_EQUAL)
    else:
        await play(ctx, batters, bowlers, 1, bowl_digits=BOWL_ALL_EQUAL)
        await play(ctx, batters, bowlers, 2, bowl_digits=BOWL_ALL_EQUAL)
    await official.req("POST", f"{ctx.url}/innings/next")
    if outcome == "b":
        await play(ctx, bowlers, batters, 1)
    else:
        await play(ctx, bowlers, batters, 1, bowl_digits=BOWL_ALL_EQUAL)
        await play(ctx, bowlers, batters, 2, bowl_digits=BOWL_ALL_EQUAL)
    return ctx


async def new_match(lg: League, ta: int, tb: int, umpire=None) -> int:
    ump = umpire or lg.umpires[0]
    r = await lg.admin.req("POST", f"/seasons/{lg.sid}/matches", json={"team_a_id": ta, "team_b_id": tb, "umpire_id": ump.id})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def play_league(lg: League, results: list[tuple[int, int, str]]) -> list[int]:
    """Create and play several matches: (team A, team B, outcome) each. Returns the match ids."""
    ids = []
    for ta, tb, outcome in results:
        mid = await new_match(lg, ta, tb)
        await play_match(lg, mid, outcome)
        ids.append(mid)
    return ids
