import { expect, test } from "@playwright/test";
import { call, loginPage, seed } from "./helpers";

test("admin manages people: search, roles, suspend and reactivate", async ({ browser }, info) => {
  const { adminUser, admin, A, B } = await seed({ start: false });
  await call(`/users/${A[2].id}/roles`, "POST", { role: "tournament_admin" }, admin); // an admin who is not a super admin

  const sup = await loginPage(browser, adminUser, "/admin/users");
  const search = sup.getByLabel("Search people");
  // Type the search, then wait for exactly that person's card (the list updates a moment later).
  const find = async (u: { email: string; name: string }) => {
    await search.fill(u.email);
    const c = sup.getByRole("article", { name: `User ${u.name}` });
    await expect(c).toBeVisible();
    await expect(sup.getByText("1 person")).toBeVisible();
    return c;
  };

  // --- search by email, then add and remove a role
  const card = await find(A[1]);
  await card.getByLabel(`Role to add for ${A[1].name}`).selectOption("umpire");
  await card.getByRole("button", { name: "Add role" }).click();
  const roles = card.getByRole("list", { name: "Roles" });
  await expect(roles.getByText("umpire")).toBeVisible();
  await sup.screenshot({ path: info.outputPath("people.png") });
  await card.getByRole("button", { name: `Remove umpire from ${A[1].name}` }).click();
  await expect(roles.getByText("umpire")).toHaveCount(0);
  await expect(roles.getByText("player")).toBeVisible();

  // --- suspend: the person is signed out and cannot sign back in
  const victim = await loginPage(browser, B[1], "/profile");
  await expect(victim.getByText(B[1].name).first()).toBeVisible();
  const vcard = await find(B[1]);
  await vcard.getByRole("button", { name: "Suspend" }).click();
  await expect(vcard.getByText("suspended", { exact: true })).toBeVisible();
  await victim.reload();
  await victim.waitForURL("**/login", { timeout: 15_000 });

  // --- the status filter finds them (combined with their email: the database may hold other suspended people)
  await sup.getByLabel("Filter by status").selectOption("suspended");
  await expect(sup.getByRole("article")).toHaveCount(1);
  await expect(sup.getByRole("article").first()).toContainText(B[1].name);

  // --- reactivate and they can sign in again
  await sup.getByRole("article").first().getByRole("button", { name: "Reactivate" }).click();
  await expect(sup.getByRole("article")).toHaveCount(0);
  await loginPage(browser, B[1], "/profile");

  // --- a tournament admin can manage umpires but never admin powers or accounts
  const ta = await loginPage(browser, A[2], "/admin/users");
  await ta.getByLabel("Search people").fill(A[3].email);
  const tcard = ta.getByRole("article", { name: /^User / }).first();
  await expect(tcard).toContainText(A[3].name);
  await expect(tcard.getByLabel(`Role to add for ${A[3].name}`).locator("option")).toHaveText(["player", "umpire"]);
  await expect(tcard.getByRole("button", { name: /Suspend|Ban|Reactivate/ })).toHaveCount(0);
  await ta.getByLabel("Search people").fill(adminUser.email);
  const boss = ta.getByRole("article", { name: /^User / }).first();
  await expect(boss.getByRole("button", { name: /Remove super admin/ })).toHaveCount(0); // cannot strip a super admin

  // --- a plain player is turned away
  const player = await loginPage(browser, A[3], "/admin/users");
  await expect(player.getByText("Admins only.")).toBeVisible({ timeout: 10_000 });
});
