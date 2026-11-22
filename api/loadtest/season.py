"""A whole season through the API: generate and publish a double round robin, play every match
(several at once), run the semi-finals and final, then read everything back and reconcile it.

    DATABASE_URL=... python -m loadtest.season --teams 6 --concurrency 6

Checks: every match has exactly the balls its result needs, the table survives a full rebuild from
the ball events unchanged, player runs add up to team runs, the champion is the final's winner, the
archive freezes the season, and the read endpoints stay fast with a season's worth of data.
"""

import argparse
import asyncio
import csv
import io
import statistics
import time
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import text

from app.create_admin import main as create_admin
from app.db.session import SessionLocal
from loadtest.world import PW, Stats, pct, register

BAT = [5, 6, 1, 2, 3, 4]
BOWL = [6, 5, 2, 1, 4, 3]  # never equal to BAT: 21 runs an over
WKT = list(BAT)  # equal to BAT: a wicket every ball


async def play(c: httpx.AsyncClient, st: Stats, admin: str, mid: int, ta: dict, tb: dict, outcome: str) -> None:
    """Admin umpires; players submit their own digits. outcome 'a': A wins by 21; 'b': B wins at once."""
    base = f"/matches/{mid}"
    post = lambda name, path, tok, **kw: st.call(c, name, "POST", f"{base}/{path}", tok, **kw)
    for t in (ta, tb):
        await st.call(c, "lineup", "PUT", f"{base}/lineup", admin, json={"team_id": t["id"], "user_ids": [p["id"] for p in t["players"]]})
    await post("toss", "toss/open", admin)
    await post("toss", "toss/winner", admin, json={"winner_team_id": ta["id"]})
    await post("toss", "toss/decision", ta["players"][0]["token"], json={"decision": "bat"})
    await post("toss", "toss/confirm", admin)
    await post("start", "start", admin)

    async def over(n: int, bat: dict, bowl: dict, bowl_digits: list[int]) -> None:
        bowler, batter = bowl["players"][(n - 1) % 4], bat["players"][(n - 1) % 4]
        await post("over", "overs/start", admin, json={"bowler_id": bowler["id"], "batter_id": batter["id"]}, expect=(201,))
        await post("over", "overs/current/signal", admin)
        await asyncio.gather(post("submit", "overs/current/submit", bowler["token"], json={"digits": bowl_digits}),
                             post("submit", "overs/current/submit", batter["token"], json={"digits": BAT}))
        for step in ("lock", "reveal", "resolve"):
            await post("over", f"overs/current/{step}", admin)

    if outcome == "a":
        await over(1, ta, tb, BOWL)
        await over(2, ta, tb, WKT)
        await over(3, ta, tb, WKT)
    else:
        await over(1, ta, tb, WKT)
        await over(2, ta, tb, WKT)
    await post("innings", "innings/next", admin)
    if outcome == "b":
        await over(1, tb, ta, BOWL)
    else:
        await over(1, tb, ta, WKT)
        await over(2, tb, ta, WKT)


