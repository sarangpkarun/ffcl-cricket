"""Delivery channels for notifications. Today: the in-app socket (see outbox.py) and browser push.

A channel receives the ids of notifications that were just committed. Adding email or WhatsApp later means
writing another channel here; nothing else needs to change.
"""

import logging
from collections.abc import Iterable
from typing import Protocol

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import settings

log = logging.getLogger("ffcl.delivery")
_pool: ArqRedis | None = None


async def enqueue(job: str, *args: object) -> None:
    """Queue a background job. A separate function so tests can run the job inline instead."""
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    await _pool.enqueue_job(job, *args, _job_id=f"{job}:{':'.join(map(str, args))}")  # one job per notification


class Channel(Protocol):
    async def deliver(self, notification_ids: list[int]) -> None: ...


class PushChannel:
    async def deliver(self, notification_ids: list[int]) -> None:
        if not settings.push_enabled:
            return
        for nid in notification_ids:
            await enqueue("send_push", nid)


CHANNELS: list[Channel] = [PushChannel()]


async def dispatch(notification_ids: Iterable[int]) -> None:
    """Hand freshly committed notifications to every channel. Never raises: delivery problems must not fail a request."""
    ids = list(notification_ids)
    if not ids:
        return
    for ch in CHANNELS:
        try:
            await ch.deliver(ids)
        except Exception:
            log.warning("delivery channel %s failed", type(ch).__name__, exc_info=True)
