// Design alignment: a teacher's qualified subjects, the Registrar's menu. Needs a seeded database.
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

async function signIn(page: Page, username: string) {
  await page.goto("/login");
  await page.getByLabel(/Namba ya shule|School code/).fill("mfano-sec");
  await page.getByLabel(/Jina la mtumiaji|Username/).fill(username);
  await page.getByLabel(/^(Nenosiri|Password)$/).fill("Mfano@2026");
  await page.getByRole("button", { name: /^(Ingia|Sign in)$/ }).click();
  await expect(page.getByRole("heading", { name: /Karibu/ })).toBeVisible();
}

test("head teacher edits the subjects a teacher can teach", async ({ page }) => {
  await signIn(page, "admin");
  await page.getByRole("link", { name: "Wafanyakazi" }).first().click();
  await page.getByRole("button", { name: "Masomo anayoweza kufundisha" }).first().click();
  const panel = page.getByTestId("staff-subjects");
  const first = panel.getByRole("checkbox").first();
  const was = await first.isChecked();
  await first.setChecked(!was);
  await panel.getByRole("button", { name: "Hifadhi" }).click();
  await expect(panel.getByRole("status")).toBeVisible();
  await first.setChecked(was);                                   // leave the data as it was for later specs
  await panel.getByRole("button", { name: "Hifadhi" }).click();
  await expect(panel.getByRole("status")).toBeVisible();
});

test("registrar sees students and enrolment, not fees or the audit log", async ({ page }) => {
  await signIn(page, "registrar");
  await expect(page.getByRole("link", { name: "Wanafunzi" }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: "Ada" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Kumbukumbu za ukaguzi" })).toHaveCount(0);
});

test("head teacher finds rooms by equipment and adds some to a room", async ({ page }) => {
  await signIn(page, "admin");
  await page.getByRole("link", { name: "Taaluma" }).first().click();
  await page.getByRole("tab", { name: "Vyumba" }).click();
  const rooms = page.getByTestId("room-equipment-list");
  await expect(rooms.filter({ hasText: "Desks ×45" })).toHaveCount(2);

  const search = page.getByLabel("Tafuta chumba kwa kifaa");
  await search.selectOption({ label: "PA system (1)" });
  await expect(rooms).toHaveCount(1);
  await page.getByRole("button", { name: "Vifaa", exact: true }).click();
  const editor = page.getByTestId("room-equipment");
  await editor.getByRole("button", { name: "Ongeza" }).click();
  await editor.getByLabel("Vifaa").last().fill("Projector");
  await editor.getByRole("button", { name: "Hifadhi" }).click();
  await expect(rooms).toContainText("Projector");
  await expect(search.locator("option", { hasText: "Projector (1)" })).toHaveCount(1);
});
