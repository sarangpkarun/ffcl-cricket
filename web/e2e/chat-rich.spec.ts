import { expect, test, type Page } from "@playwright/test";
import { loginPage, seed } from "./helpers";

const bubble = (p: Page, text: string) => p.getByRole("button", { name: "Message options" }).filter({ hasText: text });
async function openChat(p: Page) {
  await p.getByRole("tab", { name: "Chat" }).click();
  await expect(p.getByText("● Live")).toBeVisible({ timeout: 10_000 });
}
async function say(p: Page, text: string) {
  await p.getByRole("textbox", { name: "Message", exact: true }).fill(text);
  await p.getByRole("textbox", { name: "Message", exact: true }).press("Enter");
}

test("reply, react, mention, typing, seen, pin, announce, report, mute, search", async ({ browser }, info) => {
  const { adminUser, ump, A, B, match } = await seed({ start: false });
  const path = `/matches/${match}`;
  const [a, b, u, adm] = [
    await loginPage(browser, A[1], path), await loginPage(browser, B[1], path),
    await loginPage(browser, ump, path), await loginPage(browser, adminUser, path),
  ];
  for (const p of [a, b, u, adm]) await openChat(p);

  // --- reply / quote
  await say(a, "great match so far");
  await expect(b.locator("main").getByText("great match so far")).toBeVisible({ timeout: 5_000 });
  await bubble(b, "great match so far").click();
  await b.getByRole("button", { name: "Reply", exact: true }).click();
  await expect(b.locator("main").getByText(/Replying to/)).toBeVisible();
  await say(b, "agreed!");
  await expect(a.locator("main").getByText("agreed!")).toBeVisible({ timeout: 5_000 });
  await expect(a.locator("main").getByText("great match so far").nth(1)).toBeVisible(); // the quote inside b's reply

  // --- reaction shows up live on the other phone
  await bubble(b, "great match so far").click();
  await b.getByRole("button", { name: "React 🔥" }).click();
  await expect(a.getByRole("button", { name: "🔥 1" })).toBeVisible({ timeout: 5_000 });
  await a.getByRole("button", { name: "🔥 1" }).click(); // second person reacts: count goes to 2
  await expect(b.getByRole("button", { name: "🔥 2" })).toBeVisible({ timeout: 5_000 });

  // --- @mention picker
  const bName = B[1].name;
  await a.getByRole("textbox", { name: "Message", exact: true }).fill(`hey @${bName.slice(0, 4)}`);
  await a.getByRole("option", { name: new RegExp(bName) }).click();
  await expect(a.getByRole("textbox", { name: "Message", exact: true })).toHaveValue(`hey @${bName} `);
  await a.getByRole("textbox", { name: "Message", exact: true }).press("Enter");
  await expect(b.locator("b", { hasText: `@${bName}` })).toBeVisible({ timeout: 5_000 });

  // --- typing indicator
  await a.getByRole("textbox", { name: "Message", exact: true }).fill("typing something…");
  await expect(b.locator("main").getByText(/is typing/)).toBeVisible({ timeout: 5_000 });
  await a.getByRole("textbox", { name: "Message", exact: true }).fill("");

  // --- read receipt: b has the chat open, so a's newest message is "seen"
  await expect(a.locator("main").getByText(`Seen by`)).toContainText(bName, { timeout: 10_000 });

  // --- pin by the umpire (moderator of the match room)
  await bubble(u, "great match so far").click();
  await u.getByRole("button", { name: "Pin", exact: true }).click();
  for (const p of [a, b]) await expect(p.getByText(/📌/).first()).toBeVisible({ timeout: 5_000 });
  await expect(a.getByRole("button", { name: /pinned|great match so far/ }).first()).toBeVisible();
  // players cannot pin
  await bubble(a, "great match so far").click();
  await expect(a.getByRole("button", { name: "Pin", exact: true })).toHaveCount(0);
  await bubble(a, "great match so far").click();

  // --- admin announcement
  await adm.getByLabel(/Send as pinned announcement/).check();
  await say(adm, "Toss at 7 sharp");
  await expect(b.locator("main").getByText(/📢 Announcement/)).toBeVisible({ timeout: 5_000 });
  await expect(b.locator("main").getByText("Toss at 7 sharp")).toHaveCount(2); // in the chat and in the pinned bar
  await b.screenshot({ path: info.outputPath("rich-chat.png") });

  // --- report -> admin deletes + mutes -> sender is blocked
  await say(a, "you are all useless");
  await expect(b.locator("main").getByText("you are all useless")).toBeVisible({ timeout: 5_000 });
  await bubble(b, "you are all useless").click();
  await b.getByRole("button", { name: "Report", exact: true }).click();
  await b.getByLabel("Report reason").fill("abusive language");
  await b.locator("form").filter({ has: b.getByLabel("Report reason") }).getByRole("button", { name: "Send" }).click();
  await expect(b.locator("main").getByText("Reported. Thank you.")).toBeVisible();

  await adm.goto("/admin/moderation");
  await expect(adm.locator("main").getByText("you are all useless")).toBeVisible({ timeout: 10_000 });
  await expect(adm.locator("main").getByText(/abusive language/)).toBeVisible();
  await adm.getByRole("button", { name: "Delete + mute" }).first().click();
  await expect(adm.locator("main").getByText(/Removed and muted/)).toBeVisible({ timeout: 10_000 });
  await expect(adm.locator("main").getByText(A[1].name).first()).toBeVisible(); // listed under active mutes
  await expect(a.locator("main").getByText("Message removed").first()).toBeVisible({ timeout: 5_000 }); // live on a's phone
  await a.reload();
  await openChat(a);
  await expect(a.getByRole("status").filter({ hasText: /muted until/ })).toBeVisible({ timeout: 10_000 });
  await expect(a.getByRole("textbox", { name: "Message", exact: true })).toHaveCount(0);

  // --- search
  await b.getByRole("button", { name: "Search" }).click();
  await b.getByLabel("Search messages").fill("great match");
  await b.getByRole("button", { name: "Search", exact: true }).last().click();
  await expect(b.getByRole("search").getByText("great match so far")).toBeVisible({ timeout: 10_000 });
  await b.getByLabel("Search messages").fill("useless");
  await b.getByRole("button", { name: "Search", exact: true }).last().click();
  await expect(b.locator("main").getByText("No messages found.")).toBeVisible({ timeout: 10_000 }); // deleted text is never searchable

  // --- admin lifts the mute and a can post again
  await adm.getByRole("button", { name: "Lift" }).first().click();
  await expect(adm.locator("main").getByText(/Lifted mute/)).toBeVisible({ timeout: 10_000 });
  await a.reload();
  await openChat(a);
  await say(a, "sorry everyone");
  await expect(b.locator("main").getByText("sorry everyone")).toBeVisible({ timeout: 5_000 });
});
