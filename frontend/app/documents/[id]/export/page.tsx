"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import {
  activeTenant,
  artifactDownloadUrl,
  createArtifact,
  Eligibility,
  exportFinal,
  getDocument,
  getEligibility,
  runChecks,
} from "@/lib/api";

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

const FORMATS = ["hwpx", "pdf", "hwp"] as const;
const FORMAT_LABEL: Record<string, string> = {
  hwpx: "HWPX (편집 가능)",
  pdf: "PDF",
  hwp: "HWP 5.0 (한컴 필요)",
};

const CHECK_STATE_LABEL: Record<string, { label: string; cls: string }> = {
  PASSED: { label: "통과", cls: "bg-green-100 text-green-800" },
  FAILED: { label: "실패", cls: "bg-red-100 text-red-800" },
  NOT_RUN: { label: "미실행", cls: "bg-gray-100 text-gray-600" },
};

export default function ExportPage() {
  const { id } = useParams<{ id: string }>();
  const [gate, setGate] = useState<Record<string, unknown> | null>(null);
  const [status, setStatus] = useState<string>("");
  const [missing, setMissing] = useState<number[]>([]);
  const [elig, setElig] = useState<Eligibility | null>(null);
  const [eligError, setEligError] = useState<string | null>(null);
  const [result, setResult] = useState<{ label: string; url: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [mode, setMode] = useState("STUDENT_WITH_ENDNOTES");

  const loadEligibility = useCallback(async () => {
    const tenant = activeTenant();
    if (!tenant) {
      setEligError("학원이 선택되지 않았습니다");
      return;
    }
    try {
      setElig(await getEligibility(tenant, id));
      setEligError(null);
    } catch (e) {
      setEligError(String(e));
    }
  }, [id]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const doc = await getDocument(id);
        if (cancelled) return;
        const g = doc.verification?.gate ?? null;
        setGate(g);
        setMissing(Array.isArray(g?.missing_numbers) ? g.missing_numbers : []);
        setStatus(doc.verification?.status ?? "");
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
      const tenant = activeTenant();
      if (!tenant) {
        if (!cancelled) setEligError("학원이 선택되지 않았습니다");
        return;
      }
      try {
        const e = await getEligibility(tenant, id);
        if (!cancelled) {
          setElig(e);
          setEligError(null);
        }
      } catch (err) {
        if (!cancelled) setEligError(String(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  const doRunChecks = async () => {
    const tenant = activeTenant();
    if (!tenant || busy) return;
    setBusy("checks");
    setError(null);
    try {
      await runChecks(tenant, id);
      await loadEligibility();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  const doDraft = async (fmt: string) => {
    const tenant = activeTenant();
    if (!tenant || !elig || busy) return;
    setBusy(`draft-${fmt}`);
    setError(null);
    setResult(null);
    try {
      const art = await createArtifact(tenant, id, {
        revision_id: elig.revision_id,
        format: fmt,
        output_mode: mode,
      });
      setResult({
        label: `${fmt.toUpperCase()} 초안 (DRAFT)`,
        url: artifactDownloadUrl(art.id, "draft"),
      });
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  const doFinal = async (fmt: string) => {
    const tenant = activeTenant();
    if (!tenant || !elig || busy) return;
    setBusy(`final-${fmt}`);
    setError(null);
    setResult(null);
    try {
      // Final export needs a verified artifact on the head revision:
      // create it (server records proof for the fresh bytes), then
      // promote through export_final which re-binds proof to bytes.
      const art = await createArtifact(tenant, id, {
        revision_id: elig.revision_id,
        format: fmt,
        output_mode: mode,
      });
      const out = await exportFinal(tenant, id, elig.revision_id, [art.id]);
      const item = out.artifacts[0];
      if (!item) throw new Error("보낼 아티팩트가 없습니다");
      setResult({
        label: `${fmt.toUpperCase()} 최종본`,
        url: `${process.env.NEXT_PUBLIC_API_URL ?? ""}${item.download_url}`,
      });
      await loadEligibility();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  const ready = elig?.content_ready ?? false;

  return (
    <main className="mx-auto max-w-2xl p-8">
      <header className="mb-6">
        <h1 className="text-2xl font-bold">보내기</h1>
        <p className="mt-2 flex flex-wrap items-center gap-2">
          <span
            className={`inline-block rounded-full px-3 py-1 text-sm font-medium ${
              ready
                ? "bg-green-100 text-green-800"
                : "bg-amber-100 text-amber-800"
            }`}
          >
            {ready ? "콘텐츠 검증 완료" : "검증 필요"}
          </span>
          {elig && (
            <span className="text-xs text-gray-500">
              revision {elig.revision_no} · {elig.mode} · 문서 상태 {status}
            </span>
          )}
        </p>
      </header>

      {eligError && (
        <p className="mb-4 rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-700">
          게이트 조회 실패: {eligError}
        </p>
      )}

      {elig && (
        <div className="mb-6 rounded-lg border bg-white p-4 shadow-sm">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-semibold">콘텐츠 체크 (head revision)</h2>
            <button
              onClick={doRunChecks}
              disabled={busy !== null}
              className="rounded border px-3 py-1 text-xs hover:bg-gray-50 disabled:opacity-40"
            >
              {busy === "checks" ? "검증 실행 중…" : "검증 재실행"}
            </button>
          </div>
          <dl className="space-y-1.5 text-sm">
            {elig.content_checks.map((c) => {
              const st = CHECK_STATE_LABEL[c.state] ?? CHECK_STATE_LABEL.NOT_RUN;
              return (
                <div key={c.check_kind} className="flex items-center justify-between">
                  <dt className="text-gray-600">{c.check_kind}</dt>
                  <dd className={`rounded px-2 py-0.5 text-xs ${st.cls}`}>
                    {st.label}
                  </dd>
                </div>
              );
            })}
          </dl>
          {elig.blocking_issues.length > 0 && (
            <p className="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">
              차단 이슈 {elig.blocking_issues.length}건 —{" "}
              <Link href={`/documents/${id}/review`} className="underline">
                예외 검토
              </Link>
              에서 확인하세요
            </p>
          )}
          {!ready && (
            <p className="mt-3 text-xs text-gray-500">
              편집·확정 등 뮤테이션 후에는 체크가 무효화됩니다 — &ldquo;검증
              재실행&rdquo;으로 현재 revision을 다시 검증하세요.
            </p>
          )}
        </div>
      )}

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

      <div className="mb-3">
        <label className="mb-1 block text-sm font-medium">출력 모드</label>
        <select
          className="rounded border px-2 py-1 text-sm"
          value={mode}
          onChange={(e) => setMode(e.target.value)}
        >
          <option value="STUDENT">STUDENT</option>
          <option value="STUDENT_WITH_ENDNOTES">STUDENT_WITH_ENDNOTES</option>
          <option value="ANSWER_SOLUTION">ANSWER_SOLUTION</option>
          <option value="TEACHER">TEACHER</option>
        </select>
      </div>

      <div className="space-y-2">
        {FORMATS.map((fmt) => {
          const f = elig?.formats?.[fmt];
          return (
            <div
              key={fmt}
              data-format={fmt}
              className="flex items-center justify-between rounded-lg border bg-white p-3"
            >
              <div>
                <div className="text-sm font-medium uppercase">{fmt}</div>
                <div className="text-xs text-gray-500">{FORMAT_LABEL[fmt]}</div>
                {f && (
                  <div className="mt-0.5 text-xs">
                    {f.final_eligible ? (
                      <span className="text-green-700">최종 export 가능</span>
                    ) : (
                      <span className="text-gray-500">최종 조건 미충족 — 초안만 가능</span>
                    )}
                  </div>
                )}
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => doDraft(fmt)}
                  disabled={busy !== null || !elig}
                  className="rounded border px-3 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-40"
                >
                  {busy === `draft-${fmt}` ? "생성 중…" : "초안"}
                </button>
                <button
                  onClick={() => doFinal(fmt)}
                  disabled={busy !== null || !f?.final_eligible}
                  className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-40"
                  title={
                    f?.final_eligible
                      ? "검증된 바이트를 최종본으로 승격"
                      : "해당 포맷의 필수 체크가 아직 통과되지 않았습니다"
                  }
                >
                  {busy === `final-${fmt}` ? "생성 중…" : "최종 export"}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {result && (
        <p className="mt-6 rounded-lg border border-green-300 bg-green-50 p-4">
          <a
            href={result.url}
            className="font-medium text-green-800 underline"
            download
          >
            {result.label} 다운로드
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
