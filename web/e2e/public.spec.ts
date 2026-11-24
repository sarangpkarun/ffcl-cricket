import { expect, test } from "@playwright/test";
import { API, call, loginPage, newMatch, playMatch, seedLeague } from "./helpers";

const BAT = [5, 6, 1, 2, 3, 4];
const BOWL = [6, 5, 2, 1, 4, 3];

test("a signed-out visitor follows the league: pages, privacy, live match, hiding a season", async ({ browser, baseURL }, info) => {
  test.setTimeout(240_000);
  const lg = await seedLeague();
  const [A, B, C, D] = lg.teams;
  const slug = (await call<{ slug: string }>(`/seasons/${lg.season}`, "GET", undefined, lg.admin)).slug;
  const hidden = A.players[0]; // the batter who scores 21 in the finished match
  await call("/me", "PATCH", { show_publicly: false }, hidden.token);
  await playMatch(lg, await newMatch(lg, A, B), A, B, "a");
  // draft fixtures stay invisible
  await call(`/seasons/${lg.season}/fixtures/generate`, "POST", { start_date: "2031-02-01", times: ["19:00"], timezone: "UTC", replace_drafts: false }, lg.admin).catch(() => {});

  const anon = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await anon.newPage();

  // --- the page source already holds the content (search engines and slow phones need no JavaScript)
  const html = await (await page.request.get(`/league/${slug}/table`)).text();
  expect(html).toContain("Aces");
  expect(html).toContain("Points table");
  expect(html).not.toContain("@t.io"); // no email addresses anywhere

  // --- home and season pages
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "FFCL digit cricket league" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("link", { name: "Sign in" })).toBeVisible();
  await page.goto(`/league/${slug}`);
  await expect(page.getByRole("region", { name: "Latest results" })).toContainText("Aces vs Bulls", { timeout: 15_000 });
  await expect(page.getByRole("region", { name: "Latest results" })).toContainText("won by 21 runs");
  await page.getByRole("link", { name: "Table", exact: true }).click();
  await expect(page.getByRole("row", { name: /^1\. Aces/ })).toContainText("2", { timeout: 15_000 });
  await page.screenshot({ path: info.outputPath("public-table.png"), fullPage: true });

  // --- privacy: the hidden player appears by player code, with no page; fixtures show no drafts
  await page.goto(`/league/${slug}/stats`);
  const runs = page.getByRole("region", { name: "Most runs" });
  await expect(runs.getByRole("listitem").first()).toContainText("21", { timeout: 15_000 });
  await expect(runs.getByRole("listitem").first()).toContainText("FFP"); // the player code
  await expect(page.getByText(hidden.name)).toHaveCount(0);
  await expect(runs.getByRole("link")).toHaveCount(0);
  await page.goto(`/league/${slug}/players/${hidden.id}`);
  await expect(page.getByText("Page not found")).toBeVisible({ timeout: 15_000 });
  await page.goto(`/league/${slug}/players/${A.players[1].id}`);
  await expect(page.getByRole("region", { name: "Batting" })).toBeVisible({ timeout: 15_000 });
  await page.goto(`/league/${slug}/teams/${A.id}`);
  await expect(page.getByRole("region", { name: "Squad" })).toContainText(A.players[1].name, { timeout: 15_000 });
  await expect(page.getByRole("region", { name: "Squad" })).not.toContainText(hidden.name);
  await page.goto(`/league/${slug}/fixtures`);
  await expect(page.getByText("No upcoming matches yet.")).toBeVisible({ timeout: 15_000 });
  await page.goto(`/league/${slug}/rules`);
  await expect(page.getByText(/7 overs of 6 balls/)).toBeVisible({ timeout: 15_000 });

  // --- a live match: the public page updates by itself, and digits stay hidden until the reveal
  const mid = await newMatch(lg, C, D);
  const ump = lg.admin;
  for (const t of [C, D]) await call(`/matches/${mid}/lineup`, "PUT", { team_id: t.id, user_ids: t.players.map((p) => p.id) }, ump);
  await call(`/matches/${mid}/toss/open`, "POST", undefined, ump);
  await call(`/matches/${mid}/toss/winner`, "POST", { winner_team_id: C.id }, ump);
  await call(`/matches/${mid}/toss/decision`, "POST", { decision: "bat" }, C.players[0].token);
  await call(`/matches/${mid}/toss/confirm`, "POST", undefined, ump);
  await call(`/matches/${mid}/start`, "POST", undefined, ump);
  const live = await anon.newPage();
  await live.goto(`/league/${slug}/matches/${mid}`);
  await expect(live.getByText("● Live")).toBeVisible({ timeout: 15_000 }); // the public socket connected
  const batter = C.players[0];
  const bowler = D.players[0];
  await call(`/matches/${mid}/overs/start`, "POST", { bowler_id: bowler.id, batter_id: batter.id }, ump);
  await expect(live.getByRole("region", { name: "Current over" })).toContainText("waiting for the umpire's signal", { timeout: 10_000 });
  await call(`/matches/${mid}/overs/current/signal`, "POST", undefined, ump);
  await expect(live.getByRole("region", { name: "Current over" })).toContainText("players are choosing their digits", { timeout: 10_000 });
  await call(`/matches/${mid}/overs/current/submit`, "POST", { digits: BOWL }, bowler.token);
  await expect(live.getByRole("region", { name: "Current over" })).toContainText(`Bowler ${bowler.name} ✅`, { timeout: 10_000 });
  await call(`/matches/${mid}/overs/current/submit`, "POST", { digits: BAT }, batter.token);
  await call(`/matches/${mid}/overs/current/lock`, "POST", undefined, ump);
  // nothing but state is visible while the digits are locked: no digit string is on the page
  await expect(live.getByRole("region", { name: "Current over" })).toContainText("digits locked", { timeout: 10_000 });
  expect(await live.locator("body").innerText()).not.toContain("5,6,1,2,3,4");
  await call(`/matches/${mid}/overs/current/reveal`, "POST", undefined, ump);
  await call(`/matches/${mid}/overs/current/resolve`, "POST", undefined, ump);
  await expect(live.getByText("21/0")).toBeVisible({ timeout: 10_000 }); // the scorecard moved without a reload
  await live.screenshot({ path: info.outputPath("public-live.png"), fullPage: true });
  const j = await (await live.request.get(`${API}/public/matches/${mid}/live`)).json();
  expect(JSON.stringify(j)).not.toContain("@t.io");

  // --- sitemap and robots
  const sm = await (await page.request.get("/sitemap.xml")).text();
  expect(sm).toContain(`/league/${slug}/matches/${mid}`);
  expect(sm).not.toContain(`/players/${hidden.id}`);
  expect(await (await page.request.get("/robots.txt")).text()).toContain("Disallow: /admin");

  // --- a signed-in user at "/" still gets their dashboard
  const me = await loginPage(browser, B.players[1], "/");
  await expect(me.getByRole("heading", { name: "Live now" })).toBeVisible({ timeout: 15_000 });
  await expect(me.getByText("FFCL Season 24")).toHaveCount(0); // never a made-up match
  await expect(me.getByRole("link", { name: "Fixtures", exact: true })).toBeVisible();

  // --- an admin hides the season; the public can no longer see it
  const ad = await loginPage(browser, lg.adminUser, `/admin/seasons/${lg.season}/setup`);
  const box = ad.getByRole("region", { name: "Archive and exports" });
  await expect(box).toContainText(`/league/${slug}`, { timeout: 10_000 });
  await box.getByLabel("Show this season on the public site").click();
  await expect(box).toContainText("(hidden)", { timeout: 10_000 });
  await page.goto(`/league/${slug}/table`);
  await expect(page.getByText("Page not found")).toBeVisible({ timeout: 15_000 });
  await page.goto("/league");
  await expect(page.getByRole("link", { name: new RegExp(`League ${lg.season}`) })).toHaveCount(0);
  await box.getByLabel("Show this season on the public site").click();
  await expect(box).not.toContainText("(hidden)", { timeout: 10_000 });
  void baseURL;
});
