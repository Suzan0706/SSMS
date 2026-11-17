// Extension Phase 4 (design/20 §20.7): session selector (FR-72), receptionist role and dashboards (FR-73, FR-76).
import { expect, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

const GATE_JUMA = "00000002-0000-4000-8000-000000000006"; // seeded gatekeeper account

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

test("choosing another year shows its lists, read-only, and the choice is remembered", async ({ page, request }) => {
  const admin = await adminApi(request);
  const years: Array<{ name: string }> = await (await request.get("/api/v1/academic-years", { headers: admin })).json();
  if (!years.some((y) => y.name === "2025")) {
    const made = await request.post("/api/v1/academic-years", { headers: admin, data: { name: "2025", start_date: "2025-01-01", end_date: "2025-12-31" } });
    expect(made.status()).toBe(201);
  }

  await signIn(page, "admin");
  await page.getByRole("link", { name: "Wanafunzi" }).first().click();
  const classes = page.getByRole("table", { name: "Wanafunzi" }).locator("tbody tr td:nth-child(3)");
  await expect(classes.filter({ hasText: /F\d/ }).first()).toBeVisible();   // some students have a class

  await page.getByTestId("year-select").selectOption({ label: "2025" });
  await expect(page.getByRole("status").filter({ hasText: "Unatazama mwaka 2025" })).toBeVisible();
  await expect(classes.first()).toBeVisible();
  for (const text of await classes.allInnerTexts()) expect(text).not.toMatch(/F\d/);   // nobody was enrolled in 2025

  await page.reload();                                                                  // remembered for this person
  await expect(page.getByTestId("year-select").locator("option:checked")).toHaveText("2025");

  await page.getByRole("button", { name: /Rudi mwaka wa sasa/ }).click();
  await expect(page.getByRole("status").filter({ hasText: "Unatazama mwaka" })).toHaveCount(0);
  await expect(classes.filter({ hasText: /F\d/ }).first()).toBeVisible();
});

test("a receptionist gets the front-desk dashboard and no money or marks menus", async ({ page, request }) => {
  const admin = await adminApi(request);
  const added = await request.post(`/api/v1/users/${GATE_JUMA}/roles`, { headers: admin, data: { role_code: "receptionist" } });
  expect([201, 409]).toContain(added.status());
  try {
    await signIn(page, "gate.juma");
    await expect(page.getByTestId("dashboard-receptionist")).toBeVisible();
    await expect(page.getByText("Maombi yanayosubiri")).toBeVisible();
    await expect(page.getByRole("link", { name: "Wanafunzi" }).first()).toBeVisible();
    await expect(page.getByRole("link", { name: "Usajili" }).first()).toBeVisible();
    for (const hidden of ["Ada", "Alama", "Afya", "Matokeo"]) {
      await expect(page.getByRole("link", { name: hidden, exact: true })).toHaveCount(0);
    }
  } finally {
    await request.delete(`/api/v1/users/${GATE_JUMA}/roles/receptionist`, { headers: admin });
  }
});
