"""Background worker. Run with:  arq app.worker.WorkerSettings

Only cron jobs live here, and each one is idempotent, so running several workers (or
restarting one mid-job) is safe. arq's `unique` cron makes sure one worker runs each tick.
"""

from typing import ClassVar

from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings
from app.services.push import purge_dead_subscriptions, send_push
from app.services.reminders import purge_notifications, scan_deadlines, scan_reminders


class WorkerSettings:
    functions: ClassVar[list] = [scan_reminders, scan_deadlines, purge_notifications, send_push, purge_dead_subscriptions]
    cron_jobs: ClassVar[list] = [
        cron(scan_reminders, second=0, run_at_startup=True),  # every minute
        cron(scan_deadlines, second={0, 10, 20, 30, 40, 50}),  # every 10 seconds
        cron(purge_notifications, hour=3, minute=0, second=0),  # nightly
        cron(purge_dead_subscriptions, hour=3, minute=10, second=0),
    ]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 5
    job_timeout = 60
    keep_result = 0
