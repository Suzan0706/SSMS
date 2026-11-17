// Extension Phase 11 (design/20 §20.7): certificates, ID cards, email with announcements, the platform console.
import { expect, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

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

test("the admin writes a certificate template, issues it and prints a class's ID cards", async ({ page }) => {
  await signIn(page, "admin");
  await page.getByRole("link", { name: "Nyaraka" }).first().click();
  await expect(page.getByRole("heading", { name: "Vyeti na vitambulisho" })).toBeVisible();

  await page.getByLabel("Jina", { exact: true }).fill("Cheti cha kuhitimu");
  await page.getByLabel("Maandishi ya kiolezo").fill("Hii ni kuthibitisha kwamba {{name}} ({{admission_no}}) alisoma {{school}}.");
  await page.getByRole("button", { name: "Hifadhi" }).click();
  await expect(page.getByLabel("Kiolezo", { exact: true })).toContainText("Cheti cha kuhitimu");

  await page.getByLabel("Tafuta jina au namba ya usajili").fill("Amani");
  await page.getByRole("button", { name: /Amani/ }).first().click();
  await page.getByRole("button", { name: "Toa vyeti" }).click();
  const row = page.getByRole("table", { name: "Vyeti" }).getByRole("row").filter({ hasText: "Amani" });
  await expect(row).toContainText(/CT-\d{4}-\d{6}/);
  const [pdf] = await Promise.all([page.waitForEvent("download"), row.getByRole("button", { name: "PDF" }).click()]);
  expect(pdf.suggestedFilename()).toMatch(/^CT-\d{4}-\d{6}\.pdf$/);

  await page.getByRole("tab", { name: "Vitambulisho" }).click();
  await page.getByLabel("Kwa ajili ya").selectOption({ label: "F2 A" });
  await page.getByRole("button", { name: "Toa kadi" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Kadi zilizotolewa" })).toBeVisible();
  await expect(page.getByTestId("id-cards").getByRole("listitem").filter({ hasText: "Amani" })).toContainText(/ID-\d{4}-\d{6}/);
  const [cards] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Chapisha kadi" }).click()]);
  expect(cards.suggestedFilename()).toBe("id-cards.pdf");
});

test("a student downloads their own ID card", async ({ page, request }) => {
  const admin = await adminApi(request);
  const streams = await (await request.get("/api/v1/streams", { headers: admin })).json() as Array<{ id: string; name: string; class_id: string }>;
  const classes = await (await request.get("/api/v1/classes", { headers: admin })).json() as Array<{ id: string; code: string }>;
  const f2 = classes.find((c) => c.code === "F2")!;
  const stream = streams.find((s) => s.class_id === f2.id && s.name === "A")!;
  await request.post("/api/v1/identity-cards", { headers: admin, data: { stream_id: stream.id } });

  await signIn(page, "mf-2025-0014");
  const [card] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Kitambulisho changu" }).click()]);
  expect(card.suggestedFilename()).toBe("id-card.pdf");
});

test("an announcement can go by email, and the email history shows it", async ({ page }) => {
  await signIn(page, "admin");
  await page.goto("/announcements");
  await page.getByLabel("Kichwa").fill("Mkutano wa wafanyakazi");
  await page.getByLabel("Ujumbe").fill("Ijumaa saa nane mchana.");
  await page.getByLabel("Tuma pia kwa barua pepe").check();
  await page.getByRole("button", { name: "Tangazo jipya" }).click();
  await expect(page.getByTestId("announce-result")).toContainText("Wapokeaji wa barua pepe");

  await page.getByRole("button", { name: "Nitumie barua pepe ya majaribio" }).click();
  await expect(page.getByTestId("email-history")).toContainText("barua pepe ya majaribio");
});

test("the platform console signs in on its own and shows counts per school", async ({ page }) => {
  await page.goto("/console");
  await page.getByLabel("Barua pepe").fill("ops@ssms.co.tz");
  await page.getByLabel(/^(Nenosiri|Password)$/).fill("Mfano@2026");
  await page.getByRole("button", { name: /^(Ingia|Sign in)$/ }).click();
  const schools = page.getByRole("table", { name: "Shule" });
  await expect(schools.getByRole("row").filter({ hasText: "mfano-sec" })).toBeVisible();
  await expect(page.getByText("Dashibodi ya jukwaa")).toBeVisible();
});
