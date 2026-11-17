// Phase 2 end-to-end: offline marks entry -> sync -> firewall -> publish -> report card; timetable check.
// Needs a freshly seeded database (Form V PCM Term One is not yet published in the seed).
import { expect, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

test.describe.configure({ mode: "serial" });

const API = "/api/v1";

async function signIn(page: Page, username: string, password = "Mfano@2026") {
  await page.goto("/login");
  await page.getByLabel(/Namba ya shule|School code/).fill("mfano-sec");
  await page.getByLabel(/Jina la mtumiaji|Username/).fill(username);
  await page.getByLabel(/^(Nenosiri|Password)$/).fill(password);
  await page.getByRole("button", { name: /^(Ingia|Sign in)$/ }).click();
  await expect(page.getByRole("heading", { name: /Karibu/ })).toBeVisible();
}

async function adminToken(request: APIRequestContext): Promise<string> {
  const res = await request.post(`${API}/auth/login`, {
    data: { school_code: "mfano-sec", username: "admin", password: "Mfano@2026" } });
  return (await res.json()).access_token;
}

test("teacher enters a mark offline and it syncs when the connection returns", async ({ page, context }) => {
  await signIn(page, "tch.mwita");
  await page.getByRole("link", { name: "Alama" }).first().click();
  await page.getByLabel("Muhula").selectOption({ label: "Muhula wa Kwanza" });   // seed marks are Term One
  const picker = page.getByLabel("Madarasa yangu");
  await expect(picker.locator("option", { hasText: "AMATH" })).toHaveCount(1);
  await picker.selectOption(await picker.locator("option", { hasText: "AMATH" }).getAttribute("value") ?? "");
  const cell = page.getByLabel("MF-2026-0003 TERMINAL");
  await expect(cell).toBeEnabled();

  await context.setOffline(true);
  await cell.fill("88");
  await cell.press("Tab");
  await expect(page.getByTestId("sync-state")).toHaveAttribute("data-pending", "1");
  await expect(page.getByText(/Imehifadhiwa kwenye simu/)).toBeVisible();

  await context.setOffline(false);
  await expect(page.getByTestId("sync-state")).toHaveAttribute("data-pending", "0", { timeout: 15_000 });
  await expect(page.getByLabel("MF-2026-0003 TERMINAL")).toHaveValue("88");
});

test("head teacher publishes Form V after the firewall is clear and downloads a report card", async ({ page, request }) => {
  // Complete the remaining Form V marks through the API (the firewall lists them otherwise).
  const token = await adminToken(request);
  const headers = { Authorization: `Bearer ${token}` };
  const terms = await (await request.get(`${API}/terms`, { headers })).json();
  const term = terms.find((t: { term_no: number; name_en: string }) => t.term_no === 1 && t.name_en === "Term One");
  const streams = await (await request.get(`${API}/streams`, { headers })).json();
  const pcm = streams.find((s: { name: string }) => s.name === "PCM");
  const subjects = await (await request.get(`${API}/subjects`, { headers })).json();
  const items = [];
  for (const code of ["GS", "PHY-A", "CHEM-A"]) {
    const subject = subjects.find((s: { code: string }) => s.code === code);
    const sheet = await (await request.get(
      `${API}/marks/sheet?term_id=${term.id}&stream_id=${pcm.id}&subject_id=${subject.id}`, { headers })).json();
    const student = sheet.students[0];
    for (const component of sheet.components) {
      const existing = student.marks[component.id];
      if (!existing) items.push({ enrolment_id: student.enrolment_id, subject_id: subject.id,
                                  component_id: component.id, score: "30", version: 0 });
    }
  }
  const saved = await (await request.put(`${API}/marks/batch`, { headers, data: { items } })).json();
  expect(saved.errors).toBe(0);

  await signIn(page, "admin");
  await page.getByRole("link", { name: "Matokeo" }).first().click();
  await page.getByLabel("Muhula").selectOption({ label: "Muhula wa Kwanza" });
  await page.getByLabel("Darasa").selectOption({ label: "Kidato cha Tano" });
  await expect(page.getByTestId("firewall")).toHaveAttribute("data-ok", "true");
  await page.getByRole("button", { name: "Toa matokeo" }).click();
  await expect(page.getByTestId("class-results")).toBeVisible();
  await expect(page.getByTestId("class-results")).toContainText("Emmanuel");

  await page.getByRole("link", { name: "Ripoti ya maendeleo" }).first().click();
  await expect(page.getByTestId("student-results")).toContainText("Hisabati ya Juu");
  const pdf = page.waitForEvent("download");
  await page.getByRole("button", { name: /Ripoti ya maendeleo \(PDF\)/ }).click();
  expect((await pdf).suggestedFilename()).toBe("report-MF-2026-0003.pdf");
});

test("timetable shows the week and checks a new lesson live", async ({ page }) => {
  await signIn(page, "admin");
  await page.getByRole("link", { name: "Ratiba" }).first().click();
  await page.getByLabel("Muhula").selectOption({ label: "Muhula wa Kwanza" });
  await page.getByLabel("Mkondo").selectOption({ label: "F2 A" });
  await expect(page.getByRole("table").first()).toContainText("BMATH");
  await page.locator("select[name=subject_id]").selectOption({ index: 1 });
  await page.locator("select[name=room_id]").selectOption({ index: 1 });
  await expect(page.getByTestId("check")).toBeVisible();
});
