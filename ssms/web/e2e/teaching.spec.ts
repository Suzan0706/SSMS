// Extension Phase 6 (design/20 §20.7): homework set, handed in and marked; lesson register; monthly sheet.
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

test("a teacher sets homework, the student hands it in and sees the mark", async ({ page, browser }) => {
  await signIn(page, "tch.mwita");
  await page.getByRole("link", { name: "Kazi na nyenzo" }).first().click();
  await page.getByLabel("Somo", { exact: true }).selectOption({ label: "Hisabati za Msingi" });
  await page.getByRole("checkbox", { name: "F2 A" }).check();
  await page.getByLabel("Kichwa").fill("Zoezi la sehemu");
  await page.getByLabel("Mwisho wa kuwasilisha").fill("2027-01-10T10:00");
  await page.getByLabel("Maelekezo").fill("Jibu maswali 1 hadi 5");
  await page.getByLabel("Alama za juu").fill("10");
  await page.getByRole("button", { name: "Toa kazi" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Kazi imetolewa" })).toBeVisible();
  const row = page.getByRole("table", { name: "Kazi za nyumbani" }).getByRole("row", { name: /Zoezi la sehemu/ });
  await expect(row).toContainText("0/");

  const student = await browser.newPage();
  await signIn(student, "mf-2025-0014");
  await student.getByRole("link", { name: "Masomo yangu" }).first().click();
  const card = student.getByTestId("my-homework").getByRole("listitem").filter({ hasText: "Zoezi la sehemu" });
  await card.getByRole("button", { name: "Wasilisha" }).click();
  await card.getByLabel(/Jibu lako/).fill("1) 3/4  2) 1/2");
  await card.getByRole("button", { name: "Wasilisha" }).click();
  await expect(card).toContainText("Imewasilishwa");

  await page.reload();
  await row.getByRole("button", { name: "Sahihisha" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel(/^Alama: Amani/).fill("8");
  await dialog.getByLabel(/^Maoni ya mwalimu: Amani/).fill("Kazi nzuri");
  await dialog.getByRole("button", { name: "Hifadhi" }).click();
  await expect(dialog).toContainText("8.0 / 10.0");
  await dialog.getByRole("button", { name: "Funga" }).click();

  await student.reload();
  await expect(card).toContainText("Kazi nzuri");
  await expect(card.getByRole("button", { name: /Wasilisha|Badilisha jibu/ })).toHaveCount(0);   // marked: no more changes
  await student.close();
});

test("a teacher takes a lesson register and the office prints the monthly sheet", async ({ page, browser }) => {
  const teacher = await browser.newPage();
  await signIn(teacher, "tch.mwita");
  await teacher.getByRole("link", { name: "Daftari la vipindi" }).first().click();
  await teacher.getByLabel("Tarehe").fill("2026-03-02");                       // a Monday in Term One
  await teacher.getByRole("button", { name: /F2 A/ }).click();
  const first = teacher.getByRole("radiogroup").first();
  await first.getByRole("radio", { name: "Hakufika" }).click();
  await teacher.getByRole("button", { name: "Hifadhi" }).click();
  await expect(teacher.getByRole("status").filter({ hasText: "Imehifadhiwa" })).toBeVisible();
  await expect(teacher.getByRole("button", { name: /F2 A/ })).toContainText("✓");
  await teacher.close();

  await signIn(page, "admin");
  await page.getByRole("link", { name: "Mahudhurio" }).first().click();
  await page.getByRole("tab", { name: "Karatasi ya mwezi" }).click();
  await page.getByLabel("Darasa / mkondo").selectOption({ label: "F2 A" });
  await page.getByLabel("Mwezi").fill("2026-03");
  const sheet = page.getByTestId("monthly-sheet");
  await expect(sheet.locator("thead th")).toHaveCount(1 + 5 + 4);                // name, 5 register days, 4 totals
  await expect(sheet.getByRole("row", { name: /Baraka/ })).toContainText("A");
});
