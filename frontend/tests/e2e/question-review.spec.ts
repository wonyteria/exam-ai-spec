import { expect, test } from "@playwright/test";

const DOC = "doc_qr";

const RESTORATION_BODY = {
  restoration_status: "NEEDS_USER_REVIEW",
  final_status: "NEEDS_REVIEW",
  counts: {
    AUTO_RESTORED: 4,
    AUTO_CORRECTED: 1,
    NEEDS_USER_REVIEW: 1,
    USER_EDITED: 0,
    USER_CONFIRMED: 0,
    BLOCKED: 0,
    total: 6,
  },
  review_questions: [
    {
      id: "q11",
      number: 11,
      label: "11",
      status: "NEEDS_USER_REVIEW",
      issues: [
        { field: "choice:①", reason: "sign_ambiguity", detail: "부호 불일치 후보: ['-35', '35']" },
      ],
      crop: null,
    },
  ],
};

const QUESTION_BODY = {
  id: "q11",
  number: 11,
  label: "11",
  type: "multiple_choice",
  points: 3,
  body: ["다음 중 옳은 것은?"],
  choices: [
    { label: "①", body: ["35"] },
    { label: "②", body: ["-25"] },
  ],
  equations: [],
  figures: [],
  answer: null,
  status: "NEEDS_USER_REVIEW",
  confidence: 0.5,
  issues: [
    { field: "choice:①", reason: "sign_ambiguity", detail: "부호 불일치" },
  ],
  corrections: [],
  atus: [],
  logic_flags: [],
  crop: null,
  crop_clean: null,
};

const REVIEW_ITEMS_BODY = {
  items: [],
  logic_flags: [],
  gate: null,
  missing_numbers: [],
  unresolved_labels: [],
};

async function seed(
  page: import("@playwright/test").Page,
  captured: { edits: Record<string, unknown>[] },
) {
  await page.addInitScript(() => {
    localStorage.setItem("examdna_dev_user", "teacher1");
    localStorage.setItem("examdna_tenant", "tn_1");
  });
  await page.route(`**/api/documents/${DOC}/restoration`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(RESTORATION_BODY),
    });
  });
  await page.route(
    `**/api/documents/${DOC}/review-items`,
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(REVIEW_ITEMS_BODY),
      });
    },
  );
  await page.route(
    `**/api/v1/tenants/tn_1/documents/${DOC}`,
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ data: { head_revision: { id: "rev_1" } } }),
      });
    },
  );
  await page.route(
    `**/api/v1/tenants/tn_1/documents/${DOC}/revisions`,
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ data: { revisions: [] } }),
      });
    },
  );
  await page.route(
    `**/api/documents/${DOC}/questions/q11/edit`,
    async (route) => {
      const body = route.request().postDataJSON();
      captured.edits.push(body);
      if (!body.apply) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            ok: true,
            recognized: true,
            explanation: "①번 선택지를 '-35'로 수정합니다.",
            applied: false,
            preview: {
              before: QUESTION_BODY,
              after: {
                ...QUESTION_BODY,
                choices: [
                  { label: "①", body: ["-35"] },
                  { label: "②", body: ["-25"] },
                ],
              },
            },
          }),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            ok: true,
            recognized: true,
            applied: true,
            explanation: "적용되었습니다.",
            preview: { before: QUESTION_BODY, after: QUESTION_BODY },
          }),
        });
      }
    },
  );
  await page.route(
    `**/api/documents/${DOC}/questions/q11`,
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(QUESTION_BODY),
      });
    },
  );
}

test.describe("question-centric review", () => {
  test("shows status counts and only problem questions", async ({ page }) => {
    const captured = { edits: [] as Record<string, unknown>[] };
    await seed(page, captured);
    await page.goto(`/documents/${DOC}/review`);

    await expect(page.getByText("자동 복원 4")).toBeVisible();
    await expect(page.getByText("검토 필요 1")).toBeVisible();
    // Only the problem question appears in the list.
    await expect(page.getByText("11번 — ①번 선택지 확인 필요")).toBeVisible();
  });

  test("question detail opens with fields; edit previews then applies", async ({
    page,
  }) => {
    const captured = { edits: [] as Record<string, unknown>[] };
    await seed(page, captured);
    await page.goto(`/documents/${DOC}/review`);

    await page.getByText("11번 — ①번 선택지 확인 필요").click();
    await expect(page.getByText("다음 중 옳은 것은?")).toBeVisible();

    await page.getByLabel("자연어 수정").fill("①번 보기를 -35로 수정해");
    await page.getByRole("button", { name: "미리보기" }).click();
    await expect(page.getByText("수정 전 → 수정 후")).toBeVisible();
    expect(captured.edits[0].apply).toBe(false);

    await page.getByRole("button", { name: "적용" }).click();
    await expect
      .poll(() => captured.edits.length, { timeout: 10_000 })
      .toBe(2);
    expect(captured.edits[1].apply).toBe(true);
  });
});
