import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { call, loginPage, newMatch, playMatch, seedLeague } from "./helpers";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

/** Fail on anything serious or critical, and say exactly where. */
async function scan(page: Page, name: string, ready: string | RegExp) {
  await expect(page.getByText(ready).filter({ visible: true }).first()).toBeVisible({ timeout: 20_000 }); // earlier pages can stay in the DOM, hidden
  await page.waitForTimeout(300); // let late client updates settle
  const result = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  const bad = result.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  const lines = bad.map((v) => `${name}: ${v.id} (${v.impact}) ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")} -- ${v.help}`);
  expect(lines, lines.join("\n")).toEqual([]);
}

test("the public site has no serious accessibility problems", async ({ browser }) => {
  test.setTimeout(300_000);
  const lg = await seedLeague();
  const [A, B] = lg.teams;
  const mid = await newMatch(lg, A, B);
  await playMatch(lg, mid, A, B, "a");
  const slug = (await call<{ slug: string }>(`/seasons/${lg.season}`, "GET", undefined, lg.admin)).slug;
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await ctx.newPage();
  const pages: [string, string, string | RegExp][] = [
    ["home", "/", "FFCL digit cricket league"],
    ["seasons", "/league", "Seasons"],
    ["overview", `/league/${slug}`, "Latest results"],
    ["fixtures", `/league/${slug}/fixtures`, "Upcoming"],
    ["results", `/league/${slug}/results`, /won by 21 runs/],
    ["table", `/league/${slug}/table`, "Points table"],
    ["stats", `/league/${slug}/stats`, "Most runs"],
    ["insights", `/league/${slug}/insights`, "Teams compared"],
    ["rules", `/league/${slug}/rules`, "The match"],
    ["team", `/league/${slug}/teams/${A.id}`, "Squad"],
    ["player", `/league/${slug}/players/${A.players[1].id}`, "Batting"],
    ["match", `/league/${slug}/matches/${mid}`, /won by 21 runs/],
    ["history", "/league/history", "Season history"],
    ["offline", "/offline", "You are offline"],
    ["login", "/login", /Sign in/],
    ["register", "/register", /Create/],
  ];
  for (const [name, path, ready] of pages) {
    await page.goto(path);
    await scan(page, name, ready);
  }
  // the charts, opened
  await page.goto(`/league/${slug}/matches/${mid}`);
  await page.locator("details", { hasText: "Match analytics" }).locator("summary").click();
  await scan(page, "match analytics", "Runs in each over");
});

test("the signed-in app and the admin screens have no serious accessibility problems", async ({ browser }) => {
  test.setTimeout(300_000);
  const lg = await seedLeague();
  const [A, B] = lg.teams;
  const mid = await newMatch(lg, A, B);
  await playMatch(lg, mid, A, B, "a");
  await call("/disputes", "POST", { kind: "scoring", body: "The second innings was scored wrongly, the last wicket should not have counted.", match_id: mid }, A.players[0].token);
  const cap = await loginPage(browser, A.players[0], "/fixtures");
  const player: [string, string, string | RegExp][] = [
    ["fixtures", "/fixtures", "Fixtures"],
    ["standings", "/standings", "Points table"],
    ["leaderboards", "/leaderboards", "Leaderboards"],
    ["insights", "/insights", "Season insights"],
    ["notifications", "/notifications", "Notifications"],
    ["profile", "/profile", "My profile"],
    ["disputes", "/disputes", "Disputes"],
    ["chat", "/chat", /Chat|Season/],
    ["team", `/teams/${A.id}`, "Replace a player"],
    ["player", `/players/${A.players[0].id}`, "Batting"],
    ["match", `/matches/${mid}`, /won by 21 runs/],
    ["dispute", "/disputes/1", /./],
  ];
  for (const [name, path, ready] of player) {
    if (name === "dispute") continue;
    await cap.goto(path);
    await scan(cap, name, ready);
  }
  const ad = await loginPage(browser, lg.adminUser, "/admin");
  const admin: [string, string, string | RegExp][] = [
    ["admin home", "/admin", "Seasons"],
    ["season dashboard", `/admin/seasons/${lg.season}`, "Waiting for you"],
    ["season setup", `/admin/seasons/${lg.season}/setup`, "Archive and exports"],
    ["disputes", "/admin/disputes", "Disputes"],
    ["approvals", "/admin/approvals", "Roster changes"],
    ["rules", "/admin/rules", "Rule versions"],
    ["audit", "/admin/audit", "Audit log"],
    ["people", "/admin/users", "People"],
    ["adjustments", "/admin/adjustments", "Points adjustments"],
    ["duties", "/admin/duties", "Umpire duties"],
    ["moderation", "/admin/moderation", "Chat moderation"],
    ["add players", "/admin/import", "Add players"],
  ];
  for (const [name, path, ready] of admin) {
    await ad.goto(path);
    await scan(ad, name, ready);
  }
});
