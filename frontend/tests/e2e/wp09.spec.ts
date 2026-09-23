import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const VIEWPORTS = [
  { w: 360, h: 740 },
  { w: 390, h: 844 },
  { w: 768, h: 1024 },
  { w: 1280, h: 800 },
];

function png1x1() {
  return Buffer.from(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907724" +
      "0000000a49444154789c6360000002000154a24f820000000049454e44ae426082",
    "hex",
  );
}

test("wp09 full journey with contract assertions", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.addInitScript(() => {
    localStorage.setItem("examdna_dev_user", "teacher1");
    localStorage.setItem("examdna_tenant", "tn_1");
  });

  const hits: string[] = [];
  const uploadTmp = path.join(process.cwd(), "tests", "e2e", "upload.png");
  fs.writeFileSync(uploadTmp, png1x1());

  await page.route("**/api/auth/me", async (route) => {
    hits.push("GET /api/auth/me");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ authenticated: true, user_id: "teacher1", tenant_id: "tn_1", role: "owner" }),
    });
  });
  await page.route("**/api/tenants", async (route) => {
    const method = route.request().method();
    if (method === "POST") {
      hits.push("POST /api/tenants");
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ id: "tn_1", name: "학원A", role: "owner" }),
      });
      return;
    }
    hits.push("GET /api/tenants");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ tenants: [{ id: "tn_1", name: "학원A", role: "owner" }] }),
    });
  });
  await page.route("**/api/tenants/switch", async (route) => {
    hits.push("POST /api/tenants/switch");
    const body = route.request().postDataJSON() as { tenant_id: string };
    expect(body.tenant_id).toBe("tn_1");
    await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });
  await page.route("**/api/documents", async (route) => {
    if (route.request().method() === "GET") {
      hits.push("GET /api/documents");
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          documents: [{ id: "doc_1", version: 1, pages: 1, questions: 1, status: "NEEDS_REVIEW", metadata: { school: "A" } }],
        }),
      });
    } else {
      await route.continue();
    }
  });
  await page.route("**/api/uploads", async (route) => {
    hits.push("POST /api/uploads");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ job_id: "job_1", document_id: "doc_1" }),
    });
  });
  let eventStreamCalls = 0;
  await page.route("**/api/jobs/job_1/events", async (route) => {
    hits.push("GET /api/jobs/job_1/events");
    eventStreamCalls += 1;
    const body = eventStreamCalls === 1
      ? 'data: {"stage":"preprocessing","message":"단계 시작","level":"info"}\n\n'
      : 'data: {"stage":"preprocessing","message":"재시도 시작","level":"info"}\n\n' +
        'data: {"done":true,"state":"NEEDS_REVIEW"}\n\n';
    await route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body });
  });
  await page.route("**/api/jobs/job_1/cancel", async (route) => {
    hits.push("POST /api/jobs/job_1/cancel");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ state: "CANCELLED" }),
    });
  });
  await page.route("**/api/v1/tenants/tn_1/jobs/job_1/retry", async (route) => {
    hits.push("POST /api/v1/tenants/tn_1/jobs/job_1/retry");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ data: { state: "QUEUED" } }),
    });
  });
  await page.route("**/api/documents/doc_1/review-items", async (route) => {
    hits.push("GET /api/documents/doc_1/review-items");
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
            source: { page: 0, bbox: { x: 10, y: 10, w: 20, h: 20 } },
            candidates: [{ provider: "p1", value: "x", confidence: 0.9 }],
          },
        ],
        logic_flags: [],
        gate: {},
        missing_numbers: [],
      }),
    });
  });
  await page.route("**/api/v1/tenants/tn_1/documents/doc_1/pages", async (route) => {
    hits.push("GET /api/v1/tenants/tn_1/documents/doc_1/pages");
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
  await page.route("**/api/v1/tenants/tn_1/documents/doc_1", async (route) => {
    if (route.request().method() === "GET") {
      hits.push("GET /api/v1/tenants/tn_1/documents/doc_1");
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ data: { head_revision: { id: "rev_2" } } }),
      });
      return;
    }
    await route.continue();
  });
  await page.route("**/api/v1/tenants/tn_1/documents/doc_1/pages/order", async (route) => {
    hits.push("PUT /api/v1/tenants/tn_1/documents/doc_1/pages/order");
    const body = route.request().postDataJSON() as { page_ids_ordered: string[] };
    expect(body.page_ids_ordered).toEqual(["sp_1"]);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ data: { manifest: { id: "mf_2", page_ids_ordered: ["sp_1"] } } }),
    });
  });
  await page.route("**/api/documents/doc_1/crops/0**", async (route) => {
    hits.push("GET /api/documents/doc_1/crops/0");
    await route.fulfill({ status: 200, contentType: "image/png", body: png1x1() });
  });
  await page.route("**/api/documents/doc_1/review-items/atu_1", async (route) => {
    hits.push("POST /api/documents/doc_1/review-items/atu_1");
    const body = route.request().postDataJSON() as { value: string };
    expect(body.value).toBe("확정값");
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
  });
  await page.route("**/api/documents/doc_1", async (route) => {
    hits.push("GET /api/documents/doc_1");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        questions: [{ number: 1, label: "1", verification: { status: "UNVERIFIED" } }],
        verification: { status: "VERIFIED_FINAL", gate: {} },
      }),
    });
  });
  await page.route("**/api/documents/doc_1/edits", async (route) => {
    hits.push("POST /api/documents/doc_1/edits");
    const body = route.request().postDataJSON() as { instruction: string };
    expect(body.instruction.length).toBeGreaterThan(0);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, instruction: body.instruction, applied: [{ question: "1", field: "body", value: "v" }], skipped: [] }),
    });
  });
  await page.route("**/api/v1/tenants/tn_1/documents/doc_1/revisions", async (route) => {
    hits.push("GET /api/v1/tenants/tn_1/documents/doc_1/revisions");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ data: { revisions: [{ id: "rev_1" }, { id: "rev_2" }] } }),
    });
  });
  await page.route("**/api/v1/tenants/tn_1/documents/doc_1/undo", async (route) => {
    hits.push("POST /api/v1/tenants/tn_1/documents/doc_1/undo");
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: {} }) });
  });
  await page.route("**/api/v1/tenants/tn_1/documents/doc_1/redo", async (route) => {
    hits.push("POST /api/v1/tenants/tn_1/documents/doc_1/redo");
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: {} }) });
  });
  await page.route("**/api/documents/doc_1/preview", async (route) => {
    hits.push("GET /api/documents/doc_1/preview");
    await route.fulfill({ status: 200, contentType: "text/html", body: "<html><body>preview</body></html>" });
  });
  await page.route("**/api/v1/tenants/tn_1/documents/doc_1/eligibility", async (route) => {
    hits.push("GET /api/v1/tenants/tn_1/documents/doc_1/eligibility");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        data: {
          document_id: "doc_1",
          revision_id: "rev_2",
          revision_no: 2,
          mode: "EDIT",
          content_ready: false,
          content_checks: [],
          blocking_issues: [],
          formats: {
            hwpx: { checks: [], final_eligible: false, artifacts: [] },
            hwp: { checks: [], final_eligible: false, artifacts: [] },
            pdf: { checks: [], final_eligible: false, artifacts: [] },
          },
        },
      }),
    });
  });
  await page.route("**/api/v1/tenants/tn_1/documents/doc_1/artifacts", async (route) => {
    hits.push("POST /api/v1/tenants/tn_1/documents/doc_1/artifacts");
    const body = route.request().postDataJSON() as { format: string; output_mode: string; revision_id: string };
    expect(body.output_mode).toBe("TEACHER");
    expect(body.revision_id).toBe("rev_2");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        data: {
          artifact: { id: "art_1", format: body.format, artifact_sha256: "ab".repeat(32), state: "DRAFT" },
          proof: null,
        },
      }),
    });
  });
  await page.route("**/api/v1/artifacts/art_1/download**", async (route) => {
    hits.push("GET /api/v1/artifacts/art_1/download");
    await route.fulfill({
      status: 200,
      headers: {
        "content-type": "application/pdf",
        "content-disposition": 'attachment; filename="exam.pdf"',
      },
      body: Buffer.from("%PDF-1.4\n%mock"),
    });
  });

  await page.goto("/");

  // dev auth bar may start in either authenticated or login state, but upload
  // input must be actionable and call the upload API contract.
  await page.locator("input[type=file]").setInputFiles(uploadTmp);
  await expect.poll(() => hits.includes("POST /api/uploads")).toBeTruthy();
  await expect(page.locator("body")).toContainText(/완료|업로드 중|실패/);
  await page.goto("/jobs/job_1?doc=doc_1");
  await page.getByRole("button", { name: "중단" }).click();
  await page.getByRole("button", { name: "재시도" }).click();
  await expect(page.getByRole("link", { name: "예외 검토" })).toBeVisible();
  await page.getByRole("link", { name: "예외 검토" }).click();
  await expect(page).toHaveURL(/\/documents\/doc_1\/review/);
  await page.getByRole("button", { name: "원본 비교 확대" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Escape");
  await page.getByPlaceholder("확정 값 입력").fill("확정값");
  await page.getByRole("button", { name: "확정", exact: true }).click();
  await page.getByRole("link", { name: "에디터로" }).click();
  await page.getByPlaceholder("자연어로 수정 요청").dispatchEvent("compositionstart");
  await page.getByPlaceholder("자연어로 수정 요청").fill("문장 고쳐줘");
  await page.getByPlaceholder("자연어로 수정 요청").press("Enter");
  await expect(page.getByText("AI 변경 계획 승인")).toHaveCount(0);
  await page.getByPlaceholder("자연어로 수정 요청").dispatchEvent("compositionend");
  await page.getByRole("button", { name: "요청" }).click();
  await expect(page.getByRole("dialog", { name: "AI 변경 계획 승인" })).toBeVisible();
  await page.getByRole("button", { name: "승인 후 적용" }).click();
  await page.getByRole("button", { name: "Undo" }).click();
  await page.getByRole("button", { name: "Redo" }).click();
  await page.goto("/documents/doc_1/export");
  await page.locator("select").selectOption("TEACHER");
  await page
    .locator('[data-format="pdf"]')
    .getByRole("button", { name: "초안" })
    .click();
  const downloadLink = page.getByRole("link", { name: "PDF 초안 (DRAFT) 다운로드" });
  await expect(downloadLink).toBeVisible();
  // Same-origin <a download> clicks go through Chromium's download
  // pipeline, which does not traverse page.route mocks — assert the
  // link contract (href + download attr) and verify the endpoint via
  // in-page fetch, which IS routed.
  await expect(downloadLink).toHaveAttribute(
    "href",
    /\/api\/v1\/artifacts\/art_1\/download\?purpose=draft/,
  );
  const dlHeaders = await page.evaluate(async () => {
    const r = await fetch("/api/v1/artifacts/art_1/download?purpose=draft");
    return { status: r.status, cd: r.headers.get("content-disposition") };
  });
  expect(dlHeaders.status).toBe(200);
  expect(dlHeaders.cd).toContain("exam.pdf");

  expect(hits).toContain("POST /api/uploads");
  expect(hits).toContain("POST /api/documents/doc_1/review-items/atu_1");
  expect(hits).toContain("POST /api/documents/doc_1/edits");
  expect(hits).toContain("POST /api/v1/tenants/tn_1/documents/doc_1/artifacts");
});

