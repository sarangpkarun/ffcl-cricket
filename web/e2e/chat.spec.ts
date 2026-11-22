import { expect, test } from "@playwright/test";
import { loginPage, seed } from "./helpers";

test("players chat live, umpire channel stays private, history survives reload", async ({ browser }, info) => {
  const { ump, A, B, outsider, match } = await seed({ start: false });
  const path = `/matches/${match}`;
  const a = await loginPage(browser, A[1], path);
  const b = await loginPage(browser, B[1], path);
  const u = await loginPage(browser, ump, path);
  const o = await loginPage(browser, outsider, path);

  // who gets which tabs
  await expect(a.getByRole("tab", { name: "Chat" })).toBeVisible({ timeout: 10_000 });
  await expect(a.getByRole("tab", { name: "Umpire" })).toHaveCount(0);
  await expect(b.getByRole("tab", { name: "Chat" })).toBeVisible();
  await expect(u.getByRole("tab", { name: "Umpire" })).toBeVisible();
  await expect(o.getByRole("tab")).toHaveCount(0); // a stranger gets no chat at all

  await a.getByRole("tab", { name: "Chat" }).click();
  await b.getByRole("tab", { name: "Chat" }).click();
  await expect(a.locator("main").getByText("● Live")).toBeVisible({ timeout: 10_000 });
  await expect(b.locator("main").getByText("● Live")).toBeVisible();

  // the composer must be fully visible above the bottom nav (a hidden input is unusable on a phone)
  const box = await a.getByRole("textbox", { name: "Message", exact: true }).boundingBox();
  const nav = await a.locator("nav").boundingBox();
  expect(box && nav && box.y + box.height <= nav.y + 1).toBeTruthy();

  // live delivery both ways
  await a.getByRole("textbox", { name: "Message", exact: true }).fill("good luck team 🏏");
  await a.getByRole("textbox", { name: "Message", exact: true }).press("Enter");
  await expect(b.locator("main").getByText("good luck team 🏏")).toBeVisible({ timeout: 5_000 });
  await b.getByRole("textbox", { name: "Message", exact: true }).fill("you too!");
  await b.getByRole("button", { name: "Send" }).click();
  await expect(a.locator("main").getByText("you too!")).toBeVisible({ timeout: 5_000 });
  await expect(a.locator("main").getByText(/online/)).toContainText("2 online", { timeout: 10_000 });
  await a.screenshot({ path: info.outputPath("match-chat.png") });

  // markup is shown as text, never run
  await b.getByRole("textbox", { name: "Message", exact: true }).fill("<img src=x onerror=alert(1)> <b>bold?</b>");
  await b.getByRole("textbox", { name: "Message", exact: true }).press("Enter");
  await expect(a.locator("main").getByText("<b>bold?</b>", { exact: false })).toBeVisible({ timeout: 5_000 });
  await expect(a.locator("img[src='x']")).toHaveCount(0);

  // umpire channel: players never see it
  await u.getByRole("tab", { name: "Umpire" }).click();
  await u.getByRole("textbox", { name: "Message", exact: true }).fill("officials only: start at 7");
  await u.getByRole("textbox", { name: "Message", exact: true }).press("Enter");
  await expect(u.locator("main").getByText("officials only: start at 7")).toBeVisible();
  await a.waitForTimeout(1500);
  expect(await a.content()).not.toContain("officials only");
  expect(await b.content()).not.toContain("officials only");

  // edit and delete reach the other phone
  await a.getByRole("button", { name: "Message options" }).filter({ hasText: "good luck team" }).click();
  await a.getByRole("button", { name: "Edit", exact: true }).click();
  await a.locator("textarea").first().fill("good luck everyone 🏏");
  await a.getByRole("button", { name: "Save" }).click();
  await expect(b.locator("main").getByText("good luck everyone 🏏")).toBeVisible({ timeout: 5_000 });
  await expect(b.locator("main").getByText("· edited")).toBeVisible();
  await a.getByRole("button", { name: "Message options" }).filter({ hasText: "good luck everyone" }).click();
  await a.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(b.locator("main").getByText("Message removed")).toBeVisible({ timeout: 5_000 });
  await expect(b.locator("main").getByText("good luck everyone 🏏")).toHaveCount(0);

  // history survives a reload
  await a.reload();
  await a.getByRole("tab", { name: "Chat" }).click();
  await expect(a.locator("main").getByText("you too!")).toBeVisible({ timeout: 10_000 });
  await expect(a.locator("main").getByText("Message removed")).toBeVisible();

  // season chat from the Chat tab; outsiders have none
  await a.goto("/chat");
  await expect(a.locator("main").getByText(/chat$/).first()).toBeVisible({ timeout: 10_000 });
  await a.getByRole("textbox", { name: "Message", exact: true }).fill("hello league");
  await a.getByRole("textbox", { name: "Message", exact: true }).press("Enter");
  await expect(a.locator("main").getByText("hello league")).toBeVisible();
  await o.goto("/chat");
  await expect(o.locator("main").getByText(/not part of a season yet/)).toBeVisible({ timeout: 10_000 });
});
