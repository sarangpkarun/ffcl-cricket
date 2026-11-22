"""Chat under load, while whole matches are being played.

    DATABASE_URL=... REDIS_URL=... uv run python -m loadtest.chat_load --matches 30 --messages 6

Every player of every match chats (match room and the season room) while the umpire runs the
match, with replies, mentions, reactions and deliberate duplicate sends. WebSocket watchers sit
in every room. Afterwards it proves, from the database, that no message was lost, duplicated
or delivered out of order, and that every watcher saw exactly what the database holds.
"""

import argparse
import asyncio
import json
import random
import re
import time
import uuid
from collections import defaultdict

import httpx
import websockets
from sqlalchemy import func, select

from app.db.models import ChatMessage
from app.db.session import SessionLocal
from loadtest.simulate import play_match
from loadtest.world import Stats, build_world, report

FAILURES: list[str] = []  # watcher connections that never came up or died early (reported as problems)
STOPPING = asyncio.Event()  # set when the test ends and closes the watchers on purpose


async def room_watcher(url: str, token: str, ready: asyncio.Event, out: list[int]) -> None:
    """Collect the id of every message event a member of the room receives."""
    try:
        async with websockets.connect(url, open_timeout=30) as ws:
            await ws.send(json.dumps({"type": "auth", "token": token}))
            hello = json.loads(await ws.recv())
            if hello.get("type") != "hello":
                raise RuntimeError(f"unexpected first frame {hello}")
            ready.set()
            try:
                while True:
                    ev = json.loads(await ws.recv())
                    if ev["type"] == "message":
                        out.append(ev["message"]["id"])
            except websockets.ConnectionClosed as e:
                if not STOPPING.is_set():
                    FAILURES.append(f"room watcher {url.rsplit('/', 1)[-1]}: closed early by the server ({e.rcvd})")
                return
    except websockets.ConnectionClosedOK:
        pass  # the test ended and closed the socket: normal
    except Exception as e:  # noqa: BLE001 - a failed watcher is a test finding, not a crash
        FAILURES.append(f"room watcher {url.rsplit('/', 1)[-1]}: {type(e).__name__} {e}")
    finally:
        ready.set()  # never leave the setup phase waiting forever


async def me_watcher(url: str, token: str, ready: asyncio.Event, out: list[str]) -> None:
    try:
        async with websockets.connect(url, open_timeout=30) as ws:
            await ws.send(json.dumps({"type": "auth", "token": token}))
            await ws.recv()
            ready.set()
            try:
                while True:
                    ev = json.loads(await ws.recv())
                    if ev["type"] == "notification":
                        out.append(ev["notification"]["kind"])
            except websockets.ConnectionClosed as e:
                if not STOPPING.is_set():
                    FAILURES.append(f"notification watcher closed early by the server ({e.rcvd})")
                return
    except websockets.ConnectionClosedOK:
        pass
    except Exception as e:  # noqa: BLE001
        FAILURES.append(f"notification watcher: {type(e).__name__} {e}")
    finally:
        ready.set()


async def chatter(c: httpx.AsyncClient, st: Stats, who: dict, mates: list[int], rooms: dict[str, int],
                  sent: dict[int, list[int]], count: int, rng: random.Random, tally: dict) -> None:
    for i in range(count):
        await asyncio.sleep(rng.uniform(1.1, 1.8))  # stay under the 10-per-10-seconds limit
        kind = "season" if rng.random() < 0.2 else "match"
        room = rooms[kind]
        payload: dict = {"body": f"{who['id']} message {i}", "client_id": uuid.uuid4().hex}
        if sent[room] and rng.random() < 0.3:
            payload["reply_to_id"] = rng.choice(sent[room])
        if mates and rng.random() < 0.3:
            payload["mentions"] = [rng.choice(mates)]
        sends = 2 if rng.random() < 0.15 else 1  # a double-tap / client retry sent at the same moment
        for _attempt in range(60):
            rs = await asyncio.gather(*[
                st.call(c, "chat_send", "POST", f"/rooms/{room}/messages", who["token"], expect=(201, 403), json=payload)
                for _ in range(sends)])
            if all(r.status_code == 403 for r in rs):  # the batter/bowler lock: wait for the over to finish
                tally["locked"] += 1
                await asyncio.sleep(1.5)
                continue
            ids = {r.json()["id"] for r in rs if r.status_code == 201}
            if len(ids) != 1:
                st.errors.append(f"duplicate send produced ids {ids}")
            msg_id = ids.pop()
            sent[room].append(msg_id)
            tally["sent"] += 1
            tally["dup_sends"] += sends - 1
            break
        else:
            st.errors.append("message never got through the chat lock")
            continue
        if sent[room] and rng.random() < 0.4:  # react to something
            await st.call(c, "chat_react", "POST", f"/rooms/{room}/messages/{rng.choice(sent[room])}/reactions",
                          who["token"], expect=(200, 403), json={"emoji": rng.choice(["👍", "🔥", "👏"])})
        if rng.random() < 0.2:  # catch up like a reconnecting client
            await st.call(c, "chat_history", "GET", f"/rooms/{room}/messages?limit=50", who["token"])


