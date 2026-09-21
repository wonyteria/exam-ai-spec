"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { activeTenant, agentPropose, applyChanges, API, composeExam, getDocument, getHeadRevisionForTenant, listRevisions, redoDoc, sendEdit, undoDoc } from "@/lib/api";
import type { AgentProposal, ComposeResult } from "@/lib/api";
import Modal from "@/components/Modal";

export default function EditorPage() {
  const { id } = useParams<{ id: string }>();
  const [instruction, setInstruction] = useState("");
  const [log, setLog] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [previewKey, setPreviewKey] = useState(0);
  const [listKey, setListKey] = useState(0);
  const [busyUndo, setBusyUndo] = useState(false);
  const [composing, setComposing] = useState(false);
  const [undoTarget, setUndoTarget] = useState<string | null>(null);
  const [planOpen, setPlanOpen] = useState(false);
  const [conflictOpen, setConflictOpen] = useState(false);
  const [pendingInstruction, setPendingInstruction] = useState("");
  const [pendingProposal, setPendingProposal] = useState<AgentProposal | null>(null);
  const [submitBusy, setSubmitBusy] = useState(false);
  const [focusQ, setFocusQ] = useState<string | null>(null);
  const [selQ, setSelQ] = useState<QuestionSummary | null>(null);
  const [previewMode, setPreviewMode] = useState("STUDENT_WITH_ENDNOTES");
  const [composeOpen, setComposeOpen] = useState(false);
  const [composeBusy, setComposeBusy] = useState(false);
  const [composeResult, setComposeResult] = useState<ComposeResult | null>(null);
  const [composeErr, setComposeErr] = useState<string | null>(null);
  const [cTitle, setCTitle] = useState("");
  const [cCount, setCCount] = useState("");
  const [cHigh, setCHigh] = useState("");
  const [cMid, setCMid] = useState("");
  const [cLow, setCLow] = useState("");
  const [cVersions, setCVersions] = useState("1");

  useEffect(() => {
    const tenant = activeTenant();
    if (!tenant) return;
    void listRevisions(tenant, id)
      .then((revs) => setUndoTarget(revs.length >= 2 ? revs[revs.length - 2]?.id : null))
      .catch(() => setUndoTarget(null));
  }, [id, listKey]);

  const submit = async (directInstruction?: string) => {
    const ins = (directInstruction ?? instruction).trim();
    if (!ins || busy || submitBusy) return;
    setSubmitBusy(true);
    setBusy(true);
    const lines = [`> ${ins}`];
    try {
      // Exam Agent path (RESTORE-25): structural commands are translated
      // to canonical ops server-side — previewed, then applied through
      // /changes with If-Match (revisioned, undoable).
      const tenant = activeTenant();
      if (tenant) {
        const proposal = pendingProposal ?? await agentPropose(tenant, id, ins).catch(() => null);
        if (proposal && proposal.recognized && proposal.ops.length > 0) {
          const r = await applyChanges(tenant, id, proposal.ops, proposal.if_match);
          lines.push(`적용: ${proposal.explanation}`);
          lines.push(`revision #${r?.data?.revision?.revision_no ?? "?"}`);
          setPendingProposal(null);
          setPreviewKey((k) => k + 1);
          setListKey((k) => k + 1);
          setBusy(false);
          setSubmitBusy(false);
          setLog((l) => [...lines, ...l]);
          setInstruction("");
          return;
        }
      }
      const res = await sendEdit(id, ins);
      if (res.ok) {
        lines.push(
          ...(res.applied ?? []).map(
            (a) => `적용: ${a.question}번 ${a.field} → ${JSON.stringify(a.value)}`,
          ),
        );
        setPreviewKey((k) => k + 1);
        setListKey((k) => k + 1);
      } else {
        lines.push(`미적용: ${res.detail ?? "적용된 연산 없음"}`);
      }
      lines.push(
        ...(res.skipped ?? []).map(
          (s) => `건너뜀: ${s.question}번 ${s.field} — ${s.reason}`,
        ),
      );
    } catch (e) {
      const msg = String(e);
      if (msg.includes("[409")) setConflictOpen(true);
      lines.push(`오류: ${msg}`);
    } finally {
      setBusy(false);
      setSubmitBusy(false);
    }
    setLog((l) => [...lines, ...l]);
    setInstruction("");
  };

  return (
    <main className="flex h-screen flex-col">
      <div className="grid flex-1 grid-cols-1 divide-y md:grid-cols-[1fr_2fr_1fr] md:divide-x md:divide-y-0">
        <aside className="overflow-auto p-4">
          <h2 className="mb-3 font-semibold">문제 목록</h2>
          <QuestionList
            key={listKey}
            docId={id}
            onSelect={(q) => {
              setFocusQ(q.id);
              setSelQ(q);
            }}
          />
          {selQ && (
            <QuestionEditCard
              key={`${selQ.id}-${listKey}`}
              docId={id}
              question={selQ}
              onApplied={() => {
                setPreviewKey((k) => k + 1);
                setListKey((k) => k + 1);
              }}
              onLog={(line) => setLog((l) => [line, ...l])}
            />
          )}
        </aside>

        <section className="flex flex-col overflow-hidden">
          <div className="flex items-center gap-2 border-b px-3 py-2">
            <span className="text-xs font-medium text-gray-500">미리보기</span>
            <select
              className="rounded border px-2 py-1 text-xs"
              value={previewMode}
              onChange={(e) => setPreviewMode(e.target.value)}
            >
              <option value="STUDENT">학생용</option>
              <option value="STUDENT_WITH_ENDNOTES">학생용+미주</option>
              <option value="ANSWER_SOLUTION">정답·해설</option>
              <option value="TEACHER">교사용</option>
            </select>
          </div>
          <iframe
            key={`${previewKey}-${previewMode}-${focusQ ?? ""}`}
            src={`${API}/api/documents/${id}/preview?output_mode=${previewMode}${focusQ ? `#q-${focusQ}` : ""}`}
            className="h-full w-full flex-1"
            title="preview"
          />
        </section>

        <aside className="flex flex-col p-4">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-semibold">AI 편집</h2>
            <button
              onClick={() => {
                setComposeOpen(true);
                setComposeResult(null);
                setComposeErr(null);
              }}
              className="rounded border px-2 py-1 text-xs hover:bg-gray-50"
            >
              새 시험 구성
            </button>
          </div>
          <div className="mb-3 flex-1 space-y-1 overflow-auto rounded border bg-gray-50 p-2 text-sm">
            {log.length === 0 && (
              <p className="text-gray-400">
                예: &quot;6번 숫자만 바꿔줘&quot;, &quot;8번과 비슷한 문제 3개&quot;
              </p>
            )}
            {log.map((line, i) => (
              <p key={i} className={line.startsWith(">") ? "font-medium" : "text-gray-600"}>
                {line}
              </p>
            ))}
          </div>
          <div className="flex gap-2">
            <input
              className="flex-1 rounded border px-3 py-2 text-sm"
              placeholder="자연어로 수정 요청"
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              onCompositionStart={() => setComposing(true)}
              onCompositionEnd={() => setComposing(false)}
              onKeyDown={(e) => e.key === "Enter" && !composing && submit()}
            />
            <button
              onClick={async () => {
                if (!instruction.trim() || busy || submitBusy) return;
                const cmd = instruction.trim();
                setPendingInstruction(cmd);
                // fetch the agent's structural proposal for the preview
                const tenant = activeTenant();
                setPendingProposal(null);
                if (tenant) {
                  try {
                    const p = await agentPropose(tenant, id, cmd);
                    if (p.recognized) setPendingProposal(p);
                  } catch { /* preview optional */ }
                }
                setPlanOpen(true);
              }}
              disabled={busy}
              className="rounded bg-blue-600 px-4 py-2 text-sm text-white disabled:opacity-50"
            >
              요청
            </button>
          </div>
          <div className="mt-2 flex gap-2">
            <button
              onClick={async () => {
                const tenant = activeTenant();
                if (!tenant || !undoTarget || busyUndo) return;
                setBusyUndo(true);
                try {
                  await undoDoc(tenant, id, undoTarget);
                  setPreviewKey((k) => k + 1);
                  setListKey((k) => k + 1);
                } finally {
                  setBusyUndo(false);
                }
              }}
              disabled={busyUndo || !undoTarget}
              className="rounded border px-3 py-1 text-xs disabled:opacity-50"
            >
              Undo
            </button>
            <button
              onClick={async () => {
                const tenant = activeTenant();
                if (!tenant || busyUndo) return;
                setBusyUndo(true);
                try {
                  await redoDoc(tenant, id);
                  setPreviewKey((k) => k + 1);
                  setListKey((k) => k + 1);
                } finally {
                  setBusyUndo(false);
                }
              }}
              disabled={busyUndo}
              className="rounded border px-3 py-1 text-xs disabled:opacity-50"
            >
              Redo
            </button>
          </div>
        </aside>
      </div>
      <Modal
        title="AI 변경 계획 승인"
        open={planOpen}
        onClose={() => {
          if (submitBusy) return;
          setPlanOpen(false);
        }}
      >
        <p className="mb-3 text-sm">아래 변경 지시를 적용하시겠습니까?</p>
        <pre className="mb-3 whitespace-pre-wrap rounded border bg-gray-50 p-2 text-xs">{pendingInstruction}</pre>
        {pendingProposal && (
          <div className="mb-3 rounded border border-blue-200 bg-blue-50 p-2 text-xs">
            <p className="mb-1 font-medium text-blue-800">구조화된 연산: {pendingProposal.explanation}</p>
            {pendingProposal.preview.map((line, i) => (
              <p key={i} className="text-blue-700">{line}</p>
            ))}
          </div>
        )}
        <div className="flex gap-2">
          <button
            className="rounded border px-3 py-1 text-sm"
            onClick={() => {
              if (submitBusy) return;
              setPlanOpen(false);
              setLog((l) => [`> ${pendingInstruction}`, "거부: 사용자 취소", ...l]);
            }}
            disabled={submitBusy}
          >
            거부
          </button>
          <button
            className="rounded bg-blue-600 px-3 py-1 text-sm text-white disabled:opacity-50"
            onClick={async () => {
              if (submitBusy) return;
              setPlanOpen(false);
              await submit(pendingInstruction);
            }}
            disabled={submitBusy}
          >
            승인 후 적용
          </button>
        </div>
      </Modal>
      <Modal
        title="새 시험 구성"
        open={composeOpen}
        onClose={() => {
          if (composeBusy) return;
          setComposeOpen(false);
        }}
      >
        <p className="mb-3 text-sm text-gray-600">
          이 문서의 문항 풀에서 새 시험지를 만듭니다 — 원본 문서는 변경되지 않습니다.
        </p>
        <div className="mb-3 space-y-2 text-sm">
          <input
            className="w-full rounded border px-3 py-1.5"
            placeholder="시험 제목 (선택)"
            value={cTitle}
            onChange={(e) => setCTitle(e.target.value)}
          />
          <input
            className="w-full rounded border px-3 py-1.5"
            placeholder="총 문항 수 (예: 15)"
            inputMode="numeric"
            value={cCount}
            onChange={(e) => setCCount(e.target.value)}
          />
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500">난이도</span>
            {([
              ["상", cHigh, setCHigh],
              ["중", cMid, setCMid],
              ["하", cLow, setCLow],
            ] as const).map(([band, val, setter]) => (
              <label key={band} className="flex items-center gap-1 text-xs">
                {band}
                <input
                  className="w-12 rounded border px-1.5 py-1"
                  inputMode="numeric"
                  value={val}
                  onChange={(e) => setter(e.target.value)}
                />
              </label>
            ))}
            <label className="ml-auto flex items-center gap-1 text-xs">
              버전
              <select
                className="rounded border px-1.5 py-1"
                value={cVersions}
                onChange={(e) => setCVersions(e.target.value)}
              >
                <option value="1">1</option>
                <option value="2">A/B 2</option>
                <option value="3">3</option>
              </select>
            </label>
          </div>
        </div>
        {composeErr && (
          <p className="mb-3 rounded border border-red-300 bg-red-50 p-2 text-xs text-red-700">
            {composeErr}
          </p>
        )}
        {composeResult && (
          <div className="mb-3 rounded border border-green-300 bg-green-50 p-3 text-sm">
            {composeResult.exams.map((ex, i) => (
              <p key={ex.document_id}>
                <a
                  className="font-medium text-green-800 underline"
                  href={`/documents/${ex.document_id}/editor`}
                >
                  버전 {composeResult.exams.length > 1 ? `${"ABC"[i]} — ` : ""}
                  {ex.questions}문항
                </a>
              </p>
            ))}
            <p className="mt-1 text-xs text-green-700">
              예상 풀이 시간 {Math.round(composeResult.total_estimated_minutes)}분
            </p>
            {Object.keys(composeResult.unfilled).length > 0 && (
              <p className="mt-1 text-xs text-amber-700">
                채우지 못한 슬롯:{" "}
                {Object.entries(composeResult.unfilled)
                  .map(([k, v]) => `${k} ${v}문항`)
                  .join(", ")}
              </p>
            )}
          </div>
        )}
        <div className="flex gap-2">
          <button
            className="rounded border px-3 py-1 text-sm"
            onClick={() => setComposeOpen(false)}
            disabled={composeBusy}
          >
            닫기
          </button>
          <button
            className="rounded bg-blue-600 px-3 py-1 text-sm text-white disabled:opacity-50"
            disabled={composeBusy}
            onClick={async () => {
              const tenant = activeTenant();
              if (!tenant || composeBusy) return;
              setComposeBusy(true);
              setComposeErr(null);
              try {
                const mix: Record<string, number> = {};
                const hi = parseInt(cHigh, 10);
                const mi = parseInt(cMid, 10);
                const lo = parseInt(cLow, 10);
                if (hi > 0) mix["상"] = hi;
                if (mi > 0) mix["중"] = mi;
                if (lo > 0) mix["하"] = lo;
                const cnt = parseInt(cCount, 10);
                setComposeResult(
                  await composeExam(tenant, id, {
                    title: cTitle || undefined,
                    count: Number.isInteger(cnt) && cnt > 0 ? cnt : undefined,
                    difficulty_mix:
                      Object.keys(mix).length > 0 ? mix : undefined,
                    versions: parseInt(cVersions, 10) || 1,
                  }),
                );
              } catch (e) {
                setComposeErr(String(e));
              } finally {
                setComposeBusy(false);
              }
            }}
          >
            {composeBusy ? "구성 중…" : "구성"}
          </button>
        </div>
      </Modal>
      <Modal
        title="충돌 감지"
        open={conflictOpen}
        onClose={() => setConflictOpen(false)}
      >
        <p className="text-sm">
          다른 탭/사용자 수정으로 버전 충돌(409)이 발생했습니다. 최신 상태를 확인하고 다시 시도하세요.
        </p>
        <div className="mt-3">
          <button
            className="rounded border px-3 py-1 text-sm"
            onClick={() => {
              setConflictOpen(false);
              setPreviewKey((k) => k + 1);
              setListKey((k) => k + 1);
            }}
          >
            새로고침
          </button>
        </div>
      </Modal>
    </main>
  );
}

interface QuestionSummary {
  id: string;
  number: number;
  label: string;
  status: string;
  points: number | null;
  answer: string | null;
  solution: string | null;
}

function QuestionList({
  docId,
  onSelect,
}: {
  docId: string;
  onSelect?: (question: QuestionSummary) => void;
}) {
  const [questions, setQuestions] = useState<QuestionSummary[]>([]);

  useEffect(() => {
    getDocument(docId)
      .then((doc) =>
        setQuestions(
          (doc.questions ?? []).map(
            (q: {
              id?: string;
              number: number;
              label?: string | null;
              points?: number | null;
              answer?: { value?: unknown } | null;
              solution?: { steps?: { text?: string }[] } | null;
              verification: { status: string };
            }) => ({
              id: q.id ?? `n${q.number}`,
              number: q.number,
              label: q.label ?? `${q.number}`,
              status: q.verification.status,
              points: q.points ?? null,
              answer:
                q.answer?.value === undefined || q.answer?.value === null
                  ? null
                  : String(q.answer.value),
              solution:
                q.solution?.steps
                  ?.map((s) => s.text ?? "")
                  .filter(Boolean)
                  .join("\n") || null,
            }),
          ),
        ),
      )
      .catch(() => {});
  }, [docId]);

  if (questions.length === 0)
    return <p className="text-sm text-gray-400">인식된 문항이 없습니다.</p>;
  return (
    <ul className="space-y-1 text-sm">
      {questions.map((q) => (
        <li key={q.id}>
          <button
            type="button"
            onClick={() => onSelect?.(q)}
            className="flex w-full items-center justify-between rounded border bg-white px-3 py-2 text-left hover:border-blue-300 hover:bg-blue-50"
            title="미리보기에서 이 문항으로 이동 / 정답·풀이 편집"
          >
            <span>{q.label}번</span>
            <span className="flex items-center gap-1.5">
              {q.points != null && q.answer == null && (
                <span
                  className="rounded bg-red-50 px-1.5 py-0.5 text-xs text-red-600"
                  title="배점 문항에 정답이 없습니다"
                >
                  정답 없음
                </span>
              )}
              <span
                className={`rounded px-1.5 py-0.5 text-xs ${
                  q.status === "HUMAN_VERIFIED" || q.status === "AUTO_VERIFIED"
                    ? "bg-green-100 text-green-700"
                    : q.status === "UNVERIFIED"
                      ? "bg-gray-100 text-gray-500"
                      : "bg-amber-100 text-amber-700"
                }`}
              >
                {q.status}
              </span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

/** Structured per-question edit — the teacher-facing path for fields the
 * OCR can never supply (answers/solutions on papers without a key).
 * Every field becomes a canonical op in ONE /changes call. */
function QuestionEditCard({
  docId,
  question,
  onApplied,
  onLog,
}: {
  docId: string;
  question: QuestionSummary;
  onApplied: () => void;
  onLog: (line: string) => void;
}) {
  const [answer, setAnswer] = useState(question.answer ?? "");
  const [solution, setSolution] = useState(question.solution ?? "");
  const [points, setPoints] = useState(
    question.points == null ? "" : String(question.points),
  );
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const apply = async () => {
    const tenant = activeTenant();
    if (!tenant || busy) return;
    setBusy(true);
    setErr(null);
    try {
      const head = await getHeadRevisionForTenant(tenant, docId);
      if (!head?.id) throw new Error("canonical head가 없습니다");
      const ops: Record<string, unknown>[] = [];
      const target = question.id;
      if (answer.trim() && answer.trim() !== (question.answer ?? "")) {
        ops.push({ op: "SetAnswer", target_id: target, value: answer.trim() });
      }
      const curSol = question.solution ?? "";
      if (solution.trim() && solution.trim() !== curSol) {
        ops.push({ op: "SetSolution", target_id: target, value: solution });
      }
      const p = parseInt(points, 10);
      if (Number.isInteger(p) && p > 0 && p !== question.points) {
        ops.push({ op: "SetPoints", target_id: target, value: p });
      }
      if (!ops.length) {
        setErr("변경된 값이 없습니다");
        return;
      }
      const r = await applyChanges(tenant, docId, ops, head.id);
      onLog(
        `편집: ${question.label}번 ${ops.map((o) => o.op).join(", ")} → revision #${r?.data?.revision?.revision_no ?? "?"}`,
      );
      onApplied();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-4 rounded-lg border bg-white p-3 text-sm shadow-sm">
      <h3 className="mb-2 font-semibold">{question.label}번 직접 편집</h3>
      <label className="mb-2 block text-xs text-gray-600">
        정답
        <input
          className="mt-1 w-full rounded border px-2 py-1.5 text-sm"
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          placeholder="예: ② 또는 42"
        />
      </label>
      <label className="mb-2 block text-xs text-gray-600">
        풀이 (한 줄 = 한 단계)
        <textarea
          className="mt-1 w-full rounded border px-2 py-1.5 text-sm"
          rows={3}
          value={solution}
          onChange={(e) => setSolution(e.target.value)}
          placeholder={"예:\n$x^2=4$이므로 $x=\\pm 2$\n조건에서 $x>0$이므로 답은 ②"}
        />
      </label>
      <label className="mb-3 block text-xs text-gray-600">
        배점
        <input
          className="mt-1 w-24 rounded border px-2 py-1.5 text-sm"
          inputMode="numeric"
          value={points}
          onChange={(e) => setPoints(e.target.value)}
        />
      </label>
      {err && <p className="mb-2 text-xs text-red-600">{err}</p>}
      <button
        onClick={apply}
        disabled={busy}
        className="w-full rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
      >
        {busy ? "적용 중…" : "적용 (canonical revision)"}
      </button>
    </div>
  );
}
