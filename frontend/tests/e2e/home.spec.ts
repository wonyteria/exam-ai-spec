import { expect, test } from "@playwright/test";

test.describe("home library", () => {
  test("in-flight and review-handoff jobs are listed with correct links", async ({
    page,
  }) => {
    await page.addInitScript(() => {
      localStorage.setItem("examdna_dev_user", "teacher1");
      localStorage.setItem("examdna_tenant", "tn_1");
    });
    await page.route("**/api/auth/me", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          authenticated: true,
          user_id: "teacher1",
          tenant_id: "tn_1",
          role: "owner",
        }),
      });
    });
    await page.route("**/api/tenants", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          tenants: [{ id: "tn_1", name: "테스트학원", role: "owner" }],
        }),
      });
    });
    await page.route("**/api/documents", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ documents: [] }),
      });
    });
    await page.route("**/api/jobs", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          jobs: [
            {
              id: "job_running1",
              document_id: "doc_a",
              state: "RUNNING",
              kind: "restore_pipeline",
              created_at: 1,
            },
            {
              id: "job_review2",
              document_id: "doc_b",
              state: "NEEDS_REVIEW",
              kind: "restore_pipeline",
              created_at: 2,
            },
            {
              id: "job_done3",
              document_id: "doc_c",
              state: "COMPLETED",
              kind: "restore_pipeline",
              created_at: 3,
            },
          ],
        }),
      });
    });

    await page.goto("/");
    const section = page.getByText("진행 중·검토 대기 작업");
    await expect(section).toBeVisible();

    // RUNNING links to the job page; NEEDS_REVIEW links to review.
    await expect(page.getByRole("link", { name: /처리 중/ })).toHaveAttribute(
      "href",
      "/jobs/job_running1?doc=doc_a",
    );
    await expect(page.getByRole("link", { name: /검토 필요/ })).toHaveAttribute(
      "href",
      "/documents/doc_b/review",
    );
    // COMPLETED jobs are not listed.
    await expect(page.getByText("job_done3")).not.toBeVisible();
  });
});
