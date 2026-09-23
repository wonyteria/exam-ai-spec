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
  exportRestoration,
  getDocument,
  getEligibility,
  getRestoration,
  RestorationSummary,
  runChecks,
} from "@/lib/api";
import Chrome from "@/components/Chrome";

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

const FORMATS = ["hwpx", "docx", "pdf", "hwp"] as const;
const FORMAT_LABEL: Record<string, string> = {
  hwpx: "HWPX (편집 가능)",
  docx: "DOCX (워드)",
  pdf: "PDF",
  hwp: "HWP 5.0 (한컴 필요)",
};

const MODE_LABEL: Record<string, string> = {
  STUDENT: "학생용",
  STUDENT_WITH_ENDNOTES: "학생용 + 정답·해설 미주",
  ANSWER_SOLUTION: "정답·해설",
  TEACHER: "교사용",
};

const CHECK_LABEL: Record<string, string> = {
  SCHEMA_REFERENTIAL_INTEGRITY: "스키마·참조 무결성",
  SOURCE_REGION_COVERAGE: "원본 영역 커버리지",
  ORIGINAL_SOURCE_FIDELITY: "원본 충실도",
  QUESTION_CHOICE_SCORE_COMPLETENESS: "문항·배점 완결성",
  MATH_FIGURE_SEMANTIC_CONSISTENCY: "수식·도형 일치",
  SOLVE_TWO_INDEPENDENT_AGREEMENT: "독립 풀이 합의",
  ANSWER_SOLUTION_LOGIC: "정답·풀이 논리",
  CURRICULUM_COMPLIANCE: "교육과정 적합",
  REQUIRED_CONTENT_COVERAGE: "필수 내용 충족",
  BLOCKING_ISSUES_CLOSED: "차단 이슈 해소",
  APPROVED_EDIT_CONFORMANCE: "승인 편집 일치",
};

const CHECK_STATE_LABEL: Record<string, { label: string; cls: string }> = {
  PASSED: { label: "통과", cls: "chip-green" },
  FAILED: { label: "실패", cls: "chip-red" },
  NOT_RUN: { label: "미실행", cls: "chip-gray" },
};

const DOC_STATUS_LABEL: Record<string, string> = {
  NEEDS_REVIEW: "검토 필요",
  HUMAN_VERIFIED: "검증 완료",
  AUTO_VERIFIED: "검증 완료",
  VERIFIED_FINAL: "최종 검증",
  CONFLICT: "충돌",
  UNREADABLE: "판독 불가",
};

const RESTO_STATUS_LABEL: Record<string, string> = {
  RESTORED_BEST_EFFORT: "최선 복원 완료",
  NEEDS_USER_REVIEW: "검토 필요 문항 있음",
  READY_FOR_FINAL_EXPORT: "최종 export 준비됨",
};

