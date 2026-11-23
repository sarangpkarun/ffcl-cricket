import { expect, test, type Page } from "@playwright/test";
import { call, newMatch, playMatch, seedLeague } from "./helpers";

/** Bytes sent over the network for one kind of resource while a page loads. */
async function measure(page: Page, path: string, ready: string | RegExp) {
  const sizes: Record<string, number> = {};
  const rsc: string[] = [];
  const pending: Promise<void>[] = [];
  page.on("response", (r) => {
    const type = r.request().resourceType();
    if (r.url().includes("_rsc=")) rsc.push(r.url());
    pending.push(r.request().sizes().then((s) => { sizes[type] = (sizes[type] ?? 0) + s.responseBodySize; }).catch(() => {}));
  });
  await page.goto(path);
  await expect(page.getByText(ready).first()).toBeVisible({ timeout: 20_000 });
  await page.waitForLoadState("networkidle");
  await Promise.all(pending);
  return { sizes, rsc };
}

test("public pages put their metadata in the head, stay small, and do not prefetch the rest of the site", async ({ browser }) => {
  test.setTimeout(180_000);
  const lg = await seedLeague();
  const [A, B] = lg.teams;
  const mid = await newMatch(lg, A, B);
  await playMatch(lg, mid, A, B, "a");
  const slug = (await call<{ slug: string }>(`/seasons/${lg.season}`, "GET", undefined, lg.admin)).slug;
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await ctx.newPage();

  // --- every public page has its title, description, canonical address and share tags in <head>, with no JavaScript needed
  const pages = [
    { path: "/", title: "FFCL digit cricket league" },
    { path: "/league", title: "Seasons" },
    { path: `/league/${slug}`, title: lg.teams.length ? "" : "" },
    { path: `/league/${slug}/fixtures`, title: "Fixtures" },
    { path: `/league/${slug}/table`, title: "Points table" },
    { path: `/league/${slug}/stats`, title: "Leaderboards" },
    { path: `/league/${slug}/insights`, title: "Insights" },
    { path: `/league/${slug}/rules`, title: "Rules" },
    { path: `/league/${slug}/teams/${A.id}`, title: "Aces" },
    { path: `/league/${slug}/matches/${mid}`, title: "Aces vs Bulls" },
    { path: "/league/history", title: "History" },
  ];
  for (const p of pages) {
    const html = await (await page.request.get(p.path, { headers: { "user-agent": "WhatsApp/2.23 A" } })).text(); // a link-preview bot
    const head = html.slice(0, html.indexOf("</head>"));
    expect(head, p.path).toContain("<title>");
    if (p.title) expect(head, p.path).toContain(p.title);
    expect(head, p.path).toMatch(/<meta name="description" content="[^"]{20,}"/);
    expect(head, p.path).toContain('rel="canonical"');
    expect(head, p.path).toContain('property="og:title"');
  }
  // a match page also describes itself to search engines as a sports event, and has a share image
  const matchHtml = await (await page.request.get(`/league/${slug}/matches/${mid}`)).text();
  expect(matchHtml).toContain('"@type":"SportsEvent"');
  expect(matchHtml).toMatch(/property="og:image"/);
  for (const img of [`/league/${slug}/matches/${mid}/opengraph-image`, "/opengraph-image"]) {
    const r = await page.request.get(img);
    expect(r.status(), img).toBe(200);
    expect(r.headers()["content-type"], img).toContain("image/png");
    expect((await r.body()).length, img).toBeGreaterThan(5_000); // a real picture, not an empty file
  }
  // pages that must not be found say so to search engines
  const gone = await (await page.request.get(`/league/${slug}/players/999999`)).text();
  expect(gone).toContain("Page not found");

  // --- small and quiet: a season page loads little code and does not fetch the pages it links to
  const overview = await measure(page, `/league/${slug}`, "Latest results");
  expect(overview.sizes.script ?? 0).toBeLessThan(200 * 1024); // about 145 KB today
  expect(overview.sizes.font ?? 0).toBeLessThan(40 * 1024); // one font file
  expect(overview.rsc, "link prefetches").toEqual([]);
  const stats = await measure(await (await browser.newContext({ viewport: { width: 390, height: 844 } })).newPage(), `/league/${slug}/stats`, "Most runs");
  expect(stats.rsc, "link prefetches on a page with many links").toEqual([]);
  const total = Object.values(stats.sizes).reduce((a, b) => a + b, 0);
  expect(total).toBeLessThan(350 * 1024);
});
