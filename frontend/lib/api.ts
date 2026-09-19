export const API = process.env.NEXT_PUBLIC_API_URL ?? "";

// --- dev auth context ---------------------------------------------------
// Session cookie is the primary path (credentials: "include"). The dev
// stub headers only exist when the backend runs with dev auth enabled —
// they are a development convenience, not the production auth model
// (ADR-0002). Values come from localStorage, set by the academy bar.

export function devUser(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("examdna_dev_user");
}

export function activeTenant(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("examdna_tenant");
}

export function setActiveTenant(tenantId: string | null) {
  if (tenantId) window.localStorage.setItem("examdna_tenant", tenantId);
  else window.localStorage.removeItem("examdna_tenant");
}

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const user = devUser();
  const tenant = activeTenant();
  if (user) headers["x-dev-user"] = user;
  if (tenant) headers["x-dev-tenant"] = tenant;
  if (tenant) headers["x-tenant-id"] = tenant;
  return headers;
}

async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${API}${path}`, {
    credentials: "include",
    ...init,
    headers: { ...authHeaders(), ...(init.headers as Record<string, string>) },
  });
}

async function throwApiError(res: Response): Promise<never> {
  const status = res.status;
  let body = "";
  try {
    body = await res.text();
  } catch {
    body = "";
  }
  let code = "";
  let message = body || `HTTP ${status}`;
  try {
    const parsed = JSON.parse(body);
    code = parsed?.detail?.error?.code || parsed?.error?.code || "";
    message =
      parsed?.detail?.error?.message ||
      parsed?.detail ||
      parsed?.error?.message ||
      message;
  } catch {
    /* non-json */
  }
  throw new Error(`[${status}${code ? ` ${code}` : ""}] ${String(message)}`);
}

// --- auth / academies -----------------------------------------------------

export interface Me {
  authenticated: boolean;
  user_id?: string;
  display_name?: string;
  tenant_id?: string | null;
  role?: string | null;
  tenants?: { id: string; name: string; role: string }[];
  via_dev_stub?: boolean;
}

export async function getMe(): Promise<Me> {
  const res = await apiFetch("/api/auth/me", { cache: "no-store" });
  return res.json();
}

export async function devLogin(userId: string, displayName = ""): Promise<void> {
  const res = await apiFetch("/api/auth/dev-login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, display_name: displayName }),
  });
  if (!res.ok) throw new Error(await res.text());
  window.localStorage.setItem("examdna_dev_user", userId);
}

export async function logout(): Promise<void> {
  await apiFetch("/api/auth/logout", { method: "POST" });
  window.localStorage.removeItem("examdna_dev_user");
  window.localStorage.removeItem("examdna_tenant");
}

export interface Tenant {
  id: string;
  name: string;
  role: string;
}

export async function listTenants(): Promise<Tenant[]> {
  const res = await apiFetch("/api/tenants", { cache: "no-store" });
  if (!res.ok) await throwApiError(res);
  return (await res.json()).tenants;
}

export async function createTenant(name: string): Promise<Tenant> {
  const res = await apiFetch("/api/tenants", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export async function switchTenant(tenantId: string): Promise<void> {
  const res = await apiFetch("/api/tenants/switch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tenant_id: tenantId }),
  });
  if (!res.ok) await throwApiError(res);
  setActiveTenant(tenantId);
}

export async function createInvite(
  tenantId: string,
  role: "teacher" | "reviewer",
): Promise<{ code: string }> {
  const res = await apiFetch(`/api/tenants/${tenantId}/invites`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role }),
  });
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export async function acceptInvite(code: string): Promise<{ tenant_id: string }> {
  const res = await apiFetch(`/api/invites/${code}/accept`, { method: "POST" });
  if (!res.ok) await throwApiError(res);
  return res.json();
}

// --- documents --------------------------------------------------------------

export interface DocumentSummary {
  id: string;
  version: number;
  pages: number;
  questions: number;
  status: string;
  metadata: Record<string, unknown>;
}

export async function listDocuments(): Promise<DocumentSummary[]> {
  const res = await apiFetch("/api/documents", { cache: "no-store" });
  if (!res.ok) await throwApiError(res);
  return (await res.json()).documents;
}

export interface UploadResult {
  job_id: string;
  document_id: string;
}

export interface JobEvent {
  ts: number;
  stage: string;
  message: string;
  level: string;
}

export interface Job {
  id: string;
  document_id: string;
  state: string;
  events: JobEvent[];
  error?: string | null;
}

export interface ReviewItem {
  atu_id: string;
  question_number: number;
  question_label?: string;
  kind: string;
  status: string;
  source: { page: number; bbox?: unknown } | null;
  candidates: { provider: string; value: unknown; confidence: number }[];
}

export async function uploadFiles(files: File[]): Promise<UploadResult> {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  const res = await apiFetch("/api/uploads", { method: "POST", body: form });
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export async function getJob(jobId: string): Promise<Job> {
  const res = await apiFetch(`/api/jobs/${jobId}`, { cache: "no-store" });
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export interface ReviewItemsResponse {
  items: ReviewItem[];
  logic_flags: {
    question_number: number;
    question_label?: string;
    flags: { kind: string; detail: string }[];
  }[];
  gate: Record<string, unknown> | null;
  missing_numbers: number[];
}

export async function getReviewItems(docId: string): Promise<ReviewItemsResponse> {
  const res = await apiFetch(`/api/documents/${docId}/review-items`, {
    cache: "no-store",
  });
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export async function resolveItem(docId: string, atuId: string, value: string) {
  const res = await apiFetch(`/api/documents/${docId}/review-items/${atuId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export interface EditResponse {
  ok: boolean;
  instruction: string;
  applied: { question: string; field: string; value: unknown }[];
  skipped: { question: string; field: string; reason: string }[];
  detail?: string;
  document_version: number;
}

export async function sendEdit(
  docId: string,
  instruction: string,
): Promise<EditResponse> {
  const res = await apiFetch(`/api/documents/${docId}/edits`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instruction }),
  });
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export async function exportDoc(
  docId: string,
  format: string,
  output_mode = "STUDENT_WITH_ENDNOTES",
) {
  const res = await apiFetch(`/api/documents/${docId}/exports`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ format, output_mode }),
  });
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export async function cancelJob(jobId: string) {
  const res = await apiFetch(`/api/jobs/${jobId}/cancel`, { method: "POST" });
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export async function retryJobV1(tenantId: string, jobId: string) {
  const res = await apiFetch(`/api/v1/tenants/${tenantId}/jobs/${jobId}/retry`, {
    method: "POST",
  });
  if (!res.ok) await throwApiError(res);
  return res.json();
}

// --- source pages / manifest (WP03) -----------------------------------------

export interface DocPage {
  index: number;
  source_page_id: string;
  source_asset_id: string | null;
  pdf_page_index: number | null;
  sha256: string | null;
  original_name: string | null;
  width: number | null;
  height: number | null;
  manifest_position: number | null;
  transform: Record<string, unknown> | null;
  uncertain_regions: { bbox_px?: unknown; reason?: string }[];
}

export interface SourceManifestInfo {
  id: string;
  page_ids_ordered: string[];
  digest: string;
  confirmed_by: string | null;
  confirmed_at: number | null;
  missing_page_expectation: string | null;
}

export interface DocPagesResponse {
  manifest: SourceManifestInfo | null;
  pages: DocPage[];
}

async function getHeadRevisionId(
  tenantId: string,
  docId: string,
): Promise<string | null> {
  const res = await apiFetch(`/api/v1/tenants/${tenantId}/documents/${docId}`, {
    cache: "no-store",
  });
  if (!res.ok) return null;
  const data = await res.json();
  return data?.data?.head_revision?.id ?? null;
}

export async function getHeadRevisionForTenant(tenantId: string, docId: string) {
  const res = await apiFetch(`/api/v1/tenants/${tenantId}/documents/${docId}`, {
    cache: "no-store",
  });
  if (!res.ok) await throwApiError(res);
  const data = await res.json();
  return data?.data?.head_revision ?? null;
}

export async function undoDoc(tenantId: string, docId: string, restoresRevisionId: string) {
  const head = await getHeadRevisionForTenant(tenantId, docId);
  const res = await apiFetch(`/api/v1/tenants/${tenantId}/documents/${docId}/undo`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(head?.id ? { "If-Match": head.id } : {}),
    },
    body: JSON.stringify({ restores_revision_id: restoresRevisionId, reason: "ui_undo" }),
  });
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export async function redoDoc(tenantId: string, docId: string) {
  const head = await getHeadRevisionForTenant(tenantId, docId);
  const res = await apiFetch(`/api/v1/tenants/${tenantId}/documents/${docId}/redo`, {
    method: "POST",
    headers: {
      ...(head?.id ? { "If-Match": head.id } : {}),
    },
  });
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export async function listRevisions(tenantId: string, docId: string) {
  const res = await apiFetch(`/api/v1/tenants/${tenantId}/documents/${docId}/revisions`, {
    cache: "no-store",
  });
  if (!res.ok) await throwApiError(res);
  const data = await res.json();
  return data?.data?.revisions ?? [];
}

export async function getDocPages(
  tenantId: string,
  docId: string,
): Promise<DocPagesResponse> {
  const res = await apiFetch(
    `/api/v1/tenants/${tenantId}/documents/${docId}/pages`,
    { cache: "no-store" },
  );
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return data.data;
}

export async function confirmPageOrder(
  tenantId: string,
  docId: string,
  pageIdsOrdered: string[],
  missingPageExpectation?: string,
) {
  const ifMatch = await getHeadRevisionId(tenantId, docId);
  const res = await apiFetch(
    `/api/v1/tenants/${tenantId}/documents/${docId}/pages/order`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        ...(ifMatch ? { "If-Match": ifMatch } : {}),
      },
      body: JSON.stringify({
        page_ids_ordered: pageIdsOrdered,
        missing_page_expectation: missingPageExpectation ?? null,
      }),
    },
  );
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
