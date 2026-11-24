"""Close Supabase's public data API on our tables.

Supabase serves every table in the `public` schema through an HTTP API that anyone holding the (public) publishable
key can call, using the `anon` and `authenticated` roles. Tables made by SQL have row-level security off, so those
roles could read and write everything, including emails and password hashes. FFCL never uses that API: the app
connects as the table owner, which bypasses row-level security. This turns security on for every table and takes
every privilege away from those two roles, for the tables that exist and for any made later.

On a database without those roles (a normal Postgres) it does nothing.
"""

LOCKDOWN_SQL = """
DO $do$
DECLARE r record;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    RETURN;
  END IF;
  FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = '{schema}' LOOP
    EXECUTE format('ALTER TABLE {schema}.%I ENABLE ROW LEVEL SECURITY', r.tablename);
  END LOOP;
  REVOKE ALL ON ALL TABLES IN SCHEMA {schema} FROM anon, authenticated;
  REVOKE ALL ON ALL SEQUENCES IN SCHEMA {schema} FROM anon, authenticated;
  REVOKE ALL ON ALL FUNCTIONS IN SCHEMA {schema} FROM anon, authenticated;
  ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} REVOKE ALL ON TABLES FROM anon, authenticated;
  ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} REVOKE ALL ON SEQUENCES FROM anon, authenticated;
  ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} REVOKE ALL ON FUNCTIONS FROM anon, authenticated;
END
$do$;
"""


def lockdown_sql(schema: str = "public") -> str:
    if not schema.replace("_", "").isalnum():
        raise ValueError("unexpected schema name")
    return LOCKDOWN_SQL.format(schema=schema)
