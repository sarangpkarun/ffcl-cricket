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
