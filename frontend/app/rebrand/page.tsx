"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import AcademyBar from "@/components/AcademyBar";
import {
  activeTenant,
  getRebrandCandidates,
  rebrandApply,
  rebrandImport,
  rebrandLogo,
  type RebrandApplyResult,
  type RebrandCandidate,
  type RebrandManifest,
} from "@/lib/api";

const KIND_LABEL: Record<string, string> = {
  TITLE_HEADER_TEXT: "머리말 제목(텍스트)",
  TITLE_HEADER_TABLE_CELL: "머리말 표 셀 제목",
  TITLE_MASTER_TEXT: "바탕쪽 제목",
  TITLE_BODY_TOP: "본문 상단 제목",
  TITLE_IMAGE: "이미지 제목/로고",
  PAGE_NUM_CONTROL: "쪽번호 위치",
  PAGE_NUM_FIELD: "자동 쪽번호 필드",
  PAGE_NUM_MASTER_FIELD: "바탕쪽 쪽번호 필드",
  PRINT_PAGE_TOKEN: "인쇄 머리말/꼬리말 쪽번호",
  LITERAL_PAGE_NUMBER: "직접 입력 번호",
  EXISTING_WATERMARK: "기존 워터마크",
};

const KIND_GROUP: Record<string, string> = {
  TITLE_HEADER_TEXT: "title",
  TITLE_HEADER_TABLE_CELL: "title",
  TITLE_MASTER_TEXT: "title",
  TITLE_BODY_TOP: "title",
  TITLE_IMAGE: "title",
  PAGE_NUM_CONTROL: "pagenum",
  PAGE_NUM_FIELD: "pagenum",
  PAGE_NUM_MASTER_FIELD: "pagenum",
  PRINT_PAGE_TOKEN: "pagenum",
  LITERAL_PAGE_NUMBER: "pagenum",
  EXISTING_WATERMARK: "watermark",
};

function groupOf(kind: string): string {
  return KIND_GROUP[kind] ?? "other";
}

