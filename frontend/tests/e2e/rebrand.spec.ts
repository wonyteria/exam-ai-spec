import { expect, test } from "@playwright/test";

function png1x1() {
  return Buffer.from(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907724" +
      "0000000a49444154789c6360000002000154a24f820000000049454e44ae426082",
    "hex",
  );
}

const HWPX_STUB = { name: "exam.hwpx", mimeType: "application/zip", buffer: Buffer.from([0x50, 0x4b, 0x03, 0x04]) };

const CANDIDATES_BODY = {
  data: {
    manifest: {
      source_sha256: "src123",
      source_format: "hwpx",
      section_count: 1,
      header_variants: ["default"],
      footer_variants: [],
      master_page_count: 0,
      existing_watermark_count: 0,
      candidates: [
        {
          id: "cand_title",
          kind: "TITLE_HEADER_TEXT",
          section: "Contents/section0.xml",
          path: "p[0]",
          apply_page_type: "ALL",
          layer: "HEADER",
          text_preview: "타학원 수학",
          confidence: 0.9,
          requires_user_confirm: false,
          digest: "d1",
        },
        {
          id: "cand_body",
          kind: "TITLE_BODY_TOP",
          section: "Contents/section0.xml",
          path: "p[3]",
          apply_page_type: "ALL",
          layer: "BODY",
          text_preview: "1. 문제 단락 미리보기",
          confidence: 0.5,
          requires_user_confirm: true,
          digest: "d2",
        },
        {
          id: "cand_pagenum",
          kind: "PAGE_NUM_FIELD",
          section: "Contents/section0.xml",
          path: "p[5]",
          apply_page_type: "ALL",
          layer: "FOOTER",
          text_preview: "",
          confidence: 0.95,
          requires_user_confirm: false,
          digest: "d3",
        },
      ],
      flags: {},
    },
    needs_confirmation: ["cand_body"],
    fail_closed_flags: {},
  },
};

async function seedAuthAndRoutes(
  page: import("@playwright/test").Page,
  hits: string[],
  candidatesBody: Record<string, unknown> = CANDIDATES_BODY,
) {
  await page.addInitScript(() => {
    localStorage.setItem("examdna_dev_user", "teacher1");
    localStorage.setItem("examdna_tenant", "tn_1");
  });
  await page.route("**/api/auth/me", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ authenticated: true, user_id: "teacher1", tenant_id: "tn_1", role: "owner" }),
    });
  });
  await page.route("**/api/tenants", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ tenants: [{ id: "tn_1", name: "테스트학원", role: "owner" }] }),
    });
  });
  await page.route("**/api/v1/tenants/tn_1/rebrand/imports", async (route) => {
    hits.push("POST rebrand/imports");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        data: {
          document_id: "doc_r1",
          source_format: "hwpx",
          source_sha256: "src123",
          revision_id: "rev_0",
          hancom_required: false,
        },
      }),
    });
  });
  await page.route("**/api/v1/tenants/tn_1/rebrand/logo", async (route) => {
    hits.push("POST rebrand/logo");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ data: { logo_sha256: "logo123" } }),
    });
  });
  await page.route("**/api/v1/tenants/tn_1/documents/doc_r1/rebrand/candidates", async (route) => {
    hits.push("GET rebrand/candidates");
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(candidatesBody) });
  });
}

