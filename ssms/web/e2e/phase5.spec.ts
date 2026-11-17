// Phase 5 end-to-end: a student asks for a bed, the hostel office opens a boys' hostel, adds a room and approves;
// the librarian lends a book; a teacher records a discipline incident. Needs a seeded database.
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

test.describe.configure({ mode: "serial" });

const run = String(Date.now()).slice(-5);
const hostel = `Bweni la Serengeti ${run}`;

async function signIn(page: Page, username: string, password = "Mfano@2026") {
  await page.goto("/login");
  await page.getByLabel(/Namba ya shule|School code/).fill("mfano-sec");
  await page.getByLabel(/Jina la mtumiaji|Username/).fill(username);
  await page.getByLabel(/^(Nenosiri|Password)$/).fill(password);
  await page.getByRole("button", { name: /^(Ingia|Sign in)$/ }).click();
  await expect(page.getByRole("heading", { name: /Karibu/ })).toBeVisible();
}

test("student asks for a bed and the hostel office approves it", async ({ browser }) => {
  const student = await browser.newPage();
  await signIn(student, "mf-2025-0014");                                   // Amani (boy, Form II A)
  const boarding = student.getByTestId("boarding");
  await boarding.getByRole("button", { name: "Omba nafasi ya bweni" }).click();
  await expect(boarding.getByText("Inasubiri idhini")).toBeVisible();

  const office = await browser.newPage();
  await signIn(office, "admin");
  await office.getByRole("link", { name: "Mabweni" }).first().click();
  const add = office.locator("section", { has: office.getByRole("heading", { name: "Mabweni" }) });
  await add.getByLabel("Jina").fill(hostel);
  await add.getByLabel("Jinsia").selectOption("M");
  await add.getByRole("button", { name: "Ongeza" }).click();
  const card = office.locator("section", { has: office.getByRole("heading", { name: `${hostel} · M` }) });
  await card.getByLabel("Chumba").fill("S1");
  await card.getByLabel("Uwezo").fill("2");
  await card.getByRole("button", { name: "Ongeza" }).click();
  await expect(card.getByText("S1")).toBeVisible();

  await office.reload();
  const requests = office.getByTestId("requests");
  await requests.getByLabel("Amani John Massawe Chumba").selectOption({ label: `${hostel} / S1` });
  await requests.getByRole("button", { name: "Idhinisha" }).first().click();
  await expect(office.locator("section", { has: office.getByRole("heading", { name: `${hostel} · M` }) })
    .getByText("Amani John Massawe")).toBeVisible();

  await student.reload();
  await expect(student.getByTestId("boarding").getByText("Imeidhinishwa")).toBeVisible();
  await expect(student.getByTestId("boarding").getByText(`${hostel} / S1`)).toBeVisible();
});

test("librarian lends a book and takes it back", async ({ page }) => {
  await signIn(page, "admin");
  await page.getByRole("link", { name: "Maktaba" }).first().click();
  const books = page.getByTestId("books");
  const title = "Basic Mathematics for Secondary Schools Book Two";
  await expect(books.getByText(/Vilivyopo: 2\/3/)).toBeVisible();          // seed: one copy already on loan
  await books.getByLabel(`Namba ya usajili ${title}`).fill("MF-2025-0031");
  await books.getByRole("button", { name: "Azima" }).click();
  await expect(books.getByText(/Vilivyopo: 1\/3/)).toBeVisible();
  const loan = page.getByTestId("loans").getByRole("listitem").filter({ hasText: "Baraka Joseph Lyimo" });
  await loan.getByRole("button", { name: "Kimerudishwa" }).click();
  await expect(books.getByText(/Vilivyopo: 2\/3/)).toBeVisible();
});

test("teacher records a discipline incident and resolves it", async ({ page }) => {
  await signIn(page, "tch.mwita");
  await page.getByRole("link", { name: "Nidhamu" }).first().click();
  await page.getByLabel("Tafuta jina au namba ya usajili").fill("MF-2025-0040");
  await page.getByRole("button", { name: /MF-2025-0040/ }).click();
  await page.getByLabel("Kundi").selectOption("TRUANCY");
  await page.getByLabel("Ujumbe").fill(`Hakuhudhuria vipindi vya mchana (${run}).`);
  await page.getByRole("button", { name: "Hifadhi" }).click();
  const item = page.getByTestId("incidents").getByRole("listitem").filter({ hasText: run });
  await expect(item).toContainText("OPEN");
  await item.getByLabel(/Utatuzi/).fill("Amezungumza na mwalimu wa nidhamu");
  await item.getByRole("button", { name: "Funga tukio" }).click();
  await expect(page.getByTestId("incidents").getByRole("listitem").filter({ hasText: run })).toHaveCount(0);  // OPEN list
});