const RESTO_FORMATS = ["json", "hwpx", "docx", "pdf"] as const;

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
  const [resto, setResto] = useState<RestorationSummary | null>(null);
  const [restoMsg, setRestoMsg] = useState<string | null>(null);

  const loadEligibility = useCallback(async () => {
    const tenant = activeTenant();
    if (!tenant) {
      setEligError("학원이 선택되지 않았습니다");
      return null;
    }
    try {
      const e = await getEligibility(tenant, id);
      setElig(e);
      setEligError(null);
      return e;
    } catch (e) {
      setEligError(String(e));
      return null;
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
        getRestoration(id)
          .then((r) => { if (!cancelled) setResto(r); })
          .catch(() => { if (!cancelled) setResto(null); });
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

  /** Pick the FINAL_ELIGIBLE artifact for a format from eligibility —
   * the proof-bound bytes, never a freshly minted DRAFT. */
  const pickFinal = (e: Eligibility | null, fmt: string) =>
    e?.formats?.[fmt]?.artifacts?.find((a) => a.state === "FINAL_ELIGIBLE");

  const doFinal = async (fmt: string) => {
    const tenant = activeTenant();
    if (!tenant || !elig || busy) return;
    setBusy(`final-${fmt}`);
    setError(null);
    setResult(null);
    try {
      // Prefer an artifact the server already proved final-eligible.
      // If none exists, generate bytes (+server proof) then re-read
      // eligibility — a DRAFT artifact must never be promoted.
      let e = elig;
      let art = pickFinal(e, fmt);
      if (!art) {
        await createArtifact(tenant, id, {
          revision_id: e.revision_id,
          format: fmt,
          output_mode: mode,
        });
        const fresh = await loadEligibility();
        if (fresh) {
          e = fresh;
          art = pickFinal(fresh, fmt);
        }
      }
      if (!art) {
        throw new Error(
          `${fmt.toUpperCase()}: 최종 조건을 충족한 아티팩트가 없습니다 — 검증을 다시 실행해 주세요`,
        );
      }
      const out = await exportFinal(tenant, id, e.revision_id, [art.id]);
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

  const doRestoExport = async (fmt: string) => {
    if (busy) return;
    setBusy(`resto-${fmt}`);
    setError(null);
    setRestoMsg(null);
    try {
      const out = await exportRestoration(id, fmt);
      setRestoMsg(
        `${fmt.toUpperCase()} 복원본 생성 — 검토 필요 ${out.counts?.NEEDS_USER_REVIEW ?? 0}문항`,
      );
      setResult({
        label: `${fmt.toUpperCase()} 복원본 (best-effort)`,
        url: `${process.env.NEXT_PUBLIC_API_URL ?? ""}${out.url}`,
      });
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  const ready = elig?.content_ready ?? false;

  return (
    <main className="mx-auto max-w-2xl p-8 pt-20">
      <Chrome title="보내기" />
      <header className="mb-6">
        <h1 className="text-2xl font-bold">보내기</h1>
        <p className="mt-2 flex flex-wrap items-center gap-2">
          <span className={`chip ${ready ? "chip-green" : "chip-amber"} !px-3 !py-1 !text-sm`}>
            {ready ? "콘텐츠 검증 완료" : "검증 필요"}
          </span>
          {elig && (
            <span className="text-xs text-white/50">
              revision {elig.revision_no} · {elig.mode} · 문서 상태{" "}
              {DOC_STATUS_LABEL[status] ?? status}
            </span>
          )}
        </p>
      </header>

      {resto && (
        <div className="glass mb-6 rounded-2xl p-5">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-semibold">복원본 다운로드 (best-effort)</h2>
            <span
              className={`chip ${
                resto.restoration_status === "READY_FOR_FINAL_EXPORT"
                  ? "chip-green"
                  : "chip-amber"
              }`}
            >
              {RESTO_STATUS_LABEL[resto.restoration_status] ??
                resto.restoration_status}
            </span>
          </div>
          <p className="mb-3 text-sm text-white/60">
            자동 복원 {resto.counts.AUTO_RESTORED ?? 0} · 자동 교정{" "}
            {resto.counts.AUTO_CORRECTED ?? 0} · 검토 필요{" "}
            {resto.counts.NEEDS_USER_REVIEW ?? 0} · 복원 불가{" "}
            {resto.counts.BLOCKED ?? 0} / 전체 {resto.counts.total ?? 0}
            {(resto.counts.NEEDS_USER_REVIEW ?? 0) > 0 && (
              <>
                {" "}—{" "}
                <Link
                  href={`/documents/${id}/review`}
                  className="underline"
                >
                  검토 필요 문항 보기
                </Link>
              </>
            )}
          </p>
          <div className="flex flex-wrap gap-2">
            {RESTO_FORMATS.map((fmt) => (
              <button
                key={fmt}
                data-resto-format={fmt}
                onClick={() => doRestoExport(fmt)}
                disabled={busy !== null}
                className="btn-ghost"
              >
                {busy === `resto-${fmt}` ? "생성 중…" : fmt.toUpperCase()}
              </button>
            ))}
          </div>
          {restoMsg && <p className="mt-2 text-xs text-white/50">{restoMsg}</p>}
        </div>
      )}

      {eligError && (
        <p className="alert-red mb-4 p-3 text-sm">
          게이트 조회 실패: {eligError}
        </p>
      )}

      {elig && (
        <div className="glass mb-6 rounded-2xl p-5">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-semibold">콘텐츠 체크</h2>
            <button
              onClick={doRunChecks}
              disabled={busy !== null}
              className="btn-ghost !px-3 !py-1 text-xs"
            >
              {busy === "checks" ? "검증 실행 중…" : "검증 재실행"}
            </button>
          </div>
          <dl className="space-y-1.5 text-sm">
            {elig.content_checks.map((c) => {
              const st = CHECK_STATE_LABEL[c.state] ?? CHECK_STATE_LABEL.NOT_RUN;
              return (
                <div key={c.check_kind} className="flex items-center justify-between gap-3">
                  <dt className="min-w-0 text-white/70">
                    <span>{CHECK_LABEL[c.check_kind] ?? c.check_kind}</span>
                    <span className="ml-2 font-mono text-[10px] text-white/30">
                      {c.check_kind}
                    </span>
                  </dt>
                  <dd className={`chip ${st.cls}`}>{st.label}</dd>
                </div>
              );
            })}
          </dl>
          {elig.blocking_issues.length > 0 && (
            <p className="alert-red mt-3 px-3 py-2 text-sm">
              차단 이슈 {elig.blocking_issues.length}건 —{" "}
              <Link href={`/documents/${id}/review`} className="underline">
                예외 검토
              </Link>
              에서 확인하세요
            </p>
          )}
        </div>
      )}

      {gate && (
        <div className="glass mb-6 rounded-2xl p-5">
          <h2 className="mb-3 font-semibold">ZERO TYPO GATE</h2>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-sm">
            {GATE_ORDER.filter((k) => k in gate).map((k) => {
              const v = gate[k];
              const ok = v === 0 || v === false;
              return (
                <div key={k} className="flex justify-between">
                  <dt className="text-white/50">{GATE_LABEL[k]}</dt>
                  <dd className={ok ? "text-emerald-300" : "font-medium text-rose-300"}>
                    {v === true ? "예" : v === false ? "없음" : String(v)}
                  </dd>
                </div>
              );
            })}
          </dl>
          {missing.length > 0 && (
            <p className="alert-red mt-3 px-3 py-2 text-sm">
              누락된 인쇄 번호: {missing.join(", ")}번
            </p>
          )}
        </div>
      )}

      <div className="glass mb-3 rounded-2xl p-4">
        <label className="mb-1.5 block text-sm font-medium text-white/70">출력 모드</label>
        <select
          className="inp w-auto"
          value={mode}
          onChange={(e) => setMode(e.target.value)}
        >
          {Object.entries(MODE_LABEL).map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
      </div>

      <div className="space-y-2">
        {FORMATS.map((fmt) => {
          const f = elig?.formats?.[fmt];
          return (
            <div
              key={fmt}
              data-format={fmt}
              className="glass lift flex items-center justify-between rounded-2xl p-4"
            >
              <div>
                <div className="text-sm font-medium uppercase">{fmt}</div>
                <div className="text-xs text-white/50">{FORMAT_LABEL[fmt]}</div>
                {f && (
                  <div className="mt-0.5 text-xs">
                    {f.final_eligible ? (
                      <span className="text-emerald-300">최종 export 가능</span>
                    ) : (
                      <span className="text-white/40">최종 조건 미충족 — 초안만 가능</span>
                    )}
                  </div>
                )}
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => doDraft(fmt)}
                  disabled={busy !== null || !elig}
                  className="btn-ghost"
                >
                  {busy === `draft-${fmt}` ? "생성 중…" : "초안"}
                </button>
                <button
                  onClick={() => doFinal(fmt)}
                  disabled={busy !== null || !f?.final_eligible}
                  className="btn-primary"
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
        <p className="alert-green mt-6 p-4">
          <a
            href={result.url}
            className="font-medium underline"
            download
          >
            {result.label} 다운로드
          </a>
        </p>
      )}
      {error && (
        <p className="alert-red mt-6 p-4 text-sm">
          {error}
        </p>
      )}
    </main>
  );
}
