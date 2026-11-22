import { execSync } from "node:child_process";
import type { Browser, Page } from "@playwright/test";

export const API = process.env.E2E_API_URL ?? "http://localhost:8000";
const ROOT = process.env.E2E_ROOT ?? `${process.cwd()}/..`;
export const run = Date.now();
export const PASSWORD = "password123";

export async function call<T>(path: string, method: string, body?: unknown, token?: string): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    method,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${method} ${path} -> ${r.status} ${await r.text()}`);
  return r.status === 204 ? (undefined as T) : ((await r.json()) as T);
}

export type U = { email: string; token: string; id: number; name: string };
let n = 0;
export async function user(label: string): Promise<U> {
  n += 1;
  const email = `e2e${run}${n}@t.io`;
  const name = `${label}${n}`;
  const t = await call<{ access_token: string }>("/auth/register", "POST", {
    name, email, password: PASSWORD, phone: `+9177${String(run).slice(-6)}${String(n).padStart(2, "0")}`,
  });
  const me = await call<{ id: number }>("/me", "GET", undefined, t.access_token);
  return { email, token: t.access_token, id: me.id, name };
}

export async function loginPage(browser: Browser, u: U, path: string): Promise<Page> {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await ctx.newPage();
  await page.goto("/login");
  await page.getByLabel("Email").fill(u.email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/");
  await page.goto(path);
  return page;
}

/** A season with two teams of four, a match with an umpire and lineups. Optionally toss + start. */
export async function seed(opts: { start: boolean }) {
  const adminEmail = `root${run}${n}@t.io`;
  execSync(`docker compose exec -T api python -m app.create_admin ${adminEmail} ${PASSWORD} "E2E Admin"`, { cwd: ROOT });
  const admin = (await call<{ access_token: string }>("/auth/login", "POST", { email: adminEmail, password: PASSWORD })).access_token;
  const ump = await user("Ump");
  await call(`/users/${ump.id}/roles`, "POST", { role: "umpire" }, admin);
  const A = [await user("Pink"), await user("Pink"), await user("Pink"), await user("Pink")];
  const B = [await user("Green"), await user("Green"), await user("Green"), await user("Green")];
  const outsider = await user("Fan");
  execSync(
    `docker compose exec -T postgres psql -U ffcl -d ffcl -c "update users set phone_verified=true where email like 'e2e${run}%'"`,
    { cwd: ROOT },
  );
  n += 1;
  const season = await call<{ id: number }>("/seasons", "POST", { name: `E2E ${run}-${n}`, status: "active" }, admin);
  const ids: number[] = [];
  for (const [name, players] of [["Pink", A], ["Green", B]] as const) {
    const t = await call<{ id: number }>(`/seasons/${season.id}/teams`, "POST", { name }, admin);
    for (const p of players) await call(`/teams/${t.id}/members`, "POST", { user_id: p.id }, admin);
    await call(`/teams/${t.id}`, "PATCH", { captain_id: players[0].id }, admin);
    ids.push(t.id);
  }
  const m = await call<{ id: number }>(`/seasons/${season.id}/matches`, "POST", { team_a_id: ids[0], team_b_id: ids[1], umpire_id: ump.id }, admin);
  for (const [tid, players] of [[ids[0], A], [ids[1], B]] as const)
    await call(`/matches/${m.id}/lineup`, "PUT", { team_id: tid, user_ids: players.map((p) => p.id) }, admin);
  const ut = (await call<{ access_token: string }>("/auth/login", "POST", { email: ump.email, password: PASSWORD })).access_token;
  if (opts.start) {
    await call(`/matches/${m.id}/toss/open`, "POST", undefined, ut);
    await call(`/matches/${m.id}/toss/winner`, "POST", { winner_team_id: ids[0] }, ut);
    await call(`/matches/${m.id}/toss/decision`, "POST", { decision: "bat" }, ut);
    await call(`/matches/${m.id}/toss/confirm`, "POST", undefined, ut);
    await call(`/matches/${m.id}/start`, "POST", undefined, ut);
  }
  return { admin, ump, ut, A, B, outsider, match: m.id, season: season.id, teams: ids };
}
