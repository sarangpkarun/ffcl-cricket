import { expect, test } from "@playwright/test";

test("keyboard users can skip the header, and nothing animates when motion is reduced", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: "reduce" });
  const page = await ctx.newPage();
  await page.goto("/league");
  await expect(page.getByRole("heading", { name: "Seasons" })).toBeVisible({ timeout: 15_000 });

  // the first Tab lands on a visible "skip" link, and using it moves focus into the page content
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to main content" });
  await expect(skip).toBeFocused();
  await expect(skip).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page.locator("main")).toBeFocused();
  // the header links come right after it in the order a person would expect
  await page.goto("/league"); // a fresh visit: using the skip link added "#main" to the address, and a browser starts from there
  await expect(page.getByRole("heading", { name: "Seasons" })).toBeVisible({ timeout: 15_000 });
  await page.waitForLoadState("networkidle"); // a big page can still be hydrating; Tab order is only meaningful once it is done
  await page.waitForTimeout(500);
  const order: string[] = [];
  for (let i = 0; i < 3; i++) {
    await page.keyboard.press("Tab");
    order.push(await page.evaluate(() => (document.activeElement?.textContent ?? "").trim()));
  }
  expect(order).toEqual(["Skip to main content", "FFCL", "Seasons"]);

  // reduced motion: an animated element finishes instantly
  const ms = await page.evaluate(() => {
    const d = document.createElement("div");
    d.className = "animate-pulse";
    document.body.append(d);
    const v = parseFloat(getComputedStyle(d).animationDuration) * 1000;
    d.remove();
    return v;
  });
  expect(ms).toBeLessThan(1);

  // without the setting the same element does animate
  const normal = await (await browser.newContext()).newPage();
  await normal.goto("/league");
  const full = await normal.evaluate(() => {
    const d = document.createElement("div");
    d.className = "animate-pulse";
    document.body.append(d);
    const v = parseFloat(getComputedStyle(d).animationDuration) * 1000;
    d.remove();
    return v;
  });
  expect(full).toBeGreaterThan(100);
});
