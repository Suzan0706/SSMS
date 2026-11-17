// Extension Phase 9 (design/20 §20.7): library cards, lending by card number, a fined late return.
import { expect, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

const GATE_JUMA = "00000002-0000-4000-8000-000000000006";

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

test("the librarian issues cards, lends by card and a late return is fined", async ({ page, request }) => {
  const admin = await adminApi(request);
  await request.put("/api/v1/fine-rules/library-day", { headers: admin, data: { amount_tzs: "100", grace_days: 0 } });
  await request.post(`/api/v1/users/${GATE_JUMA}/roles`, { headers: admin, data: { role_code: "librarian" } });
  try {
    await signIn(page, "gate.juma");
    await page.getByRole("link", { name: "Maktaba" }).first().click();

    const cards = page.getByTestId("library-cards");
    await page.getByLabel("Darasa / mkondo").selectOption({ label: "F2 A" });
    await page.getByRole("button", { name: "Toa kadi" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Kadi zilizotolewa" })).toBeVisible();
    const amaniCard = cards.getByRole("listitem").filter({ hasText: "Amani" });
    const cardNo = (await amaniCard.locator(".font-mono").innerText()).trim();
    expect(cardNo).toMatch(/^LC-\d{4}-\d{6}$/);
    const [pdf] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Chapisha kadi" }).click()]);
    expect(pdf.suggestedFilename()).toBe("library-cards.pdf");

    // the seeded loan (Basic Mathematics, due 2026-03-16) is long overdue: returning it fines Amani
    const loans = page.getByTestId("loans");
    await loans.getByRole("listitem").filter({ hasText: "Basic Mathematics" }).getByRole("button", { name: "Kimerudishwa" }).click();
    await expect(page.getByRole("status").filter({ hasText: "faini ya maktaba imewekwa" })).toBeVisible();

    const book = page.getByTestId("books").getByRole("listitem").filter({ hasText: "Basic Mathematics" });
    await book.getByRole("textbox").fill(cardNo);
    await book.getByRole("button", { name: "Azima" }).click();
    await expect(loans).toContainText("Amani");
  } finally {
    await request.delete(`/api/v1/users/${GATE_JUMA}/roles/librarian`, { headers: admin });
  }
});
