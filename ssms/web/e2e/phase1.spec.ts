// Phase 1 end-to-end flow against the real API and a freshly seeded PostgreSQL 16 database.
// Runs serially: later steps use records created by earlier ones.
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { readFileSync } from "node:fs";

test.describe.configure({ mode: "serial" });

const run = Date.now().toString().slice(-6);
const guardianPhone = `0655${run}`;                     // new number every run
const staffNo = `MF-STF-E${run}`;

async function staffLogin(page: Page, username: string, password: string) {
  await page.goto("/login");
  await page.getByLabel(/Namba ya shule|School code/).fill("mfano-sec");
  await page.getByLabel(/Jina la mtumiaji|Username/).fill(username);
  await page.getByLabel(/^(Nenosiri|Password)$/).fill(password);
  await page.getByRole("button", { name: /^(Ingia|Sign in)$/ }).click();
}

async function signOut(page: Page) {
  await page.getByRole("button", { name: /^(Toka|Sign out)$/ }).first().click();
  await expect(page.getByLabel(/Namba ya shule|School code/)).toBeVisible();
}

test("login page speaks Kiswahili first and switches to English", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("button", { name: "Ingia" })).toBeVisible();
  await page.getByRole("button", { name: "English" }).click();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  await page.getByRole("button", { name: "Kiswahili" }).click();
});

test("wrong password shows the server's Kiswahili message", async ({ page }) => {
  await staffLogin(page, "admin", "not-the-password");
  await expect(page.getByRole("alert")).toContainText("Jina la mtumiaji au nenosiri si sahihi");
});

test("admin admits a student with a new guardian", async ({ page }) => {
  await staffLogin(page, "admin", "Mfano@2026");
  await expect(page.getByRole("heading", { name: /Karibu, Halima/ })).toBeVisible();
  await page.getByRole("link", { name: "Wanafunzi" }).first().click();
  await expect(page.getByText("MF-2025-0014")).toBeVisible();

  await page.getByRole("link", { name: "Sajili mwanafunzi" }).click();
  await page.locator("input[name=first_name]").fill("Imani");
  await page.locator("input[name=last_name]").fill(`Mollel${run}`);
  await page.locator("input[name=date_of_birth]").fill("2013-05-20");
  await page.locator("select[name=stream_id]").selectOption({ label: "F1 A" });
  await page.locator("input[name=guardian_first_name]").fill("Rehema");
  await page.locator("input[name=guardian_last_name]").fill("Mollel");
  await page.locator("input[name=guardian_phone]").fill(guardianPhone);
  await page.locator("input[name=consent]").check();
  await page.getByRole("button", { name: "Hifadhi" }).click();

  await expect(page.getByTestId("admission-no")).toHaveText(/^TZ-\d{4}-\d{4}$/);
  await expect(page.getByText(/F1 A/)).toBeVisible();
  await expect(page.getByText(`255${guardianPhone.slice(1)}`)).toBeVisible();   // admin may see the number
});

test("new staff member must replace the temporary password", async ({ page }) => {
  await staffLogin(page, "admin", "Mfano@2026");
  await page.getByRole("link", { name: "Wafanyakazi" }).first().click();
  await page.getByRole("button", { name: "Ongeza mfanyakazi" }).click();
  await page.locator("input[name=first_name]").fill("Esther");
  await page.locator("input[name=last_name]").fill(`Kweka${run}`);
  await page.locator("input[name=phone]").fill(`0688${run}`);
  await page.locator("input[name=staff_no]").fill(staffNo);
  await page.getByRole("button", { name: "Hifadhi" }).click();
  const credentials = (await page.getByTestId("temp-password").textContent())!.split(" / ");
  await signOut(page);

  await staffLogin(page, credentials[0], credentials[1]);
  await expect(page.getByText("Kwa usalama, weka nenosiri jipya")).toBeVisible();
  await page.locator("input[name=current_password]").fill(credentials[1]);
  await page.locator("input[name=new_password]").fill(`Mwalimu${run}x`);
  await page.getByRole("button", { name: "Hifadhi" }).click();
  await expect(page.getByText(/Karibu, Esther/)).toBeVisible();
});

test("bulk import rejects a bad file with a report, then accepts a good one", async ({ page }) => {
  await staffLogin(page, "admin", "Mfano@2026");
  await page.getByRole("link", { name: "Kupakia kwa wingi" }).first().click();
  const header = "first_name,last_name,gender,date_of_birth,class_code,stream_name,guardian_first_name,"
    + "guardian_last_name,guardian_gender,guardian_phone,guardian_relationship,guardian_sms_consent,data_processing_consent";
  const good = `Baraka,Import${run},M,2012-02-02,F1,A,Juma,Import,M,0656${run},FATHER,YES,YES`;
  const bad = `Neema,Import${run},F,2012-02-02,F9,A,Juma,Import,M,12345,FATHER,YES,YES`;

  await page.locator("input[type=file]").setInputFiles({ name: "bad.csv", mimeType: "text/csv",
    buffer: Buffer.from(`${header}\n${good}\n${bad}\n`) });
  await page.getByRole("button", { name: "Pakia" }).click();
  await expect(page.getByTestId("job-status")).toHaveAttribute("data-status", "FAILED", { timeout: 20_000 });
  await expect(page.getByTestId("job-status").getByRole("button", { name: "Pakua ripoti ya makosa" })).toBeVisible();

  await page.locator("input[type=file]").setInputFiles({ name: "good.csv", mimeType: "text/csv",
    buffer: Buffer.from(`${header}\n${good}\n`) });
  await page.getByRole("button", { name: "Pakia" }).click();
  await expect(page.getByTestId("job-status")).toHaveAttribute("data-status", "SUCCEEDED", { timeout: 20_000 });
});

test("parent signs in with an SMS code", async ({ page }) => {
  const log = process.env.E2E_API_LOG;
  test.skip(!log, "E2E_API_LOG (the API's console-SMS log) is needed to read the code");
  await page.goto("/login");
  await page.getByRole("tab", { name: "Wazazi" }).click();
  await page.getByLabel("Namba ya simu").fill(guardianPhone);
  await page.getByRole("button", { name: "Tuma namba ya siri" }).click();
  await expect(page.getByLabel("Namba ya siri (tarakimu 6)")).toBeVisible();

  let code = "";
  await expect.poll(() => {
    const lines = readFileSync(log!, "utf-8").split("\n").filter((l) => l.includes(`****${guardianPhone.slice(-4)}`));
    code = lines.at(-1)?.match(/\b(\d{6})\b/)?.[1] ?? "";
    return code;
  }, { timeout: 10_000 }).toMatch(/^\d{6}$/);
  await page.getByLabel("Namba ya siri (tarakimu 6)").fill(code);
  await page.getByRole("button", { name: "Thibitisha" }).click();
  await expect(page.getByText(/Karibu, Rehema Mollel/)).toBeVisible();
  await expect(page.getByText("Taarifa za watoto wako")).toBeVisible();
  await expect(page.getByRole("link", { name: "Wanafunzi" })).toHaveCount(0);     // parents have no staff menus
});
