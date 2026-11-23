import { expect, test } from "@playwright/test";
import { call, loginPage, newMatch, playMatch, run, seedLeague, user } from "./helpers";

test("season admins, the season dashboard, starting the next season, and the remembered season", async ({ browser }, info) => {
  test.setTimeout(240_000);
  const one = await seedLeague();
  const two = await seedLeague();
  const [A, B] = one.teams;
  await playMatch(one, await newMatch(one, A, B), A, B, "a");
  const nameOf = async (id: number) => (await call<{ name: string }>(`/seasons/${id}`, "GET", undefined, one.admin)).name;
  const seasonOne = await nameOf(one.season);
  const seasonTwo = await nameOf(two.season);

  // --- a global admin makes someone the admin of one season only, from the People screen
  const sa = await user(`SeasonAdmin${run}x`);
  const ad = await loginPage(browser, one.adminUser, "/admin/users");
  await ad.getByLabel("Search people").fill(sa.name);
  const card = ad.getByRole("article", { name: `User ${sa.name}` });
  await expect(card).toBeVisible({ timeout: 15_000 });
  await card.getByLabel(`Role to add for ${sa.name}`).selectOption("tournament_admin");
  await card.getByLabel(`Season for ${sa.name}'s admin role`).selectOption({ label: `Only ${seasonOne}` });
  await card.getByRole("button", { name: "Add role" }).click();
  await expect(card.getByRole("list", { name: "Roles" })).toContainText(`tournament admin (${seasonOne})`, { timeout: 10_000 });
  await ad.screenshot({ path: info.outputPath("people-scoped.png"), fullPage: true });

  // --- that person sees and manages their season, and only that
  const s = await loginPage(browser, sa, "/admin");
  await expect(s.getByRole("heading", { name: "Seasons" })).toBeVisible({ timeout: 15_000 });
  await expect(s.getByRole("link", { name: new RegExp(seasonOne) })).toBeVisible();
  await expect(s.getByRole("link", { name: new RegExp(seasonTwo) })).toHaveCount(0);
  for (const hidden of [/People/, /Chat moderation/, /Rule versions/, /Audit log/]) await expect(s.getByRole("link", { name: hidden })).toHaveCount(0);
  await expect(s.getByRole("button", { name: "Create season" })).toHaveCount(0);
  await s.getByRole("link", { name: new RegExp(seasonOne) }).click();
  await expect(s.getByRole("region", { name: "At a glance" })).toContainText("4", { timeout: 15_000 }); // teams
  await expect(s.getByRole("region", { name: "Waiting for you" })).toBeVisible();
  await expect(s.getByText("Start the next season from this one")).toHaveCount(0); // only global admins create seasons
  await s.screenshot({ path: info.outputPath("dashboard-scoped.png"), fullPage: true });
  await s.goto(`/admin/seasons/${two.season}`);
  await expect(s.getByText("Insufficient role")).toBeVisible({ timeout: 15_000 });
  await s.goto("/admin/users");
  await expect(s.getByText("Admins only")).toBeVisible({ timeout: 15_000 });
  await s.goto("/admin/adjustments");
  const sel = s.getByLabel("Season");
  await expect(sel.locator("option")).toHaveCount(1, { timeout: 15_000 }); // only their own season to choose from

  // --- a global admin starts the next season from the first, with the players
  const g = await loginPage(browser, one.adminUser, `/admin/seasons/${one.season}`);
  await expect(g.getByRole("region", { name: "At a glance" })).toContainText("12", { timeout: 15_000 }); // players
  await g.getByText("Start the next season from this one").click();
  const next = `Next ${run}`;
  await g.getByLabel("Name of the new season").fill(next);
  await g.getByLabel("Also copy the players, captains and vice-captains").check();
  await g.getByRole("button", { name: "Create the new season" }).click();
  await expect(g.getByRole("status")).toContainText("New season created", { timeout: 10_000 });
  await g.getByRole("link", { name: "Open it" }).click();
  await expect(g.getByRole("heading", { name: next })).toBeVisible({ timeout: 15_000 });
  await expect(g.getByRole("region", { name: "At a glance" })).toContainText("12");
  await expect(g.getByText("hidden from the public")).toBeVisible();
  await g.screenshot({ path: info.outputPath("dashboard-new.png"), fullPage: true });

  // --- the chosen season is remembered
  const p = await loginPage(browser, A.players[1], "/fixtures");
  const pick = p.getByLabel("Season");
  await expect(pick.locator("option")).not.toHaveCount(0, { timeout: 15_000 });
  const other = await pick.locator("option").evaluateAll((os, id) => (os as HTMLOptionElement[]).map((o) => o.value).filter((v) => v !== id)[0], String(one.season));
  await pick.selectOption(other);
  await p.reload();
  await expect(p.getByLabel("Season")).toHaveValue(other, { timeout: 15_000 });
  await p.goto("/standings");
  await expect(p.getByLabel("Season")).toHaveValue(other, { timeout: 15_000 }); // the same choice on the other screens
});
