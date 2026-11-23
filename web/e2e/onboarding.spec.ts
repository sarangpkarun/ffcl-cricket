import { expect, test } from "@playwright/test";
import { call, loginPage, newMatch, PASSWORD, run, seedLeague, user } from "./helpers";

test("an admin imports a team, a player joins from the link, and numbers are verified by hand", async ({ browser }, info) => {
  test.setTimeout(180_000);
  const lg = await seedLeague();
  const admin = await loginPage(browser, lg.adminUser, "/admin/import");
  const phone = `+9166${String(run).slice(-7)}`;
  await admin.getByLabel("Players (CSV)").fill(`name,phone,team\nAsha Rao,${phone},Aces\nBroken,12,Aces\nNobody,+9166000000001,Ghosts`);
  await admin.getByRole("button", { name: "Check the list" }).click();
  await expect(admin.getByRole("status").filter({ hasText: "1 ready, 2 with problems" })).toBeVisible();
  await expect(admin.getByText("No team with this name in the season")).toBeVisible();
  await admin.screenshot({ path: info.outputPath("import-preview.png"), fullPage: true });
  await admin.getByRole("button", { name: "Create 1 invite link" }).click();
  const shown = admin.locator("section[aria-label='New links'] span.font-mono");
  await expect(shown).toHaveCount(1);
  const url = (await shown.textContent())!.trim();
  expect(url).toContain("/join/");
  await admin.screenshot({ path: info.outputPath("import-links.png"), fullPage: true });

  // the player opens the link on their own phone and finishes
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const p = await ctx.newPage();
  await p.goto(new URL(url).pathname);
  await expect(p.getByRole("heading", { name: "Welcome, Asha Rao" })).toBeVisible();
  await p.getByLabel("Email").fill(`asha${run}@t.io`);
  await p.getByLabel("Password (min 8)").fill(PASSWORD);
  await p.getByRole("button", { name: "Join Aces" }).click();
  await p.waitForURL("**/profile");
  await expect(p.getByText("✅ verified")).toBeVisible();
  await p.screenshot({ path: info.outputPath("joined.png"), fullPage: true });
  // the link is spent
  const again = await ctx.newPage();
  await again.goto(new URL(url).pathname);
  await expect(again.getByText(/no longer valid/)).toBeVisible();

  // someone who registered by themselves is verified by an admin, with a reason
  const walk = await user("Walkin");
  await call(`/teams/${lg.teams[1].id}/members`, "POST", { user_id: walk.id }, lg.admin);
  await admin.goto("/admin/import");
  const row = admin.getByRole("listitem").filter({ hasText: walk.name });
  await row.getByLabel(/Why is/).fill("called them to check");
  await row.getByRole("button", { name: /Verify .* number/ }).click();
  await expect(admin.getByRole("listitem").filter({ hasText: walk.name })).toHaveCount(0, { timeout: 10_000 });
  const me = await call<{ phone_verified: boolean }>("/me", "GET", undefined, walk.token);
  expect(me.phone_verified).toBe(true);
});

test("the umpire can award a walkover only after the waiting time", async ({ browser }, info) => {
  test.setTimeout(180_000);
  const lg = await seedLeague();
  const [A, B] = lg.teams;
  const early = await newMatch(lg, A, B);
  const late = (await call<{ id: number }>(`/seasons/${lg.season}/matches`, "POST", { team_a_id: lg.teams[2].id, team_b_id: lg.teams[3].id, umpire_id: lg.umpires[1].id }, lg.admin)).id;
  const minutes = (m: number) => new Date(Date.now() + m * 60_000).toISOString();
  await call(`/matches/${early}`, "PATCH", { scheduled_at: minutes(-5) }, lg.admin);
  await call(`/matches/${late}`, "PATCH", { scheduled_at: minutes(-30) }, lg.admin);
  const page = await loginPage(browser, lg.umpires[0], `/matches/${early}`);
  await expect(page.getByText(/The captains have \d+ more minutes? to answer the toss/)).toBeVisible();
  await expect(page.getByRole("button", { name: /is absent/ })).toHaveCount(0);

  const page2 = await loginPage(browser, lg.umpires[1], `/matches/${late}`);
  await expect(page2.getByText("The waiting time is over")).toBeVisible();
  await page2.screenshot({ path: info.outputPath("toss-absent.png"), fullPage: true });
  page2.once("dialog", (d) => void d.accept());
  await page2.getByRole("button", { name: "Dragons is absent" }).click();
  await expect(page2.getByText(/🏆 Cobras won by walkover/)).toBeVisible({ timeout: 10_000 });
  const t = await call<{ matches_counted: number }>(`/seasons/${lg.season}/standings`, "GET", undefined, lg.admin);
  expect(t.matches_counted).toBe(1);
});
