"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { API, exportDoc } from "@/lib/api";

export default function ExportPage() {
  const { id } = useParams<{ id: string }>();
  const [gate, setGate] = useState<Record<string, number | boolean> | null>(null);
  const [status, setStatus] = useState<string>("");
  const [result, setResult] = useState<{ file: string; url: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API}/api/documents/${id}`)
      .then((r) => r.json())
      .then((doc) => {
        setGate(doc.verification?.gate ?? null);
        setStatus(doc.verification?.status ?? "");
      })
      .catch(() => {});
  }, [id]);

  const doExport = async (format: string) => {
    setError(null);
    setResult(null);
    try {
      setResult(await exportDoc(id, format));
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <main className="mx-auto max-w-2xl p-8">
      <h1 className="mb-1 text-2xl font-bold">내보내기</h1>
      <p className="mb-6 text-sm text-gray-500">
        문서 상태: <b>{status}</b>
      </p>

      {gate && (
        <div className="mb-6 rounded-lg border p-4">
          <h2 className="mb-2 font-semibold">ZERO TYPO GATE</h2>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
            {Object.entries(gate).map(([k, v]) => (
              <div key={k} className="flex justify-between">
                <dt className="text-gray-500">{k}</dt>
                <dd className={v === 0 || v === false ? "text-green-700" : "text-red-600"}>
                  {String(v)}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      <div className="flex gap-3">
        {["hwpx", "pdf", "hwp"].map((fmt) => (
          <button
            key={fmt}
            onClick={() => doExport(fmt)}
            className="rounded-lg bg-blue-600 px-4 py-2 uppercase text-white"
          >
            {fmt}
          </button>
        ))}
      </div>

      {result && (
        <p className="mt-6">
          <a
            href={`${API}${result.url}`}
            className="text-blue-600 underline"
            download
          >
            {result.file} 다운로드
          </a>
        </p>
      )}
      {error && <p className="mt-6 text-sm text-red-600">{error}</p>}
    </main>
  );
}
