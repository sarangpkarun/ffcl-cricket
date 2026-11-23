# FFCL

Digit-based cricket league platform. See `docs/ROADMAP.md`, `docs/PHASE1.md`, `RULES.md`.

## Run
    cp .env.example .env
    make up        # postgres, redis, api (:8000), web (:3100)
    make migrate   # schema + default rule set
    make test && make lint

Host ports are offset (Postgres 55433, Redis 56379, web 3100) to avoid clashes with other local services.

## First admin
    docker compose exec api python -m app.create_admin EMAIL PASSWORD "Name"
Then sign in at http://localhost:3100/login and open Profile → Admin dashboard.

## End-to-end browser test
With the stack running (`make up`, `make migrate`): `cd web && pnpm e2e`. It seeds a season through the API, then drives an umpire and two players on phone-sized Chrome windows through one over and checks the digits stay hidden until the reveal.

## Public site
Anyone can follow the league without signing in: `/` (current season), `/league` (all seasons), `/league/<season>/...` (fixtures, results, table, stats, rules, teams, players, live matches) and `/league/history`. The pages are server-rendered from the read-only `/public` API and are in `sitemap.xml`. Set `NEXT_PUBLIC_SITE_URL` to the real address; in Docker the web container uses `API_INTERNAL_URL=http://api:8000`. Players can hide their name from their profile; admins can hide a whole season on its setup page.

## Background worker
`make up` also starts a `worker` container (`arq app.worker.WorkerSettings`) that sends match reminders, the "toss is due" nudge and the 30-second submission-deadline alert. It is safe to run several.

## Security
See `docs/SECURITY.md`. In production set `ENVIRONMENT=production`, a strong `JWT_SECRET` and keep `AUTH_RATE_LIMITS_ENABLED=true`; the server refuses to start otherwise. The local `.env` turns the limits off because tests and demos register many users from one machine.

## Load test
With the stack running: `cd api && DATABASE_URL=postgresql+asyncpg://ffcl:ffcl@localhost:55433/ffcl REDIS_URL=redis://localhost:56379/0 uv run python -m loadtest.simulate --matches 10 --watchers 3`

It plays whole matches concurrently (with duplicate submits and racing resolves), keeps WebSocket watchers connected, then checks every match has exactly 84 ball events, the right result, and that every watcher ended on the database's final sequence number. Chat under load (240 players chatting while 30 matches are played, live watchers in every room): `uv run python -m loadtest.chat_load --matches 30`, add `--api http://localhost:8010` to point it at another server (for example `uvicorn app.main:app --workers 4 --port 8010`).

A whole season: `uv run python -m loadtest.season --teams 6` generates and publishes a double round robin for 6 teams, plays all 30 league matches and the semi-finals and final (six at a time), then rebuilds the table from the ball events and compares it, checks player runs against the results ledger, archives the season, and times every read endpoint with a season's data (about 12 seconds in all on a dev laptop, p95 under 160 ms per read).

On a dev laptop (one uvicorn worker, auto-reload on): 10 matches = 1,861 requests in ~8s, 30 matches = 5,581 requests in ~23s, p95 about half a second, zero errors. Production should run several workers behind Nginx.
