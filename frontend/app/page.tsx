"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import AcademyBar from "@/components/AcademyBar";
import Modal from "@/components/Modal";
import {
  listDocuments,
  uploadFiles,
  type DocumentSummary,
} from "@/lib/api";

export default function UploadPage() {
  const router = useRouter();
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ code: string; message: string } | null>(
    null,
  );
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [queue, setQueue] = useState<{ name: string; status: string }[]>([]);
  const [offline, setOffline] = useState(false);
  const [deleteIndex, setDeleteIndex] = useState<number | null>(null);

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
  }, []);

  const onFiles = useCallback(
    async (files: FileList | null) => {
      if (!files?.length || busy) return;
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

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-8">
      <AcademyBar onChanged={refreshLibrary} />
      <div className="text-center">
        <h1 className="mb-2 text-3xl font-bold">AI 시험지 복원</h1>
        <p className="text-gray-500">
          풀고 채점한 시험지를 올리면 원래 인쇄 시험지로 복원합니다
        </p>
      </div>
      {offline && (
        <p className="rounded border border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-800">
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
        className={`flex h-64 w-full max-w-2xl cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed transition ${
          dragging ? "border-blue-500 bg-blue-50" : "border-gray-300 bg-gray-50"
        }`}
      >
        <span className="text-lg font-medium">
          {busy ? "업로드 중..." : "시험지 사진·스캔·PDF를 여기에 드롭"}
        </span>
        <span className="mt-2 text-sm text-gray-400">또는 클릭해서 선택</span>
        <input
          type="file"
          multiple
          accept=".jpg,.jpeg,.png,.pdf,.bmp,.webp"
          className="hidden"
          onChange={(e) => onFiles(e.target.files)}
        />
      </label>
      {error && (
        <p className="text-sm text-red-600" role="alert">
          <span className="font-semibold">{error.code}</span>
          {error.message ? `: ${error.message}` : ""}
        </p>
      )}
      {queue.length > 0 && (
        <ul className="w-full max-w-2xl rounded-lg border bg-white">
          {queue.map((q, i) => (
            <li key={`${q.name}-${i}`} className="flex justify-between border-b px-3 py-2 text-sm last:border-b-0">
              <span className="truncate">{q.name}</span>
              <span className="flex items-center gap-2 text-gray-500">
                {q.status}
                {!busy && (
                  <button
                    className="rounded border px-2 py-0.5 text-xs"
                    onClick={() => setDeleteIndex(i)}
                  >
                    제거
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      <Modal
        title="삭제 확인"
        open={deleteIndex !== null}
        onClose={() => {
          if (busy) return;
          setDeleteIndex(null);
        }}
      >
        <p className="mb-3 text-sm">큐에서 이 파일을 제거하시겠습니까?</p>
        <div className="flex gap-2">
          <button
            className="rounded border px-3 py-1 text-sm"
            onClick={() => setDeleteIndex(null)}
            disabled={busy}
          >
            취소
          </button>
          <button
            className="rounded bg-red-600 px-3 py-1 text-sm text-white"
            onClick={() => {
              if (deleteIndex === null || busy) return;
              setQueue((q) => q.filter((_, idx) => idx !== deleteIndex));
              setDeleteIndex(null);
            }}
            disabled={busy}
          >
            삭제
          </button>
        </div>
      </Modal>

      <Link
        href="/rebrand"
        className="w-full max-w-2xl rounded-lg border border-dashed border-gray-300 bg-gray-50 px-4 py-2 text-center text-sm text-blue-700 hover:bg-blue-50"
      >
        외부 학원 HWP/HWPX 브랜드 변경 →
      </Link>

      {docs.length > 0 && (
        <div className="w-full max-w-2xl">
          <h2 className="mb-2 text-sm font-semibold text-gray-700">문서 보관함</h2>
          <ul className="divide-y rounded-xl border border-gray-200 bg-white">
            {docs.map((d) => {
              const needsReview = !["HUMAN_VERIFIED", "AUTO_VERIFIED"].includes(
                d.status,
              );
              const badge = d.status === "HUMAN_VERIFIED" ||
                d.status === "AUTO_VERIFIED"
                ? "bg-green-100 text-green-800"
                : d.status === "CONFLICT" || d.status === "UNREADABLE"
                  ? "bg-red-100 text-red-800"
                  : "bg-amber-100 text-amber-800";
              return (
                <li key={d.id}>
                  <Link
                    href={
                      needsReview
                        ? `/documents/${d.id}/review`
                        : `/documents/${d.id}/editor`
                    }
                    className="flex items-center justify-between px-4 py-3 hover:bg-gray-50"
                  >
                    <span className="text-sm">
                      {String(d.metadata?.school || "시험지")} — {d.questions}
                      문항, {d.pages}페이지
                    </span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${badge}`}
                    >
                      {needsReview ? "검토 필요" : "검증 완료"}
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
