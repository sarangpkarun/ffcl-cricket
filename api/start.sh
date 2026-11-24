#!/bin/sh
# Production start: bring the database up to date, run the reminders worker beside the API, then serve the API.
# Used on hosts that give one free process (Render): the worker is restarted if it stops.
set -e

alembic upgrade head

(
  while true; do
    arq app.worker.WorkerSettings || true
    echo "worker stopped; restarting in 5 seconds" >&2
    sleep 5
  done
) &

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
