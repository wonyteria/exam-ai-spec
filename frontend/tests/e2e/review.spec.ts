import { expect, test } from "@playwright/test";

const DOC = "doc_r1";

const REVIEW_BODY = {
  items: [
    {
      atu_id: "atu_1",
      question_number: 5,
      question_label: "?mark1",
      kind: "text_token",
      status: "UNVERIFIED",
      source: null,
      candidates: [
        { provider: "paddle", value: "합동 조건" },
        { provider: "easyocr", value: "합동 조권" },
      ],
    },
    {
      atu_id: "atu_2",
      question_number: 6,
      question_label: "6",
      kind: "points",
      status: "CONFLICT",
      source: null,
      candidates: [
        { provider: "paddle", value: "3" },
        { provider: "easyocr", value: "4" },
      ],
    },
    {
      atu_id: "atu_3",
      question_number: 6,
      question_label: "6",
      kind: "text_token",
      status: "UNVERIFIED",
      source: null,
      candidates: [],
    },
  ],
  logic_flags: [],
  gate: null,
  missing_numbers: [4],
  unresolved_labels: ["?mark1"],
};

const REVISIONS_BODY = {
  data: {
    revisions: [
      {
        id: "rev_1",
        document_id: DOC,
        revision_no: 1,
        mode: "snapshot",
        created_at: 1,
      },
      {
        id: "rev_2",
        document_id: DOC,
        revision_no: 2,
        mode: "pipeline",
        created_at: 2,
      },
    ],
  },
};

async function seed(
  page: import("@playwright/test").Page,
  captured: { changes: Record<string, unknown>[]; resolved: string[] },
) {
  await page.addInitScript(() => {
    localStorage.setItem("examdna_dev_user", "teacher1");
    localStorage.setItem("examdna_tenant", "tn_1");
  });
  await page.route(`**/api/documents/${DOC}/review-items`, async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(REVIEW_BODY),
      });
    } else {
      await route.continue();
    }
  });
  await page.route(
    `**/api/documents/${DOC}/review-items/*`,
    async (route) => {
      captured.resolved.push(route.request().url().split("/").pop() ?? "");
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ok: true, revisioned: true }),
      });
    },
  );
  await page.route(
    `**/api/v1/tenants/tn_1/documents/${DOC}/revisions`,
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(REVISIONS_BODY),
      });
    },
  );
  await page.route(
    `**/api/v1/tenants/tn_1/documents/${DOC}/changes`,
    async (route) => {
      captured.changes.push({
        ops: route.request().postDataJSON()?.ops,
        ifMatch: route.request().headers()["if-match"],
      });
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: { revision: { id: "rev_3", revision_no: 3 } },
        }),
      });
    },
  );
}

test.describe("review page", () => {
  test("?-labeled group offers number confirmation via canonical changes", async ({
    page,
  }) => {
    const captured = { changes: [] as Record<string, unknown>[], resolved: [] as string[] };
    await seed(page, captured);
    await page.goto(`/documents/${DOC}/review`);

    await expect(page.getByText("?mark1번 문항")).toBeVisible();
    const group = page.locator("section", { hasText: "?mark1번 문항" });
    await group.getByPlaceholder("번호").fill("4");
    await group.getByRole("button", { name: "번호 확정" }).click();

    await expect
      .poll(() => captured.changes.length, { timeout: 10_000 })
      .toBe(1);
    expect(captured.changes[0].ifMatch).toBe("rev_2");
    expect(captured.changes[0].ops).toEqual([
      { op: "SetField", target_id: "?mark1", field: "number", value: 4 },
    ]);
  });

  test("clicking an OCR candidate fills the confirm input; 확정 resolves", async ({
    page,
  }) => {
    const captured = { changes: [] as Record<string, unknown>[], resolved: [] as string[] };
    await seed(page, captured);
    await page.goto(`/documents/${DOC}/review`);

    // candidate click fills the input
    await page.getByRole("button", { name: '"합동 조건"' }).click();
    const input = page.locator('input[placeholder="확정 값 입력"]').first();
    await expect(input).toHaveValue("합동 조건");

    await input.press("Enter");
    await expect
      .poll(() => captured.resolved, { timeout: 10_000 })
      .toContain("atu_1");
  });

  test("status filter narrows the list", async ({ page }) => {
    const captured = { changes: [] as Record<string, unknown>[], resolved: [] as string[] };
    await seed(page, captured);
    await page.goto(`/documents/${DOC}/review`);

    await page.getByRole("tab", { name: /충돌/ }).click();
    await expect(page.getByText("배점")).toBeVisible();
    await expect(page.getByText("?mark1번 문항")).not.toBeVisible();
    await page.getByRole("tab", { name: /전체/ }).click();
    await expect(page.getByText("?mark1번 문항")).toBeVisible();
  });
});
