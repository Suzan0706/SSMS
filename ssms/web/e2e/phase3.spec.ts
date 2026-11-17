// Phase 3 end-to-end: the bursar records cash and gets a receipt; a parent sees the statement with that receipt.
// Needs a seeded database (Baraka Lyimo, MF-2025-0031, has an open Term One invoice in the seed).
import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

test.describe.configure({ mode: "serial" });

const API = "/api/v1";
const run = String(Date.now()).slice(-6);
const reference = `E2E-CASH-${run}`;
const parentPhone = `0656${run}`;                     // new number every run

async function signIn(page: Page, username: string, password = "Mfano@2026") {
  await page.goto("/login");
  await page.getByLabel(/Namba ya shule|School code/).fill("mfano-sec");
  await page.getByLabel(/Jina la mtumiaji|Username/).fill(username);
  await page.getByLabel(/^(Nenosiri|Password)$/).fill(password);
  await page.getByRole("button", { name: /^(Ingia|Sign in)$/ }).click();
  await expect(page.getByRole("heading", { name: /Karibu/ })).toBeVisible();
}

test("bursar records a cash payment and downloads the receipt", async ({ page }) => {
  await signIn(page, "bursar");
  await page.getByRole("link", { name: "Ada" }).first().click();
  await page.getByRole("tab", { name: "Rekodi malipo" }).click();
  await page.getByLabel("Tafuta jina au namba ya usajili").fill("MF-2025-0031");
  await page.getByRole("button", { name: /MF-2025-0031/ }).click();
  await expect(page.getByTestId("statement")).toBeVisible();
  const before = await page.getByTestId("outstanding").innerText();

  await page.getByLabel("Kumbukumbu").fill(reference);
  await page.getByLabel("Kiasi").fill("50,000");
  await page.getByRole("button", { name: "Hifadhi na risiti" }).click();
  await expect(page.getByTestId("receipt-no")).toContainText(/RCT-2026-\d{6}/);
  await expect(page.getByTestId("outstanding")).not.toHaveText(before);
  await expect(page.getByTestId("statement").getByText(reference)).toBeVisible();

  const download = page.waitForEvent("download");
  await page.getByTestId("receipt-no").getByRole("button", { name: "PDF" }).click();
  expect((await download).suggestedFilename()).toMatch(/^RCT-2026-\d{6}\.pdf$/);

  // The same reference again is refused (one payment per channel reference).
  await page.getByLabel("Kumbukumbu").fill(reference);
  await page.getByLabel("Kiasi").fill("1000");
  await page.getByRole("button", { name: "Hifadhi na risiti" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
});

test("parent sees the child's statement with the bursar's receipt", async ({ page, request }) => {
  const log = process.env.E2E_API_LOG;
  test.skip(!log, "E2E_API_LOG (the API's console-SMS log) is needed to read the code");
  const login = await request.post(`${API}/auth/login`, {
    data: { school_code: "mfano-sec", username: "admin", password: "Mfano@2026" } });
  const headers = { Authorization: `Bearer ${(await login.json()).access_token}` };
  const students = await (await request.get(`${API}/students?q=MF-2025-0031`, { headers })).json();
  const linked = await request.post(`${API}/students/${students.items[0].id}/guardians`, { headers, data: {
    first_name: "Upendo", last_name: "Lyimo", gender: "F", phone: parentPhone, relationship: "MOTHER",
    sms_consent: true } });
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

  await expect(page.getByRole("heading", { name: "Watoto wangu" })).toBeVisible();
  await page.getByTestId("children").getByRole("button", { name: /Baraka/ }).click();
  const statement = page.getByTestId("statement");
  await expect(statement.getByText(reference)).toBeVisible();
  await expect(statement.getByRole("button", { name: /RCT-2026-\d{6}/ }).first()).toBeVisible();
  await expect(statement.getByText("Omba kubatilisha")).toHaveCount(0);           // parents cannot request reversals
  await expect(page.getByRole("button", { name: "Lipa" })).toBeVisible();      // mobile-money prompt offered
  await expect(page.getByRole("link", { name: "Ada" })).toHaveCount(0);        // no staff finance menu
});
