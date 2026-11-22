import { expect, test, type Page } from "@playwright/test";
import { loginPage, seed } from "./helpers";

const keys = (d: number[]) => d.map((x) => `digit ${x}`);
async function enter(page: Page, digits: number[]) {
  for (const k of keys(digits)) await page.getByRole("button", { name: k }).click();
  await page.getByRole("button", { name: "Confirm" }).click();
}

test("umpire runs an over with two phones; digits stay private until reveal", async ({ browser }, info) => {
  const { ump, A, B, match } = await seed({ start: true });
  const m = { id: match };

  // ---- UI: three phones ----
  const path = `/matches/${m.id}`;
  const umpPage = await loginPage(browser, ump, path);
  const batter = A[0];
  const bowler = B[0];
  const batterPage = await loginPage(browser, batter, path);
  const bowlerPage = await loginPage(browser, bowler, path);

  await umpPage.getByText("Umpire console").waitFor();
  for (const p of [umpPage, batterPage, bowlerPage]) await expect(p.getByText("● Live")).toBeVisible({ timeout: 10_000 });
  await umpPage.locator("select").nth(0).selectOption({ label: bowler.name });
  await umpPage.locator("select").nth(1).selectOption({ label: batter.name });
  await umpPage.getByRole("button", { name: "Start over" }).click();
  await umpPage.getByRole("button", { name: /Send signal/ }).click();

  await expect(bowlerPage.getByRole("button", { name: "digit 1" })).toBeVisible({ timeout: 10_000 });
  await expect(batterPage.getByRole("button", { name: "digit 1" })).toBeVisible({ timeout: 10_000 });
  await bowlerPage.screenshot({ path: info.outputPath("bowler-keypad.png") });

  await enter(bowlerPage, [6, 5, 2, 1, 4, 3]);
  await expect(bowlerPage.getByText(/Locked/)).toBeVisible();
  await bowlerPage.reload(); // a refresh mid-over must restore the locked state from the server
  await expect(bowlerPage.getByText(/Locked/)).toBeVisible({ timeout: 10_000 });
  // opponent's page must never contain the bowler's digits before the reveal
  await expect(batterPage.getByRole("button", { name: "digit 1" })).toBeVisible();
  await expect(umpPage.getByText(/Bowler ✅/)).toBeVisible({ timeout: 5_000 });
  await enter(batterPage, [5, 6, 1, 2, 3, 4]);
  await expect(umpPage.getByText(/Batter ✅/)).toBeVisible({ timeout: 10_000 });
  const secret = "6️⃣ 5️⃣ 2️⃣ 1️⃣ 4️⃣ 3️⃣";
  expect(await batterPage.content()).not.toContain(secret);

  await umpPage.getByRole("button", { name: "Lock submissions" }).click();
  await expect(umpPage.getByText(secret)).toBeVisible();          // umpire sees after lock
  await batterPage.waitForTimeout(3500);                           // let the batter's poll run
  expect(await batterPage.content()).not.toContain(secret);        // players still blind
  await umpPage.getByRole("button", { name: "Reveal digits" }).click();
  await expect(batterPage.getByText(secret)).toBeVisible({ timeout: 10_000 });
  await umpPage.getByRole("button", { name: /Calculate and publish/ }).click();

  // 5v6 + 6v5 + 1v2 + 2v1 + 3v4 + 4v3 = 21 runs, no wickets
  for (const p of [umpPage, batterPage, bowlerPage]) {
    await expect(p.getByText("21/0")).toBeVisible({ timeout: 10_000 });
  }
  await batterPage.screenshot({ path: info.outputPath("scoreboard.png"), fullPage: true });
});
