import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.models import RuleSet, UserRole
from app.db.session import get_session
from app.engine.rules import DEFAULT_RULES
from app.main import app

TEST_DB = "ffcl_test"
BASE_URL = make_url(settings.database_url)
TEST_URL = BASE_URL.set(database=TEST_DB)


@pytest_asyncio.fixture
async def engine():
    admin = create_async_engine(BASE_URL.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as c:
        exists = await c.scalar(text("SELECT 1 FROM pg_database WHERE datname=:n"), {"n": TEST_DB})
        if not exists:
            await c.execute(text(f"CREATE DATABASE {TEST_DB}"))
    await admin.dispose()
    eng = create_async_engine(TEST_URL, poolclass=NullPool)
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.drop_all)
        await c.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(eng, expire_on_commit=False)() as s:
        s.add(RuleSet(name="FFCL", version=1, config=DEFAULT_RULES))
        await s.commit()
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine):
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s


@pytest_asyncio.fixture
async def client(engine):
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def override():
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()


class Actor:
    def __init__(self, client, db, id_, headers, phone):
        self.client, self.db, self.id, self.h, self.phone = client, db, id_, headers, phone

    async def req(self, method, url, **kw):
        return await self.client.request(method, url, headers=self.h, **kw)


@pytest.fixture
def make_user(client, db):
    counter = {"n": 0}

    async def _make(name="User", roles=(), verified=True):
        counter["n"] += 1
        n = counter["n"]
        phone = f"+9199000{n:05d}"
        r = await client.post(
            "/auth/register",
            json={"name": f"{name}{n}", "email": f"u{n}@t.io", "password": "password123", "phone": phone},
        )
        assert r.status_code == 201, r.text
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        me = (await client.get("/me", headers=h)).json()
        for role in roles:
            db.add(UserRole(user_id=me["id"], role=role))
        if verified:
            from app.db.models import User

            u = await db.get(User, me["id"])
            u.phone_verified = True
        await db.commit()
        return Actor(client, db, me["id"], h, phone)

    return _make
