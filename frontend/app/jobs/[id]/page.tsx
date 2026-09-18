"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { API, JobEvent } from "@/lib/api";

const STAGE_LABELS: Record<string, string> = {
  preprocessing: "이미지 정규화",
  student_trace: "학생 필기·채점 흔적 분리",
  print_layer: "인쇄 레이어 복원",
  segmentation: "문항 분리",
  recognition: "본문·수식·도형 인식",
  source_verification: "원본 대조 검증",
  logic_verification: "문항 논리 검증",
  solving: "문제 풀이 검증",
  rendering: "문서 생성",
  export_verification: "HWP 역검증",
  zero_typo_gate: "ZERO TYPO GATE",
  pipeline: "파이프라인",
};

function JobView() {
  const { id } = useParams<{ id: string }>();
  const search = useSearchParams();
  const docId = search.get("doc");
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [state, setState] = useState("UPLOADED");
  const done = useRef(false);

  useEffect(() => {
    const es = new EventSource(`${API}/api/jobs/${id}/events`);
    es.onmessage = (msg) => {
      const data = JSON.parse(msg.data);
      if (data.done) {
        setState(data.state);
        done.current = true;
        es.close();
        return;
      }
      setEvents((prev) => [...prev, data as JobEvent]);
    };
    return () => es.close();
  }, [id]);

  const stages = [...new Set(events.filter((e) => e.stage !== "pipeline").map((e) => e.stage))];
  const finished = ["COMPLETED", "NEEDS_REVIEW", "FAILED"].includes(state);
  const lastStage = stages.at(-1);

  return (
    <main className="mx-auto max-w-3xl p-8">
      <h1 className="mb-1 text-2xl font-bold">
        {state === "FAILED" ? "처리 실패" : finished ? "처리 완료" : "시험지를 복원하고 있습니다"}
      </h1>
      <p className="mb-6 text-sm text-gray-500">
        상태:{" "}
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-medium ${
            state === "COMPLETED"
              ? "bg-green-100 text-green-800"
              : state === "NEEDS_REVIEW"
                ? "bg-amber-100 text-amber-800"
                : state === "FAILED"
                  ? "bg-red-100 text-red-800"
                  : "bg-blue-100 text-blue-800"
          }`}
        >
          {state}
        </span>
      </p>

      <ol className="space-y-2">
        {stages.map((stage) => {
          const last = events.filter((e) => e.stage === stage).at(-1);
          const isCurrent = !finished && stage === lastStage;
          return (
            <li
              key={stage}
              className={`flex items-start gap-3 rounded-lg border bg-white p-3 ${
                isCurrent ? "border-blue-400" : ""
              }`}
            >
              <span
                className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs ${
                  isCurrent
                    ? "bg-blue-100 text-blue-700"
                    : "bg-green-100 text-green-700"
                }`}
              >
                {isCurrent ? "…" : "✓"}
              </span>
              <div>
                <div className="font-medium">
                  {STAGE_LABELS[stage] ?? stage}
                </div>
                {last && (
                  <div
                    className={`text-sm ${
                      last.level === "warn"
                        ? "text-amber-600"
                        : last.level === "error"
                          ? "text-red-600"
                          : "text-gray-500"
                    }`}
                  >
                    {last.message}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>

      {finished && docId && (
        <div className="mt-8 flex gap-3">
          <Link
            href={`/documents/${docId}/review`}
            className="rounded-lg bg-blue-600 px-4 py-2 text-white"
          >
            예외 검토
          </Link>
          <Link
            href={`/documents/${docId}/editor`}
            className="rounded-lg border px-4 py-2"
          >
            에디터
          </Link>
          <Link
            href={`/documents/${docId}/export`}
            className="rounded-lg border px-4 py-2"
          >
            내보내기
          </Link>
        </div>
      )}
    </main>
  );
}

export default function JobPage() {
  return (
    <Suspense fallback={<main className="p-8">로딩…</main>}>
      <JobView />
    </Suspense>
  );
}
