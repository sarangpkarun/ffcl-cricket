import { expect, test } from "@playwright/test";
import { call, loginPage, seedLeague } from "./helpers";

test("admin builds, checks and publishes a schedule; players see it only after publishing", async ({ browser }, info) => {
  const lg = await seedLeague();
  const mine = lg.teams[0];
  const player = mine.players[1];

  // a player has an empty fixtures page, with their notification socket connected
  const pl = await loginPage(browser, player, "/fixtures");
  await expect(pl.getByText(/No upcoming matches yet/)).toBeVisible({ timeout: 10_000 });
  await expect(pl.locator('a[data-live="true"]')).toBeVisible({ timeout: 10_000 });

  // --- 1 + 2: set the format and preview
  const ad = await loginPage(browser, lg.adminUser, `/admin/seasons/${lg.season}/setup`);
  await ad.getByLabel("First day").fill("2030-01-07");
  await ad.getByLabel("Kick-off times (local, comma separated)").fill("19:00");
  await ad.getByLabel("Time zone").fill("UTC");
  await ad.getByRole("button", { name: "Preview schedule" }).click();
  await expect(ad.getByRole("status").filter({ hasText: "6 matches · 3 rounds · 4 teams" })).toBeVisible({ timeout: 10_000 });
  await ad.getByRole("region", { name: "Preview" }).screenshot({ path: info.outputPath("preview.png") });

  // --- 3: create the drafts, then review them
  await ad.getByRole("button", { name: "Create 6 draft fixtures" }).click();
  await expect(ad.getByText(/Created 6 draft fixtures/)).toBeVisible({ timeout: 10_000 });
  const rows = ad.getByRole("listitem", { name: /Draft match/ });
  await expect(rows).toHaveCount(6);
  await pl.reload();
  await expect(pl.getByText(/No upcoming matches yet/)).toBeVisible(); // drafts are invisible to players

  // move match 1, then try to put a match that shares a team at the same time: a clash
  const first = rows.first();
  await first.getByLabel(/Time for match/).fill("2030-02-01T10:00");
  await first.getByRole("button", { name: "Save", exact: true }).click();
  await expect(first.getByLabel(/Time for match/)).toHaveValue("2030-02-01T10:00");
  const firstTeams = ((await first.locator("p").first().textContent()) ?? "").split("·")[1].split(" vs ").map((s) => s.trim());
  let rival = null;
  for (let i = 1; i < 6 && !rival; i++) {
    const teams = ((await rows.nth(i).locator("p").first().textContent()) ?? "").split("·")[1].split(" vs ").map((s) => s.trim());
    if (teams.some((t) => firstTeams.includes(t))) rival = rows.nth(i);
  }
  expect(rival).not.toBeNull();
  await rival!.getByLabel(/Time for match/).fill("2030-02-01T10:00");
  await rival!.getByRole("button", { name: "Save", exact: true }).click();
  await expect(rival!.getByRole("alert")).toContainText("Clash:");
  await ad.screenshot({ path: info.outputPath("clash.png"), fullPage: true });
  await rival!.getByRole("button", { name: "Save anyway" }).click(); // an admin can override
  await expect(rival!.getByRole("alert")).toHaveCount(0); // the clash message is gone once it is saved

  // delete one draft
  await rows.last().getByRole("button", { name: "Delete" }).click();
  await expect(rows).toHaveCount(5);

  // --- 4: publish (two-step confirmation) and the player is told
  await ad.getByRole("button", { name: "Publish 5 fixtures" }).click();
  await ad.getByRole("button", { name: "Yes, publish and notify everyone" }).click();
  await expect(ad.getByRole("status").filter({ hasText: /Published 5 fixtures/ })).toBeVisible({ timeout: 10_000 });
  await expect(pl.getByRole("status").filter({ hasText: "New fixtures are published" })).toBeVisible({ timeout: 10_000 });

  // the player now sees them, and the team filter narrows the list to that team
  await pl.goto("/fixtures");
  const cards = pl.getByRole("link", { name: /^Match \d+:/ });
  await expect(cards).toHaveCount(5, { timeout: 10_000 });
  const list = await call<{ id: number }[]>(`/seasons/${lg.season}/fixtures?team_id=${mine.id}`, "GET", undefined, player.token);
  expect(list.length).toBeGreaterThan(0);
  await pl.getByLabel("Team").selectOption({ label: mine.name });
  await expect(cards).toHaveCount(list.length); // wait for the filtered list to settle
  for (let i = 0; i < list.length; i++) await expect(cards.nth(i)).toContainText(mine.name);
  await pl.screenshot({ path: info.outputPath("fixtures.png"), fullPage: true });

  // --- rescheduling a published match reaches the players
  await call(`/matches/${list[0].id}`, "PATCH", { scheduled_at: "2031-01-01T10:00:00Z", force: true }, lg.admin);
  await expect(pl.getByRole("status").filter({ hasText: /rescheduled/ })).toBeVisible({ timeout: 10_000 });
});
