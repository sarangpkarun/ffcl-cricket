import { expect, test } from "@playwright/test";
import { loginPage, newMatch, playMatch, seedLeague } from "./helpers";

test("leaderboards, player of the match, player and team pages", async ({ browser }, info) => {
  test.setTimeout(180_000);
  const lg = await seedLeague();
  const [A, B, C] = lg.teams;
  const fan = await loginPage(browser, B.players[1], "/leaderboards");
  await expect(fan.getByText(/No statistics yet/)).toBeVisible({ timeout: 10_000 });

  const m1 = await newMatch(lg, A, B);
  await playMatch(lg, m1, A, B, "a");
  const m2 = await newMatch(lg, A, C);
  await playMatch(lg, m2, A, C, "a");
  await fan.reload();
  const runs = fan.getByRole("region", { name: "Most runs" });
  await expect(runs.getByRole("listitem").first()).toContainText(A.players[0].name, { timeout: 10_000 });
  await expect(runs.getByRole("listitem").first()).toContainText("42"); // 21 in each of two matches
  await expect(fan.getByRole("region", { name: "Best strike rate" })).toContainText("350.00"); // 42 off 12 balls
  await expect(fan.getByRole("region", { name: "Best win percentage" }).getByRole("listitem").first()).toContainText("100%");
  await fan.getByLabel("Team").selectOption({ label: "Bulls" });
  await expect(runs).toContainText("Nobody yet");
  await fan.screenshot({ path: info.outputPath("leaderboards.png"), fullPage: true });

  // --- the admin chooses the player of the match; players see it
  const ad = await loginPage(browser, lg.adminUser, `/matches/${m1}`);
  const panel = ad.getByRole("region", { name: "Player of the match" });
  await expect(panel).toContainText("Suggested: " + A.players[0].name, { timeout: 10_000 });
  await panel.getByLabel("Choose player of the match").selectOption(String(A.players[0].id));
  await panel.getByRole("button", { name: "Award player of the match" }).click();
  await expect(panel.getByRole("link", { name: A.players[0].name })).toBeVisible({ timeout: 10_000 });
  const pl = await loginPage(browser, B.players[2], `/matches/${m1}`);
  await expect(pl.getByRole("region", { name: "Player of the match" })).toContainText(A.players[0].name, { timeout: 10_000 });
  await expect(pl.getByLabel("Choose player of the match")).toHaveCount(0); // only officials choose

  // --- player page
  await pl.goto(`/players/${A.players[0].id}`);
  await expect(pl.getByRole("heading", { name: A.players[0].name })).toBeVisible({ timeout: 10_000 });
  await expect(pl.getByRole("region", { name: "Batting" })).toContainText("42");
  await expect(pl.getByRole("region", { name: "Bowling" })).toContainText("Player of match");
  await expect(pl.getByRole("region", { name: "Match history" }).getByRole("listitem")).toHaveCount(2);
  await pl.screenshot({ path: info.outputPath("player.png"), fullPage: true });

  // --- team page block
  await pl.goto(`/teams/${A.id}`);
  await expect(pl.getByRole("region", { name: "Team statistics" })).toContainText("Win 100%", { timeout: 10_000 });
  await expect(pl.getByRole("region", { name: "Team statistics" })).toContainText(A.players[0].name);
});
