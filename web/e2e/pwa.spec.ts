import { expect, test } from "@playwright/test";
import { apiLog, call, loginPage, seedLeague } from "./helpers";

/** A browser without a real push service: subscribing returns a believable fake subscription. */
function fakePush() {
  const fake = (() => {
    const key = (n: number) => btoa(String.fromCharCode(...Array.from({ length: n }, (_, i) => (i * 7 + n) % 256))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    // a real browser keeps the same endpoint across reloads, so the fake does too
    const endpoint = localStorage.getItem("e2e.endpoint") ?? "https://fcm.googleapis.com/fcm/send/e2e-" + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
    localStorage.setItem("e2e.endpoint", endpoint);
    let live = true;
    const sub = {
      endpoint,
      toJSON: () => ({ endpoint, keys: { p256dh: key(65), auth: key(16) } }),
      unsubscribe: async () => { live = false; localStorage.removeItem("e2e.push"); return true; },
    };
    return { sub, alive: () => live };
  })();
  const stored = () => localStorage.getItem("e2e.push");
  PushManager.prototype.subscribe = async () => { localStorage.setItem("e2e.push", "1"); return fake.sub as unknown as PushSubscription; };
  PushManager.prototype.getSubscription = async () => (stored() && fake.alive() ? (fake.sub as unknown as PushSubscription) : null);
  // lets a test pretend the tab is hidden or visible
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => (window as unknown as { __vis?: string }).__vis ?? "visible" });
}