test("rebrand journey: import, confirm candidates, apply with contract assertions", async ({ page }) => {
  const hits: string[] = [];
  await seedAuthAndRoutes(page, hits);

  let applyBody: Record<string, unknown> | null = null;
  await page.route("**/api/v1/tenants/tn_1/documents/doc_r1/rebrand/apply", async (route) => {
    hits.push("POST rebrand/apply");
    applyBody = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        data: {
          revision: { id: "rev_1", revision_no: 2 },
          artifact: { id: "art_1", artifact_sha256: "deadbeef", state: "FINAL" },
          invariant: { passed: true, violations: [], removed_paths: ["p[5]"], replaced_paths: ["p[0]"], added_paths: [] },
          proof: { checks: { HWPX_OPEN_VALIDITY: "PASSED", HWP_ACTUAL_REOPEN: "PASSED" } },
          worker_unavailable: false,
        },
      }),
    });
  });

  await page.goto("/rebrand");

  // 1. import the HWPX (file content is opaque to the UI; backend sniffs it)
  const fileInput = page.locator('input[accept=".hwp,.hwpx"]');
  await expect(fileInput).toBeEnabled();
  await fileInput.setInputFiles(HWPX_STUB);
  await expect(page.getByText("변경 후보 확인")).toBeVisible();
  // confirmation-required candidate is not auto-selected and labelled
  const bodyRow = page.locator("li", { hasText: "1. 문제 단락 미리보기" });
  await expect(bodyRow.getByText("확인 필요")).toBeVisible();
  await expect(bodyRow.locator('input[type="checkbox"]')).not.toBeChecked();
  // auto-safe candidates are pre-selected
  await expect(
    page.locator("li", { hasText: "타학원 수학" }).locator('input[type="checkbox"]'),
  ).toBeChecked();

  // 2. academy name + logo
  await page.getByLabel("학원명").fill("테스트학원");
  await page.locator('input[accept="image/png"]').setInputFiles({
    name: "logo.png",
    mimeType: "image/png",
    buffer: png1x1(),
  });
  await expect(page.getByText("로고 등록됨")).toBeVisible();

  // 3. apply
  await page.getByRole("button", { name: "확인 후 적용" }).click();
  await expect(page.getByText("적용 완료")).toBeVisible();
  await expect(page.getByText("rev_1")).toBeVisible();
  await expect(page.getByText("통과")).toBeVisible();
  await expect(page.locator("li", { hasText: "HWP_ACTUAL_REOPEN" })).toContainText("PASSED");

  // contract assertions on the request body
  expect(hits).toContain("POST rebrand/imports");
  expect(hits).toContain("POST rebrand/logo");
  expect(hits).toContain("GET rebrand/candidates");
  expect(hits).toContain("POST rebrand/apply");
  expect(applyBody).not.toBeNull();
  expect(applyBody!.academy_name).toBe("테스트학원");
  expect(applyBody!.logo_sha256).toBe("logo123");
  expect(applyBody!.watermark_enabled).toBe(true);
  expect(applyBody!.remove_page_numbers).toBe(true);
  // auto-safe candidates confirmed; confirmation-required candidate NOT sent
  const confirmed = applyBody!.confirmed_candidate_ids as string[];
  expect(confirmed).toEqual(expect.arrayContaining(["cand_title", "cand_pagenum"]));
  expect(confirmed).not.toContain("cand_body");
});

test("rebrand surfaces fail-closed error from apply", async ({ page }) => {
  const hits: string[] = [];
  await seedAuthAndRoutes(page, hits);

  await page.route("**/api/v1/tenants/tn_1/documents/doc_r1/rebrand/apply", async (route) => {
    hits.push("POST rebrand/apply");
    await route.fulfill({
      status: 422,
      contentType: "application/json",
      body: JSON.stringify({ error: { code: "TITLE_AMBIGUOUS", message: "확인되지 않은 제목 후보가 여러 개입니다" } }),
    });
  });

  await page.goto("/rebrand");
  const fileInput = page.locator('input[accept=".hwp,.hwpx"]');
  await expect(fileInput).toBeEnabled();
  await fileInput.setInputFiles(HWPX_STUB);
  await page.getByLabel("학원명").fill("테스트학원");
  // no logo uploaded — turn off the watermark so apply is enabled
  await page.locator("label", { hasText: "중앙 워터마크 추가" }).locator("input").uncheck();
  await page.getByRole("button", { name: "확인 후 적용" }).click();

  const alert = page.locator('div[role="alert"]').filter({ hasText: "TITLE_AMBIGUOUS" });
  await expect(alert).toContainText("확인되지 않은 제목 후보가 여러 개입니다");
  // user can retry after fixing selections
  await expect(page.getByRole("button", { name: "확인 후 적용" })).toBeEnabled();
});

test("rebrand shows fail-closed source flags", async ({ page }) => {
  const hits: string[] = [];
  const flagged = JSON.parse(JSON.stringify(CANDIDATES_BODY));
  flagged.data.fail_closed_flags = { encrypted_or_protected: true };
  flagged.data.manifest.flags = { encrypted_or_protected: true };
  await seedAuthAndRoutes(page, hits, flagged);

  await page.goto("/rebrand");
  const fileInput = page.locator('input[accept=".hwp,.hwpx"]');
  await expect(fileInput).toBeEnabled();
  await fileInput.setInputFiles(HWPX_STUB);
  await expect(
    page.locator('div[role="alert"]').filter({ hasText: "encrypted_or_protected" }),
  ).toBeVisible();
});
