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
  const adminUser: U = { email: adminEmail, token: admin, id: 0, name: "E2E Admin" };
  return { admin, adminUser, ump, ut, A, B, outsider, match: m.id, season: season.id, teams: ids };
}

/** A season with 4 teams of 3 players, 3 umpires and an admin. No matches yet. */
export async function seedLeague() {
  const adminEmail = `lroot${run}${n}@t.io`;
  execSync(`docker compose exec -T api python -m app.create_admin ${adminEmail} ${PASSWORD} "League Admin"`, { cwd: ROOT });
  const admin = (await call<{ access_token: string }>("/auth/login", "POST", { email: adminEmail, password: PASSWORD })).access_token;
  const umpires = [await user("Umpire"), await user("Umpire"), await user("Umpire")];
  for (const u of umpires) await call(`/users/${u.id}/roles`, "POST", { role: "umpire" }, admin);
  const teams: { id: number; name: string; players: U[] }[] = [];
  for (const name of ["Aces", "Bulls", "Cobras", "Dragons"]) {
    teams.push({ id: 0, name, players: [await user(name), await user(name), await user(name)] });
  }
  execSync(
    `docker compose exec -T postgres psql -U ffcl -d ffcl -c "update users set phone_verified=true where email like 'e2e${run}%'"`,
    { cwd: ROOT },
  );
  n += 1;
  const season = await call<{ id: number }>("/seasons", "POST", { name: `League ${run}-${n}`, status: "active" }, admin);
  for (const t of teams) {
    t.id = (await call<{ id: number }>(`/seasons/${season.id}/teams`, "POST", { name: t.name }, admin)).id;
    for (const p of t.players) await call(`/teams/${t.id}/members`, "POST", { user_id: p.id }, admin);
    await call(`/teams/${t.id}`, "PATCH", { captain_id: t.players[0].id }, admin);
  }
  const adminUser: U = { email: adminEmail, token: admin, id: 0, name: "League Admin" };
  return { admin, adminUser, season: season.id, teams, umpires };
}

type LeagueSeed = Awaited<ReturnType<typeof seedLeague>>;
type TeamSeed = LeagueSeed["teams"][number];

export async function newMatch(lg: LeagueSeed, a: TeamSeed, b: TeamSeed): Promise<number> {
  const m = await call<{ id: number }>(`/seasons/${lg.season}/matches`, "POST", { team_a_id: a.id, team_b_id: b.id, umpire_id: lg.umpires[0].id }, lg.admin);
  return m.id;
}

/**
 * Play an existing match to the end with the admin as the official. Team A wins the toss and bats first.
 *   a   : A scores 21 then is all out, B is all out for 0 -> A wins by 21 runs
 *   b   : A is all out for 0, B scores 5 off one ball      -> B wins
 *   tie : both all out for 0
 */
export async function playMatch(lg: LeagueSeed, matchId: number, a: TeamSeed, b: TeamSeed, outcome: "a" | "b" | "tie") {
  const t = lg.admin;
  const m = `/matches/${matchId}`;
  const post = (path: string, body?: unknown, token = t) => call(`${m}/${path}`, "POST", body, token);
  for (const team of [a, b]) await call(`${m}/lineup`, "PUT", { team_id: team.id, user_ids: team.players.map((p) => p.id) }, t);
  await post("toss/open");
  await post("toss/winner", { winner_team_id: a.id });
  await post("toss/decision", { decision: "bat" }, a.players[0].token);
  await post("toss/confirm");
  await post("start");
  const BAT = "561234", NO_EQUAL = "652143", ALL_EQUAL = "561234";
  const over = async (n: number, batting: TeamSeed, bowling: TeamSeed, bowlDigits: string) => {
    const bowler = bowling.players[(n - 1) % 3];
    const batter = batting.players[(n - 1) % 3];
    await post("overs/start", { bowler_id: bowler.id, batter_id: batter.id });
    await post("overs/current/signal");
    await post("overs/current/submit", { digits: bowlDigits }, bowler.token);
    await post("overs/current/submit", { digits: BAT }, batter.token);
    await post("overs/current/lock");
    await post("overs/current/reveal");
    await post("overs/current/resolve");
  };
  if (outcome === "a") {
    await over(1, a, b, NO_EQUAL); await over(2, a, b, ALL_EQUAL); await over(3, a, b, ALL_EQUAL);
  } else {
    await over(1, a, b, ALL_EQUAL); await over(2, a, b, ALL_EQUAL);
  }
  await post("innings/next");
  if (outcome === "b") {
    await over(1, b, a, NO_EQUAL);
  } else {
    await over(1, b, a, ALL_EQUAL); await over(2, b, a, ALL_EQUAL);
  }
}