export default function RebrandPage() {
  const [tenant, setTenant] = useState<string | null>(null);
  const [docId, setDocId] = useState<string | null>(null);
  const [sourceInfo, setSourceInfo] = useState<{
    format: string;
    sha256: string;
    hancom: boolean;
  } | null>(null);
  const [manifest, setManifest] = useState<RebrandManifest | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [academy, setAcademy] = useState("");
  const [logoSha, setLogoSha] = useState("");
  const [watermarkOn, setWatermarkOn] = useState(true);
  const [replaceWm, setReplaceWm] = useState(false);
  const [removeNums, setRemoveNums] = useState(true);
  const [result, setResult] = useState<RebrandApplyResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ code: string; message: string } | null>(
    null,
  );
  const fileRef = useRef<HTMLInputElement>(null);
  const logoRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let id: number | null = null;
    if (typeof window !== "undefined") {
      id = window.requestAnimationFrame(() => setTenant(activeTenant()));
    }
    return () => {
      if (id !== null) window.cancelAnimationFrame(id);
    };
  }, []);

  const parseErr = (e: unknown) => {
    const raw = String(e instanceof Error ? e.message : e);
    const m = raw.match(/\[(\d+)(?:\s+([A-Z0-9_]+))?\]\s*(.*)$/);
    setError({
      code: m?.[2] || (m?.[1] ? `HTTP_${m[1]}` : "ERROR"),
      message: m?.[3] || raw,
    });
  };

  const onImport = useCallback(
    async (file: File | null) => {
      if (!file || !tenant || busy) return;
      setBusy(true);
      setError(null);
      setResult(null);
      try {
        const imp = await rebrandImport(tenant, file);
        setDocId(imp.document_id);
        setSourceInfo({
          format: imp.source_format,
          sha256: imp.source_sha256,
          hancom: imp.hancom_required,
        });
        const scan = await getRebrandCandidates(tenant, imp.document_id);
        setManifest(scan.manifest);
        // pre-select confident auto candidates; anything flagged for
        // confirmation stays unselected — the user decides explicitly
        setSelected(
          new Set(
            scan.manifest.candidates
              .filter((c) => c.confidence >= 0.8 && !c.requires_user_confirm)
              .map((c) => c.id),
          ),
        );
      } catch (e) {
        parseErr(e);
      } finally {
        setBusy(false);
      }
    },
    [tenant, busy],
  );

  const onLogo = useCallback(
    async (file: File | null) => {
      if (!file || !tenant) return;
      try {
        const r = await rebrandLogo(tenant, file);
        setLogoSha(r.logo_sha256);
      } catch (e) {
        parseErr(e);
      }
    },
    [tenant],
  );

  const toggle = (id: string) => {
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  };

  const onApply = useCallback(async () => {
    if (!tenant || !docId || !academy.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const r = await rebrandApply(tenant, docId, {
        academy_name: academy.trim(),
        confirmed_candidate_ids: Array.from(selected),
        remove_page_numbers: removeNums,
        watermark_enabled: watermarkOn,
        watermark_replace_existing: replaceWm,
        logo_sha256: logoSha,
      });
      setResult(r);
    } catch (e) {
      parseErr(e);
    } finally {
      setBusy(false);
    }
  }, [
    tenant,
    docId,
    academy,
    selected,
    removeNums,
    watermarkOn,
    replaceWm,
    logoSha,
    busy,
  ]);

  const groups: Record<string, RebrandCandidate[]> = { title: [], pagenum: [], watermark: [] };
  for (const c of manifest?.candidates ?? []) {
    (groups[groupOf(c.kind)] ?? (groups.other ??= [])).push(c);
  }

  return (
    <main className="mx-auto max-w-4xl p-4">
      <AcademyBar />
      <h1 className="mt-4 text-xl font-bold">외부 시험지 브랜드 변경</h1>
      <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
        다른 학원 HWP/HWPX의 제목을 현재 학원명으로 바꾸고, 중앙 로고 워터마크를
        넣고, 쪽번호만 제거합니다. 원본은 변경되지 않습니다.
      </p>

      {error && (
        <div role="alert" className="mt-3 rounded border border-red-400 bg-red-50 p-3 text-sm text-red-800 dark:bg-red-950 dark:text-red-200">
          <span className="font-mono font-semibold">{error.code}</span>{" "}
          {error.message}
        </div>
      )}

      <section className="mt-4 rounded border p-4 dark:border-neutral-700">
        <h2 className="font-semibold">1. 파일 가져오기</h2>
        <input
          ref={fileRef}
          type="file"
          accept=".hwp,.hwpx"
          aria-label="HWP 또는 HWPX 파일"
          onChange={(e) => onImport(e.target.files?.[0] ?? null)}
          disabled={!tenant || busy}
          className="mt-2"
        />
        {sourceInfo && (
          <p className="mt-2 text-sm">
            형식: <b>{sourceInfo.format.toUpperCase()}</b> · SHA256{" "}
            <code className="text-xs">{sourceInfo.sha256.slice(0, 16)}…</code>
            {sourceInfo.hancom && (
              <span className="ml-2 text-amber-600">
                HWP 원본 — 스캔에 한글 COM 변환이 필요합니다
              </span>
            )}
          </p>
        )}
      </section>

      {manifest && (
        <section className="mt-4 rounded border p-4 dark:border-neutral-700">
          <h2 className="font-semibold">2. 변경 후보 확인</h2>
          <p className="mt-1 text-xs text-neutral-500">
            선택한 항목만 변경됩니다. 구조 조사에서 발견된 후보이며 확인이
            필요한 항목은 표시됩니다.
          </p>
          {(["title", "pagenum", "watermark"] as const).map((g) =>
            groups[g]?.length ? (
              <div key={g} className="mt-3">
                <h3 className="text-sm font-semibold">
                  {g === "title" && "제목 후보"}
                  {g === "pagenum" && "쪽번호 후보"}
                  {g === "watermark" && "기존 워터마크"}
                </h3>
                <ul className="mt-1 space-y-1">
                  {groups[g].map((c) => (
                    <li key={c.id} className="flex items-center gap-2 text-sm">
                      <label className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={selected.has(c.id)}
                          onChange={() => toggle(c.id)}
                        />
                        <span>{KIND_LABEL[c.kind] ?? c.kind}</span>
                      </label>
                      <span className="text-neutral-500">
                        {c.text_preview}
                      </span>
                      {c.requires_user_confirm && (
                        <span className="rounded bg-amber-100 px-1 text-xs text-amber-800 dark:bg-amber-900 dark:text-amber-200">
                          확인 필요
                        </span>
                      )}
                      <span className="text-xs text-neutral-400">
                        {c.section} · {c.apply_page_type}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null,
          )}
        </section>
      )}

      {manifest && (
        <section className="mt-4 rounded border p-4 dark:border-neutral-700">
          <h2 className="font-semibold">3. 브랜드 적용</h2>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-sm">
              학원명
              <input
                value={academy}
                onChange={(e) => setAcademy(e.target.value)}
                className="rounded border px-2 py-1 dark:bg-neutral-800"
                placeholder="우리학원"
              />
            </label>
            <label className="flex items-center gap-2 text-sm">
              로고(PNG)
              <input
                ref={logoRef}
                type="file"
                accept="image/png"
                onChange={(e) => onLogo(e.target.files?.[0] ?? null)}
              />
            </label>
            {logoSha && <span className="text-xs text-green-700">로고 등록됨</span>}
          </div>
          <div className="mt-2 flex flex-wrap gap-4 text-sm">
            <label className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={watermarkOn}
                onChange={(e) => setWatermarkOn(e.target.checked)}
              />
              중앙 워터마크 추가
            </label>
            <label className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={replaceWm}
                onChange={(e) => setReplaceWm(e.target.checked)}
                disabled={!manifest.existing_watermark_count}
              />
              기존 워터마크와 병합 허용
            </label>
            <label className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={removeNums}
                onChange={(e) => setRemoveNums(e.target.checked)}
              />
              쪽번호 제거
            </label>
          </div>
          <button
            onClick={onApply}
            disabled={
              busy || !academy.trim() || !selected.size || (watermarkOn && !logoSha)
            }
            className="mt-3 rounded bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40"
          >
            {busy ? "처리 중…" : "확인 후 적용"}
          </button>
          {watermarkOn && !logoSha && (
            <p className="mt-1 text-xs text-amber-600">
              워터마크를 넣으려면 학원 로고 PNG를 먼저 등록하세요.
            </p>
          )}
        </section>
      )}

      {result && (
        <section className="mt-4 rounded border border-green-400 p-4 dark:border-green-700">
          <h2 className="font-semibold text-green-800 dark:text-green-300">
            적용 완료 — 새 revision 생성
          </h2>
          <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
            <dt>revision</dt>
            <dd className="font-mono text-xs">{result.revision.id}</dd>
            <dt>artifact sha256</dt>
            <dd className="font-mono text-xs">
              {result.artifact.artifact_sha256.slice(0, 24)}…
            </dd>
            <dt>구조 불변 검사</dt>
            <dd>{result.invariant.passed ? "통과" : "실패"}</dd>
            <dt>제거</dt>
            <dd>{result.invariant.removed_paths.length}건</dd>
            <dt>교체</dt>
            <dd>{result.invariant.replaced_paths.length}건</dd>
          </dl>
          <ul className="mt-2 text-xs">
            {Object.entries(result.proof.checks).map(([k, v]) => (
              <li key={k}>
                <span className="font-mono">{k}</span>:{" "}
                <b className={v === "PASSED" ? "text-green-700" : "text-amber-700"}>
                  {v}
                </b>
              </li>
            ))}
          </ul>
          {result.worker_unavailable && (
            <p className="mt-2 text-sm text-amber-700">
              한글 COM worker를 사용할 수 없어 실제 재열기/렌더 증명은
              NOT_RUN입니다. 최종 다운로드 전 실제 한글 증명이 필요합니다.
            </p>
          )}
        </section>
      )}

      <p className="mt-6 text-sm">
        <Link href="/" className="text-blue-600 underline">
          ← 업로드로 돌아가기
        </Link>
      </p>
    </main>
  );
}
