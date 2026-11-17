// Extension Phase 3 (design/20 §20.7): indigo theme, the shared table, file upload through the web server.
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

test("the interface uses the indigo theme", async ({ page }) => {
  await page.goto("/login");
  const button = page.getByRole("button", { name: /^(Ingia|Sign in)$/ });
  await expect(button).toHaveCSS("background-color", "rgb(79, 70, 229)");          // #4F46E5
  await signIn(page, "admin");
  await expect(page.getByRole("navigation").first()).toHaveCSS("background-color", "rgb(30, 27, 75)"); // #1E1B4B
  await expect(page.locator("body")).toHaveCSS("background-color", "rgb(248, 250, 252)");        // #F8FAFC
});

test("the student table sorts, searches and pages", async ({ page }) => {
  await signIn(page, "admin");
  await page.getByRole("link", { name: "Wanafunzi" }).first().click();
  const table = page.getByRole("table", { name: "Wanafunzi" });
  const names = table.locator("tbody tr td:nth-child(2)");
  await expect(names.first()).toHaveText(/\w/);                                   // real rows, not the loading placeholders

  const sortByName = table.getByRole("button", { name: "Jina" });
  await sortByName.click();
  await expect(table.locator("th").nth(1)).toHaveAttribute("aria-sort", "ascending");
  const ascending = await names.allInnerTexts();
  expect(ascending).toEqual([...ascending].sort((a, b) => a.localeCompare(b)));
  await sortByName.click();
  await expect(table.locator("th").nth(1)).toHaveAttribute("aria-sort", "descending");
  expect(await names.allInnerTexts()).toEqual([...ascending].reverse());

  await page.getByLabel("Tafuta jina au namba ya usajili").fill("MF-2025-0014");
  await expect(table.locator("tbody tr")).toHaveCount(1);
  await expect(page.getByText(/Zinaonyeshwa 1–1 kati ya 1/)).toBeVisible();
  await expect(page.getByRole("button", { name: /Inayofuata/ })).toBeDisabled();
});

test("a photo uploads through the web server and only the right people can read it", async ({ request }) => {
  const login = async (username: string, school_code = "mfano-sec") => {
    const res = await request.post("/api/v1/auth/login", { data: { school_code, username, password: "Mfano@2026" } });
    expect(res.ok()).toBeTruthy();
    return { Authorization: `Bearer ${(await res.json()).access_token}` };
  };
  const admin = await login("admin");
  const png = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.alloc(100, 48)]);
  const up = await request.post("/api/v1/files", {
    headers: admin, multipart: { purpose: "PHOTO", file: { name: "picha.png", mimeType: "image/png", buffer: png } },
  });
  expect(up.status()).toBe(201);
  const { url } = await up.json();
  const read = await request.get(url, { headers: admin });
  expect(read.status()).toBe(200);
  expect(Buffer.compare(await read.body(), png)).toBe(0);

  const wrong = await request.post("/api/v1/files", {
    headers: admin, multipart: { purpose: "PHOTO", file: { name: "picha.png", mimeType: "image/png", buffer: Buffer.from("%PDF-1.4") } },
  });
  expect(wrong.status()).toBe(422);
  const otherSchool = await login("admin", "upendo-pri");
  expect((await request.get(url, { headers: otherSchool })).status()).toBe(404);
});

test("the front page shows the modules and roles and leads to sign-in", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Mfumo kamili wa usimamizi wa shule" })).toBeVisible();
  await page.getByRole("tab", { name: "Ada na ankara" }).click();
  await expect(page.getByRole("tabpanel")).toContainText("GePG");
  const parent = page.getByRole("listitem").filter({ has: page.getByRole("heading", { name: "Mzazi" }) });
  await parent.getByRole("link", { name: "Ingia" }).click();
  await expect(page).toHaveURL(/\/login\?as=parent$/);
  await expect(page.getByRole("tab", { name: "Wazazi" })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("link", { name: /Rudi mwanzo/ }).click();
  await expect(page.getByRole("link", { name: "Ingia" }).first()).toBeVisible();
  await expect(page.locator("body")).not.toHaveText(/Mfano@2026|password:/i);   // no demo passwords on the page
});
