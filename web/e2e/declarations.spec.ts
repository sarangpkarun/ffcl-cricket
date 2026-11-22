import { expect, test } from "@playwright/test";
import { call, loginPage, newMatch, seedLeague } from "./helpers";

test("walkover, abandonment, reversal, a manual adjustment and a missed duty", async ({ browser }, info) => {
  test.setTimeout(180_000);
  const lg = await seedLeague();
  const [A, B, C] = lg.teams;
  const fan = await loginPage(browser, A.players[1], "/standings");

  // --- walkover from the umpire console: Bulls do not turn up
  const m1 = await newMatch(lg, A, B);
  const ad = await loginPage(browser, lg.adminUser, `/matches/${m1}`);
  await ad.getByText("Declare a walkover").click();
  await ad.getByRole("combobox").filter({ hasText: "Team that did not turn up" }).selectOption({ label: "Bulls" });
  await ad.getByLabel("Reason").first().fill("no one arrived");
  await ad.getByRole("button", { name: "Award walkover" }).click();
  await expect(ad.getByText(/Aces won by walkover/)).toBeVisible({ timeout: 10_000 });
  await ad.screenshot({ path: info.outputPath("walkover.png"), fullPage: true });
  await fan.reload();
  const aces = fan.getByRole("row", { name: /Aces/ });
  await expect(aces).toContainText("2", { timeout: 10_000 });
  await expect(fan.getByRole("row", { name: /Bulls/ })).toBeVisible();

  // --- the admin reverses it; the table forgets it
  await ad.getByLabel("Reason for reversing").fill("they did come after all");
  await ad.getByRole("button", { name: "Reverse this decision" }).click();
  await expect(ad.getByText(/won by walkover/)).toHaveCount(0, { timeout: 10_000 });
  const t = await call<{ matches_counted: number }>(`/seasons/${lg.season}/standings`, "GET", undefined, lg.admin);
  expect(t.matches_counted).toBe(0);

  // --- abandon another match
  const m2 = await newMatch(lg, A, C);
  await ad.goto(`/matches/${m2}`);
  await ad.locator("summary", { hasText: "Abandon match" }).click();
  await ad.getByLabel("Reason (e.g. rain)").fill("heavy rain");
  await ad.getByRole("button", { name: "Abandon match", exact: true }).click();
  await expect(ad.getByText(/Match abandoned: heavy rain/)).toBeVisible({ timeout: 10_000 });

  // --- a manual adjustment from the admin screen reaches the table
  await ad.goto("/admin/adjustments");
  await ad.getByLabel("Team", { exact: true }).selectOption({ label: "Cobras" });
  await ad.getByLabel("Points (+/-)").fill("-1");
  await ad.getByLabel("Reason", { exact: true }).fill("late to the ground");
  await ad.getByRole("button", { name: "Add adjustment" }).click();
  await expect(ad.getByText("late to the ground")).toBeVisible({ timeout: 10_000 });
  await ad.getByLabel(/Reason to cancel adjustment/).fill("mistake");
  await ad.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(ad.getByText("Cancelled")).toBeVisible({ timeout: 10_000 });

  // --- umpire duty: mark the umpire of match 2 as missed
  await ad.goto("/admin/duties");
  await expect(ad.getByText(/Match \d+/).first()).toBeVisible({ timeout: 10_000 });
  const duty = ad.getByRole("listitem").filter({ hasText: "assigned" }).first();
  await duty.getByLabel(/Reason for duty/).fill("did not show");
  await duty.getByRole("button", { name: "Mark missed" }).click();
  await expect(ad.getByRole("listitem").filter({ hasText: "missed" }).first()).toBeVisible({ timeout: 10_000 });
  await ad.screenshot({ path: info.outputPath("duties.png"), fullPage: true });
});
