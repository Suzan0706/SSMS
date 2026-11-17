// Extension Phase 10 (design/20 §20.7): parents and students see results, progress by term, homework and attendance.
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { readFileSync } from "node:fs";

const API = "/api/v1";
const run = String(Date.now()).slice(-6);
const parentPhone = `0658${run}`;

async function signIn(page: Page, username: string) {
  await page.goto("/login");
  await page.getByLabel(/Namba ya shule|School code/).fill("mfano-sec");
  await page.getByLabel(/Jina la mtumiaji|Username/).fill(username);
  await page.getByLabel(/^(Nenosiri|Password)$/).fill("Mfano@2026");
  await page.getByRole("button", { name: /^(Ingia|Sign in)$/ }).click();
  await expect(page.getByRole("heading", { name: /Karibu/ })).toBeVisible();
}

test("a parent sees the child's results, progress by term and homework", async ({ page, request }) => {
  const log = process.env.E2E_API_LOG;
  test.skip(!log, "E2E_API_LOG (the API's console-SMS log) is needed to read the code");
  const login = await request.post(`${API}/auth/login`, { data: { school_code: "mfano-sec", username: "admin", password: "Mfano@2026" } });
  const headers = { Authorization: `Bearer ${(await login.json()).access_token}` };
  const students = await (await request.get(`${API}/students?q=MF-2025-0014`, { headers })).json();
  const linked = await request.post(`${API}/students/${students.items[0].id}/guardians`, { headers, data: {
    first_name: "Halima", last_name: "Massawe", gender: "F", phone: parentPhone, relationship: "MOTHER", sms_consent: true } });
  expect(linked.status()).toBe(201);

  await page.goto("/login");
  await page.getByRole("tab", { name: "Wazazi" }).click();
  await page.getByLabel("Namba ya simu").fill(parentPhone);
  await page.getByRole("button", { name: "Tuma namba ya siri" }).click();
  let code = "";
  await expect.poll(() => {
    const lines = readFileSync(log!, "utf-8").split("\n").filter((l) => l.includes(`****${parentPhone.slice(-4)}`));
    code = lines.at(-1)?.match(/\b(\d{6})\b/)?.[1] ?? "";
    return code;
  }, { timeout: 10_000 }).toMatch(/^\d{6}$/);
  await page.getByLabel("Namba ya siri (tarakimu 6)").fill(code);
  await page.getByRole("button", { name: "Thibitisha" }).click();

  await page.getByTestId("children").getByRole("button", { name: /Amani/ }).click();
  await expect(page.getByTestId("progress")).toContainText("Muhula wa Kwanza");
  await expect(page.getByTestId("progress")).toContainText(/\d+\/\d+/);          // class position
  await expect(page.getByTestId("homework-due")).toBeVisible();
  await expect(page.getByTestId("month-attendance")).toBeVisible();
});

test("a student sees their own progress, attendance and homework at home", async ({ page }) => {
  await signIn(page, "mf-2025-0014");
  await expect(page.getByTestId("progress")).toContainText("Muhula wa Kwanza");
  await expect(page.getByTestId("month-attendance")).toBeVisible();
  await expect(page.getByTestId("homework-due")).toBeVisible();
});
