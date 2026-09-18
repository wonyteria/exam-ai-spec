"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  activeTenant,
  API,
  confirmPageOrder,
  DocPage,
  getDocPages,
  getReviewItems,
  resolveItem,
  ReviewItem,
  SourceManifestInfo,
} from "@/lib/api";

interface LogicFlagGroup {
  question_number: number;
  question_label?: string;
  flags: { kind: string; detail: string }[];
}

const KIND_LABEL: Record<string, string> = {
  question_number: "문항 번호",
  text_token: "텍스트",
  number: "숫자",
  variable: "변수",
  math_symbol: "수식",
  unit: "단위",
  points: "배점",
  choice: "선택지",
  figure_label: "도형",
  angle: "각도",
  length: "길이",
};

const STATUS_LABEL: Record<string, { label: string; cls: string }> = {
  UNVERIFIED: { label: "미검증", cls: "bg-amber-100 text-amber-800" },
  CONFLICT: { label: "충돌", cls: "bg-red-100 text-red-800" },
  UNREADABLE: { label: "판독 불가", cls: "bg-red-100 text-red-800" },
};

function cropUrl(docId: string, source: ReviewItem["source"]): string | null {
  if (!source || !source.bbox) return null;
  const b = source.bbox as { x: number; y: number; w: number; h: number };
  return `${API}/api/documents/${docId}/crops/${source.page}?x=${b.x}&y=${b.y}&w=${b.w}&h=${b.h}`;
}

