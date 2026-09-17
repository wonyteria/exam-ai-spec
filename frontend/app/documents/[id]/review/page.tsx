"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { getReviewItems, resolveItem, ReviewItem } from "@/lib/api";

interface LogicFlagGroup {
  question_number: number;
  question_label?: string;
  flags: { kind: string; detail: string }[];
}

export default function ReviewPage() {
  const { id } = useParams<{ id: string }>();
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [flags, setFlags] = useState<LogicFlagGroup[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await getReviewItems(id);
      setItems(data.items);
      setFlags(data.logic_flags);
    } catch (e) {
      setError(String(e));
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const resolve = async (atuId: string) => {
    const value = values[atuId];
    if (value === undefined) return;
    await resolveItem(id, atuId, value);
    setItems((prev) => prev.filter((i) => i.atu_id !== atuId));
  };

  return (
    <main className="mx-auto max-w-4xl p-8">
      <h1 className="mb-1 text-2xl font-bold">예외 검토</h1>
      <p className="mb-6 text-sm text-gray-500">
        판단 불가 항목만 확인합니다 — 전체 검수는 필요 없습니다
      </p>
      {error && <p className="text-red-600">{error}</p>}

      {items.length === 0 && flags.length === 0 && !error && (
        <p className="rounded-lg border border-green-300 bg-green-50 p-4 text-green-800">
          확인할 항목이 없습니다.
        </p>
      )}

      {items.map((item) => (
        <div key={item.atu_id} className="mb-4 rounded-lg border p-4">
          <div className="mb-2 flex items-center gap-2 text-sm">
            <span className="font-semibold">{item.question_label ?? item.question_number}번 문항</span>
            <span className="rounded bg-gray-100 px-2 py-0.5">{item.kind}</span>
            <span className="rounded bg-amber-100 px-2 py-0.5 text-amber-800">
              {item.status}
            </span>
          </div>
          {item.candidates.length > 0 && (
            <div className="mb-2 text-sm text-gray-600">
              후보:{" "}
              {item.candidates.map((c) => `${c.provider}: ${JSON.stringify(c.value)}`).join(" | ")}
            </div>
          )}
          <div className="flex gap-2">
            <input
              className="flex-1 rounded border px-3 py-1.5"
              placeholder="확정 값 입력"
              value={values[item.atu_id] ?? ""}
              onChange={(e) =>
                setValues((v) => ({ ...v, [item.atu_id]: e.target.value }))
              }
            />
            <button
              onClick={() => resolve(item.atu_id)}
              className="rounded bg-blue-600 px-4 py-1.5 text-white"
            >
              확정
            </button>
          </div>
        </div>
      ))}

      {flags.map((g) => (
        <div key={g.question_number} className="mb-2 rounded-lg border border-amber-300 bg-amber-50 p-4">
          <span className="font-semibold">{g.question_label ?? g.question_number}번 문항</span>
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
        <Link href={`/documents/${id}/editor`} className="rounded-lg border px-4 py-2">
          에디터로
        </Link>
        <Link href={`/documents/${id}/export`} className="rounded-lg border px-4 py-2">
          내보내기
        </Link>
      </div>
    </main>
  );
}
