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
  question_source?: { page: number; bbox?: unknown } | null;
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

export interface JobSummary {
  id: string;
  document_id: string;
  state: string;
  kind: string;
  created_at: number;
  error?: string | null;
}

export async function listJobs(): Promise<JobSummary[]> {
  const res = await apiFetch("/api/jobs", { cache: "no-store" });
  if (!res.ok) await throwApiError(res);
  return (await res.json()).jobs;
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
  unresolved_labels?: string[];
}

export async function getReviewItems(docId: string): Promise<ReviewItemsResponse> {
  const res = await apiFetch(`/api/documents/${docId}/review-items`, {
    cache: "no-store",
  });
  if (!res.ok) await throwApiError(res);
  return res.json();
}

// Canonical-aware document read (canonical head when a record exists).
export async function getDocument(docId: string) {
  const res = await apiFetch(`/api/documents/${docId}`, { cache: "no-store" });
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

// --- exam agent (RESTORE-25) ---------------------------------------------------

export interface AgentProposal {
  command: string;
  recognized: boolean;
  explanation: string;
  preview: string[];
  ops: Record<string, unknown>[];
  if_match: string;
}

export async function agentPropose(
  tenantId: string,
  docId: string,
  command: string,
): Promise<AgentProposal> {
  const res = await apiFetch(
    `/api/v1/tenants/${tenantId}/documents/${docId}/agent`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command }),
    },
  );
  if (!res.ok) await throwApiError(res);
  return (await res.json()).data;
}

export async function applyChanges(
  tenantId: string,
  docId: string,
  ops: Record<string, unknown>[],
  ifMatch: string,
) {
  const res = await apiFetch(
    `/api/v1/tenants/${tenantId}/documents/${docId}/changes`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "If-Match": ifMatch,
      },
      body: JSON.stringify({ ops }),
    },
  );
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export interface CanonicalIssue {
  id: string;
  question_ids: string[];
  kind: string;
  severity: string;
  blocking: boolean;
  state: string;
  reason: string;
}

export async function getIssues(
  tenantId: string,
  docId: string,
): Promise<CanonicalIssue[]> {
  const res = await apiFetch(
    `/api/v1/tenants/${tenantId}/documents/${docId}/issues?state=OPEN`,
    { cache: "no-store" },
  );
  if (!res.ok) await throwApiError(res);
  return (await res.json()).data.issues;
}

export interface RevisionInfo {
  id: string;
  revision_no: number;
  mode: string;
  created_at: number;
}

export async function getRevisions(
  tenantId: string,
  docId: string,
): Promise<RevisionInfo[]> {
  const res = await apiFetch(
    `/api/v1/tenants/${tenantId}/documents/${docId}/revisions`,
  );
  if (!res.ok) await throwApiError(res);
  return (await res.json()).data.revisions;
}

/** Confirm the real printed number of a `?`-labeled (masked-anchor)
 * question — canonical SetField number mutation under If-Match CAS. */
export async function renumberQuestion(
  tenantId: string,
  docId: string,
  questionLabel: string,
  number: number,
) {
  const revs = await getRevisions(tenantId, docId);
  const head = revs.reduce((a, b) => (b.revision_no > a.revision_no ? b : a));
  return applyChanges(
    tenantId,
    docId,
    [
      {
        op: "SetField",
        target_id: questionLabel,
        field: "number",
        value: number,
      },
    ],
    head.id,
  );
}

export interface ComposeResult {
  exams: {
    document_id: string;
    revision_id: string;
    questions: number;
    answer_key: Record<string, string>;
  }[];
  unfilled: Record<string, number>;
  total_estimated_minutes: number;
}

export async function composeExam(
  tenantId: string,
  docId: string,
  body: {
    count?: number;
    difficulty_mix?: Record<string, number>;
    versions?: number;
    seed?: number;
    title?: string;
    time_budget_min?: number;
  },
): Promise<ComposeResult> {
  const res = await apiFetch(
    `/api/v1/tenants/${tenantId}/documents/${docId}/compose`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) await throwApiError(res);
  return (await res.json()).data;
}

export interface ContentCheck {
  check_kind: string;
  state: string;
  applicable: boolean;
  stale_reason: string | null;
  method: string;
  result_summary: string;
}