test("the app can be installed, works offline, and tells you about the browser prompt", async ({ browser, baseURL }) => {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await ctx.newPage();

  // --- manifest and icons
  const manifest = await (await page.request.get("/manifest.webmanifest")).json();
  expect(manifest).toMatchObject({ name: "FFCL digit cricket league", short_name: "FFCL", display: "standalone", start_url: "/" });
  expect(manifest.icons.map((i: { sizes: string; purpose: string }) => `${i.sizes}/${i.purpose}`)).toEqual(["192x192/any", "512x512/any", "512x512/maskable"]);
  for (const icon of manifest.icons) {
    const r = await page.request.get(icon.src);
    expect(r.status()).toBe(200);
    expect(r.headers()["content-type"]).toContain("image/png");
    const png = await r.body(); // the picture really is the size the manifest promises
    expect(`${png.readUInt32BE(16)}x${png.readUInt32BE(20)}`).toBe(icon.sizes);
  }
  // iPhone: the home-screen icon is a 180 x 180 picture linked from every page, and the page can run as an app
  const html = await (await page.request.get("/")).text();
  const touch = html.match(/<link rel="apple-touch-icon" href="([^"]+)"/)?.[1];
  expect(touch, "apple-touch-icon link").toBeTruthy();
  const tp = await (await page.request.get(touch!)).body();
  expect(`${tp.readUInt32BE(16)}x${tp.readUInt32BE(20)}`).toBe("180x180");
  expect(html).toMatch(/<meta name="mobile-web-app-capable" content="yes"/);
  expect(html).toMatch(/<meta name="apple-mobile-web-app-title" content="FFCL"/);
  expect(manifest.theme_color).toBe("#0f3d2e");
  const sw = await page.request.get("/sw.js");
  expect(sw.headers()["content-type"]).toMatch(/javascript/);

  // --- the service worker takes over and an offline visit shows the friendly page
  await page.goto("/league");
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.reload(); // now controlled by the worker
  await expect.poll(() => page.evaluate(() => !!navigator.serviceWorker.controller)).toBe(true);
  await ctx.setOffline(true);
  await page.goto("/league/anything").catch(() => {});
  await expect(page.getByRole("heading", { name: "You are offline" })).toBeVisible({ timeout: 10_000 });
  await ctx.setOffline(false);
  await page.goto("/league");
  await expect(page.getByRole("heading", { name: "Seasons" })).toBeVisible({ timeout: 15_000 });

  // --- the install banner: shown on the browser's prompt, remembered after "Not now"
  await page.evaluate(() => {
    const e = Object.assign(new Event("beforeinstallprompt", { cancelable: true }), { prompt: async () => {}, userChoice: Promise.resolve({ outcome: "dismissed" }) });
    window.dispatchEvent(e);
  });
  const banner = page.getByRole("complementary", { name: "Install the app" });
  await expect(banner).toContainText("Install FFCL on your phone");
  await banner.getByRole("button", { name: "Not now" }).click();
  await expect(banner).toHaveCount(0);
  await page.reload();
  await page.evaluate(() => window.dispatchEvent(Object.assign(new Event("beforeinstallprompt", { cancelable: true }), { prompt: async () => {}, userChoice: Promise.resolve({ outcome: "dismissed" }) })));
  await expect(page.getByRole("complementary", { name: "Install the app" })).toHaveCount(0); // asked once is enough

  // --- iPhone Safari has no prompt, so it is told how to add the app
  const iphone = await browser.newContext({ viewport: { width: 390, height: 844 }, userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1" });
  const ip = await iphone.newPage();
  await ip.goto("/league");
  await expect(ip.getByRole("complementary", { name: "Install the app" })).toContainText("Add to Home Screen");
  void baseURL;
});

test("browser push: turn on, test alert, alerts only when the app is not in front, and the worker shows them", async ({ browser, baseURL }, info) => {
  test.setTimeout(180_000);
  const lg = await seedLeague();
  const [A, B] = lg.teams;
  const player = A.players[1];
  const origin = new URL(baseURL!).origin;
  const page = await loginPage(browser, player, "/notifications", { permissions: ["notifications"] }, fakePush);
  const section = page.getByRole("region", { name: "Push notifications" });

  // --- turn it on
  await expect(section.getByRole("button", { name: "Turn on alerts on this device" })).toBeVisible({ timeout: 15_000 });
  await section.getByRole("button", { name: "Turn on alerts on this device" }).click();
  await expect(section.getByRole("status")).toContainText("Alerts are on for this device", { timeout: 10_000 });
  const devices = await call<{ service: string }[]>("/me/push/subscriptions", "GET", undefined, player.token);
  expect(devices).toHaveLength(1);
  expect(devices[0].service).toBe("fcm.googleapis.com");
  await page.screenshot({ path: info.outputPath("push-settings.png"), fullPage: true });

  // --- choose which alerts: defaults are on for important ones and off for noisy ones
  const wicket = section.getByLabel(/Alert me: .*wicket/i);
  await expect(wicket).not.toBeChecked();
  await expect(section.getByLabel(/Alert me: .*result/i)).toBeChecked();
  await wicket.click();
  await expect.poll(async () => (await call<{ kind: string; push: boolean }[]>("/notifications/prefs", "GET", undefined, player.token)).find((p) => p.kind === "wicket")?.push).toBe(true);

  // --- the test button reaches the push service (dry run in this environment)
  await section.getByRole("button", { name: "Send a test alert" }).click();
  await expect(section.getByRole("status")).toContainText("Test sent", { timeout: 10_000 });
  await expect.poll(() => apiLog().includes("FFCL test notification")).toBe(true);

  // --- while the app is in front, a new notification is NOT also pushed
  const umpire = player; // the admin makes this player the umpire of a match (they are on neither side)
  const m1 = await call<{ id: number }>(`/seasons/${lg.season}/matches`, "POST", { team_a_id: B.id, team_b_id: lg.teams[2].id, umpire_id: lg.umpires[0].id }, lg.admin);
  const before = (apiLog().match(/PUSH DRY RUN/g) ?? []).length;
  const m2 = await call<{ id: number }>(`/seasons/${lg.season}/matches`, "POST", { team_a_id: B.id, team_b_id: lg.teams[3].id }, lg.admin);
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange"))); // visible: heartbeat "fg"
  await page.waitForTimeout(1000);
  await call(`/users/${umpire.id}/roles`, "POST", { role: "umpire" }, lg.admin).catch(() => {});
  await call(`/matches/${m2.id}`, "PATCH", { umpire_id: umpire.id }, lg.admin);
  await expect(page.getByTestId("unread-badge")).toBeVisible({ timeout: 10_000 }); // it arrived in the app
  await page.waitForTimeout(1500);
  expect((apiLog().match(/PUSH DRY RUN/g) ?? []).length).toBe(before);

  // --- once the app is in the background, it is pushed
  await page.evaluate(() => { (window as unknown as { __vis: string }).__vis = "hidden"; document.dispatchEvent(new Event("visibilitychange")); });
  await page.waitForTimeout(1000);
  await call(`/matches/${m1.id}`, "PATCH", { umpire_id: umpire.id }, lg.admin);
  await expect.poll(() => (apiLog().match(/PUSH DRY RUN/g) ?? []).length, { timeout: 10_000 }).toBe(before + 1);
  const line = apiLog().split("\n").filter((l) => l.includes("PUSH DRY RUN")).pop()!;
  expect(line).toContain(`"link": "/matches/${m1.id}"`);
  expect(line).toContain('"kind": "umpire_assigned"');
  expect(line).not.toMatch(/digit/i);

  // --- the service worker shows a delivered push (sent through the browser's own test hook)
  const cdp = await page.context().newCDPSession(page);
  const registrations: string[] = [];
  cdp.on("ServiceWorker.workerRegistrationUpdated", (e: { registrations: { registrationId: string; scopeURL: string }[] }) => {
    for (const r of e.registrations) if (r.scopeURL.startsWith(origin)) registrations.push(r.registrationId);
  });
  await cdp.send("ServiceWorker.enable");
  await expect.poll(() => registrations.length).toBeGreaterThan(0);
  await cdp.send("ServiceWorker.deliverPushMessage", { origin, registrationId: registrations[0], data: JSON.stringify({ id: 99, title: "Match 7 has a result", body: "Pink won by 21 runs", link: "/matches/7" }) });
  await expect.poll(async () => page.evaluate(async () => (await (await navigator.serviceWorker.ready).getNotifications()).map((n) => `${n.title}|${n.body}|${n.data.link}`)), { timeout: 10_000 })
    .toContain("Match 7 has a result|Pink won by 21 runs|/matches/7");

  // --- turn it off again: the device is forgotten on the server
  await page.reload();
  await page.getByRole("region", { name: "Push notifications" }).getByRole("button", { name: "Turn off on this device" }).click();
  await expect(page.getByRole("region", { name: "Push notifications" }).getByRole("status")).toContainText("Alerts are off", { timeout: 10_000 });
  expect(await call<unknown[]>("/me/push/subscriptions", "GET", undefined, player.token)).toHaveLength(0);
});
