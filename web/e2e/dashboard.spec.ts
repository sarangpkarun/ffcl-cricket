import { expect, test } from "@playwright/test";
import { loginPage, newMatch, seedLeague } from "./helpers";

test("the home screen shows the real season and its next matches, and they open", async ({ browser }, info) => {
  const lg = await seedLeague();
  const [A, B] = lg.teams;
  const mid = await newMatch(lg, A, B);
  const page = await loginPage(browser, A.players[1], "/");
  await expect(page.getByRole("heading", { name: /^League / })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("FFCL Season 24")).toHaveCount(0);
  const next = page.getByRole("region", { name: "Next matches" });
  const card = next.getByRole("link").first();
  await expect(card).toContainText("Aces");
  await expect(card).toContainText("Bulls");
  await page.screenshot({ path: info.outputPath("home.png"), fullPage: true });
  await card.click();
  await page.waitForURL(`**/matches/${mid}`);
});
