export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
  kind: string;
  status: string;
  source: { page: number; bbox?: unknown } | null;
  candidates: { provider: string; value: unknown; confidence: number }[];
}

export async function uploadFiles(files: File[]): Promise<UploadResult> {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  const res = await fetch(`${API}/api/uploads`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getJob(jobId: string): Promise<Job> {
  const res = await fetch(`${API}/api/jobs/${jobId}`, { cache: "no-store" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getReviewItems(docId: string) {
  const res = await fetch(`${API}/api/documents/${docId}/review-items`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function resolveItem(docId: string, atuId: string, value: string) {
  const res = await fetch(`${API}/api/documents/${docId}/review-items/${atuId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function sendEdit(docId: string, instruction: string) {
  const res = await fetch(`${API}/api/documents/${docId}/edits`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instruction }),
  });
  return res.json();
}

export async function exportDoc(docId: string, format: string) {
  const res = await fetch(`${API}/api/documents/${docId}/exports`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ format }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
