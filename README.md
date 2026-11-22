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

## Load test
With the stack running: `cd api && DATABASE_URL=postgresql+asyncpg://ffcl:ffcl@localhost:55433/ffcl REDIS_URL=redis://localhost:56379/0 uv run python -m loadtest.simulate --matches 10 --watchers 3`

It plays whole matches concurrently (with duplicate submits and racing resolves), keeps WebSocket watchers connected, then checks every match has exactly 84 ball events, the right result, and that every watcher ended on the database's final sequence number. On a dev laptop (one uvicorn worker, auto-reload on): 10 matches = 1,861 requests in ~8s, 30 matches = 5,581 requests in ~23s, p95 about half a second, zero errors. Production should run several workers behind Nginx.
