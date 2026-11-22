import { expect, test, type Page } from "@playwright/test";
import { call, loginPage, seed } from "./helpers";

const box = (p: Page) => p.getByRole("textbox", { name: "Message", exact: true });
const badge = (p: Page) => p.getByTestId("unread-badge");

test("notifications, live match feed and the submission chat lock", async ({ browser }, info) => {
  const { ut, A, B, match } = await seed({ start: false });
  const m = `/matches/${match}`;
  const batter = A[0]; // Pink captain
  const bowler = B[0]; // Green captain
  const capA = await loginPage(browser, batter, m);
  const capB = await loginPage(browser, bowler, m);
  const umpire = (path: string, body?: unknown) => call(`${m}/${path}`, "POST", body, ut);

  // wait until each phone's notification socket is connected, so events arrive live
  for (const p of [capA, capB]) await expect(p.locator('a[data-live="true"]')).toBeVisible({ timeout: 10_000 });

  // --- the toss opens: both captains get a toast and a badge
  await umpire("toss/open");
  for (const p of [capA, capB]) {
    await expect(p.getByRole("status").filter({ hasText: "The toss is open" })).toBeVisible({ timeout: 10_000 });
    await expect(badge(p)).toHaveText("1");
  }
  await capA.getByRole("status").getByRole("button", { name: "Dismiss notification" }).click();

  // --- the inbox lists it; opening it clears the badge and goes to the match
  await capA.getByRole("link", { name: /Notifications/ }).click();
  await expect(capA.getByRole("button", { name: /The toss is open/ })).toBeVisible();
  await capA.getByRole("button", { name: /The toss is open/ }).click();
  await capA.waitForURL(`**${m}`);
  await expect(badge(capA)).toHaveCount(0);
  await expect(badge(capB)).toHaveText("1"); // the other captain still has theirs

  // --- toss, start: the announcements appear in the match chat without any reload
  await capA.getByRole("tab", { name: "Chat" }).click();
  await expect(capA.getByText("● Live")).toBeVisible({ timeout: 10_000 });
  await capB.getByRole("tab", { name: "Chat" }).click();
  await expect(capB.getByText("● Live")).toBeVisible({ timeout: 10_000 });
  await umpire("toss/winner", { winner_team_id: (await call<{ team_a_id: number }>(m, "GET", undefined, ut)).team_a_id });
  await call(`${m}/toss/decision`, "POST", { decision: "bat" }, ut);
  await umpire("toss/confirm");
  await umpire("start");
  await expect(capA.getByText("🪙 Toss won by Pink.")).toBeVisible({ timeout: 10_000 });
  await expect(capB.getByText("🏏 Pink elected to bat first.")).toBeVisible();
  await expect(capB.getByText("🎾 First innings started. Pink are batting.")).toBeVisible();

  // --- an over opens: the pair are told it is their turn and the composer is locked
  await call(`${m}/overs/start`, "POST", { bowler_id: bowler.id, batter_id: batter.id }, ut);
  await expect(box(capA)).toBeVisible(); // not locked until the signal
  await umpire("overs/current/signal");
  for (const p of [capA, capB]) {
    await expect(p.getByRole("status").filter({ hasText: /Chat is paused for you/ })).toBeVisible({ timeout: 10_000 });
    await expect(box(p)).toHaveCount(0);
    await expect(p.getByText(/Over 1: .* bowls to .*Submissions are open/)).toBeVisible();
  }
  await expect(capB.getByRole("status").filter({ hasText: "Over 1: submit your digits now" })).toBeVisible();
  await capB.screenshot({ path: info.outputPath("chat-locked.png") });

  // --- the pair submit, the umpire locks: chat opens again
  await call(`${m}/overs/current/submit`, "POST", { digits: "652143" }, bowler.token);
  await call(`${m}/overs/current/submit`, "POST", { digits: "561234" }, batter.token);
  await umpire("overs/current/lock");
  for (const p of [capA, capB]) await expect(box(p)).toBeVisible({ timeout: 10_000 });

  // --- reveal + resolve: the over summary and a six are announced
  await umpire("overs/current/reveal");
  await umpire("overs/current/resolve");
  await expect(capB.getByText("📊 Over 1 done: 21 runs, 0 wickets. Pink 21/0 (1.0 ov).")).toBeVisible({ timeout: 10_000 });
  await expect(capB.getByText(/🔥 .* scored 6 runs \(1\.2\)\./)).toBeVisible();
  // no digit sequences ever appear in the feed
  expect(await capB.content()).not.toContain("652143");
  expect(await capB.content()).not.toContain("561234");

  // --- preferences stick across a reload
  await capA.goto("/notifications");
  const everyOver = capA.getByRole("checkbox", { name: "Every over finishes in my match" });
  await expect(everyOver).not.toBeChecked();
  await everyOver.check();
  await capA.reload();
  await expect(capA.getByRole("checkbox", { name: "Every over finishes in my match" })).toBeChecked({ timeout: 10_000 });
  await capA.getByRole("button", { name: "Mark all read" }).click();
  await expect(badge(capA)).toHaveCount(0);
});
