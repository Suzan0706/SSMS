// Phase 6 end-to-end: the head teacher's dashboard, a report previewed and exported, a data-subject export, the audit
// log. Needs a seeded database; counts are not exact because earlier specs add students.
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

test.describe.configure({ mode: "serial" });

async function signIn(page: Page, username: string, password = "Mfano@2026") {
  await page.goto("/login");
  await page.getByLabel(/Namba ya shule|School code/).fill("mfano-sec");
  await page.getByLabel(/Jina la mtumiaji|Username/).fill(username);
  await page.getByLabel(/^(Nenosiri|Password)$/).fill(password);
  await page.getByRole("button", { name: /^(Ingia|Sign in)$/ }).click();
  await expect(page.getByRole("heading", { name: /Karibu/ })).toBeVisible();
}

test("head teacher sees the dashboard and exports a report", async ({ page }) => {
  await signIn(page, "admin");
  await expect(page.getByTestId("dashboard-admin")).toBeVisible();
  await expect(page.getByTestId("tile-students")).toContainText(/\d+/);
  await expect(page.getByRole("figure", { name: "Wanafunzi kwa darasa" })).toContainText("F2");

  await page.getByRole("link", { name: "Ripoti" }).first().click();
  await page.getByRole("button", { name: "Onyesha" }).click();
  await expect(page.getByTestId("report-total")).toContainText(/Jumla ya safu: \d+/);
  await expect(page.getByRole("cell", { name: "MF-2025-0031" })).toBeVisible();
  await page.getByLabel("Muundo").selectOption("csv");
  await page.getByRole("button", { name: "Pakua zote" }).click();
  await expect(page.getByTestId("export-job")).toHaveAttribute("data-status", "SUCCEEDED", { timeout: 20_000 });
  const download = page.waitForEvent("download");
  await page.getByTestId("export-job").getByRole("button", { name: "Pakua" }).click();
  expect((await download).suggestedFilename()).toBe("enrolment.csv");
});

test("privacy officer exports a student's data and the audit log records it", async ({ page }) => {
  await signIn(page, "admin");
  await page.getByRole("link", { name: "Faragha (PDPA)" }).first().click();
  await page.getByLabel("Tafuta jina au namba ya usajili").fill("MF-2025-0044");
  await page.getByRole("button", { name: /MF-2025-0044/ }).click();
  await expect(page.getByLabel("Mhusika")).toBeVisible();
  await page.getByLabel("Aina ya ombi").selectOption("EXPORT");
  await page.getByRole("button", { name: "Hifadhi" }).click();
  const request = page.getByTestId("dsr-list").getByRole("listitem").filter({ hasText: "Mariam" }).first();
  await request.getByRole("button", { name: "Toa nakala ya taarifa" }).click();
  await expect(request).toContainText("COMPLETED");
  const download = page.waitForEvent("download");
  await request.getByRole("button", { name: "Pakua" }).click();
  expect((await download).suggestedFilename()).toMatch(/^data-.+\.json$/);

  await page.getByRole("link", { name: "Kumbukumbu za ukaguzi" }).first().click();
  await page.getByLabel("Kitendo").selectOption("EXPORT");
  await expect(page.getByTestId("audit-list")).toContainText("data_subject_requests");
});
