// Each role card on the front page leads to that role's own home page (asked for on 2026-11-12: choosing
// "Mkutubi" used to end in the administrator's view, because there was no librarian account to sign in with).
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

async function viaCard(page: Page, card: string, username: string, expectedLabel: string) {
  await page.goto("/");
  const role = page.getByRole("listitem").filter({ has: page.getByRole("heading", { name: card, exact: true }) });
  await role.getByRole("link", { name: "Ingia" }).click();
  await expect(page.getByTestId("signing-in-as")).toContainText(expectedLabel);
  if (await page.getByLabel(/^(Namba ya simu|Phone number)$/).isVisible()) {           // the parent card opens the SMS-code tab
    await page.getByRole("button", { name: /Una jina la mtumiaji na nenosiri/ }).click();
  }
  await page.getByLabel(/Namba ya shule|School code/).fill("mfano-sec");
  await page.getByLabel(/Jina la mtumiaji|Username/).fill(username);
  await page.getByLabel(/^(Nenosiri|Password)$/).fill("Mfano@2026");
  await page.getByRole("button", { name: /^(Ingia|Sign in)$/ }).click();
  await expect(page.getByRole("heading", { name: /Karibu/ })).toBeVisible();
}

const cases: Array<[string, string, string, (page: Page) => Promise<void>]> = [
  ["Mkutubi", "librarian", "Mkutubi", async (page) => {
    await expect(page.getByTestId("dashboard-librarian")).toBeVisible();
    await expect(page.getByRole("link", { name: "Maktaba" }).first()).toBeVisible();
    for (const hidden of ["Ada", "Alama", "Matokeo"]) await expect(page.getByRole("link", { name: hidden, exact: true })).toHaveCount(0);
  }],
  ["Mpokezi", "reception", "Mpokezi", async (page) => {
    await expect(page.getByTestId("dashboard-receptionist")).toBeVisible();
    for (const hidden of ["Ada", "Alama", "Afya"]) await expect(page.getByRole("link", { name: hidden, exact: true })).toHaveCount(0);
  }],
  ["Mhasibu", "bursar", "Mhasibu", async (page) => { await expect(page.getByTestId("dashboard-bursar")).toBeVisible(); }],
  ["Mwalimu", "tch.laizer", "Mwalimu", async (page) => { await expect(page.getByTestId("dashboard-teacher")).toBeVisible(); }],
  ["Msimamizi wa shule", "admin", "Msimamizi wa shule", async (page) => { await expect(page.getByTestId("dashboard-admin")).toBeVisible(); }],
  ["Mwanafunzi", "mf-2025-0014", "Mwanafunzi", async (page) => { await expect(page.getByTestId("today-lessons")).toBeVisible(); }],
  ["Mzazi", "mzazi", "Mzazi", async (page) => { await expect(page.getByTestId("children")).toContainText("Amani"); }],
];

for (const [card, username, label, landing] of cases) {
  test(`the ${card} card leads to the ${card} home page`, async ({ page }) => {
    await viaCard(page, card, username, label);
    await landing(page);
    await expect(page.getByTestId("role-notice")).toHaveCount(0);
  });
}

test("choosing a role and signing in with another account says so", async ({ page }) => {
  await viaCard(page, "Mkutubi", "admin", "Mkutubi");
  await expect(page.getByTestId("role-notice")).toContainText("Ulichagua Mkutubi");
  await expect(page.getByTestId("role-notice")).toContainText("Msimamizi wa shule");
  await page.getByRole("button", { name: /Toka, uingie kwa akaunti nyingine/ }).click();
  await expect(page.getByTestId("signing-in-as")).toContainText("Mkutubi");
});