test("wp09 error-status recovery messages", async ({ page, context }) => {
  await page.addInitScript(() => {
    localStorage.setItem("examdna_dev_user", "u1");
    localStorage.setItem("examdna_tenant", "tn_1");
  });
  await page.route("**/api/auth/me", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ authenticated: true, user_id: "u1", tenant_id: "tn_1", role: "owner" }) }));
  await page.route("**/api/tenants", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ tenants: [{ id: "tn_1", name: "A", role: "owner" }] }) }));
  await page.route("**/api/uploads", (r) => r.fulfill({ status: 429, contentType: "application/json", body: JSON.stringify({ detail: { error: { code: "QUOTA_EXCEEDED", message: "quota" } } }) }));
  await page.goto("/");
  await page.locator("input[type=file]").setInputFiles({
    name: "q.png",
    mimeType: "image/png",
    buffer: png1x1(),
  });
  await expect.poll(() => page.locator("body").innerText()).toContain("QUOTA_EXCEEDED");
  await expect(page.locator("body")).toContainText("QUOTA_EXCEEDED");

  await page.route("**/api/documents/doc_1/edits", (r) => r.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: { error: { code: "REVISION_CONFLICT", message: "stale" } } }) }));
  await page.route("**/api/documents/doc_1", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ questions: [], verification: { status: "NEEDS_REVIEW", gate: {} } }) }));
  await page.goto("/documents/doc_1/editor");
  await page.getByPlaceholder("자연어로 수정 요청").fill("수정");
  await page.getByRole("button", { name: "요청" }).click();
  await page.getByRole("button", { name: "승인 후 적용" }).click();
  await expect(page.getByRole("dialog", { name: "충돌 감지" })).toBeVisible();

  await page.route("**/api/v1/tenants/tn_1/documents/doc_1/eligibility", (r) => r.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      data: {
        document_id: "doc_1",
        revision_id: "rev_2",
        revision_no: 2,
        mode: "EDIT",
        content_ready: false,
        content_checks: [],
        blocking_issues: [],
        formats: {
          hwpx: { checks: [], final_eligible: false, artifacts: [] },
          hwp: { checks: [], final_eligible: false, artifacts: [] },
          pdf: { checks: [], final_eligible: false, artifacts: [] },
        },
      },
    }),
  }));
  await page.route("**/api/v1/tenants/tn_1/documents/doc_1/artifacts", (r) => r.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: { error: { code: "HWP_WORKER_UNAVAILABLE", message: "unavailable" } } }) }));
  await page.goto("/documents/doc_1/export");
  await page
    .locator('[data-format="hwp"]')
    .getByRole("button", { name: "초안" })
    .click();
  await expect(page.getByText("HWP_WORKER_UNAVAILABLE")).toBeVisible();

  await page.goto("/");
  await context.setOffline(true);
  await expect(page.getByText("오프라인 상태입니다.")).toBeVisible();
  await context.setOffline(false);
  await expect(page.getByText("오프라인 상태입니다.")).toHaveCount(0);
});

for (const v of VIEWPORTS) {
  test(`wp09 responsive shell ${v.w}`, async ({ page }) => {
    await page.setViewportSize({ width: v.w, height: v.h });
    await page.goto("/");
    await expect(page.getByText("AI 시험지 복원")).toBeVisible();
  });
}
