import { expect, test } from "@playwright/test";
import { call, loginPage, newMatch, playMatch, seedLeague } from "./helpers";

test("analytics: match charts, team and player sections, season insights, digit habits only after the season", async ({ browser }, info) => {
  test.setTimeout(240_000);
  const lg = await seedLeague();
  const [A, B, C] = lg.teams;
  const mid = await newMatch(lg, A, B);
  await playMatch(lg, mid, A, B, "a");
  await playMatch(lg, await newMatch(lg, A, C), A, C, "b");
  const slug = (await call<{ slug: string }>(`/seasons/${lg.season}`, "GET", undefined, lg.admin)).slug;

  // --- a player opens the finished match and its analytics
  const pl = await loginPage(browser, B.players[1], `/matches/${mid}`);
  const panel = pl.locator("details", { hasText: "Match analytics" });
  await panel.locator("summary").click();
  await expect(panel.getByRole("img", { name: /Runs after each ball/ })).toBeVisible({ timeout: 15_000 });
  await expect(panel.getByRole("img", { name: /Runs after each ball/ })).toHaveAttribute("aria-label", /Aces 21\/7/);
  await expect(panel.getByRole("img", { name: /Runs in each over/ })).toBeVisible();
  await expect(panel).toContainText("Biggest over: 21 runs in over 1");
  await expect(panel.getByRole("region", { name: "Powerplays" })).toContainText("Bowling powerplay");
  await expect(panel.getByRole("region", { name: "Powerplays" })).toContainText("21 runs, 1 wkt (18.00/over)");
  await pl.screenshot({ path: info.outputPath("match-analytics.png"), fullPage: true });

  // --- team and player sections
  await pl.goto(`/teams/${A.id}`);
  const team = pl.locator("details", { hasText: "Team analytics" });
  await team.locator("summary").click();
  await expect(team.getByText("Batting first")).toBeVisible({ timeout: 15_000 });
  await expect(team.getByText("1/2").first()).toBeVisible(); // won one of two batting first
  await expect(team.getByRole("region", { name: "Toss" })).toContainText("Won 2, lost 0");
  await pl.goto(`/players/${A.players[0].id}`);
  const player = pl.locator("details", { hasText: "Analytics" });
  await player.locator("summary").click();
  await expect(player.getByRole("region", { name: "Form" })).toBeVisible({ timeout: 15_000 });
  await expect(player.getByRole("region", { name: "By over type" })).toContainText("Normal overs");
  await expect(player.getByText(/Digit habits are shown once the season is finished/)).toBeVisible(); // still being played

  // --- season insights, signed in and public
  await pl.goto("/insights");
  await expect(pl.getByText("Avg 1st innings")).toBeVisible({ timeout: 15_000 });
  await expect(pl.getByRole("region", { name: "Teams" })).toContainText("Aces");
  await expect(pl.getByText(/Digit habits are shown once the season is finished/)).toBeVisible();
  const anon = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const pub = await anon.newPage();
  const html = await (await pub.request.get(`/league/${slug}/insights`)).text();
  expect(html).toContain("Teams compared"); // already in the page source
  await pub.goto(`/league/${slug}/insights`);
  await expect(pub.getByText(/Digit habits are shown once the season is finished/)).toBeVisible({ timeout: 15_000 });
  await pub.goto(`/league/${slug}/matches/${mid}`);
  const pm = pub.locator("details", { hasText: "Match analytics" });
  await pm.locator("summary").click();
  await expect(pm.getByRole("img", { name: /Runs after each ball/ })).toBeVisible({ timeout: 15_000 });
  await pub.goto(`/league/${slug}/teams/${A.id}`);
  await expect(pub.getByText("Batting by over type")).toBeVisible({ timeout: 15_000 });

  // --- the season ends: now the digit habits appear, everywhere
  await call(`/seasons/${lg.season}`, "PATCH", { status: "completed" }, lg.admin);
  await pl.goto("/insights");
  await pl.getByLabel("Season").selectOption(String(lg.season)); // other tests leave active seasons behind, so choose ours
  await expect(pl.getByRole("region", { name: "Digits chosen across the season" })).toContainText("As batter", { timeout: 15_000 });
  await expect(pl.getByRole("region", { name: "Digits chosen across the season" })).toContainText("favourite");
  await pl.goto(`/players/${A.players[0].id}`);
  await pl.locator("details", { hasText: "Analytics" }).locator("summary").click();
  await expect(pl.getByRole("region", { name: "Digit habits" })).toContainText("As batter", { timeout: 15_000 });
  await pub.goto(`/league/${slug}/insights`);
  await expect(pub.getByRole("region", { name: "Digits chosen across the season" })).toContainText("As bowler", { timeout: 15_000 });
  await pub.screenshot({ path: info.outputPath("insights.png"), fullPage: true });
});
