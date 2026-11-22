"""Load/consistency test: many matches played end to end at once against a running API.

    DATABASE_URL=... REDIS_URL=... uv run python -m loadtest.simulate --matches 10 --watchers 3

Needs the stack running (`make up`, `make migrate`). Creates its own users/season, prefixed
`load<timestamp>`. Exits non-zero if anything is inconsistent.
"""

import argparse
import asyncio
import json
import statistics
import time
from collections import defaultdict

import httpx
import websockets
from sqlalchemy import func, select, text

from app.create_admin import main as create_admin
from app.db.models import BallEvent, Innings, Match
from app.db.session import SessionLocal

PW = "password123"
BAT = "561234"
BOWL = "652143"  # never equals BAT on any ball: 21 runs per over
BOWL_WKT = "652144"  # last ball equals the batter's 4: a wicket


class Stats:
    def __init__(self) -> None:
        self.lat: dict[str, list[float]] = defaultdict(list)
        self.errors: list[str] = []
        self.expected_conflicts = 0

    async def call(self, c: httpx.AsyncClient, name: str, method: str, url: str, token: str,
                   expect: tuple[int, ...] = (200, 201, 204), **kw) -> httpx.Response:
        t = time.perf_counter()
        r = await c.request(method, url, headers={"Authorization": f"Bearer {token}"}, **kw)
        self.lat[name].append((time.perf_counter() - t) * 1000)
        if r.status_code not in expect:
            self.errors.append(f"{name} {r.status_code} {r.text[:120]}")
        return r


def pct(xs: list[float], p: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, int(len(s) * p))]


async def watcher(url: str, token: str, ready: asyncio.Event, out: dict) -> None:
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"type": "auth", "token": token}))
        hello = json.loads(await ws.recv())
        out["seqs"] = [hello["seq"]]
        ready.set()
        try:
            while True:
                m = json.loads(await ws.recv())
                if m["type"] == "changed":
                    out["seqs"].append(m["seq"])
        except websockets.ConnectionClosed:
            return


async def register(c: httpx.AsyncClient, st: Stats, prefix: str, n: int, label: str) -> dict:
    email = f"{prefix}{n}@t.io"
    r = await st.call(c, "register", "POST", "/auth/register", "x", json={
        "name": f"{label}{n}", "email": email, "password": PW, "phone": f"+9188{prefix[-6:]}{n:04d}"})
    tok = r.json()["access_token"]
    me = (await c.get("/me", headers={"Authorization": f"Bearer {tok}"})).json()
    return {"id": me["id"], "token": tok, "email": email}


async def play_match(c: httpx.AsyncClient, st: Stats, mid: int, ump: dict, A: list, B: list,
                     team_a: int, team_b: int, watchers: int, ws_base: str, chaos: bool) -> dict:
    u = ump["token"]
    base = f"/matches/{mid}"
    post = lambda name, path, tok, **kw: st.call(c, name, "POST", f"{base}/{path}", tok, **kw)

    ready = [asyncio.Event() for _ in range(watchers)]
    wouts: list[dict] = [{} for _ in range(watchers)]
    wtasks = [asyncio.create_task(watcher(f"{ws_base}/ws/matches/{mid}", A[i % 4]["token"], ready[i], wouts[i]))
              for i in range(watchers)]
    await asyncio.gather(*(e.wait() for e in ready))

    await post("toss", "toss/open", u)
    await post("toss", "toss/winner", u, json={"winner_team_id": team_a})
    await post("toss", "toss/decision", A[0]["token"], json={"decision": "bat"})
    await post("toss", "toss/confirm", u)
    await post("start", "start", u)

    for innings, (bat_team, bowl_team) in enumerate(((A, B), (B, A)), start=1):
        if innings == 2:
            await post("innings", "innings/next", u)
        for over in range(1, 8):
            bowler, batter = bowl_team[(over - 1) % 4], bat_team[(over - 1) % 4]
            await post("over_start", "overs/start", u, json={"bowler_id": bowler["id"], "batter_id": batter["id"]}, expect=(201,))
            await post("signal", "overs/current/signal", u)
            bowl_digits = BOWL_WKT if (innings == 2 and over == 1) else BOWL
            subs = [post("submit", "overs/current/submit", bowler["token"], json={"digits": bowl_digits}),
                    post("submit", "overs/current/submit", batter["token"], json={"digits": BAT})]
            if chaos:  # duplicate submits racing the real ones must be idempotent (same digits => 200)
                subs.append(post("submit_dup", "overs/current/submit", bowler["token"], json={"digits": bowl_digits}))
            await asyncio.gather(*subs)
            await post("lock", "overs/current/lock", u)
            await post("reveal", "overs/current/reveal", u)
            if chaos:  # 4 simultaneous resolves: exactly one may win
                rs = await asyncio.gather(*[post("resolve", "overs/current/resolve", u, expect=(200, 409)) for _ in range(4)])
                wins = sum(r.status_code == 200 for r in rs)
                st.expected_conflicts += len(rs) - wins
                if wins != 1:
                    st.errors.append(f"match {mid} over {over}: {wins} resolves succeeded")
            else:
                await post("resolve", "overs/current/resolve", u)
    live = (await st.call(c, "live", "GET", f"{base}/live", u)).json()
    await asyncio.sleep(0.5)  # let the final notifications arrive
    for t in wtasks:
        t.cancel()
    return {"live": live, "watchers": [w["seqs"] for w in wouts]}


