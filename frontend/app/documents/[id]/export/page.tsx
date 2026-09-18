"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { API, exportDoc } from "@/lib/api";

const GATE_LABEL: Record<string, string> = {
  text_conflict: "텍스트 충돌",
  number_conflict: "번호 충돌",
  math_conflict: "수식 충돌",
  choice_conflict: "선택지 충돌",
  figure_conflict: "도형 충돌",
  missing_condition: "조건 누락",
  missing_object: "문항 누락",
  logic_conflict: "논리 충돌",
  unsolvable_question: "풀이 불가",
  ambiguous_answer: "정답 불일치",
  unverified: "미검증",
  hwp_mismatch: "HWP 불일치",
  document_empty: "문서 비어 있음",
};

const GATE_ORDER = Object.keys(GATE_LABEL);

export default function ExportPage() {
  const { id } = useParams<{ id: string }>();
  const [gate, setGate] = useState<Record<string, unknown> | null>(null);
  const [status, setStatus] = useState<string>("");
  const [missing, setMissing] = useState<number[]>([]);
  const [result, setResult] = useState<{ file: string; url: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API}/api/documents/${id}`)
      .then((r) => r.json())
      .then((doc) => {
        const g = doc.verification?.gate ?? null;
        setGate(g);
        setMissing(Array.isArray(g?.missing_numbers) ? g.missing_numbers : []);
        setStatus(doc.verification?.status ?? "");
      })
      .catch(() => {});
  }, [id]);

  const doExport = async (format: string) => {
    setError(null);
    setResult(null);
    setBusy(format);
    try {
      setResult(await exportDoc(id, format));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  const verified = status === "VERIFIED_FINAL";

  return (
    <main className="mx-auto max-w-2xl p-8">
      <header className="mb-6">
        <h1 className="text-2xl font-bold">내보내기</h1>
        <p className="mt-2">
          <span
            className={`inline-block rounded-full px-3 py-1 text-sm font-medium ${
              verified
                ? "bg-green-100 text-green-800"
                : "bg-amber-100 text-amber-800"
            }`}
          >
            {verified ? "VERIFIED FINAL" : status || "상태 확인 중"}
          </span>
        </p>
      </header>

      {gate && (
        <div className="mb-6 rounded-lg border bg-white p-4 shadow-sm">
          <h2 className="mb-3 font-semibold">ZERO TYPO GATE</h2>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-sm">
            {GATE_ORDER.filter((k) => k in gate).map((k) => {
              const v = gate[k];
              const ok = v === 0 || v === false;
              return (
                <div key={k} className="flex justify-between">
                  <dt className="text-gray-500">{GATE_LABEL[k]}</dt>
                  <dd className={ok ? "text-green-700" : "font-medium text-red-600"}>
                    {v === true ? "예" : String(v)}
                  </dd>
                </div>
              );
            })}
          </dl>
          {missing.length > 0 && (
            <p className="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">
              누락된 인쇄 번호: {missing.join(", ")}번
            </p>
          )}
        </div>
      )}

      {!verified && (
        <p className="mb-4 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
          게이트를 통과하지 못한 문서입니다 — 내보내기 전에{" "}
          <Link href={`/documents/${id}/review`} className="font-medium underline">
            예외 검토
          </Link>
          를 권장합니다.
        </p>
      )}

      <div className="flex gap-3">
        {["hwpx", "pdf", "hwp"].map((fmt) => (
          <button
            key={fmt}
            onClick={() => doExport(fmt)}
            disabled={busy !== null}
            className="rounded-lg bg-blue-600 px-4 py-2 uppercase text-white hover:bg-blue-700 disabled:opacity-50"
            title={fmt === "hwp" ? "Windows + 한컴 설치 필요" : undefined}
          >
            {busy === fmt ? "생성 중…" : fmt}
          </button>
        ))}
      </div>

      {result && (
        <p className="mt-6 rounded-lg border border-green-300 bg-green-50 p-4">
          <a
            href={`${API}${result.url}`}
            className="font-medium text-green-800 underline"
            download
          >
            {result.file} 다운로드
          </a>
        </p>
      )}
      {error && (
        <p className="mt-6 rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </p>
      )}
    </main>
  );
}
