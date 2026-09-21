"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { activeTenant, API, cancelJob, JobEvent, retryJobV1 } from "@/lib/api";
import Chrome from "@/components/Chrome";

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

const STATE_LABEL: Record<string, { label: string; cls: string }> = {
  COMPLETED: { label: "완료", cls: "chip-green" },
  NEEDS_REVIEW: { label: "검토 필요", cls: "chip-amber" },
  FAILED: { label: "실패", cls: "chip-red" },
  CANCELLED: { label: "중단됨", cls: "chip-gray" },
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
  const [streamLost, setStreamLost] = useState(false);
  const done = useRef(false);
  const seenEvents = useRef<Set<string>>(new Set());

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
    es.onopen = () => setStreamLost(false);
    es.onerror = () => setStreamLost(true);
    es.onmessage = (msg) => {
      const data = JSON.parse(msg.data);
      if (data.done) {
        setState(data.state);
        setStreamLost(false);
        done.current = true;
        es.close();
        return;
      }
      const key = `${data.ts}:${data.stage}:${data.message}`;
      if (seenEvents.current.has(key)) return;
      seenEvents.current.add(key);
      setEvents((prev) => [...prev, data as JobEvent]);
    };
    return () => es.close();
  }, [id, streamGeneration]);

  const stages = [...new Set(events.filter((e) => e.stage !== "pipeline").map((e) => e.stage))];
  const finished = ["COMPLETED", "NEEDS_REVIEW", "FAILED"].includes(state);
  const lastStage = stages.at(-1);
  const stageOrder = Object.keys(STAGE_LABELS).filter((s) => s !== "pipeline");
  const doneCount = finished
    ? stageOrder.length
    : Math.max(0, stages.length - 1);
  const pct = Math.round((doneCount / stageOrder.length) * 100);
  const st = STATE_LABEL[state] ?? { label: "처리 중", cls: "chip-blue" };

  return (
    <main className="mx-auto max-w-3xl p-8 pt-20">
      <Chrome title="처리" />
      <h1 className="mb-1 text-2xl font-bold">
        {state === "FAILED" ? "처리 실패" : finished ? "처리 완료" : "시험지를 복원하고 있습니다"}
      </h1>
      <p className="mb-6 text-sm text-dim">
        <span className={`chip ${st.cls}`}>{st.label}</span>
      </p>
      {!finished && (
        <div className="glass mb-6 rounded-2xl p-4">
          <div className="mb-1 flex justify-between text-xs text-white/50">
            <span>
              {doneCount}/{stageOrder.length} 단계
            </span>
            <span>{pct}%</span>
          </div>
          <div
            className="h-2 overflow-hidden rounded-full bg-white/10"
            role="progressbar"
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div
              className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-cyan-400 transition-all duration-500"
              style={{ width: `${pct}%` }}
            />
          </div>
          <p className="mt-2 text-xs text-white/40">
            실제 OCR은 페이지당 수 분 걸릴 수 있습니다 — 페이지를 닫지 마세요
          </p>
        </div>
      )}
      {offline && <p className="alert-amber mb-3 p-2 text-xs">오프라인 상태입니다.</p>}
      {streamLost && !finished && (
        <p className="alert-amber mb-3 p-2 text-xs">
          실시간 연결이 끊겼습니다 — 자동으로 재연결합니다
        </p>
      )}
      {error && <p className="alert-red mb-3 p-2 text-xs">{error}</p>}

      <ol className="space-y-2">
        {stages.map((stage) => {
          const last = events.filter((e) => e.stage === stage).at(-1);
          const isCurrent = !finished && stage === lastStage;
          return (
            <li
              key={stage}
              className={`glass lift flex items-start gap-3 rounded-2xl p-3 ${
                isCurrent ? "!border-indigo-400/50" : ""
              }`}
            >
              <span
                className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs ${
                  isCurrent
                    ? "bg-indigo-400/20 text-indigo-300"
                    : "bg-emerald-400/15 text-emerald-300"
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
                        ? "text-amber-300"
                        : last.level === "error"
                          ? "text-rose-300"
                          : "text-white/50"
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
            className="btn-primary"
          >
            예외 검토
          </Link>
          <Link
            href={`/documents/${docId}/editor`}
            className="btn-ghost"
          >
            에디터
          </Link>
          <Link
            href={`/documents/${docId}/export`}
            className="btn-ghost"
          >
            보내기
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
          className="btn-ghost !px-3 !py-1 text-xs"
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
              seenEvents.current.clear();
              done.current = false;
              setStreamGeneration((generation) => generation + 1);
            } catch (e) {
              setError(String(e));
            } finally {
              setBusy(null);
            }
          }}
          disabled={busy !== null || !(state === "FAILED" || state === "CANCELLED")}
          className="btn-ghost !px-3 !py-1 text-xs"
        >
          {busy === "retry" ? "재시도 요청 중…" : "재시도"}
        </button>
      </div>
    </main>
  );
}

export default function JobPage() {
  return (
    <Suspense fallback={<main className="p-8 text-white/60">로딩…</main>}>
      <JobView />
    </Suspense>
  );
}