async def main(n_matches: int, watchers: int, api: str, chaos: bool) -> int:
    prefix = f"load{int(time.time())}"
    admin_email = f"{prefix}root@t.io"
    await create_admin(admin_email, PW, "Load Admin")
    st = Stats()
    limits = httpx.Limits(max_connections=200, keepalive_expiry=2)  # < uvicorn's 5s keep-alive
    async with httpx.AsyncClient(base_url=api, timeout=60, limits=limits) as c:
        admin = (await c.post("/auth/login", json={"email": admin_email, "password": PW})).json()["access_token"]
        season = (await st.call(c, "setup", "POST", "/seasons", admin, json={"name": f"Load {prefix}", "status": "active"})).json()["id"]
        print(f"registering {n_matches * 9} users...")
        users = await asyncio.gather(*[register(c, st, prefix, i, "P") for i in range(n_matches * 9)])
        async with SessionLocal() as s:
            await s.execute(text("update users set phone_verified=true where email like :p"), {"p": f"{prefix}%"})
            await s.commit()
        plans = []
        for i in range(n_matches):
            chunk = users[i * 9:(i + 1) * 9]
            ump, A, B = chunk[0], chunk[1:5], chunk[5:9]
            await st.call(c, "setup", "POST", f"/users/{ump['id']}/roles", admin, json={"role": "umpire"})
            tids = []
            for name, players in ((f"Pink{i}", A), (f"Green{i}", B)):
                t = (await st.call(c, "setup", "POST", f"/seasons/{season}/teams", admin, json={"name": name})).json()["id"]
                for p in players:
                    await st.call(c, "setup", "POST", f"/teams/{t}/members", admin, json={"user_id": p["id"]})
                await st.call(c, "setup", "PATCH", f"/teams/{t}", admin, json={"captain_id": players[0]["id"]})
                tids.append(t)
            m = (await st.call(c, "setup", "POST", f"/seasons/{season}/matches", admin,
                               json={"team_a_id": tids[0], "team_b_id": tids[1], "umpire_id": ump["id"]})).json()["id"]
            for tid, players in ((tids[0], A), (tids[1], B)):
                await st.call(c, "setup", "PUT", f"/matches/{m}/lineup", admin, json={"team_id": tid, "user_ids": [p["id"] for p in players]})
            plans.append((m, ump, A, B, tids[0], tids[1]))

        print(f"playing {n_matches} matches at once ({watchers} websocket watchers each, chaos={chaos})...")
        ws_base = api.replace("http", "ws", 1)
        t0 = time.perf_counter()
        results = await asyncio.gather(*[play_match(c, st, m, ump, A, B, ta, tb, watchers, ws_base, chaos)
                                         for (m, ump, A, B, ta, tb) in plans])
        wall = time.perf_counter() - t0

    problems = list(st.errors)
    async with SessionLocal() as s:
        for (m, *_), res in zip(plans, results, strict=True):
            live = res["live"]
            i1, i2 = live["innings"]
            if (i1["runs"], i2["runs"], live["match"]["status"]) != (147, 143, "completed"):
                problems.append(f"match {m}: unexpected {i1['runs']}/{i2['runs']} {live['match']['status']}")
            if not (live["match"]["result"] or "").endswith("won by 4 runs"):
                problems.append(f"match {m}: result {live['match']['result']!r}")
            inn_ids = list(await s.scalars(select(Innings.id).where(Innings.match_id == m)))
            n_balls = await s.scalar(select(func.count()).select_from(BallEvent).where(BallEvent.innings_id.in_(inn_ids)))
            if n_balls != 84:
                problems.append(f"match {m}: {n_balls} ball events, expected 84")
            seq = await s.scalar(select(Match.seq).where(Match.id == m))
            for k, seqs in enumerate(res["watchers"]):
                if not seqs or seqs[-1] != seq:
                    problems.append(f"match {m} watcher {k}: last seq {seqs[-1] if seqs else None}, db has {seq}")
                if seqs != sorted(seqs):
                    problems.append(f"match {m} watcher {k}: sequence went backwards")

    allv = [x for v in st.lat.values() for x in v]
    print(f"\n{len(allv)} requests in {wall:.1f}s  ({len(allv) / wall:.0f} req/s)  conflicts expected: {st.expected_conflicts}")
    print(f"{'endpoint':<12}{'n':>6}{'p50':>8}{'p95':>8}{'p99':>8}{'max':>8}   (ms)")
    for k, v in sorted(st.lat.items()):
        print(f"{k:<12}{len(v):>6}{statistics.median(v):>8.0f}{pct(v, .95):>8.0f}{pct(v, .99):>8.0f}{max(v):>8.0f}")
    print(f"{'ALL':<12}{len(allv):>6}{statistics.median(allv):>8.0f}{pct(allv, .95):>8.0f}{pct(allv, .99):>8.0f}{max(allv):>8.0f}")
    if problems:
        print(f"\nFAILED: {len(problems)} problem(s)")
        for p in problems[:25]:
            print(" -", p)
        return 1
    print(f"\nOK: {n_matches} matches completed, 84 balls each, no duplicates, all watchers in sync")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches", type=int, default=10)
    ap.add_argument("--watchers", type=int, default=3)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--no-chaos", action="store_true")
    a = ap.parse_args()
    raise SystemExit(asyncio.run(main(a.matches, a.watchers, a.api, not a.no_chaos)))
