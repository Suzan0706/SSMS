// Extension Phase 7 (design/20 §20.7): candidate numbers, admit cards, exam timetable PDF, subject ranking.
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

test("the office numbers candidates and prints admit cards; the student downloads theirs", async ({ page, browser }) => {
  await signIn(page, "admin");
  await page.getByRole("link", { name: "Mitihani" }).first().click();
  await page.getByLabel("Muhula", { exact: true }).selectOption({ label: "Muhula wa Kwanza" });
  await page.getByLabel("Kipindi").selectOption({ label: "Mitihani ya katikati Machi 2026 (2026-03-16 – 2026-03-20)" });
  const bar = page.getByTestId("exam-documents");
  await expect(bar).toContainText(/Watahiniwa: 0\/\d+/);
  await bar.getByRole("button", { name: "Toa namba za watahiniwa" }).click();
  await expect(bar.getByRole("status")).toContainText("Waliopewa namba");
  const [cards] = await Promise.all([page.waitForEvent("download"), bar.getByRole("button", { name: "Kadi za mtihani" }).click()]);
  expect(cards.suggestedFilename()).toBe("admit-cards.pdf");
  const [timetable] = await Promise.all([page.waitForEvent("download"), bar.getByRole("button", { name: /Ratiba ya mitihani/ }).click()]);
  expect(timetable.suggestedFilename()).toBe("exam-timetable.pdf");

  const student = await browser.newPage();
  await signIn(student, "mf-2025-0014");
  await student.getByRole("link", { name: "Masomo yangu" }).first().click();
  await student.getByRole("tab", { name: "Kadi za mtihani" }).click();
  await expect(student.getByTestId("admit-cards")).toContainText("S.4521-");
  const [own] = await Promise.all([student.waitForEvent("download"), student.getByRole("button", { name: "Pakua kadi ya mtihani" }).click()]);
  expect(own.suggestedFilename()).toBe("admit-card.pdf");
  await student.close();
});

test("results show a subject's ranking, best first", async ({ page }) => {
  await signIn(page, "admin");
  await page.getByRole("link", { name: "Matokeo" }).first().click();
  await page.getByLabel("Muhula", { exact: true }).selectOption({ label: "Muhula wa Kwanza" });
  await page.getByLabel("Darasa", { exact: true }).selectOption({ label: "Kidato cha Pili" });
  await page.getByLabel("Nafasi kwa somo").selectOption({ label: "Hisabati za Msingi" });
  const ranking = page.getByTestId("subject-ranking");
  await expect(ranking.locator("tbody tr").first().locator("td").first()).toHaveText("1");
});
