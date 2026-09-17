"use client";

import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { uploadFiles } from "@/lib/api";

export default function UploadPage() {
  const router = useRouter();
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    <main className="flex min-h-screen flex-col items-center justify-center p-8">
      <h1 className="mb-2 text-3xl font-bold">AI 시험지 복원</h1>
      <p className="mb-8 text-gray-500">
        풀고 채점한 시험지를 올리면 원래 인쇄 시험지로 복원합니다
      </p>
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
      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
    </main>
  );
}