async def main(n_teams: int, api: str, concurrency: int, reads: int) -> int:
    st = Stats()
    t0 = time.perf_counter()
    async with httpx.AsyncClient(base_url=api, timeout=120, limits=httpx.Limits(max_connections=60, keepalive_expiry=2)) as c:
        prefix = f"season{int(time.time())}"
        admin_email = f"{prefix}root@t.io"
        await create_admin(admin_email, PW, "Season Admin")
        admin = (await c.post("/auth/login", json={"email": admin_email, "password": PW})).json()["access_token"]
        season = (await st.call(c, "setup", "POST", "/seasons", admin, json={"name": f"Season {prefix}", "status": "active"})).json()["id"]
        users = await asyncio.gather(*[register(c, st, prefix, i, "P") for i in range(n_teams * 4 + 3)])
        async with SessionLocal() as s:
            await s.execute(text("update users set phone_verified=true where email like :p"), {"p": f"{prefix}%"})
            await s.commit()
        for u in users[-3:]:
            await st.call(c, "setup", "POST", f"/users/{u['id']}/roles", admin, json={"role": "umpire"})
        teams = []
        for i in range(n_teams):
            players = users[i * 4:(i + 1) * 4]
            tid = (await st.call(c, "setup", "POST", f"/seasons/{season}/teams", admin, json={"name": f"Team {i + 1}"})).json()["id"]
            for p in players:
                await st.call(c, "setup", "POST", f"/teams/{tid}/members", admin, json={"user_id": p["id"]})
            await st.call(c, "setup", "PATCH", f"/teams/{tid}", admin, json={"captain_id": players[0]["id"]})
            teams.append({"id": tid, "players": players})
        by_id = {t["id"]: t for t in teams}
        print(f"setup done in {time.perf_counter() - t0:.1f}s")

        start = (datetime.now(UTC) + timedelta(days=1)).date().isoformat()
        gen = await st.call(c, "fixtures", "POST", f"/seasons/{season}/fixtures/generate", admin,
                            json={"start_date": start, "times": ["10:00", "13:00", "16:00", "19:00"], "legs": 2, "parallel": 3})
        await st.call(c, "fixtures", "POST", f"/seasons/{season}/fixtures/publish", admin, json={})
        fx = (await st.call(c, "fixtures", "GET", f"/seasons/{season}/fixtures", admin)).json()
        print(f"{len(fx)} league matches generated and published ({gen.status_code})")

        sem = asyncio.Semaphore(concurrency)
        results = ["a", "b"]  # alternate winners so the table is varied

        async def one(i: int, f: dict) -> None:
            async with sem:
                await play(c, st, admin, f["id"], by_id[f["team_a"]["id"]], by_id[f["team_b"]["id"]], results[i % 2])

        t1 = time.perf_counter()
        await asyncio.gather(*[one(i, f) for i, f in enumerate(fx)])
        print(f"{len(fx)} league matches played in {time.perf_counter() - t1:.1f}s")

        table = (await c.get(f"/seasons/{season}/standings", headers={"Authorization": f"Bearer {admin}"})).json()
        assert table["league_complete"], table["pending_matches"]
        await st.call(c, "knockouts", "POST", f"/seasons/{season}/knockouts/generate", admin,
                      json={"first_at": (datetime.now(UTC) + timedelta(days=30)).isoformat()})
        bracket = (await c.get(f"/seasons/{season}/bracket", headers={"Authorization": f"Bearer {admin}"})).json()
        for m in bracket["matches"]:
            await play(c, st, admin, m["id"], by_id[m["team_a"]["id"]], by_id[m["team_b"]["id"]], "a")
        bracket = (await c.get(f"/seasons/{season}/bracket", headers={"Authorization": f"Bearer {admin}"})).json()
        final = next(m for m in bracket["matches"] if m["round_label"] == "Final")
        await play(c, st, admin, final["id"], by_id[final["team_a"]["id"]], by_id[final["team_b"]["id"]], "a")
        bracket = (await c.get(f"/seasons/{season}/bracket", headers={"Authorization": f"Bearer {admin}"})).json()
        problems: list[str] = []
        champion = bracket["champion"]
        if not champion or champion["id"] != final["team_a"]["id"]:
            problems.append(f"champion {champion} is not the final's winner (team {final['team_a']['id']})")

        # --- reconcile ---
        before = (await c.get(f"/seasons/{season}/standings", headers={"Authorization": f"Bearer {admin}"})).json()["rows"]
        rebuilt = (await st.call(c, "rebuild", "POST", "/admin/results/rebuild", admin, json={"season_id": season})).json()["rebuilt"]
        after = (await c.get(f"/seasons/{season}/standings", headers={"Authorization": f"Bearer {admin}"})).json()["rows"]
        if before != after:
            problems.append("table changed after a full rebuild from the ball events")
        players_csv = list(csv.DictReader(io.StringIO((await st.call(c, "export", "GET", f"/seasons/{season}/export/players.csv", admin)).text)))
        player_runs = sum(int(r["runs"]) for r in players_csv)
        async with SessionLocal() as s:
            row = (await s.execute(text(
                "select coalesce(sum(coalesce(r.a_runs,0)+coalesce(r.b_runs,0)),0), count(*) from match_results r "
                "join matches m on m.id = r.match_id where m.season_id = :s and r.result_type in ('normal','tie')"), {"s": season})).one()
            balls = (await s.execute(text(
                "select m.id, count(*) from matches m join innings i on i.match_id=m.id join ball_events b on b.innings_id=i.id "
                "where m.season_id=:s group by m.id having count(*) not in (20, 8)"), {"s": season})).all()
        if player_runs != int(row[0]):
            problems.append(f"player runs {player_runs} != ledger runs {row[0]}")
        if int(row[1]) != len(fx) + 3:
            problems.append(f"{row[1]} counted results, expected {len(fx) + 3}")
        print(f"rebuilt {rebuilt} results; player runs {player_runs} == ledger runs {row[0]}; champion {champion and champion['name']}")

        # --- read performance with a season's data ---
        timed = {"standings": f"/seasons/{season}/standings", "leaderboards": f"/seasons/{season}/leaderboards",
                 "fixtures": f"/seasons/{season}/fixtures", "player": f"/players/{users[0]['id']}/stats",
                 "team": f"/teams/{teams[0]['id']}/stats", "history": "/history",
                 "audit": "/admin/audit?limit=50", "players.csv": f"/seasons/{season}/export/players.csv"}
        for _ in range(reads):
            await asyncio.gather(*[st.call(c, f"read:{k}", "GET", u, admin) for k, u in timed.items()])

        # --- archive freezes it ---
        arch = await st.call(c, "archive", "POST", f"/seasons/{season}/archive", admin)
        late = await c.post(f"/seasons/{season}/adjustments", headers={"Authorization": f"Bearer {admin}"},
                            json={"team_id": teams[0]["id"], "points": 1, "reason": "after archive"})
        if arch.status_code != 200 or late.status_code != 409:
            problems.append(f"archive {arch.status_code}, write after archive {late.status_code} (expected 200 and 409)")
        hist = (await c.get("/history", headers={"Authorization": f"Bearer {admin}"})).json()
        if not any(h["season"]["id"] == season and h["champion"] for h in hist):
            problems.append("archived season missing from history or has no champion")
        if balls:
            problems.append(f"matches with an unexpected number of balls: {balls[:3]}")

    wall = time.perf_counter() - t0
    reads_ms = {k: v for k, v in st.lat.items() if k.startswith("read:")}
    print(f"\nwhole run {wall:.1f}s; read endpoints with a full season (ms):")
    print(f"{'endpoint':<20}{'n':>5}{'p50':>8}{'p95':>8}{'max':>8}")
    for k, v in sorted(reads_ms.items()):
        print(f"{k[5:]:<20}{len(v):>5}{statistics.median(v):>8.0f}{pct(v, .95):>8.0f}{max(v):>8.0f}")
    slow = [k for k, v in reads_ms.items() if pct(v, .95) > 1500]
    if slow:
        problems.append(f"slow reads (p95 > 1.5s): {slow}")
    problems += st.errors[:10]
    print("\nPROBLEMS:" if problems else "\nOK: no problems")
    for p in problems:
        print(" -", p)
    return 1 if problems else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--teams", type=int, default=6)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--reads", type=int, default=10)
    a = ap.parse_args()
    raise SystemExit(asyncio.run(main(a.teams, a.api, a.concurrency, a.reads)))
