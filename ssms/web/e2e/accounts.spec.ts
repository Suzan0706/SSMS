// Extension Phase 8 (design/20 §20.7): an expense recorded by the bursar, reversed with the head's approval; fines.
// The API runs on 2026-10-21 (scripts/e2e_api.py), so dates are given explicitly.
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

async function period(page: Page) {
  await page.getByLabel("Kuanzia").last().fill("2026-10-01");
  await page.getByLabel("Hadi").last().fill("2026-10-21");
}

test("the bursar records an expense; reversing it needs the head teacher", async ({ page, browser }) => {
  const bursar = await browser.newPage();
  await signIn(bursar, "bursar");
  await bursar.getByRole("link", { name: "Mapato na matumizi" }).first().click();
  await bursar.getByLabel("Aina", { exact: true }).selectOption("EXPENSE");
  await bursar.getByLabel("Kundi").selectOption({ label: "Maji na umeme" });
  await bursar.getByLabel("Tarehe").fill("2026-10-20");
  await bursar.getByLabel("Kiasi (TZS)").fill("120000");
  await bursar.getByLabel("Amelipwa").fill("TANESCO");
  await bursar.getByLabel("Maelezo mafupi").fill("Umeme wa Oktoba");
  await bursar.getByRole("button", { name: "Rekodi" }).click();
  await period(bursar);
  const row = bursar.getByRole("table", { name: "Miamala" }).getByRole("row", { name: /Umeme wa Oktoba/ });
  await expect(row).toContainText("120,000");
  await row.getByRole("button", { name: "Omba kubatilisha" }).click();
  await bursar.getByRole("dialog").getByLabel("Sababu").fill("Kiasi kimekosewa");
  await bursar.getByRole("dialog").getByRole("button", { name: "Omba kubatilisha" }).click();
  await expect(row).toContainText("Kubatilisha kumeombwa");
  await expect(row.getByRole("button", { name: "Idhinisha" })).toHaveCount(0);   // the bursar cannot approve
  await bursar.close();

  await signIn(page, "admin");
  await page.getByRole("link", { name: "Mapato na matumizi" }).first().click();
  await period(page);
  const pending = page.getByRole("table", { name: "Miamala" }).getByRole("row", { name: /Umeme wa Oktoba/ });
  await pending.getByRole("button", { name: "Idhinisha" }).click();
  await expect(pending).toContainText("REVERSED");

  await page.getByRole("tab", { name: "Taarifa ya mapato na matumizi" }).click();
  await period(page);
  await expect(page.getByTestId("income-statement")).toContainText("5100 · Maji na umeme");
});

test("the office sets the late fee and charges it on overdue invoices", async ({ page }) => {
  await signIn(page, "admin");
  await page.getByRole("link", { name: "Mapato na matumizi" }).first().click();
  await page.getByRole("tab", { name: "Faini" }).click();
  const late = page.getByRole("region", { name: "Faini ya kuchelewa kulipa ada" });
  await late.getByLabel("Kiasi (TZS)").fill("5000");
  await late.getByLabel("Siku za neema").fill("7");
  await late.getByRole("button", { name: "Hifadhi" }).click();
  await expect(late.getByRole("status")).toContainText("Imehifadhiwa");
  await late.getByRole("button", { name: "Weka faini sasa" }).click();
  await expect(late.getByRole("status")).toContainText(/Ankara zilizotozwa faini: [1-9]/);
});
