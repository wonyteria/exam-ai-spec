"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { activeTenant, API, cancelJob, JobEvent, retryJobV1 } from "@/lib/api";

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
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [streamGeneration, setStreamGeneration] = useState(0);
  const [offline, setOffline] = useState(false);
  const done = useRef(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const on = () => setOffline(false);
    const off = () => setOffline(true);
    const initial = window.requestAnimationFrame(() =>
      setOffline(!window.navigator.onLine),
    );
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.cancelAnimationFrame(initial);
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);

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
  }, [id, streamGeneration]);

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
      {offline && <p className="mb-3 rounded border border-amber-300 bg-amber-50 p-2 text-xs text-amber-800">오프라인 상태입니다.</p>}
      {error && <p className="mb-3 rounded border border-red-300 bg-red-50 p-2 text-xs text-red-700">{error}</p>}

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
      <div className="mt-4 flex gap-2">
        <button
          onClick={async () => {
            if (busy) return;
            setBusy("cancel");
            setError(null);
            try {
              const j = await cancelJob(id);
              setState(j.state ?? "CANCELLED");
            } catch (e) {
              setError(String(e));
            } finally {
              setBusy(null);
            }
          }}
          disabled={busy !== null || finished}
          className="rounded border px-3 py-1 text-xs disabled:opacity-40"
        >
          {busy === "cancel" ? "중단 요청 중…" : "중단"}
        </button>
        <button
          onClick={async () => {
            const tenant = activeTenant();
            if (!tenant || busy) return;
            setBusy("retry");
            setError(null);
            try {
              await retryJobV1(tenant, id);
              setState("UPLOADED");
              setEvents([]);
              done.current = false;
              setStreamGeneration((generation) => generation + 1);
            } catch (e) {
              setError(String(e));
            } finally {
              setBusy(null);
            }
          }}
          disabled={busy !== null || !(state === "FAILED" || state === "CANCELLED")}
          className="rounded border px-3 py-1 text-xs disabled:opacity-40"
        >
          {busy === "retry" ? "재시도 요청 중…" : "재시도"}
        </button>
      </div>
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
