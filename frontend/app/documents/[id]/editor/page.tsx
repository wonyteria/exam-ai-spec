"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { API, sendEdit } from "@/lib/api";

export default function EditorPage() {
  const { id } = useParams<{ id: string }>();
  const [instruction, setInstruction] = useState("");
  const [log, setLog] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!instruction.trim() || busy) return;
    setBusy(true);
    const res = await sendEdit(id, instruction);
    setLog((l) => [
      `> ${instruction}`,
      res.ok ? "적용됨" : `미적용: ${res.detail ?? "?"}`,
      ...l,
    ]);
    setInstruction("");
    setBusy(false);
  };

  return (
    <main className="flex h-screen flex-col">
      <div className="grid flex-1 grid-cols-[1fr_2fr_1fr] divide-x">
        <aside className="overflow-auto p-4">
          <h2 className="mb-3 font-semibold">문제 목록</h2>
          <QuestionList docId={id} />
        </aside>

        <section className="overflow-auto">
          <iframe
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
              onKeyDown={(e) => e.key === "Enter" && submit()}
            />
            <button
              onClick={submit}
              disabled={busy}
              className="rounded bg-blue-600 px-4 py-2 text-sm text-white disabled:opacity-50"
            >
              요청
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
        <li key={q.number} className="flex justify-between rounded border px-3 py-2">
          <span>{q.label}번</span>
          <span className="text-gray-500">{q.status}</span>
        </li>
      ))}
    </ul>
  );
}
