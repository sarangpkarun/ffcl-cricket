"""Build a league (season, teams, players, umpires, matches) against a running API.

Shared by the load tests and by manual checks:
    DATABASE_URL=... python -m loadtest.world --matches 2 --start-in 9
"""

import argparse
import asyncio
import statistics
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import text

from app.create_admin import main as create_admin
from app.db.session import SessionLocal

PW = "password123"


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


async def register(c: httpx.AsyncClient, st: Stats, prefix: str, n: int, label: str) -> dict:
    email = f"{prefix}{n}@t.io"
    r = await st.call(c, "register", "POST", "/auth/register", "x", json={
        "name": f"{label}{n}", "email": email, "password": PW, "phone": f"+9188{prefix[-6:]}{n:04d}"})
    tok = r.json()["access_token"]
    me = (await c.get("/me", headers={"Authorization": f"Bearer {tok}"})).json()
    return {"id": me["id"], "token": tok, "email": email}


async def build_world(c: httpx.AsyncClient, st: Stats, n_matches: int, label: str = "Load",
                      start_in_minutes: int | None = None) -> dict:
    """Create n_matches matches of 4 v 4 with a captain each and an umpire, lineups set.

    Returns {"prefix", "admin", "season", "plans"} where each plan is
    (match_id, umpire, team_a_players, team_b_players, team_a_id, team_b_id).
    """
    prefix = f"{label.lower()}{int(time.time())}"
    admin_email = f"{prefix}root@t.io"
    await create_admin(admin_email, PW, f"{label} Admin")
    admin = (await c.post("/auth/login", json={"email": admin_email, "password": PW})).json()["access_token"]
    season = (await st.call(c, "setup", "POST", "/seasons", admin, json={"name": f"{label} {prefix}", "status": "active"})).json()["id"]
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
        body = {"team_a_id": tids[0], "team_b_id": tids[1], "umpire_id": ump["id"]}
        if start_in_minutes is not None:
            body["scheduled_at"] = (datetime.now(UTC) + timedelta(minutes=start_in_minutes)).isoformat()
        m = (await st.call(c, "setup", "POST", f"/seasons/{season}/matches", admin, json=body)).json()["id"]
        for tid, players in ((tids[0], A), (tids[1], B)):
            await st.call(c, "setup", "PUT", f"/matches/{m}/lineup", admin, json={"team_id": tid, "user_ids": [p["id"] for p in players]})
        plans.append((m, ump, A, B, tids[0], tids[1]))
    return {"prefix": prefix, "admin": admin, "season": season, "plans": plans}


def report(st: Stats, wall: float) -> list[float]:
    allv = [x for v in st.lat.values() for x in v]
    print(f"\n{len(allv)} requests in {wall:.1f}s  ({len(allv) / wall:.0f} req/s)  conflicts expected: {st.expected_conflicts}")
    print(f"{'endpoint':<12}{'n':>6}{'p50':>8}{'p95':>8}{'p99':>8}{'max':>8}   (ms)")
    for k, v in sorted(st.lat.items()):
        print(f"{k:<12}{len(v):>6}{statistics.median(v):>8.0f}{pct(v, .95):>8.0f}{pct(v, .99):>8.0f}{max(v):>8.0f}")
    print(f"{'ALL':<12}{len(allv):>6}{statistics.median(allv):>8.0f}{pct(allv, .95):>8.0f}{pct(allv, .99):>8.0f}{max(allv):>8.0f}")
    return allv


async def _cli(n: int, api: str, start_in: int | None) -> None:
    st = Stats()
    async with httpx.AsyncClient(base_url=api, timeout=60, limits=httpx.Limits(keepalive_expiry=2)) as c:
        w = await build_world(c, st, n, label="Manual", start_in_minutes=start_in)
    print(f"season {w['season']}; prefix {w['prefix']}")
    for m, ump, A, B, *_ in w["plans"]:
        print(f"match {m}: umpire {ump['email']} / players {A[0]['email']} {B[0]['email']} (password {PW})")
    if st.errors:
        print("ERRORS:", st.errors[:5])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches", type=int, default=1)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--start-in", type=int, default=None, help="schedule each match this many minutes from now")
    a = ap.parse_args()
    asyncio.run(_cli(a.matches, a.api, a.start_in))