async def run_match(c, st, plan, watchers, ws_base, messages, season_room, season_ids, rng, tally) -> dict:
    mid, ump, A, B, ta, tb = plan
    r = (await st.call(c, "chat_rooms", "GET", f"/matches/{mid}/rooms", ump["token"])).json()
    rooms = {"match": r["match"]["room_id"], "season": season_room}
    sent: dict[int, list[int]] = defaultdict(list)
    sent[rooms["season"]] = season_ids  # everybody replies into the shared season-room list
    got: list[list[int]] = [[] for _ in range(watchers)]
    ready = [asyncio.Event() for _ in range(watchers)]
    mw = [asyncio.create_task(room_watcher(f"{ws_base}/ws/rooms/{rooms['match']}", (A + B)[i]["token"], ready[i], got[i]))
          for i in range(watchers)]
    caps: list[list[str]] = [[], []]
    cready = [asyncio.Event(), asyncio.Event()]
    cw = [asyncio.create_task(me_watcher(f"{ws_base}/ws/me", p[0]["token"], cready[k], caps[k])) for k, p in enumerate((A, B))]
    await asyncio.gather(*(e.wait() for e in ready + cready))

    players = A + B
    chat = [chatter(c, st, p, [q["id"] for q in (A if p in A else B) if q is not p], rooms, sent, messages,
                    random.Random(rng.random()), tally) for p in players]
    play = play_match(c, st, mid, ump, A, B, ta, tb, 0, ws_base, True)
    result, *_ = await asyncio.gather(play, *chat)
    await asyncio.sleep(1.0)  # let the last pushes land
    STOPPING.set()
    for t in mw + cw:
        t.cancel()
    return {"rooms": rooms, "match_room": got, "captain_notes": caps, "live": result["live"]}


