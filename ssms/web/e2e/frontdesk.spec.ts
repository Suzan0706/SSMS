// Extension Phase 5 (design/20 §20.7): inquiries, calendar, staff register, leave and student photos.
// The API runs on a fixed school day (2026-10-21, scripts/e2e_api.py), so dates are given explicitly.
import { expect, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

const GATE_JUMA = "00000002-0000-4000-8000-000000000006";
const DAY = "2026-10-21";
// a real 1×1 PNG, so the browser can decode and shrink it before upload
const PNG_1PX = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==", "base64");

async function signIn(page: Page, username: string) {
  await page.goto("/login");
  await page.getByLabel(/Namba ya shule|School code/).fill("mfano-sec");
  await page.getByLabel(/Jina la mtumiaji|Username/).fill(username);
  await page.getByLabel(/^(Nenosiri|Password)$/).fill("Mfano@2026");
  await page.getByRole("button", { name: /^(Ingia|Sign in)$/ }).click();
  await expect(page.getByRole("heading", { name: /Karibu/ })).toBeVisible();
}

async function adminApi(request: APIRequestContext) {
  const res = await request.post("/api/v1/auth/login", { data: { school_code: "mfano-sec", username: "admin", password: "Mfano@2026" } });
  return { Authorization: `Bearer ${(await res.json()).access_token}` };
}

test("the front desk records an inquiry, follows it up and turns it into an application", async ({ page, request }) => {
  const admin = await adminApi(request);
  await request.post(`/api/v1/users/${GATE_JUMA}/roles`, { headers: admin, data: { role_code: "receptionist" } });
  try {
    await signIn(page, "gate.juma");
    await page.getByRole("link", { name: "Maulizo ya kujiunga" }).first().click();
    const form = page.locator("form").first();
    await form.getByLabel("Jina", { exact: true }).fill("Zuhura Ally Mtumwa");
    await form.getByLabel("Namba ya simu").fill("0715 222 333");
    await form.getByRole("button", { name: "Hifadhi" }).click();
    const row = page.getByRole("table", { name: "Maulizo ya kujiunga" }).getByRole("row", { name: /Zuhura Ally Mtumwa/ });
    await expect(row).toContainText("255715222333");

    await row.getByRole("button", { name: "Fuatilia" }).click();
    await page.getByLabel("Maelezo").fill("Mama atakuja Jumatatu");
    await page.getByRole("dialog").getByRole("button", { name: "Hifadhi" }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);

    await row.getByRole("button", { name: "Fungua ombi" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Tarehe ya kuzaliwa").fill("2014-05-02");
    await dialog.getByLabel("Darasa analotaka").selectOption({ label: "F1" });
    await dialog.getByLabel("Mzazi / mlezi: Jina la kwanza").fill("Asha");
    await dialog.getByRole("button", { name: "Fungua ombi" }).click();
    await expect(page).toHaveURL(/\/enrolment$/);
  } finally {
    await request.delete(`/api/v1/users/${GATE_JUMA}/roles/receptionist`, { headers: admin });
  }
});

test("an event planned by the office shows on the calendar and on the home page", async ({ page }) => {
  await signIn(page, "admin");
  await page.getByRole("link", { name: "Kalenda ya shule" }).first().click();
  await page.getByLabel("Jina (Kiswahili)").fill("Siku ya wazazi");
  await page.getByLabel("Kuanzia").fill("2026-11-06");
  await page.getByRole("button", { name: "Hifadhi" }).click();
  await expect(page.getByTestId("calendar")).toContainText("Siku ya wazazi");
  await page.getByRole("link", { name: "Mwanzo" }).click();
  await expect(page.getByTestId("upcoming-events")).toContainText("Siku ya wazazi");
});

test("the office marks the staff register and a teacher's leave is approved", async ({ page, browser, request }) => {
  const admin = await adminApi(request);
  const kind = await request.post("/api/v1/leave-types", { headers: admin, data: { name_en: "Annual", name_sw: "Likizo ya mwaka", applies_to: "STAFF", days_per_year: 28 } });
  expect([201, 409]).toContain(kind.status());

  await signIn(page, "admin");
  await page.getByRole("link", { name: "Daftari la wafanyakazi" }).first().click();
  await page.getByLabel("Tarehe").fill(DAY);
  const status = page.getByLabel(/^Hali: .*Mwita/);
  await expect(status).toBeVisible();
  await status.selectOption({ label: "Amechelewa" });
  await page.getByRole("button", { name: "Hifadhi" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Imehifadhiwa" })).toBeVisible();
  await page.reload();
  await page.getByLabel("Tarehe").fill(DAY);
  await expect(page.getByLabel(/^Hali: .*Mwita/)).toHaveValue("LATE");

  const teacher = await browser.newPage();
  await signIn(teacher, "tch.mwita");
  await teacher.getByRole("link", { name: "Likizo" }).first().click();
  await teacher.getByLabel("Aina ya likizo").selectOption({ label: "Likizo ya mwaka (28)" });
  await teacher.getByLabel("Kuanzia").fill("2026-12-14");
  await teacher.getByLabel("Hadi").fill("2026-12-18");
  await teacher.getByLabel("Sababu").fill("Safari ya familia");
  await teacher.getByRole("button", { name: "Omba likizo" }).click();
  await expect(teacher.getByRole("table", { name: "Maombi yangu" })).toContainText("PENDING");

  await page.getByRole("link", { name: "Likizo" }).first().click();
  const pending = page.getByRole("table", { name: "Ya kuamua" }).getByRole("row", { name: /2026-12-14/ });
  await pending.getByRole("button", { name: "Idhinisha" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Idhinisha" }).click();
  await expect(pending).toHaveCount(0);                                   // no longer pending
  await teacher.reload();
  await expect(teacher.getByRole("table", { name: "Maombi yangu" })).toContainText("APPROVED");
  await teacher.close();
});

test("a student photo is uploaded from the profile", async ({ page }) => {
  await signIn(page, "admin");
  await page.getByRole("link", { name: "Wanafunzi" }).first().click();
  await page.getByRole("link", { name: "Amani John Massawe" }).click();
  const panel = page.getByTestId("student-photo");
  await expect(panel.getByLabel("Hakuna picha")).toBeVisible();
  await panel.locator('input[type="file"]').setInputFiles({ name: "amani.png", mimeType: "image/png", buffer: PNG_1PX });
  await expect(panel.getByRole("img", { name: "Picha: Amani John Massawe" })).toBeVisible();
  await panel.getByRole("button", { name: "Ondoa picha" }).click();
  await expect(panel.getByLabel("Hakuna picha")).toBeVisible();
});
