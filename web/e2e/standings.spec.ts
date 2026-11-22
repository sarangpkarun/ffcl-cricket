import { expect, test } from "@playwright/test";
import { call, loginPage, newMatch, playMatch, seedLeague } from "./helpers";

test("league table, knockouts from the admin screen, the final and the champion", async ({ browser }, info) => {
  test.setTimeout(240_000);
  const lg = await seedLeague();
  const [A, B, C, D] = lg.teams;
  const fan = await loginPage(browser, A.players[1], "/standings");
  await expect(fan.getByText(/No results yet/)).toBeVisible({ timeout: 10_000 });

  // --- the league: Aces beat everyone, Bulls beat Cobras and Dragons, Cobras beat Dragons
  for (const [x, y] of [[A, B], [A, C], [A, D], [B, C], [B, D], [C, D]] as const) {
    await playMatch(lg, await newMatch(lg, x, y), x, y, "a");
  }
  await fan.reload();
  const top = fan.getByRole("row", { name: /^1\. Aces/ });
  await expect(top).toContainText("6"); // 3 wins x 2 points
  await expect(top).toContainText("+3.000"); // 21 against 0 each time, the loser all out for the full 7 overs
  await expect(fan.getByRole("row", { name: /^4\. Dragons/ })).toContainText("-3.000");
  for (const [i, name] of ["Aces", "Bulls", "Cobras", "Dragons"].entries()) {
    await expect(fan.getByRole("row", { name: new RegExp(`^${i + 1}\\. ${name}`) })).toBeVisible();
  }
  await expect(fan.getByText(/Top 4 qualify\. Win 2, tie 1, loss 0\./)).toBeVisible();
  await fan.screenshot({ path: info.outputPath("table.png"), fullPage: true });

  // --- the admin creates the knockouts from the setup page
  const ad = await loginPage(browser, lg.adminUser, `/admin/seasons/${lg.season}/setup`);
  const section = ad.getByRole("region", { name: "Knockouts setup" });
  await expect(section).toContainText("The league is finished", { timeout: 10_000 });
  await section.getByLabel("First semi-final").fill("2031-06-01T18:00");
  await section.getByLabel(/Second semi-final/).fill("2031-06-01T21:00");
  await section.getByRole("button", { name: "Create the knockouts" }).click();
  await expect(section.getByRole("status")).toContainText("Semi-final 1 Aces v Dragons", { timeout: 10_000 });
  await expect(section.getByRole("status")).toContainText("Semi-final 2 Bulls v Cobras");

  await fan.reload();
  await expect(fan.getByRole("link", { name: /Semi-final 1: Aces vs Dragons/ })).toBeVisible({ timeout: 10_000 });
  await expect(fan.getByRole("link", { name: /Semi-final 2: Bulls vs Cobras/ })).toBeVisible();
  await expect(fan.getByRole("link", { name: /^Final:/ })).toHaveCount(0);

  // --- the semi-finals are played; the final appears by itself
  const bracket = await call<{ matches: { id: number; round_label: string }[] }>(`/seasons/${lg.season}/bracket`, "GET", undefined, lg.admin);
  const id = (label: string) => bracket.matches.find((m) => m.round_label === label)!.id;
  await playMatch(lg, id("Semi-final 1"), A, D, "a");
  await playMatch(lg, id("Semi-final 2"), B, C, "a");
  await fan.reload();
  await expect(fan.getByRole("link", { name: /Final: Aces vs Bulls/ })).toBeVisible({ timeout: 10_000 });
  await expect(fan.getByRole("link", { name: /Semi-final 1: Aces vs Dragons/ })).toContainText("Aces won by 21 runs");
  await fan.screenshot({ path: info.outputPath("bracket.png"), fullPage: true });

  // --- the final: Bulls chase it down and are champions
  const after = await call<{ matches: { id: number; round_label: string }[] }>(`/seasons/${lg.season}/bracket`, "GET", undefined, lg.admin);
  await playMatch(lg, after.matches.find((m) => m.round_label === "Final")!.id, A, B, "b");
  await fan.reload();
  await expect(fan.getByRole("status").filter({ hasText: "Bulls are champions" })).toBeVisible({ timeout: 10_000 });
  // the league table itself is untouched by the knockouts
  await expect(fan.getByRole("row", { name: /^1\. Aces/ })).toContainText("6");
});