export interface FormatEligibility {
  checks: { check_kind: string; state: string }[];
  final_eligible: boolean;
  artifacts: { id: string; state: string; sha256: string }[];
}

export interface Eligibility {
  document_id: string;
  revision_id: string;
  revision_no: number;
  mode: string;
  content_ready: boolean;
  content_checks: ContentCheck[];
  blocking_issues: Record<string, unknown>[];
  formats: Record<string, FormatEligibility>;
}

export async function getEligibility(
  tenantId: string,
  docId: string,
): Promise<Eligibility> {
  const res = await apiFetch(
    `/api/v1/tenants/${tenantId}/documents/${docId}/eligibility`,
    { cache: "no-store" },
  );
  if (!res.ok) await throwApiError(res);
  return (await res.json()).data;
}

export async function runChecks(
  tenantId: string,
  docId: string,
): Promise<ContentCheck[]> {
  const res = await apiFetch(
    `/api/v1/tenants/${tenantId}/documents/${docId}/checks/run`,
    { method: "POST" },
  );
  if (!res.ok) await throwApiError(res);
  return (await res.json()).data.checks;
}

export interface CreatedArtifact {
  id: string;
  format: string;
  artifact_sha256: string;
  state: string;
}

export async function createArtifact(
  tenantId: string,
  docId: string,
  body: { revision_id: string; format: string; output_mode: string },
): Promise<CreatedArtifact> {
  const res = await apiFetch(
    `/api/v1/tenants/${tenantId}/documents/${docId}/artifacts`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) await throwApiError(res);
  return (await res.json()).data.artifact;
}

export interface FinalExportResult {
  artifacts: { id: string; format: string; sha256: string; download_url: string }[];
}

export async function exportFinal(
  tenantId: string,
  docId: string,
  revisionId: string,
  artifactIds: string[],
): Promise<FinalExportResult> {
  const res = await apiFetch(
    `/api/v1/tenants/${tenantId}/documents/${docId}/exports`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ revision_id: revisionId, artifact_ids: artifactIds }),
    },
  );
  if (!res.ok) await throwApiError(res);
  return (await res.json()).data;
}

export function artifactDownloadUrl(artifactId: string, purpose: "draft" | "final"): string {
  return `${API}/api/v1/artifacts/${artifactId}/download?purpose=${purpose}`;
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

// --- imported HWP/HWPX rebranding (REQ-16) ---------------------------------------

export interface RebrandCandidate {
  id: string;
  kind: string;
  section: string;
  path: string;
  apply_page_type: string;
  layer: string;
  text_preview: string;
  confidence: number;
  requires_user_confirm: boolean;
  digest: string;
}

export interface RebrandManifest {
  source_sha256: string;
  source_format: string;
  section_count: number;
  header_variants: string[];
  footer_variants: string[];
  master_page_count: number;
  existing_watermark_count: number;
  candidates: RebrandCandidate[];
  flags: Record<string, boolean>;
}

export interface RebrandImportResult {
  document_id: string;
  source_format: string;
  source_sha256: string;
  revision_id: string;
  hancom_required: boolean;
}

export async function rebrandImport(
  tenantId: string,
  file: File,
): Promise<RebrandImportResult> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await apiFetch(`/api/v1/tenants/${tenantId}/rebrand/imports`, {
    method: "POST",
    body: fd,
  });
  if (!res.ok) await throwApiError(res);
  return (await res.json()).data;
}

export async function rebrandLogo(
  tenantId: string,
  file: File,
): Promise<{ logo_sha256: string }> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await apiFetch(`/api/v1/tenants/${tenantId}/rebrand/logo`, {
    method: "POST",
    body: fd,
  });
  if (!res.ok) await throwApiError(res);
  return (await res.json()).data;
}

export async function getRebrandCandidates(
  tenantId: string,
  docId: string,
): Promise<{ manifest: RebrandManifest; needs_confirmation: string[]; fail_closed_flags: Record<string, boolean> }> {
  const res = await apiFetch(
    `/api/v1/tenants/${tenantId}/documents/${docId}/rebrand/candidates`,
    { cache: "no-store" },
  );
  if (!res.ok) await throwApiError(res);
  return (await res.json()).data;
}

