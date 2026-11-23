import { expect, test } from "@playwright/test";
import { call, loginPage, newMatch, playMatch, run, seedLeague } from "./helpers";

const BODY = `[${run}] The second innings was scored wrongly, the last wicket should not have counted.`;

test("a captain disputes a result, the other side replies, an admin resolves it, everyone is told", async ({ browser }, info) => {
  test.setTimeout(240_000);
  const lg = await seedLeague();
  const [A, B] = lg.teams;
  const mid = await newMatch(lg, A, B);
  await playMatch(lg, mid, A, B, "a");
  const slug = (await call<{ slug: string }>(`/seasons/${lg.season}`, "GET", undefined, lg.admin)).slug;

  // --- Team A's captain raises it from the finished match
  const capA = await loginPage(browser, A.players[0], `/matches/${mid}`);
  const panel = capA.getByRole("region", { name: "Disputes" });
  await expect(panel).toBeVisible({ timeout: 15_000 });
  await panel.getByText("Raise a dispute").click();
  await panel.getByLabel("What is it about").selectOption("scoring");
  await panel.getByLabel("What happened").fill("too short");
  await panel.getByRole("button", { name: "Send to the organisers" }).click(); // the browser's own length check stops it
  await expect(capA).toHaveURL(new RegExp(`/matches/${mid}$`));
  await panel.getByLabel("What happened").fill(BODY);
  await panel.getByRole("button", { name: "Send to the organisers" }).click();
  await expect(capA.getByRole("heading", { name: "The score or result" })).toBeVisible({ timeout: 15_000 });
  await expect(capA.getByRole("paragraph").filter({ hasText: BODY })).toBeVisible();
  await expect(capA.getByText("Open", { exact: true })).toBeVisible();
  const did = Number(new URL(capA.url()).pathname.split("/").pop());
  await capA.screenshot({ path: info.outputPath("dispute-raised.png"), fullPage: true });

  // the same person cannot raise a second one about this match
  await capA.goto(`/matches/${mid}`);
  await expect(capA.getByRole("region", { name: "Disputes" })).toContainText("You already have an open dispute", { timeout: 15_000 });

  // --- the other side sees it, and replies
  const capB = await loginPage(browser, B.players[0], "/disputes");
  await expect(capB.getByRole("link", { name: /The score or result/ })).toBeVisible({ timeout: 15_000 });
  await capB.getByRole("link", { name: /The score or result/ }).click();
  await expect(capB.getByRole("paragraph").filter({ hasText: BODY })).toBeVisible({ timeout: 15_000 });
  await capB.getByLabel("Your message").fill("We disagree: the umpire scored every ball correctly.");
  await capB.getByRole("button", { name: "Send" }).click();
  await expect(capB.getByRole("region", { name: "Conversation" })).toContainText("We disagree", { timeout: 10_000 });
  await expect(capB.getByText("Private note")).toHaveCount(0); // parties cannot keep private notes

  // --- an outsider is told it does not exist
  const outsider = await loginPage(browser, A.players[2], `/disputes/${did}`);
  await expect(outsider.getByText("Dispute not found")).toBeVisible({ timeout: 15_000 });

  // --- the admin picks it up, keeps a private note, adds a point to make it right, and resolves it
  const adjustment = await call<{ id: number }>(`/seasons/${lg.season}/adjustments`, "POST", { team_id: A.id, points: 1, reason: "dispute upheld" }, lg.admin);
  const ad = await loginPage(browser, lg.adminUser, "/admin");
  await expect(ad.getByRole("link", { name: /Disputes/ })).toContainText(/[1-9]/, { timeout: 15_000 }); // other runs may have left some too
  await ad.getByRole("link", { name: /Disputes/ }).click();
  const mine = ad.getByRole("link", { name: new RegExp(`\\[${run}\\]`) });
  await expect(mine).toBeVisible({ timeout: 15_000 });
  await mine.click();
  await ad.getByRole("button", { name: "I will look into this" }).click();
  await expect(ad.getByText(/Being looked at/)).toBeVisible({ timeout: 10_000 });
  await ad.getByLabel("Your message").fill("Captain A has raised this kind of thing before.");
  await ad.getByLabel(/Private note/).check();
  await ad.getByRole("button", { name: "Send" }).click();
  await expect(ad.getByText("private note, only organisers see this")).toBeVisible({ timeout: 10_000 });
  const decide = ad.getByRole("region", { name: "Decide" });
  await decide.getByLabel("Outcome").fill("The last wicket was counted twice. A point was added to put it right.");
  await decide.getByLabel("What was done").selectOption("points_adjusted");
  await decide.getByLabel("Which adjustment").selectOption(String(adjustment.id));
  await decide.getByRole("button", { name: "Resolve" }).click();
  await expect(ad.getByRole("region", { name: "Outcome" })).toContainText("Points were adjusted", { timeout: 10_000 });
  await ad.screenshot({ path: info.outputPath("dispute-resolved.png"), fullPage: true });

  // --- both captains see the outcome; Team A's captain never sees the private note
  await capA.goto(`/disputes/${did}`);
  await expect(capA.getByRole("region", { name: "Outcome" })).toContainText("counted twice", { timeout: 15_000 });
  await expect(capA.getByText("Captain A has raised this")).toHaveCount(0);
  await expect(capA.getByRole("region", { name: "Conversation" })).toContainText("We disagree");
  await expect(capA.getByLabel("Your message")).toHaveCount(0); // closed: no more messages
  const told = await call<{ notifications: { title: string }[] }>("/notifications?limit=30", "GET", undefined, B.players[0].token);
  expect(told.notifications.map((n) => n.title)).toContain("Dispute resolved");

  // --- nothing about it on the public site
  const anon = await browser.newContext();
  const pub = await anon.newPage();
  await pub.goto(`/league/${slug}/matches/${mid}`);
  await expect(pub.getByText("Aces vs Bulls").first()).toBeVisible({ timeout: 15_000 });
  expect((await pub.locator("body").innerText()).toLowerCase()).not.toContain("dispute");
});
