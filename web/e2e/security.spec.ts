import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { call, loginPage, newMatch, PASSWORD, seedLeague, user } from "./helpers";

declare global { interface Window { __csp?: string[] } }
const collect = () => {
  window.__csp = [];
  document.addEventListener("securitypolicyviolation", (e) => window.__csp!.push(`${e.violatedDirective} ${e.blockedURI}`));
};

async function violations(page: Page, path: string): Promise<string[]> {
  await page.goto(path);
  await page.waitForLoadState("load");
  await page.waitForTimeout(700); // let the page run its scripts and open its sockets; there is no "idle" while live pages poll
  return page.evaluate(() => window.__csp ?? []);
}

test("every screen runs under the content policy, with the security headers present", async ({ browser, baseURL }, info) => {
  test.setTimeout(240_000);
  const lg = await seedLeague();
  const [A, B] = lg.teams;
  const mid = await newMatch(lg, A, B);
  const slug = (await call<{ slug: string }>(`/seasons/${lg.season}`, "GET", undefined, lg.admin)).slug;
  await call(`/seasons/${lg.season}`, "PATCH", { is_public: true }, lg.admin);

  // the headers
  const res = await fetch(`${baseURL}/privacy`);
  const csp = res.headers.get("content-security-policy") ?? "";
  for (const part of ["default-src 'self'", "frame-ancestors 'none'", "object-src 'none'", "base-uri 'self'", "form-action 'self'"]) expect(csp).toContain(part);
  expect(csp).not.toMatch(/script-src[^;]*https?:\/\//); // no outside script source
  expect(res.headers.get("x-content-type-options")).toBe("nosniff");
  expect(res.headers.get("x-frame-options")).toBe("DENY");
  expect(res.headers.get("referrer-policy")).toBe("strict-origin-when-cross-origin");
  expect(res.headers.get("permissions-policy")).toContain("camera=()");

  const seen: Record<string, string[]> = {};
  const check = async (page: Page, paths: string[]) => { for (const p of paths) { const v = await violations(page, p); if (v.length) seen[p] = v; } };

  const fan = await loginPage(browser, A.players[1], "/fixtures", {}, collect);
  await check(fan, ["/fixtures", "/standings", "/leaderboards", "/insights", "/notifications", "/profile", "/chat", "/history", `/matches/${mid}`, `/teams/${A.id}`, `/players/${A.players[1].id}`, "/disputes"]);
  const ad = await loginPage(browser, lg.adminUser, "/admin", {}, collect);
  await check(ad, ["/admin", "/admin/import", "/admin/users", "/admin/rules", "/admin/audit", "/admin/approvals", `/admin/seasons/${lg.season}`, `/admin/seasons/${lg.season}/setup`, "/admin/moderation", "/admin/disputes"]);
  const anon = await (await browser.newContext({ viewport: { width: 390, height: 844 } })).newPage();
  await anon.addInitScript(collect);
  await check(anon, ["/", "/league", `/league/${slug}`, `/league/${slug}/matches/${mid}`, `/league/${slug}/stats`, "/privacy", "/terms", "/login", "/offline"]);
  expect(seen).toEqual({});

  // the policy really is on: a script from another site is refused
  await anon.goto("/privacy");
  const blocked = await anon.evaluate(async () => {
    const got: string[] = [];
    document.addEventListener("securitypolicyviolation", (e) => got.push(e.violatedDirective));
    const s = document.createElement("script");
    s.src = "https://evil.example/x.js";
    document.head.appendChild(s);
    const f = document.createElement("iframe");
    f.src = "https://evil.example/";
    document.body.appendChild(f);
    await new Promise((r) => setTimeout(r, 500));
    return got;
  });
  expect(blocked.join(" ")).toContain("script-src");
  expect(blocked.join(" ")).toContain("frame-src");
  await anon.screenshot({ path: info.outputPath("privacy.png"), fullPage: true });
});

test("devices, downloading your data, and leaving", async ({ browser }, info) => {
  test.setTimeout(180_000);
  const u = await user("Leaver");
  const phone = await loginPage(browser, u, "/profile");
  const laptop = await loginPage(browser, u, "/profile");
  await expect(laptop.getByRole("region", { name: "Where you are signed in" }).getByRole("listitem")).toHaveCount(3, { timeout: 10_000 }); // the sign-up, the phone and this laptop
  await expect(laptop.getByText("This device")).toBeVisible();
  await laptop.screenshot({ path: info.outputPath("devices.png"), fullPage: true });
  // end the other sign-in from the laptop: the phone is signed out
  const list = laptop.getByRole("region", { name: "Where you are signed in" }).getByRole("listitem");
  await laptop.getByRole("button", { name: /^Sign out / }).first().click();
  await expect(list).toHaveCount(2, { timeout: 10_000 });
  await laptop.getByRole("button", { name: /^Sign out / }).first().click();
  await expect(list).toHaveCount(1, { timeout: 10_000 });
  await phone.reload();
  await phone.waitForURL("**/login", { timeout: 15_000 });

  // download
  const [file] = await Promise.all([laptop.waitForEvent("download"), laptop.getByRole("button", { name: "Download my data" }).click()]);
  const data = JSON.parse(readFileSync((await file.path())!, "utf8"));
  expect(data.profile.email).toBe(u.email);
  expect(JSON.stringify(data)).not.toMatch(/password_hash|refresh/);

  // leave
  await laptop.getByText("Delete my account", { exact: true }).click();
  await laptop.getByLabel("Your password to confirm").fill(PASSWORD);
  await laptop.screenshot({ path: info.outputPath("delete.png"), fullPage: true });
  await laptop.getByRole("button", { name: "Delete my account for good" }).click();
  await laptop.waitForURL(/\/(login)?$/, { timeout: 15_000 }); // signed out, so the app sends them to sign in
  const login = await fetch(`${process.env.E2E_API_URL ?? "http://localhost:8000"}/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: u.email, password: PASSWORD }) });
  expect(login.status).toBe(401);
});
