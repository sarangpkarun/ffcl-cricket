import logging

from app.realtime import client

log = logging.getLogger("ffcl.ratelimit")


async def allow(key: str, limit: int, window_seconds: int) -> bool:
    """Fixed-window counter in Redis. Fails open if Redis is unavailable."""
    try:
        r = client()
        n = await r.incr(key)
        if n == 1:
            await r.expire(key, window_seconds)
        return n <= limit
    except Exception:
        log.warning("rate limiter unavailable, allowing", exc_info=True)
        return True
