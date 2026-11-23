"""The public side under load: anonymous viewers on a live match, page traffic, and a push fan-out.

    # the server must run behind a proxy header so every simulated viewer has its own address:
    TRUST_PROXY=true AUTH_RATE_LIMITS_ENABLED=false uvicorn app.main:app --port 8010
    # for the push part, the server, this script and an arq worker all need PUSH_ENABLED=true PUSH_DRY_RUN=true
    DATABASE_URL=... python -m loadtest.public_load --viewers 200 --api http://localhost:8010 --push 500

What it checks:
- 200 anonymous sockets watch a match while it is played; each ends on the database's final sequence number
  and never goes backwards; polling viewers see a consistent, finished scorecard.
- Public page endpoints stay fast and error-free while that happens (standings, leaderboards, analytics, fixtures).
- One address cannot open more than the per-address socket limit.
- 500 devices all receive a notification through the worker, and none is lost.
"""

import argparse
import asyncio
import json
import secrets
import statistics
import time

import httpx
import websockets
from sqlalchemy import func, select

from app.core.config import settings
from app.db.models import BallEvent, Innings, Match, Notification, PushSubscription, Season, User
from app.db.session import SessionLocal
from loadtest.simulate import play_match
from loadtest.world import Stats, build_world, pct


def fake_ip(i: int) -> str:
    return f"10.{(i // 250) % 250}.{i % 250}.{(i * 7) % 250 + 1}"


async def viewer(i: int, ws_url: str, out: dict, ready: asyncio.Event, stop: asyncio.Event) -> None:
    """One anonymous visitor with a live socket."""
    try:
        async with websockets.connect(ws_url, additional_headers={"X-Forwarded-For": fake_ip(i)}, open_timeout=30) as ws:
            hello = json.loads(await ws.recv())
            out["seqs"] = [hello["seq"]]
            ready.set()
            while not stop.is_set():
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 0.5))
                except TimeoutError:
                    continue
                if m["type"] == "changed":
                    out["seqs"].append(m["seq"])
    except Exception as e:  # noqa: BLE001
        out["error"] = repr(e)
        ready.set()


async def reader(i: int, c: httpx.AsyncClient, paths: list[str], lat: dict[str, list[float]], errors: list[str], stop: asyncio.Event) -> None:
    """A visitor clicking around the public pages."""
    headers = {"X-Forwarded-For": fake_ip(10_000 + i)}
    n = 0
    while not stop.is_set():
        path = paths[(i + n) % len(paths)]
        n += 1
        t = time.perf_counter()
        try:
            r = await c.get(path, headers=headers)
            lat.setdefault(path.split("?")[0].rsplit("/", 1)[-1] or "root", []).append((time.perf_counter() - t) * 1000)
            if r.status_code >= 500 or r.status_code == 429:
                errors.append(f"{path} -> {r.status_code}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{path} -> {e!r}")
        await asyncio.sleep(1.5)


async def socket_cap_check(ws_url: str) -> str | None:
    """One address may only hold `public_ws_per_ip` sockets; the next is refused."""
    held = []
    try:
        for _ in range(settings.public_ws_per_ip):
            ws = await websockets.connect(ws_url, additional_headers={"X-Forwarded-For": "198.51.100.77"})
            await ws.recv()
            held.append(ws)
        extra = await websockets.connect(ws_url, additional_headers={"X-Forwarded-For": "198.51.100.77"})
        try:
            await asyncio.wait_for(extra.recv(), 5)
            return "an extra socket from one address was accepted"
        except websockets.ConnectionClosed as e:
            if e.rcvd is None or e.rcvd.code != 4429:
                return f"extra socket closed with {e.rcvd.code if e.rcvd else None}, expected 4429"
        return None
    finally:
        for ws in held:
            await ws.close()


async def push_fanout(n: int) -> tuple[list[str], float]:
    """n users with one device each, one notification to all of them, and wait for the worker to deliver."""
    from app.services.notify import notify
    from app.services.outbox import flush

    problems: list[str] = []
    if not settings.push_enabled:
        return ["push is not enabled in this process (PUSH_ENABLED=true PUSH_DRY_RUN=true), skipped"], 0.0
    tag = secrets.token_hex(4)
    async with SessionLocal() as db:
        users = [User(player_code=f"PL{tag}{i:05d}"[:16], name=f"Push {i}", email=f"pushload{tag}{i}@t.io", password_hash="x", status="active") for i in range(n)]
        db.add_all(users)
        await db.flush()
        for u in users:
            db.add(PushSubscription(user_id=u.id, endpoint=f"https://fcm.googleapis.com/fcm/send/load-{tag}-{u.id}", p256dh="p" * 87, auth="a" * 22))
        await db.commit()
        ids = [u.id for u in users]
        t0 = time.perf_counter()
        await notify(db, ids, "result", "Match result", "Aces won by 21 runs", {"link": "/matches/1"}, f"load:{tag}")
        await db.commit()
        await flush(db)  # queues one job per notification for the worker
    deadline = time.perf_counter() + 120
    done = 0
    while time.perf_counter() < deadline:
        async with SessionLocal() as db:
            done = await db.scalar(select(func.count()).select_from(PushSubscription).where(
                PushSubscription.user_id.in_(ids), PushSubscription.last_success_at.is_not(None))) or 0
        if done >= n:
            break
        await asyncio.sleep(0.5)
    took = time.perf_counter() - t0
    async with SessionLocal() as db:
        made = await db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id.in_(ids), Notification.dedupe_key == f"load:{tag}")) or 0
    if made != n:
        problems.append(f"{made} notifications created for {n} users")
    if done != n:
        problems.append(f"only {done} of {n} devices were pushed within 120 s (is the arq worker running with the same push settings?)")
    return problems, took


