"use client";

import { useCallback, useEffect, useState } from "react";
import {
  API,
  confirmQuestion,
  editQuestion,
  getQuestionDetail,
  getRestoration,
  QuestionDetail,
  RestorationSummary,
} from "@/lib/api";
import Modal from "@/components/Modal";

const STATUS_META: Record<string, { label: string; cls: string }> = {
  AUTO_RESTORED: { label: "자동 복원", cls: "chip-green" },
  AUTO_CORRECTED: { label: "자동 교정", cls: "chip-blue" },
  NEEDS_USER_REVIEW: { label: "검토 필요", cls: "chip-amber" },
  USER_EDITED: { label: "수정됨", cls: "chip-blue" },
  USER_CONFIRMED: { label: "확정", cls: "chip-green" },
  BLOCKED: { label: "복원 불가", cls: "chip-red" },
};

const ISSUE_LABEL: Record<string, string> = {
  conflict: "후보 충돌",
  unverified: "미검증",
  unreadable: "판독 불가",
  sign_ambiguity: "부호 불일치",
  print_handwriting_overlap: "인쇄·필기 겹침",
  occluded: "가려진 영역",
};

function issueSummary(issues: { field: string; reason: string }[]): string {
  if (!issues.length) return "";
  const fields = new Set(issues.map((i) => i.field));
  if (fields.size === 1) {
    const f = [...fields][0];
    if (f.startsWith("choice:")) return `${f.slice(7)}번 선택지 확인 필요`;
    if (f === "body") return "문장 일부 확인 필요";
    if (f.startsWith("figure")) return "도형 표기 확인 필요";
    return `${f} 확인 필요`;
  }
  return `${fields.size}개 필드 확인 필요`;
}

export default function QuestionReview({ docId }: { docId: string }) {
  const [summary, setSummary] = useState<RestorationSummary | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [detail, setDetail] = useState<QuestionDetail | null>(null);
  const [instruction, setInstruction] = useState("");
  const [preview, setPreview] = useState<{
    before: QuestionDetail;
    after: QuestionDetail;
  } | null>(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setSummary(await getRestoration(docId));
  }, [docId]);

  useEffect(() => {
    refresh().catch(() => setSummary(null));
  }, [refresh]);

  async function openQuestion(qid: string) {
    setOpen(qid);
    setDetail(null);
    setPreview(null);
    setInstruction("");
    setMsg("");
    setDetail(await getQuestionDetail(docId, qid));
  }

  async function runEdit(apply: boolean) {
    if (!detail || !instruction.trim()) return;
    setBusy(true);
    try {
      const res = await editQuestion(docId, detail.id, instruction, apply);
      if (!res.ok) {
        setMsg(res.explanation || "지시를 해석할 수 없습니다.");
        setPreview(null);
        return;
      }
      if (!apply) {
        setPreview(res.preview ?? null);
        setMsg(res.explanation || "수정 미리보기");
        return;
      }
      setMsg(res.explanation || "수정이 적용되었습니다.");
      setPreview(null);
      setInstruction("");
      setDetail(await getQuestionDetail(docId, detail.id));
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!detail) return;
    setBusy(true);
    try {
      await confirmQuestion(docId, detail.id);
      setDetail(await getQuestionDetail(docId, detail.id));
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  if (!summary) return null;
  const c = summary.counts;

  return (
    <section className="glass mb-6 rounded-2xl p-5">
      <h2 className="mb-3 font-semibold">문항별 복원 상태</h2>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 12 }}>
        <span className="chip chip-green">자동 복원 {c.AUTO_RESTORED ?? 0}</span>
        <span className="chip chip-blue">자동 교정 {c.AUTO_CORRECTED ?? 0}</span>
        <span className="chip chip-amber">검토 필요 {c.NEEDS_USER_REVIEW ?? 0}</span>
        <span className="chip chip-red">복원 불가 {c.BLOCKED ?? 0}</span>
        <span className="chip chip-gray">전체 {c.total ?? 0}</span>
      </div>
      {summary.review_questions.length === 0 ? (
        <p>검토가 필요한 문항이 없습니다.</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {summary.review_questions.map((q) => (
            <li key={q.id} style={{ marginBottom: 6 }}>
              <button
                className="btn-ghost"
                style={{ width: "100%", textAlign: "left" }}
                onClick={() => openQuestion(q.id)}
              >
                <span
                  className={`chip ${STATUS_META[q.status]?.cls ?? "chip-gray"}`}
                  style={{ marginRight: 8 }}
                >
                  {STATUS_META[q.status]?.label ?? q.status}
                </span>
                {q.label}번 — {issueSummary(q.issues)}
              </button>
            </li>
          ))}
        </ul>
      )}

      <Modal
        title={detail ? `${detail.label}번 문항` : "문항"}
        open={open !== null}
        onClose={() => setOpen(null)}
      >
        {!detail ? (
          <p>불러오는 중…</p>
        ) : (
          <div>
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
              {detail.crop && (
                <figure style={{ margin: 0 }}>
                  <figcaption>원본</figcaption>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={`${API}${detail.crop}`}
                    alt="원본 crop"
                    style={{ maxWidth: 320, border: "1px solid #333" }}
                  />
                </figure>
              )}
              {detail.crop_clean && (
                <figure style={{ margin: 0 }}>
                  <figcaption>복원본</figcaption>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={`${API}${detail.crop_clean}`}
                    alt="복원 crop"
                    style={{ maxWidth: 320, border: "1px solid #333" }}
                  />
                </figure>
              )}
            </div>
            <div style={{ marginTop: 12 }}>
              {detail.body.map((t, i) => (
                <p key={i} style={{ margin: "4px 0" }}>{t}</p>
              ))}
              <ol style={{ paddingLeft: 20 }}>
                {detail.choices.map((ch) => (
                  <li key={ch.label}>
                    {ch.label} {ch.body.join(" ")}
                  </li>
                ))}
              </ol>
              {detail.issues.map((i, idx) => (
                <p key={idx} className="chip chip-amber" style={{ marginRight: 6 }}>
                  {i.field}: {ISSUE_LABEL[i.reason] ?? i.reason}
                  {i.detail ? ` — ${i.detail}` : ""}
                </p>
              ))}
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <input
                aria-label="자연어 수정"
                placeholder='예: "①번 보기를 -35로 수정해"'
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                style={{ flex: 1 }}
              />
              <button
                className="btn-ghost"
                disabled={busy || !instruction.trim()}
                onClick={() => runEdit(false)}
              >
                미리보기
              </button>
              <button
                className="btn-primary"
                disabled={busy || !preview}
                onClick={() => runEdit(true)}
              >
                적용
              </button>
              <button
                className="btn-ghost"
                disabled={busy}
                onClick={confirm}
              >
                확정
              </button>
            </div>
            {msg && <p>{msg}</p>}
            {preview && (
              <div style={{ marginTop: 8 }}>
                <h3>수정 전 → 수정 후</h3>
                <pre style={{ whiteSpace: "pre-wrap" }}>
                  {JSON.stringify(
                    {
                      before: {
                        body: preview.before.body,
                        choices: preview.before.choices,
                        points: preview.before.points,
                      },
                      after: {
                        body: preview.after.body,
                        choices: preview.after.choices,
                        points: preview.after.points,
                      },
                    },
                    null,
                    2,
                  )}
                </pre>
              </div>
            )}
          </div>
        )}
      </Modal>
    </section>
  );
}
