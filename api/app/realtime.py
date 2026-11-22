"""Redis pub/sub fan-out for live matches.

Messages carry ONLY the match id and its sequence number. Clients refetch their
own privacy-filtered view, so a broadcast can never leak hidden digits.
PostgreSQL stays the source of truth; if Redis is down, publishing is skipped
and clients fall back to slow polling.
"""

import asyncio
import json
import logging
import weakref

import redis.asyncio as aioredis

from app.core.config import settings

log = logging.getLogger("ffcl.realtime")

# redis-py caps a pool at 100 connections unless told otherwise, and every open WebSocket holds a
# dedicated subscription connection. Sharing one pool let a few hundred sockets starve ordinary
# commands (publishing, rate limits, presence) and each other, so they get separate pools:
#  - commands share a bounded pool and WAIT for a free connection instead of failing;
#  - subscriptions get their own large pool; Redis' own `maxclients` is the real ceiling.
COMMAND_CONNECTIONS = 100
COMMAND_WAIT_SECONDS = 15
SUBSCRIBER_CONNECTIONS = 20_000

_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, aioredis.Redis]" = (
    weakref.WeakKeyDictionary()
)
_subscribers: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, aioredis.Redis]" = (
    weakref.WeakKeyDictionary()
)


def channel(match_id: int) -> str:
    return f"match:{match_id}"


def client() -> aioredis.Redis:
    """Shared client for ordinary commands. One per event loop (tests run each test on its own loop)."""
    loop = asyncio.get_running_loop()
    c = _clients.get(loop)
    if c is None:
        pool = aioredis.BlockingConnectionPool.from_url(
            settings.redis_url, max_connections=COMMAND_CONNECTIONS, timeout=COMMAND_WAIT_SECONDS)
        c = aioredis.Redis(connection_pool=pool)
        _clients[loop] = c
    return c


def new_pubsub() -> "aioredis.client.PubSub":
    """A subscription for one WebSocket, on the dedicated subscriber pool."""
    loop = asyncio.get_running_loop()
    c = _subscribers.get(loop)
    if c is None:
        c = aioredis.from_url(settings.redis_url, max_connections=SUBSCRIBER_CONNECTIONS)
        _subscribers[loop] = c
    return c.pubsub()


async def publish_change(match_id: int, seq: int) -> None:
    try:
        await client().publish(channel(match_id), json.dumps({"type": "changed", "seq": seq}))
    except Exception:
        log.warning("redis publish failed for match %s", match_id, exc_info=True)


def room_channel(room_id: int) -> str:
    return f"room:{room_id}"


async def publish_room(room_id: int, payload: dict) -> None:
    """Chat events. Safe to carry message bodies: every subscriber is authorised for the room."""
    try:
        await client().publish(room_channel(room_id), json.dumps(payload, default=str))
    except Exception:
        log.warning("redis publish failed for room %s", room_id, exc_info=True)


def user_channel(user_id: int) -> str:
    return f"user:{user_id}"


async def publish_user(user_id: int, payload: dict) -> None:
    try:
        await client().publish(user_channel(user_id), json.dumps(payload, default=str))
    except Exception:
        log.warning("redis publish failed for user %s", user_id, exc_info=True)
