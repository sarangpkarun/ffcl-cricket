import { execSync } from "node:child_process";
import { expect, test, type Browser, type Page } from "@playwright/test";

const API = process.env.E2E_API_URL ?? "http://localhost:8000";
const ROOT = process.env.E2E_ROOT ?? `${process.cwd()}/..`;
const run = Date.now();
const PASSWORD = "password123";

async function call<T>(path: string, method: string, body?: unknown, token?: string): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    method,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${method} ${path} -> ${r.status} ${await r.text()}`);
  return r.status === 204 ? (undefined as T) : ((await r.json()) as T);
}

type U = { email: string; token: string; id: number; name: string };
let n = 0;
async function user(label: string): Promise<U> {
  n += 1;
  const email = `e2e${run}${n}@t.io`;
  const name = `${label}${n}`;
  const t = await call<{ access_token: string }>("/auth/register", "POST", {
    name, email, password: PASSWORD, phone: `+9177${String(run).slice(-6)}${String(n).padStart(2, "0")}`,
  });
  const me = await call<{ id: number }>("/me", "GET", undefined, t.access_token);
  return { email, token: t.access_token, id: me.id, name };
}

async function loginPage(browser: Browser, u: U, path: string): Promise<Page> {
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

const keys = (d: number[]) => d.map((x) => `digit ${x}`);
async function enter(page: Page, digits: number[]) {
  for (const k of keys(digits)) await page.getByRole("button", { name: k }).click();
  await page.getByRole("button", { name: "Confirm" }).click();
}

test("umpire runs an over with two phones; digits stay private until reveal", async ({ browser }, info) => {
  // ---- seed through the API ----
  const adminEmail = `root${run}@t.io`;
  execSync(`docker compose exec -T api python -m app.create_admin ${adminEmail} ${PASSWORD} "E2E Admin"`, { cwd: ROOT });
  const admin = (await call<{ access_token: string }>("/auth/login", "POST", { email: adminEmail, password: PASSWORD })).access_token;
  const ump = await user("Ump");
  await call(`/users/${ump.id}/roles`, "POST", { role: "umpire" }, admin);
  const A = [await user("Pink"), await user("Pink"), await user("Pink"), await user("Pink")];
  const B = [await user("Green"), await user("Green"), await user("Green"), await user("Green")];
  execSync(
    `docker compose exec -T postgres psql -U ffcl -d ffcl -c "update users set phone_verified=true where email like 'e2e${run}%'"`,
    { cwd: ROOT },
  );
  const season = await call<{ id: number }>("/seasons", "POST", { name: `E2E ${run}`, status: "active" }, admin);
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
  await call(`/matches/${m.id}/toss/open`, "POST", undefined, ut);
  await call(`/matches/${m.id}/toss/winner`, "POST", { winner_team_id: ids[0] }, ut);
  await call(`/matches/${m.id}/toss/decision`, "POST", { decision: "bat" }, ut);
  await call(`/matches/${m.id}/toss/confirm`, "POST", undefined, ut);
  await call(`/matches/${m.id}/start`, "POST", undefined, ut);

  // ---- UI: three phones ----
  const path = `/matches/${m.id}`;
  const umpPage = await loginPage(browser, ump, path);
  const batter = A[0];
  const bowler = B[0];
  const batterPage = await loginPage(browser, batter, path);
  const bowlerPage = await loginPage(browser, bowler, path);

  await umpPage.getByText("Umpire console").waitFor();
  for (const p of [umpPage, batterPage, bowlerPage]) await expect(p.getByText("● Live")).toBeVisible({ timeout: 10_000 });
  await umpPage.locator("select").nth(0).selectOption({ label: bowler.name });
  await umpPage.locator("select").nth(1).selectOption({ label: batter.name });
  await umpPage.getByRole("button", { name: "Start over" }).click();
  await umpPage.getByRole("button", { name: /Send signal/ }).click();

  await expect(bowlerPage.getByRole("button", { name: "digit 1" })).toBeVisible({ timeout: 10_000 });
  await expect(batterPage.getByRole("button", { name: "digit 1" })).toBeVisible({ timeout: 10_000 });
  await bowlerPage.screenshot({ path: info.outputPath("bowler-keypad.png") });

  await enter(bowlerPage, [6, 5, 2, 1, 4, 3]);
  await expect(bowlerPage.getByText(/Locked/)).toBeVisible();
  await bowlerPage.reload(); // a refresh mid-over must restore the locked state from the server
  await expect(bowlerPage.getByText(/Locked/)).toBeVisible({ timeout: 10_000 });
  // opponent's page must never contain the bowler's digits before the reveal
  await expect(batterPage.getByRole("button", { name: "digit 1" })).toBeVisible();
  await expect(umpPage.getByText(/Bowler ✅/)).toBeVisible({ timeout: 5_000 });
  await enter(batterPage, [5, 6, 1, 2, 3, 4]);
  await expect(umpPage.getByText(/Batter ✅/)).toBeVisible({ timeout: 10_000 });
  const secret = "6️⃣ 5️⃣ 2️⃣ 1️⃣ 4️⃣ 3️⃣";
  expect(await batterPage.content()).not.toContain(secret);

  await umpPage.getByRole("button", { name: "Lock submissions" }).click();
  await expect(umpPage.getByText(secret)).toBeVisible();          // umpire sees after lock
  await batterPage.waitForTimeout(3500);                           // let the batter's poll run
  expect(await batterPage.content()).not.toContain(secret);        // players still blind
  await umpPage.getByRole("button", { name: "Reveal digits" }).click();
  await expect(batterPage.getByText(secret)).toBeVisible({ timeout: 10_000 });
  await umpPage.getByRole("button", { name: /Calculate and publish/ }).click();

  // 5v6 + 6v5 + 1v2 + 2v1 + 3v4 + 4v3 = 21 runs, no wickets
  for (const p of [umpPage, batterPage, bowlerPage]) {
    await expect(p.getByText("21/0")).toBeVisible({ timeout: 10_000 });
  }
  await batterPage.screenshot({ path: info.outputPath("scoreboard.png"), fullPage: true });
});
