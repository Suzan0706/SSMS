// Phase 4 end-to-end: a class teacher takes the morning register offline and it syncs; a gate tap shows on the
// register; the head teacher posts an announcement; a parent sees the child's mark for today and the announcement.
// Needs a seeded database and the API started with api/scripts/e2e_api.py, which fixes the date; the browser is pinned
// to the same day below, so these tests give the same result on any day.
import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

test.describe.configure({ mode: "serial" });

const API = "/api/v1";
const SCHOOL_DAY = "2026-10-21";                    // the date in api/scripts/e2e_api.py, a Wednesday in Term Two

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date(`${SCHOOL_DAY}T09:00:00+03:00`));
});
const run = String(Date.now()).slice(-6);
const parentPhone = `0657${run}`;
const title = `Mkutano wa wazazi ${run}`;

async function signIn(page: Page, username: string, password = "Mfano@2026") {
  await page.goto("/login");
  await page.getByLabel(/Namba ya shule|School code/).fill("mfano-sec");
  await page.getByLabel(/Jina la mtumiaji|Username/).fill(username);
  await page.getByLabel(/^(Nenosiri|Password)$/).fill(password);
  await page.getByRole("button", { name: /^(Ingia|Sign in)$/ }).click();
  await expect(page.getByRole("heading", { name: /Karibu/ })).toBeVisible();
}

test("class teacher takes the register offline, it syncs, and a gate tap shows", async ({ page, context, request }) => {
  await signIn(page, "tch.laizer");                 // class teacher of Form II B, Kiswahili
  await page.getByRole("link", { name: "Mahudhurio" }).first().click();
  const register = page.getByTestId("register");
  await expect(register).toBeVisible();

  await context.setOffline(true);
  await page.getByRole("button", { name: "Wote wapo" }).click();
  await page.getByRole("button", { name: "Mariam Ali Said Hakufika" }).click();
  await expect(page.getByTestId("sync-state")).toHaveAttribute("data-pending", "2");
  await expect(page.getByText(/Imehifadhiwa kwenye simu/)).toBeVisible();

  await context.setOffline(false);
  await expect(page.getByTestId("sync-state")).toHaveAttribute("data-pending", "0", { timeout: 15_000 });
  await page.reload();
  await expect(page.getByRole("button", { name: "Mariam Ali Said Hakufika" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "Juma Ali Kombo Yupo" })).toHaveAttribute("aria-pressed", "true");

  const now = `${SCHOOL_DAY}T07:25:00+03:00`;
  const tap = await request.post(`${API}/devices/taps`, {
    headers: { "X-Device-Key": "demo-device-key-mfano-gate" },
    data: { taps: [{ token: "card-15", captured_at: now, client_record_id: crypto.randomUUID() }] },
  });
  expect((await tap.json()).results[0].student_name).toBe("Juma Kombo");
  await page.reload();
  await expect(register.getByText(/Geti \d\d:\d\d/)).toBeVisible();
  await page.getByRole("button", { name: "Funga daftari" }).click();
  await expect(page.getByText("Daftari limefungwa ✓")).toBeVisible();
});

test("head teacher posts an announcement to parents", async ({ page }) => {
  await signIn(page, "admin");
  await page.getByRole("link", { name: "Matangazo" }).first().click();
  await page.getByLabel("Kichwa").fill(title);
  await page.getByLabel("Ujumbe").fill("Mkutano utafanyika Jumamosi saa nne asubuhi ukumbini.");
  await page.getByLabel("Wapokeaji").selectOption("PARENTS");
  await page.getByRole("button", { name: "Tangazo jipya" }).click();
  await expect(page.getByTestId("announce-result")).toBeVisible();
  await expect(page.getByTestId("announcements").getByText(title)).toBeVisible();
});

test("parent sees today's mark and the announcement", async ({ page, request }) => {
  const log = process.env.E2E_API_LOG;
  test.skip(!log, "E2E_API_LOG (the API's console-SMS log) is needed to read the code");
  const login = await request.post(`${API}/auth/login`, {
    data: { school_code: "mfano-sec", username: "admin", password: "Mfano@2026" } });
  const headers = { Authorization: `Bearer ${(await login.json()).access_token}` };
  const students = await (await request.get(`${API}/students?q=MF-2025-0044`, { headers })).json();
  const linked = await request.post(`${API}/students/${students.items[0].id}/guardians`, { headers, data: {
    first_name: "Upendo", last_name: "Said", gender: "F", phone: parentPhone, relationship: "MOTHER", sms_consent: true } });
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

  const child = page.getByTestId("children").getByRole("button", { name: /Mariam/ });
  await expect(child).toContainText("Leo: Hakufika");
  await child.click();
  await expect(page.getByTestId("month-attendance")).toContainText("Hakufika: 1");
  await expect(page.getByTestId("announcements").getByText(title)).toBeVisible();
  await expect(page.getByRole("link", { name: "Mahudhurio" })).toHaveCount(0);     // no staff menu
});