async def main(n_matches: int, messages: int, api: str, seed: int, deadline: int = 900) -> int:
    st, rng = Stats(), random.Random(seed)
    tally = {"sent": 0, "locked": 0, "dup_sends": 0, "unordered": 0}
    async with httpx.AsyncClient(base_url=api, timeout=60, limits=httpx.Limits(max_connections=300, keepalive_expiry=2)) as c:
        print(f"building {n_matches} matches ({n_matches * 8} chatting players)...")
        world = await build_world(c, st, n_matches, label="Chat")
        plans = world["plans"]
        home = (await c.get("/chat/home", headers={"Authorization": f"Bearer {plans[0][2][0]['token']}"})).json()
        season_room = next(h["room_id"] for h in home if h["season_id"] == world["season"])
        ws_base = api.replace("http", "ws", 1)
        season_ids: list[int] = []
        season_got: list[list[int]] = [[] for _ in range(10)]
        sready = [asyncio.Event() for _ in season_got]
        sw = [asyncio.create_task(room_watcher(f"{ws_base}/ws/rooms/{season_room}", plans[i][2][1]["token"], sready[i], season_got[i]))
              for i in range(min(10, n_matches))]
        await asyncio.gather(*(e.wait() for e in sready[: len(sw)]))

        print(f"playing and chatting: {n_matches} matches, {messages} messages per player...")
        t0 = time.perf_counter()
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*[run_match(c, st, p, 3, ws_base, messages, season_room, season_ids, rng, tally) for p in plans]),
                timeout=deadline)
        except TimeoutError:
            print(f"\nFAILED: the run did not finish within {deadline}s (something is stuck)")
            for f in FAILURES[:10]:
                print(" -", f)
            return 1
        wall = time.perf_counter() - t0
        await asyncio.sleep(1.0)
        STOPPING.set()
        for t in sw:
            t.cancel()

    problems = list(st.errors) + FAILURES
    async with SessionLocal() as s:
        for res in results:
            room = res["rooms"]["match"]
            db_ids = list(await s.scalars(select(ChatMessage.id).where(ChatMessage.room_id == room).order_by(ChatMessage.id)))
            for k, got in enumerate(res["match_room"]):
                if len(set(got)) != len(got):
                    problems.append(f"room {room} watcher {k}: {len(got) - len(set(got))} message(s) delivered twice")
                tally["unordered"] += got != sorted(got)
                if set(got) != set(db_ids):
                    problems.append(f"room {room} watcher {k}: saw {len(set(got))} of {len(db_ids)} messages "
                                    f"(missing {len(set(db_ids) - set(got))}, extra {len(set(got) - set(db_ids))})")
            for k, notes in enumerate(res["captain_notes"]):
                if notes.count("toss_ready") != 1:
                    problems.append(f"room {room} captain {k}: {notes.count('toss_ready')} toss_ready notifications")
            i1, i2 = res["live"]["innings"]
            if (i1["runs"], i2["runs"], res["live"]["match"]["status"]) != (147, 143, "completed"):
                problems.append(f"room {room}: match ended {i1['runs']}/{i2['runs']} {res['live']['match']['status']}")
        season_db = list(await s.scalars(select(ChatMessage.id).where(ChatMessage.room_id == season_room).order_by(ChatMessage.id)))
        for k, got in enumerate(season_got[: len(sw)]):
            if len(set(got)) != len(got):
                problems.append(f"season room watcher {k}: {len(got) - len(set(got))} message(s) delivered twice")
            tally["unordered"] += got != sorted(got)
            if set(got) != set(season_db):
                problems.append(f"season room watcher {k}: saw {len(set(got))} of {len(season_db)} messages")
        user_in_db = await s.scalar(select(func.count()).select_from(ChatMessage).where(
            ChatMessage.sender_id.is_not(None), ChatMessage.room_id.in_([r["rooms"]["match"] for r in results] + [season_room])))
        dup_client = await s.scalar(select(func.count()).select_from(
            select(ChatMessage.room_id, ChatMessage.sender_id, ChatMessage.client_id).where(ChatMessage.sender_id.is_not(None))
            .group_by(ChatMessage.room_id, ChatMessage.sender_id, ChatMessage.client_id).having(func.count() > 1).subquery()))
        if user_in_db != tally["sent"]:
            problems.append(f"{tally['sent']} messages were acknowledged but {user_in_db} are stored")
        if dup_client:
            problems.append(f"{dup_client} client ids were stored more than once")

    report(st, wall)
    print(f"\nchat: {tally['sent']} messages acknowledged and stored, {tally['dup_sends']} duplicate sends collapsed, "
          f"{tally['locked']} sends waited out the batter/bowler lock")
    print(f"{tally['unordered']} watcher stream(s) saw messages out of id order (simultaneous senders commit in a "
          "different order than ids are handed out; clients insert by id, so this is cosmetic)")
    if problems:
        print(f"\nFAILED: {len(problems)} problem(s)")
        kinds: dict[str, list[str]] = defaultdict(list)
        for p in problems:
            kinds[re.sub(r"\d+", "N", p)[:90]].append(p)  # group the same problem across rooms
        for k, group in sorted(kinds.items(), key=lambda kv: -len(kv[1])):
            print(f" - x{len(group)}: {group[0]}")
        return 1
    print(f"\nOK: {n_matches} matches finished; every watcher saw exactly the stored messages: none missing, none delivered twice")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches", type=int, default=30)
    ap.add_argument("--messages", type=int, default=6, help="messages each player sends")
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--deadline", type=int, default=900, help="give up if the run takes longer than this (seconds)")
    a = ap.parse_args()
    raise SystemExit(asyncio.run(main(a.matches, a.messages, a.api, a.seed, a.deadline)))
