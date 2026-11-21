LOCAL_DB=postgresql+asyncpg://ffcl:ffcl@localhost:55433/ffcl

up:
	docker compose up -d --build
down:
	docker compose down
migrate:
	cd api && DATABASE_URL=$(LOCAL_DB) uv run alembic upgrade head && DATABASE_URL=$(LOCAL_DB) uv run python -m app.seed
test:
	cd api && DATABASE_URL=$(LOCAL_DB) uv run pytest -q
	cd web && pnpm test
lint:
	cd api && uv run ruff check . && uv run mypy app
	cd web && pnpm lint && pnpm exec tsc --noEmit
