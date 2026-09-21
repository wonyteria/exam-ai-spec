import { expect, test } from "@playwright/test";

const DOC = "doc_x1";

const DOC_BODY = {
  id: DOC,
  verification: { status: "NEEDS_REVIEW", gate: { text_conflict: 0 } },
};

const ELIGIBILITY_BASE = {
  document_id: DOC,
  revision_id: "rev_9",
  revision_no: 9,
  mode: "EDIT",
  content_ready: false,
  content_checks: [
    {
      check_kind: "SCHEMA_REFERENTIAL_INTEGRITY",
      state: "PASSED",
      applicable: true,
      stale_reason: null,
      method: "schema",
      result_summary: "ok",
    },
    {
      check_kind: "QUESTION_CHOICE_SCORE_COMPLETENESS",
      state: "NOT_RUN",
      applicable: true,
      stale_reason: null,
      method: "",
      result_summary: "",
    },
  ],
  blocking_issues: [] as Record<string, unknown>[],
  formats: {
    hwpx: {
      checks: [
        { check_kind: "FORMAT_OPEN_VALIDITY", state: "NOT_RUN" },
        { check_kind: "LAYOUT_STYLE_BOUNDS", state: "NOT_RUN" },
      ],
      final_eligible: false,
      artifacts: [] as { id: string; state: string; sha256: string }[],
    },
    hwp: { checks: [], final_eligible: false, artifacts: [] },
    pdf: { checks: [], final_eligible: false, artifacts: [] },
  },
};

async function seed(
  page: import("@playwright/test").Page,
  captured: { artifacts: Record<string, unknown>[]; exports: Record<string, unknown>[] },
  eligibility: typeof ELIGIBILITY_BASE = ELIGIBILITY_BASE,
  afterCreate?: (e: typeof ELIGIBILITY_BASE) => typeof ELIGIBILITY_BASE,
) {
  let artifactCalls = 0;
  await page.addInitScript(() => {
    localStorage.setItem("examdna_dev_user", "teacher1");
    localStorage.setItem("examdna_tenant", "tn_1");
  });
  await page.route(`**/api/documents/${DOC}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(DOC_BODY),
    });
  });
  await page.route(
    `**/api/v1/tenants/tn_1/documents/${DOC}/eligibility`,
    async (route) => {
      // After an artifact is created the server re-proves and the next
      // eligibility read can report FINAL_ELIGIBLE artifacts.
      const e =
        artifactCalls > 0 && afterCreate ? afterCreate(eligibility) : eligibility;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ data: e }),
      });
    },
  );
  await page.route(
    `**/api/v1/tenants/tn_1/documents/${DOC}/artifacts`,
    async (route) => {
      artifactCalls += 1;
      captured.artifacts.push(route.request().postDataJSON());
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            artifact: {
              id: "art_1",
              format: "hwpx",
              artifact_sha256: "ab".repeat(32),
              state: "DRAFT",
            },
            proof: null,
          },
        }),
      });
    },
  );
  await page.route(
    `**/api/v1/tenants/tn_1/documents/${DOC}/exports`,
    async (route) => {
      captured.exports.push(route.request().postDataJSON());
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            artifacts: [
              {
                id: "art_1",
                format: "hwpx",
                sha256: "ab".repeat(32),
                download_url: "/api/v1/artifacts/art_1/download?purpose=final",
              },
            ],
          },
        }),
      });
    },
  );
}

test.describe("export page", () => {
  test("draft artifact creation uses head revision and exposes draft download", async ({
    page,
  }) => {
    const captured = { artifacts: [] as Record<string, unknown>[], exports: [] as Record<string, unknown>[] };
    await seed(page, captured);
    await page.goto(`/documents/${DOC}/export`);

    await expect(page.getByText("검증 필요")).toBeVisible();
    await expect(
      page.getByText("SCHEMA_REFERENTIAL_INTEGRITY"),
    ).toBeVisible();

    const row = page.locator('[data-format="hwpx"]');
    await row.getByRole("button", { name: "초안" }).click();

    await expect
      .poll(() => captured.artifacts.length, { timeout: 10_000 })
      .toBe(1);
    expect(captured.artifacts[0]).toMatchObject({
      revision_id: "rev_9",
      format: "hwpx",
    });
    await expect(page.getByText("HWPX 초안 (DRAFT) 다운로드")).toBeVisible();
    // Final export is gated — the button must be disabled while the
    // format's required checks are not all PASSED.
    await expect(
      row.getByRole("button", { name: "최종 export" }),
    ).toBeDisabled();
    expect(captured.exports).toHaveLength(0);
  });

  test("final export promotes the FINAL_ELIGIBLE artifact, not a fresh draft", async ({
    page,
  }) => {
    const elig = structuredClone(ELIGIBILITY_BASE);
    elig.content_ready = true;
    elig.formats.hwpx.final_eligible = true;
    const captured = { artifacts: [] as Record<string, unknown>[], exports: [] as Record<string, unknown>[] };
    // The freshly created artifact is DRAFT — the UI must re-read
    // eligibility and promote the artifact the server proved
    // FINAL_ELIGIBLE instead of sending the draft id.
    await seed(page, captured, elig, (e) => {
      const next = structuredClone(e);
      next.formats.hwpx.artifacts = [
        { id: "art_final1", state: "FINAL_ELIGIBLE", sha256: "cd".repeat(32) },
      ];
      return next;
    });
    await page.goto(`/documents/${DOC}/export`);

    await expect(page.getByText("콘텐츠 검증 완료")).toBeVisible();
    const row = page.locator('[data-format="hwpx"]');
    const finalBtn = row.getByRole("button", { name: "최종 export" });
    await expect(finalBtn).toBeEnabled();
    await finalBtn.click();

    await expect
      .poll(() => captured.exports.length, { timeout: 10_000 })
      .toBe(1);
    expect(captured.exports[0]).toMatchObject({
      revision_id: "rev_9",
      artifact_ids: ["art_final1"],
    });
    await expect(page.getByText("HWPX 최종본 다운로드")).toBeVisible();
  });

  test("final export fails closed when no FINAL_ELIGIBLE artifact appears", async ({
    page,
  }) => {
    const elig = structuredClone(ELIGIBILITY_BASE);
    elig.content_ready = true;
    elig.formats.hwpx.final_eligible = true;
    const captured = { artifacts: [] as Record<string, unknown>[], exports: [] as Record<string, unknown>[] };
    await seed(page, captured, elig); // eligibility never gains a FINAL_ELIGIBLE artifact
    await page.goto(`/documents/${DOC}/export`);

    const row = page.locator('[data-format="hwpx"]');
    await row.getByRole("button", { name: "최종 export" }).click();

    await expect(page.getByText(/최종 조건을 충족한 아티팩트가 없습니다/)).toBeVisible();
    expect(captured.exports).toHaveLength(0);
  });

  test("blocking issues link back to review", async ({ page }) => {
    const elig = structuredClone(ELIGIBILITY_BASE);
    elig.blocking_issues = [
      { id: "iss_1", kind: "QUESTION_CHOICE_SCORE_COMPLETENESS", blocking: true },
    ];
    const captured = { artifacts: [] as Record<string, unknown>[], exports: [] as Record<string, unknown>[] };
    await seed(page, captured, elig);
    await page.goto(`/documents/${DOC}/export`);

    await expect(page.getByText("차단 이슈 1건")).toBeVisible();
    const link = page.getByRole("link", { name: "예외 검토" });
    await expect(link).toHaveAttribute("href", `/documents/${DOC}/review`);
  });
});