export interface RebrandApplyResult {
  revision: { id: string; revision_no: number };
  artifact: { id: string; artifact_sha256: string; state: string };
  invariant: {
    passed: boolean;
    violations: string[];
    removed_paths: string[];
    replaced_paths: string[];
    added_paths: string[];
  };
  proof: { checks: Record<string, string> };
  worker_unavailable: boolean;
}

export async function rebrandApply(
  tenantId: string,
  docId: string,
  body: {
    academy_name: string;
    confirmed_candidate_ids: string[];
    remove_page_numbers: boolean;
    watermark_enabled: boolean;
    watermark_replace_existing?: boolean;
    logo_sha256?: string;
  },
): Promise<RebrandApplyResult> {
  const res = await apiFetch(
    `/api/v1/tenants/${tenantId}/documents/${docId}/rebrand/apply`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) await throwApiError(res);
  return (await res.json()).data;
}

export async function setPageRole(
  tenantId: string,
  docId: string,
  sourcePageId: string,
  role: string,
): Promise<unknown> {
  const ifMatch = await getHeadRevisionId(tenantId, docId);
  const res = await apiFetch(
    `/api/v1/tenants/${tenantId}/documents/${docId}/pages/${sourcePageId}/role`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        ...(ifMatch ? { "If-Match": ifMatch } : {}),
      },
      body: JSON.stringify({ page_role: role }),
    },
  );
  if (!res.ok) await throwApiError(res);
  return res.json();
}

// --- question-centric restoration -------------------------------------------

export interface FieldIssue {
  field: string;
  reason: string;
  detail: string;
}

export interface AutoCorrection {
  rule: string;
  field: string;
  before: unknown;
  after: unknown;
}

export interface QuestionDetail {
  id: string;
  number: number;
  label: string;
  type: string | null;
  points: number | null;
  body: string[];
  choices: { label: string; body: string[] }[];
  equations: { id: string; latex: string | null }[];
  figures: { id: string; labels: Record<string, string>; description?: string }[];
  answer: unknown;
  status: string;
  confidence: number;
  issues: FieldIssue[];
  corrections: AutoCorrection[];
  atus: {
    id: string;
    kind: string;
    field: string | null;
    status: string;
    value: unknown;
    candidates: { provider: string; value: unknown; confidence: number }[];
  }[];
  logic_flags: { kind: string; detail: string }[];
  crop: string | null;
  crop_clean: string | null;
}

export interface RestorationSummary {
  restoration_status: string;
  final_status: string;
  counts: Record<string, number>;
  review_questions: {
    id: string;
    number: number;
    label: string;
    status: string;
    issues: FieldIssue[];
    crop: string | null;
  }[];
}

export async function getRestoration(
  docId: string,
): Promise<RestorationSummary> {
  const res = await apiFetch(`/api/documents/${docId}/restoration`, {
    cache: "no-store",
  });
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export async function getQuestionDetail(
  docId: string,
  qid: string,
): Promise<QuestionDetail> {
  const res = await apiFetch(`/api/documents/${docId}/questions/${qid}`, {
    cache: "no-store",
  });
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export interface QuestionEditResult {
  ok: boolean;
  recognized?: boolean;
  explanation?: string;
  needs_clarification?: boolean;
  applied?: boolean;
  ops?: { op: string; target: string; field?: string; value?: unknown }[];
  preview?: { before: QuestionDetail; after: QuestionDetail };
}

export async function editQuestion(
  docId: string,
  qid: string,
  instruction: string,
  apply = false,
): Promise<QuestionEditResult> {
  const res = await apiFetch(`/api/documents/${docId}/questions/${qid}/edit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instruction, apply }),
  });
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export async function confirmQuestion(
  docId: string,
  qid: string,
): Promise<{ ok: boolean; status: string }> {
  const res = await apiFetch(
    `/api/documents/${docId}/questions/${qid}/confirm`,
    { method: "POST" },
  );
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export interface RestorationExportResult {
  file: string;
  url: string;
  restoration_status: string;
  counts: Record<string, number>;
  final: boolean;
}

export async function exportRestoration(
  docId: string,
  format: string,
): Promise<RestorationExportResult> {
  const res = await apiFetch(
    `/api/documents/${docId}/restoration/export`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ format }),
    },
  );
  if (!res.ok) await throwApiError(res);
  return res.json();
}
