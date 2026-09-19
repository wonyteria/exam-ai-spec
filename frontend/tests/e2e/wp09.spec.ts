import { expect, test } from "@playwright/test";

const sizes = [
  { w: 360, h: 740 },
  { w: 390, h: 844 },
  { w: 768, h: 1024 },
  { w: 1280, h: 800 },
];

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("examdna_dev_user", "u1");
    localStorage.setItem("examdna_tenant", "tn_1");
  });
  await page.route("**/api/auth/me", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ authenticated: true, user_id: "u1", tenant_id: "tn_1", role: "owner" }),
    });
  });
  await page.route("**/api/tenants", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ tenants: [{ id: "tn_1", name: "A", role: "owner" }] }),
    });
  });
  await page.route("**/api/documents", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        documents: [{ id: "doc_1", version: 1, pages: 1, questions: 1, status: "NEEDS_REVIEW", metadata: {} }],
      }),
    });
  });
  await page.route("**/api/documents/doc_1/review-items", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            atu_id: "atu_1",
            question_number: 1,
            question_label: "1",
            kind: "text_token",
            status: "UNVERIFIED",
            source: { page: 0, bbox: { x: 1, y: 1, w: 10, h: 10 } },
            candidates: [{ provider: "p1", value: "값", confidence: 0.8 }],
          },
        ],
        logic_flags: [],
        gate: {},
        missing_numbers: [],
      }),
    });
  });
  await page.route("**/api/v1/tenants/tn_1/documents/doc_1/pages", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        data: {
          manifest: { id: "mf_1", page_ids_ordered: ["sp_1"], digest: "d", confirmed_by: null, confirmed_at: null, missing_page_expectation: null },
          pages: [{ index: 0, source_page_id: "sp_1", source_asset_id: "a1", pdf_page_index: null, sha256: "s", original_name: "p1.png", width: 10, height: 10, manifest_position: 0, transform: null, uncertain_regions: [] }],
        },
      }),
    });
  });
  await page.route("**/api/documents/doc_1/crops/0**", async (route) => {
    await route.fulfill({ status: 404, body: "missing" });
  });
  await page.route("**/api/documents/doc_1/review-items/atu_1", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
  });
});

for (const s of sizes) {
  test(`review responsive journey ${s.w}`, async ({ page }) => {
    await page.setViewportSize({ width: s.w, height: s.h });
    await page.goto("/documents/doc_1/review");
    await expect(page.getByText("예외 검토")).toBeVisible();
    await expect(page.getByRole("link", { name: "에디터로" })).toBeVisible();
    await expect(page.getByRole("link", { name: "내보내기" })).toBeVisible();
  });
}
