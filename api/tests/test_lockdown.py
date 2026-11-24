"""The Supabase lockdown turns security on and removes the public roles' privileges, and does nothing without them."""

import pytest
from sqlalchemy import text

from app.db.lockdown import lockdown_sql

SCHEMA = "lockdown_scratch"


async def exists_role(conn, name):
    return bool(await conn.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :n"), {"n": name}))


async def test_the_lockdown_closes_the_public_roles_out_of_every_table(engine):
    async with engine.connect() as conn:
        had = {r: await exists_role(conn, r) for r in ("anon", "authenticated")}
    if any(had.values()):
        pytest.skip("this server already has Supabase-style roles; not touching them")
    async with engine.begin() as conn:
        await conn.exec_driver_sql(f"CREATE SCHEMA {SCHEMA}")
        await conn.exec_driver_sql("CREATE ROLE anon NOLOGIN")
        await conn.exec_driver_sql("CREATE ROLE authenticated NOLOGIN")
        await conn.exec_driver_sql(f"CREATE TABLE {SCHEMA}.people (id serial primary key, email text)")
        await conn.exec_driver_sql(f"GRANT ALL ON ALL TABLES IN SCHEMA {SCHEMA} TO anon, authenticated")
        await conn.exec_driver_sql(f"GRANT USAGE ON SCHEMA {SCHEMA} TO anon, authenticated")
    try:
        async with engine.begin() as conn:
            assert await conn.scalar(text("SELECT has_table_privilege('anon', :t, 'SELECT')"), {"t": f"{SCHEMA}.people"})  # open before
            await conn.exec_driver_sql(lockdown_sql(SCHEMA))
        async with engine.connect() as conn:
            for role in ("anon", "authenticated"):
                for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    assert not await conn.scalar(text("SELECT has_table_privilege(:r, :t, :p)"), {"r": role, "t": f"{SCHEMA}.people", "p": priv}), (role, priv)
            assert await conn.scalar(text("SELECT relrowsecurity FROM pg_class WHERE oid = to_regclass(:t)"), {"t": f"{SCHEMA}.people"})
        # a table made afterwards is closed too
        async with engine.begin() as conn:
            await conn.exec_driver_sql(f"CREATE TABLE {SCHEMA}.later (id int)")
            assert not await conn.scalar(text("SELECT has_table_privilege('anon', :t, 'SELECT')"), {"t": f"{SCHEMA}.later"})
    finally:
        async with engine.begin() as conn:
            await conn.exec_driver_sql(f"DROP SCHEMA {SCHEMA} CASCADE")
            await conn.exec_driver_sql("DROP OWNED BY anon, authenticated")
            await conn.exec_driver_sql("DROP ROLE anon")
            await conn.exec_driver_sql("DROP ROLE authenticated")


async def test_without_those_roles_it_changes_nothing(engine):
    async with engine.connect() as conn:
        if await exists_role(conn, "anon"):
            pytest.skip("this server has an anon role")
    async with engine.begin() as conn:
        await conn.exec_driver_sql(lockdown_sql("public"))  # must not fail or alter anything
        assert not await conn.scalar(text("SELECT bool_or(relrowsecurity) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind = 'r'"))


def test_the_schema_name_is_checked():
    with pytest.raises(ValueError):
        lockdown_sql("public; drop table users")
