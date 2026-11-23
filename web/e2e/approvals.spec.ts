import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { loginPage, run as runId, seedLeague, user } from "./helpers";

const ROOT = process.env.E2E_ROOT ?? `${process.cwd()}/..`;

test("roster change, phone change, rule version, audit log, archive, exports and history", async ({ browser }, info) => {
  test.setTimeout(240_000);
  const lg = await seedLeague();
  const [A] = lg.teams;
  const captain = A.players[0];
  const leaving = A.players[1];
  const free = await user(`Newcomer${runId}x`);
  execSync(`docker compose exec -T postgres psql -U ffcl -d ffcl -c "update users set phone_verified=true where id=${free.id}"`, { cwd: ROOT });

  // --- the captain asks for a replacement
  const cap = await loginPage(browser, captain, `/teams/${A.id}`);
  const form = cap.getByRole("region", { name: "Replace a player" });
  await form.getByLabel("Player leaving").selectOption({ label: leaving.name });
  await form.getByPlaceholder("Search the player joining").fill(free.name);
  await form.getByRole("button", { name: new RegExp(free.name) }).click();
  await form.getByLabel("Reason").fill("moving to another city");
  await form.getByRole("button", { name: "Ask an admin to approve" }).click();
  await expect(form.getByRole("listitem")).toContainText("pending", { timeout: 10_000 });

  // --- the admin approves it
  const ad = await loginPage(browser, lg.adminUser, "/admin/approvals");
  const roster = ad.getByRole("region", { name: "Roster changes" });
  await expect(roster).toContainText(`${leaving.name} out`, { timeout: 10_000 });
  await ad.screenshot({ path: info.outputPath("approvals.png"), fullPage: true });
  await roster.getByRole("button", { name: "Approve" }).click();
  await expect(ad.getByRole("status")).toContainText("Roster change approved", { timeout: 10_000 });
  await cap.reload();
  await expect(cap.getByText(free.name).first()).toBeVisible({ timeout: 10_000 });
  await expect(cap.getByRole("region", { name: "Replace a player" }).getByRole("listitem")).toContainText("approved");

  // --- a player changes their phone number
  const pl = await loginPage(browser, A.players[2], "/profile");
  const phone = pl.getByRole("region", { name: "Change phone number" });
  const newPhone = `+9166${String(Date.now()).slice(-8)}`;
  await phone.getByLabel("New mobile number").fill(newPhone);
  await phone.getByLabel("Why are you changing it?").fill("lost my old sim card");
  await phone.getByRole("button", { name: "Ask for approval" }).click();
  await expect(phone).toContainText("Waiting for an admin", { timeout: 10_000 });
  await ad.goto("/admin/approvals");
  const phones = ad.getByRole("region", { name: "Phone number changes" });
  await expect(phones).toContainText(newPhone, { timeout: 10_000 });
  await phones.getByRole("button", { name: "Approve" }).click();
  await expect(ad.getByRole("status")).toContainText("Phone change approved", { timeout: 10_000 });
  await pl.reload();
  await phone.getByRole("button", { name: "Send code to the new number" }).click();
  await expect(phone.getByLabel("6-digit code")).toBeVisible({ timeout: 10_000 });
  const readCode = () => {
    const logs = process.env.E2E_API_LOG ? readFileSync(process.env.E2E_API_LOG, "utf8") : execSync("docker compose logs api --since 2m 2>&1", { cwd: ROOT, encoding: "utf8" });
    const codes = [...logs.matchAll(new RegExp(`OTP for \\${newPhone}: (\\d{6})`, "g"))];
    return codes.length ? codes[codes.length - 1][1] : null;
  };
  await expect.poll(readCode, { timeout: 10_000, message: "the code appears in the API log" }).not.toBeNull(); // logs can lag a moment
  const code = readCode()!;
  await phone.getByLabel("6-digit code").fill(code);
  await phone.getByRole("button", { name: "Confirm new number" }).click();
  await expect(pl.getByText(newPhone).first()).toBeVisible({ timeout: 10_000 });

  // --- a new rule version, then used by the season
  await ad.goto("/admin/rules");
  await expect(ad.getByLabel("Version", { exact: true })).not.toHaveValue("", { timeout: 10_000 });
  const penalty = ad.getByLabel("Missed umpire duty penalty");
  const current = Number(await penalty.getAttribute("placeholder"));
  await penalty.fill(String(current === 2 ? 3 : 2)); // rule versions persist, so always pick a different value
  await ad.getByLabel("Why this change").fill("a bigger penalty for no-show umpires");
  await ad.getByRole("button", { name: "Save as a new version" }).click();
  await expect(ad.getByRole("status")).toContainText("New version saved", { timeout: 10_000 });
  await expect(ad.getByRole("region", { name: "Changes from the previous version" })).toContainText("umpire_duty_penalty", { timeout: 10_000 });
  const apply = ad.getByRole("region", { name: "Apply to a season" });
  await apply.getByLabel("Season").selectOption(String(lg.season));
  await apply.getByRole("button", { name: "Apply to this season" }).click();
  await expect(ad.getByRole("status")).toContainText("Applied", { timeout: 10_000 });
  await ad.screenshot({ path: info.outputPath("rules.png"), fullPage: true });

  // --- the audit log shows what happened
  await ad.goto("/admin/audit");
  await ad.getByLabel("Action").selectOption("roster.approve");
  await ad.getByRole("button", { name: "Search" }).click();
  await expect(ad.getByRole("listitem").first()).toContainText("roster.approve", { timeout: 10_000 });
  await ad.getByLabel("Action").selectOption("phone.complete");
  await ad.getByRole("button", { name: "Search" }).click();
  await expect(ad.getByRole("listitem").first()).toContainText("phone.complete", { timeout: 10_000 });
  await ad.screenshot({ path: info.outputPath("audit.png"), fullPage: true });

  // --- exports, then archive the season
  await ad.goto(`/admin/seasons/${lg.season}/setup`);
  const box = ad.getByRole("region", { name: "Archive and exports" });
  const [dl] = await Promise.all([ad.waitForEvent("download"), box.getByRole("button", { name: "Download table (CSV)" }).click()]);
  expect(dl.suggestedFilename()).toBe(`season-${lg.season}-table.csv`);
  await box.getByRole("button", { name: "Archive this season" }).click();
  await box.getByRole("button", { name: "Yes, archive it" }).click();
  await expect(box).toContainText("archived and read-only", { timeout: 10_000 });
  // an archived season cannot be changed: the captain's next request is refused
  await cap.reload();
  const again = cap.getByRole("region", { name: "Replace a player" });
  await again.getByLabel("Player leaving").selectOption({ index: 1 });
  await again.getByPlaceholder("Search the player joining").fill(free.name);
  await again.getByRole("button", { name: new RegExp(free.name) }).click();
  await again.getByLabel("Reason").fill("trying after the archive");
  await again.getByRole("button", { name: "Ask an admin to approve" }).click();
  await expect(again.getByRole("alert")).toContainText("archived", { timeout: 10_000 });

  // --- history lists it
  await pl.goto("/history");
  await expect(pl.getByRole("heading", { name: /League/ }).first()).toBeVisible({ timeout: 10_000 });
});