async def main(viewers: int, readers: int, api: str, push: int) -> int:
    st = Stats()
    ws_base = api.replace("http", "ws", 1)
    limits = httpx.Limits(max_connections=400, keepalive_expiry=2)
    async with httpx.AsyncClient(base_url=api, timeout=60, limits=limits) as c:
        print("building a league and one match...")
        w = await build_world(c, st, 1, label="Public")
        mid, ump, A, B, ta, tb = w["plans"][0]
        async with SessionLocal() as s:
            slug = await s.scalar(select(Season.slug).where(Season.id == w["season"]))
        ws_url = f"{ws_base}/ws/public/matches/{mid}"
        stop, ready = asyncio.Event(), [asyncio.Event() for _ in range(viewers)]
        outs: list[dict] = [{} for _ in range(viewers)]
        socks = [asyncio.create_task(viewer(i, ws_url, outs[i], ready[i], stop)) for i in range(viewers)]
        await asyncio.gather(*(e.wait() for e in ready))
        connected = sum(1 for o in outs if "seqs" in o)
        print(f"{connected} of {viewers} anonymous sockets connected")

        lat: dict[str, list[float]] = {}
        errors: list[str] = []
        paths = [f"/public/seasons/{slug}", f"/public/seasons/{slug}/standings", f"/public/seasons/{slug}/leaderboards",
                 f"/public/seasons/{slug}/fixtures", f"/public/seasons/{slug}/analytics", f"/public/matches/{mid}/live",
                 f"/public/matches/{mid}/analytics", f"/public/seasons/{slug}/rules", "/public/seasons", "/public/history"]
        readers_t = [asyncio.create_task(reader(i, c, paths, lat, errors, stop)) for i in range(readers)]

        print(f"playing the match with {connected} sockets and {readers} readers watching...")
        t0 = time.perf_counter()
        res = await play_match(c, st, mid, ump, A, B, ta, tb, 0, ws_base, False)
        wall = time.perf_counter() - t0
        await asyncio.sleep(2.0)  # let the last updates arrive
        cap_problem = await socket_cap_check(ws_url)
        stop.set()
        await asyncio.gather(*socks, *readers_t, return_exceptions=True)

        # what a visitor arriving now sees
        final = (await c.get(f"/public/matches/{mid}/live", headers={"X-Forwarded-For": "203.0.113.5"})).json()

    problems = list(st.errors) + errors[:10]
    async with SessionLocal() as s:
        seq = await s.scalar(select(Match.seq).where(Match.id == mid))
        inn_ids = list(await s.scalars(select(Innings.id).where(Innings.match_id == mid)))
        balls = await s.scalar(select(func.count()).select_from(BallEvent).where(BallEvent.innings_id.in_(inn_ids)))
    if balls != 84:
        problems.append(f"{balls} ball events, expected 84")
    if final["match"]["seq"] != seq or final["match"]["status"] != "completed":
        problems.append(f"a new visitor sees seq {final['match']['seq']} {final['match']['status']}, the database has {seq}")
    if res["live"]["match"]["status"] != "completed":
        problems.append("the match did not complete")
    behind = stuck = lost = 0
    for i, o in enumerate(outs):
        if "error" in o:
            lost += 1
            problems.append(f"viewer {i}: {o['error']}") if lost <= 5 else None
            continue
        seqs = o["seqs"]
        if seqs != sorted(seqs):
            problems.append(f"viewer {i}: sequence went backwards")
        if not seqs or seqs[-1] != seq:
            stuck += 1
        behind += len(seqs) < 5
    if stuck:
        problems.append(f"{stuck} viewers did not end on the final sequence number {seq}")
    if lost:
        problems.append(f"{lost} viewers could not connect or lost their socket")
    if cap_problem:
        problems.append(cap_problem)

    print(f"\nmatch played in {wall:.1f}s; final sequence {seq}; viewers saw between {min((len(o.get('seqs', [])) for o in outs), default=0)} and "
          f"{max((len(o.get('seqs', [])) for o in outs), default=0)} updates")
    print(f"{'public read':<22}{'n':>6}{'p50':>8}{'p95':>8}{'p99':>8}{'max':>8}   (ms)")
    allv: list[float] = []
    for k, v in sorted(lat.items()):
        allv += v
        print(f"{k:<22}{len(v):>6}{statistics.median(v):>8.0f}{pct(v, .95):>8.0f}{pct(v, .99):>8.0f}{max(v):>8.0f}")
    if allv:
        print(f"{'ALL':<22}{len(allv):>6}{statistics.median(allv):>8.0f}{pct(allv, .95):>8.0f}{pct(allv, .99):>8.0f}{max(allv):>8.0f}")
        if pct(allv, 0.95) > 1000:
            problems.append(f"public reads p95 {pct(allv, 0.95):.0f} ms is over one second")

    if push:
        print(f"\npush fan-out to {push} devices...")
        push_problems, took = await push_fanout(push)
        if took:
            print(f"{push} devices pushed in {took:.1f}s ({push / took:.0f} per second)")
        problems += push_problems

    print("\nPROBLEMS:" if problems else "\nOK: viewers in sync, reads fast, address limit enforced" + (", every device pushed" if push else ""))
    for p in problems:
        print(" -", p)
    return 1 if problems else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--viewers", type=int, default=200)
    ap.add_argument("--readers", type=int, default=40)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--push", type=int, default=0, help="also fan a notification out to this many devices")
    a = ap.parse_args()
    raise SystemExit(asyncio.run(main(a.viewers, a.readers, a.api, a.push)))
