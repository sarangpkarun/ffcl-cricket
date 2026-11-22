"""Who is online in a room: a Redis sorted set of user ids scored by last heartbeat."""

import logging
import time

from app.realtime import client

log = logging.getLogger("ffcl.presence")
STALE_SECONDS = 60  # clients heartbeat every 20s


def _key(room_id: int) -> str:
    return f"presence:room:{room_id}"


async def touch(room_id: int, user_id: int) -> bool:
    """Record a heartbeat. Returns True if the user was not online before."""
    try:
        r = client()
        was = await r.zscore(_key(room_id), user_id)
        now = time.time()
        await r.zadd(_key(room_id), {str(user_id): now})
        await r.expire(_key(room_id), 3600)
        return was is None or was < now - STALE_SECONDS
    except Exception:
        log.warning("presence unavailable", exc_info=True)
        return False


async def leave(room_id: int, user_id: int) -> None:
    try:
        await client().zrem(_key(room_id), str(user_id))
    except Exception:
        log.warning("presence unavailable", exc_info=True)


async def online_users(room_id: int) -> list[int]:
    try:
        rows = await client().zrangebyscore(_key(room_id), time.time() - STALE_SECONDS, "+inf")
        return [int(x) for x in rows]  # type: ignore[arg-type]
    except Exception:
        log.warning("presence unavailable", exc_info=True)
        return []