export default function ReviewPage() {
  const { id } = useParams<{ id: string }>();
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [flags, setFlags] = useState<LogicFlagGroup[]>([]);
  const [missingNumbers, setMissingNumbers] = useState<number[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [pages, setPages] = useState<DocPage[]>([]);
  const [manifest, setManifest] = useState<SourceManifestInfo | null>(null);
  const [orderMsg, setOrderMsg] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await getReviewItems(id);
        if (cancelled) return;
        setItems(data.items);
        setFlags(data.logic_flags);
        setMissingNumbers(data.missing_numbers ?? []);
        const tenant = activeTenant();
        if (tenant) {
          try {
            const pd = await getDocPages(tenant, id);
            if (cancelled) return;
            setPages(pd.pages);
            setManifest(pd.manifest);
          } catch {
            /* page manifest unavailable — order panel stays hidden */
          }
        }
      } catch (e) {
        if (!cancelled) setError(String(e));
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  const resolve = async (atuId: string) => {
    const value = values[atuId];
    if (value === undefined) return;
    await resolveItem(id, atuId, value);
    setItems((prev) => prev.filter((i) => i.atu_id !== atuId));
  };

  const movePage = (index: number, dir: -1 | 1) => {
    setPages((prev) => {
      const j = index + dir;
      if (j < 0 || j >= prev.length) return prev;
      const next = [...prev];
      [next[index], next[j]] = [next[j], next[index]];
      return next;
    });
    setOrderMsg(null);
  };

  const confirmOrder = async () => {
    const tenant = activeTenant();
    if (!tenant) return;
    try {
      const res = await confirmPageOrder(
        tenant,
        id,
        pages.map((p) => p.source_page_id),
      );
      setManifest(res.data.manifest);
      setOrderMsg("페이지 순서를 확정했습니다");
    } catch (e) {
      setOrderMsg(`확정 실패: ${String(e)}`);
    }
  };

  const pending = items.length + flags.length + missingNumbers.length;

  return (
    <main className="mx-auto max-w-4xl p-8">
      <header className="mb-6">
        <h1 className="text-2xl font-bold">예외 검토</h1>
        <p className="mt-1 text-sm text-gray-500">
          판단 불가 항목만 확인합니다 — 전체 검수는 필요 없습니다
        </p>
        {loaded && pending > 0 && (
          <span className="mt-2 inline-block rounded-full bg-amber-100 px-3 py-1 text-sm font-medium text-amber-800">
            {pending}건 대기
          </span>
        )}
      </header>

      {error && (
        <p className="mb-4 rounded-lg border border-red-300 bg-red-50 p-4 text-red-700">
          {error}
        </p>
      )}

      {pages.length > 0 && (
        <section className="mb-6 rounded-lg border bg-white p-4 shadow-sm">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-semibold">페이지 순서</h2>
            <span
              className={`rounded px-2 py-0.5 text-xs ${
                manifest?.confirmed_by
                  ? "bg-green-100 text-green-800"
                  : "bg-amber-100 text-amber-800"
              }`}
            >
              {manifest?.confirmed_by ? "확정됨" : "미확정"}
            </span>
          </div>
          <ol className="mb-3 space-y-1">
            {pages.map((p, i) => (
              <li
                key={p.source_page_id ?? i}
                className="flex items-center gap-2 rounded border px-3 py-1.5 text-sm"
              >
                <span className="w-6 text-gray-400">{i + 1}</span>
                <span className="flex-1 truncate">
                  {p.original_name ?? p.source_page_id}
                  {p.pdf_page_index !== null && (
                    <span className="ml-1 text-xs text-gray-500">
                      (PDF {p.pdf_page_index + 1}p)
                    </span>
                  )}
                </span>
                {p.uncertain_regions.length > 0 && (
                  <span
                    className="rounded bg-amber-50 px-1.5 py-0.5 text-xs text-amber-700"
                    title="인쇄 겹침으로 보류된 영역 — 원본 대조 필요"
                  >
                    보류 {p.uncertain_regions.length}
                  </span>
                )}
                <button
                  onClick={() => movePage(i, -1)}
                  disabled={i === 0}
                  className="rounded border px-2 py-0.5 text-xs disabled:opacity-30"
                  aria-label="위로"
                >
                  ↑
                </button>
                <button
                  onClick={() => movePage(i, 1)}
                  disabled={i === pages.length - 1}
                  className="rounded border px-2 py-0.5 text-xs disabled:opacity-30"
                  aria-label="아래로"
                >
                  ↓
                </button>
              </li>
            ))}
          </ol>
          <div className="flex items-center gap-3">
            <button
              onClick={confirmOrder}
              className="rounded bg-blue-600 px-4 py-1.5 text-sm text-white hover:bg-blue-700"
            >
              순서 확정
            </button>
            {orderMsg && <span className="text-sm text-gray-600">{orderMsg}</span>}
          </div>
        </section>
      )}

      {missingNumbers.length > 0 && (
        <div className="mb-4 rounded-lg border border-red-300 bg-red-50 p-4">
          <span className="font-semibold text-red-800">
            인쇄 번호 누락: {missingNumbers.join(", ")}번
          </span>
          <p className="text-sm text-red-700">
            문항이 통째로 인식되지 않았습니다 — 원본 이미지를 확인해 주세요
          </p>
        </div>
      )}

      {loaded && pending === 0 && !error && (
        <p className="rounded-lg border border-green-300 bg-green-50 p-4 text-green-800">
          확인할 항목이 없습니다. 내보내기로 진행할 수 있습니다.
        </p>
      )}

      {items.map((item) => {
        const status = STATUS_LABEL[item.status] ?? {
          label: item.status,
          cls: "bg-gray-100 text-gray-700",
        };
        const crop = cropUrl(id, item.source);
        return (
          <div
            key={item.atu_id}
            className="mb-4 rounded-lg border bg-white p-4 shadow-sm"
          >
            <div className="mb-3 flex items-center gap-2 text-sm">
              <span className="font-semibold">
                {item.question_label ?? item.question_number}번 문항
              </span>
              <span className="rounded bg-gray-100 px-2 py-0.5 text-gray-700">
                {KIND_LABEL[item.kind] ?? item.kind}
              </span>
              <span className={`rounded px-2 py-0.5 ${status.cls}`}>
                {status.label}
              </span>
            </div>

            {crop && (
              <div className="mb-3">
                <p className="mb-1 text-xs font-medium text-gray-500">원본 영역</p>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={crop}
                  alt="원본 영역"
                  className="max-h-64 rounded border bg-gray-50 object-contain"
                />
              </div>
            )}

            {item.candidates.length > 0 && (
              <div className="mb-3 space-y-1 text-sm">
                {item.candidates.map((c, i) => (
                  <div key={i} className="flex items-baseline gap-2">
                    <span className="shrink-0 rounded bg-blue-50 px-1.5 py-0.5 text-xs text-blue-700">
                      {c.provider}
                    </span>
                    <span className="break-all text-gray-700">
                      {JSON.stringify(c.value)}
                    </span>
                  </div>
                ))}
              </div>
            )}

            <div className="flex gap-2">
              <input
                className="flex-1 rounded border px-3 py-1.5 text-sm"
                placeholder="확정 값 입력"
                value={values[item.atu_id] ?? ""}
                onChange={(e) =>
                  setValues((v) => ({ ...v, [item.atu_id]: e.target.value }))
                }
                onKeyDown={(e) => e.key === "Enter" && resolve(item.atu_id)}
              />
              <button
                onClick={() => resolve(item.atu_id)}
                className="rounded bg-blue-600 px-4 py-1.5 text-sm text-white hover:bg-blue-700"
              >
                확정
              </button>
            </div>
          </div>
        );
      })}

      {flags.map((g) => (
        <div
          key={g.question_number}
          className="mb-2 rounded-lg border border-amber-300 bg-amber-50 p-4"
        >
          <span className="font-semibold">
            {g.question_label ?? g.question_number}번 문항
          </span>
          <ul className="ml-4 list-disc text-sm text-amber-900">
            {g.flags.map((f, i) => (
              <li key={i}>
                {f.kind} — {f.detail}
              </li>
            ))}
          </ul>
        </div>
      ))}

      <div className="mt-8 flex gap-3">
        <Link
          href={`/documents/${id}/editor`}
          className="rounded-lg border px-4 py-2 text-sm"
        >
          에디터로
        </Link>
        <Link
          href={`/documents/${id}/export`}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700"
        >
          내보내기
        </Link>
      </div>
    </main>
  );
}
