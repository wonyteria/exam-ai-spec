"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import AcademyBar from "@/components/AcademyBar";
import {
  listDocuments,
  uploadFiles,
  type DocumentSummary,
} from "@/lib/api";

export default function UploadPage() {
  const router = useRouter();
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [docs, setDocs] = useState<DocumentSummary[]>([]);

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
      try {
        const { job_id, document_id } = await uploadFiles(Array.from(files));
        router.push(`/jobs/${job_id}?doc=${document_id}`);
      } catch (e) {
        setError(String(e));
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
      {error && <p className="text-sm text-red-600">{error}</p>}

      {docs.length > 0 && (
        <div className="w-full max-w-2xl">
          <h2 className="mb-2 text-sm font-semibold text-gray-700">문서 보관함</h2>
          <ul className="divide-y rounded-xl border border-gray-200 bg-white">
            {docs.map((d) => (
              <li key={d.id}>
                <Link
                  href={`/documents/${d.id}/editor`}
                  className="flex items-center justify-between px-4 py-3 hover:bg-gray-50"
                >
                  <span className="text-sm">
                    {String(d.metadata?.school || "시험지")} — {d.questions}문항,{" "}
                    {d.pages}페이지
                  </span>
                  <span className="text-xs text-gray-500">{d.status}</span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </main>
  );
}
