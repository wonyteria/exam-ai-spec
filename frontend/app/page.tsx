"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import AcademyBar from "@/components/AcademyBar";
import {
  listDocuments,
  listJobs,
  uploadFiles,
  type DocumentSummary,
  type JobSummary,
} from "@/lib/api";

const JOB_STATE_LABEL: Record<string, { label: string; cls: string }> = {
  NEEDS_REVIEW: { label: "검토 필요", cls: "chip-amber" },
};

export default function UploadPage() {
  const router = useRouter();
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ code: string; message: string } | null>(
    null,
  );
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [queue, setQueue] = useState<{ name: string; status: string }[]>([]);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    const on = () => setOffline(false);
    const off = () => setOffline(true);
    let initial: number | null = null;
    if (typeof window !== "undefined") {
      initial = window.requestAnimationFrame(() =>
        setOffline(!window.navigator.onLine),
      );
      window.addEventListener("online", on);
      window.addEventListener("offline", off);
    }
    return () => {
      if (typeof window !== "undefined") {
        if (initial !== null) window.cancelAnimationFrame(initial);
        window.removeEventListener("online", on);
        window.removeEventListener("offline", off);
      }
    };
  }, []);

  const refreshLibrary = useCallback(async () => {
    try {
      setDocs(await listDocuments());
    } catch {
      setDocs([]); // no active tenant yet — library stays empty
    }
    try {
      setJobs(await listJobs());
    } catch {
      setJobs([]);
    }
  }, []);

  const onFiles = useCallback(
    async (files: FileList | File[] | null) => {
      if (!files?.length || busy) return;
      const ALLOWED = /\.(jpe?g|png|pdf|bmp|webp)$/i;
      const MAX_BYTES = 50 * 1024 * 1024;
      const bad = Array.from(files).find(
        (f) => !ALLOWED.test(f.name) || f.size > MAX_BYTES,
      );
      if (files.length > 50) {
        setError({
          code: "TOO_MANY_FILES",
          message: `한 번에 최대 50페이지까지 올릴 수 있습니다 (${files.length}개 선택됨)`,
        });
        return;
      }
      if (bad) {
        setError({
          code: "INVALID_FILE",
          message: !ALLOWED.test(bad.name)
            ? `지원하지 않는 형식입니다: ${bad.name} (JPG·PNG·PDF·BMP·WebP만 가능)`
            : `파일이 너무 큽니다: ${bad.name} (최대 50MB)`,
        });
        return;
      }
      setBusy(true);
      setError(null);
      const entries = Array.from(files).map((f) => ({
        name: f.name,
        status: "대기",
      }));
      setQueue(entries);
      try {
        setQueue((q) => q.map((x) => ({ ...x, status: "업로드 중" })));
        const { job_id, document_id } = await uploadFiles(Array.from(files));
        setQueue((q) => q.map((x) => ({ ...x, status: "완료" })));
        await new Promise<void>((resolve) => {
          requestAnimationFrame(() => resolve());
        });
        router.push(`/jobs/${job_id}?doc=${document_id}`);
      } catch (e) {
        const raw = String(e);
        const m = raw.match(/\[(\d+)(?:\s+([A-Z0-9_]+))?\]\s*(.*)$/);
        setError({
          code: m?.[2] || (m?.[1] ? `HTTP_${m[1]}` : "UPLOAD_ERROR"),
          message: m?.[3] || raw,
        });
        setQueue((q) => q.map((x) => ({ ...x, status: "실패" })));
        setBusy(false);
      }
    },
    [busy, router],
  );

  const liveJobs = jobs.filter(
    (j) => !["COMPLETED", "FAILED", "CANCELLED"].includes(j.state),
  );

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-8">
      <AcademyBar onChanged={refreshLibrary} />
      <div className="text-center">
        <h1 className="mb-2 bg-gradient-to-br from-white via-indigo-100 to-cyan-200 bg-clip-text text-4xl font-bold tracking-tight text-transparent">
          AI 시험지 복원
        </h1>
        <p className="text-dim">
          풀고 채점한 시험지를 올리면 원래 인쇄 시험지로 복원합니다
        </p>
      </div>
      {offline && (
        <p className="alert-amber px-4 py-2 text-sm" role="alert">
          오프라인 상태입니다. 네트워크 복구 후 다시 시도하세요.
        </p>
      )}
      <label
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          onFiles(e.dataTransfer.files);
        }}
        className={`glass lift flex h-64 w-full max-w-2xl cursor-pointer flex-col items-center justify-center rounded-3xl border-2 border-dashed transition ${
          dragging
            ? "!border-cyan-300/70 !bg-cyan-400/10 shadow-[0_0_60px_rgba(34,211,238,0.25)]"
            : "border-white/20"
        }`}
      >
        <span className="text-3xl" aria-hidden>
          ⬆
        </span>
        <span className="mt-3 text-lg font-medium">
          {busy ? "업로드 중..." : "시험지 사진·스캔·PDF를 여기에 드롭"}
        </span>
        <span className="mt-1 text-sm text-white/40">또는 클릭해서 선택</span>
        <input
          type="file"
          multiple
          accept=".jpg,.jpeg,.png,.pdf,.bmp,.webp"
          className="hidden"
          onChange={(e) => {
            const picked = e.target.files ? Array.from(e.target.files) : null;
            e.target.value = ""; // allow re-picking the same files
            onFiles(picked);
          }}
        />
      </label>
      {error && (
        <p className="alert-red px-4 py-2 text-sm" role="alert">
          <span className="font-semibold">{error.code}</span>
          {error.message ? `: ${error.message}` : ""}
        </p>
      )}
      {queue.length > 0 && (
        <ul className="glass w-full max-w-2xl overflow-hidden rounded-2xl">
          {queue.map((q, i) => (
            <li
              key={`${q.name}-${i}`}
              className="flex justify-between border-b border-white/8 px-4 py-2.5 text-sm last:border-b-0"
            >
              <span className="truncate">{q.name}</span>
              <span className="flex items-center gap-2 text-white/50">
                {q.status}
                {!busy && (
                  <button
                    className="btn-ghost !px-2 !py-0.5 text-xs"
                    onClick={() =>
                      setQueue((q) => q.filter((_, idx) => idx !== i))
                    }
                  >
                    제거
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}

      <Link
        href="/rebrand"
        className="glass-soft lift w-full max-w-2xl rounded-2xl border-dashed px-4 py-2.5 text-center text-sm text-cyan-300"
      >
        외부 학원 HWP/HWPX 브랜드 변경 →
      </Link>

      {liveJobs.length > 0 && (
        <div className="w-full max-w-2xl">
          <h2 className="mb-2 text-sm font-semibold text-white/70">
            진행 중·검토 대기 작업
          </h2>
          <ul className="glass divide-y divide-white/8 overflow-hidden rounded-2xl">
            {liveJobs.map((j) => (
              <li key={j.id}>
                <Link
                  href={
                    j.state === "NEEDS_REVIEW"
                      ? `/documents/${j.document_id}/review`
                      : `/jobs/${j.id}?doc=${j.document_id}`
                  }
                  className="lift flex items-center justify-between px-4 py-3 text-sm"
                >
                  <span className="text-white/70">
                    작업 {j.id.slice(0, 12)}…
                  </span>
                  <span
                    className={`chip ${JOB_STATE_LABEL[j.state]?.cls ?? "chip-blue"}`}
                  >
                    {JOB_STATE_LABEL[j.state]?.label ?? "처리 중"}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}

      {docs.length > 0 && (
        <div className="w-full max-w-2xl">
          <h2 className="mb-2 text-sm font-semibold text-white/70">문서 보관함</h2>
          <ul className="glass divide-y divide-white/8 overflow-hidden rounded-2xl">
            {docs.map((d) => {
              const verified = ["HUMAN_VERIFIED", "AUTO_VERIFIED"].includes(
                d.status,
              );
              const cls = verified
                ? "chip-green"
                : d.status === "CONFLICT" || d.status === "UNREADABLE"
                  ? "chip-red"
                  : "chip-amber";
              return (
                <li key={d.id}>
                  <Link
                    href={
                      verified
                        ? `/documents/${d.id}/editor`
                        : `/documents/${d.id}/review`
                    }
                    className="lift flex items-center justify-between px-4 py-3"
                  >
                    <span className="text-sm">
                      {String(d.metadata?.school || "시험지")} — {d.questions}
                      문항, {d.pages}페이지
                    </span>
                    <span className={`chip ${cls}`}>
                      {verified ? "검증 완료" : "검토 필요"}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </main>
  );
}
