"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { activeTenant, API, listRevisions, redoDoc, sendEdit, undoDoc } from "@/lib/api";

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

  useEffect(() => {
    const tenant = activeTenant();
    if (!tenant) return;
    void listRevisions(tenant, id)
      .then((revs) => setUndoTarget(revs.length >= 2 ? revs[revs.length - 2]?.id : null))
      .catch(() => setUndoTarget(null));
  }, [id, listKey]);

  const submit = async () => {
    if (!instruction.trim() || busy) return;
    setBusy(true);
    const res = await sendEdit(id, instruction);
    const lines = [`> ${instruction}`];
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
    setLog((l) => [...lines, ...l]);
    setInstruction("");
    setBusy(false);
  };

  return (
    <main className="flex h-screen flex-col">
      <div className="grid flex-1 grid-cols-1 divide-y md:grid-cols-[1fr_2fr_1fr] md:divide-x md:divide-y-0">
        <aside className="overflow-auto p-4">
          <h2 className="mb-3 font-semibold">문제 목록</h2>
          <QuestionList key={listKey} docId={id} />
        </aside>

        <section className="overflow-auto">
          <iframe
            key={previewKey}
            src={`${API}/api/documents/${id}/preview`}
            className="h-full w-full"
            title="preview"
          />
        </section>

        <aside className="flex flex-col p-4">
          <h2 className="mb-3 font-semibold">AI 편집</h2>
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
              onClick={submit}
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
    </main>
  );
}

function QuestionList({ docId }: { docId: string }) {
  const [questions, setQuestions] = useState<
    { number: number; label: string; status: string }[]
  >([]);

  useEffect(() => {
    fetch(`${API}/api/documents/${docId}`)
      .then((r) => r.json())
      .then((doc) =>
        setQuestions(
          (doc.questions ?? []).map(
            (q: { number: number; label?: string | null; verification: { status: string } }) => ({
              number: q.number,
              label: q.label ?? `${q.number}`,
              status: q.verification.status,
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
        <li
          key={q.number}
          className="flex items-center justify-between rounded border bg-white px-3 py-2"
        >
          <span>{q.label}번</span>
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
        </li>
      ))}
    </ul>
  );
}
