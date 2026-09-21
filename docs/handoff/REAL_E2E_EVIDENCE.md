# REAL E2E — 실제 촬영 시험지 파이프라인 검증

Date: 2026-09-21
Fixture: `samples/simwon_2025_mid2/` (심원중학교 2학년 수학 2025-2학기 1차 지필평가,
5 photographed pages — 실제 학생 필기·채점 원/체크 포함). Family:
`golden-001-replay` (동일 시험 — 같은 family로 등록, 누출 검사 유효).
Driver: `backend/scripts/run_real_exam.py`
Env: `EXAMDNA_PADDLEOCR=1 EXAMDNA_PADDLE_PAGE=1 EXAMDNA_EASYOCR=1` (전부 로컬, 외부 전송 없음)

## Result (latest run)

| metric | value |
|---|---|
| pages | 5/5 processed, `unprocessed_pages=0` |
| questions detected | **30** (20 객관식 중 19 + 논술형 3 + 하위문항 8) |
| missing anchors | `[4]` → `missing_numbers=[4,10,16]` honest (10/16 captured under ambiguous `?` labels) |
| ATUs | 150 — `AUTO_VERIFIED 26` (two-engine exact agreement), `CONFLICT 18`, `UNVERIFIED 106` |
| text_conflicts | 17 — real cross-engine disagreements surfaced, never merged |
| reconstruction | 697 regions `REVIEW_REQUIRED` (handwriting/grading occlusion) — fail-closed |
| exports | `exam.hwpx`, `exam.docx`, `preview.html` generated; `artifact_proof=PASS` (DOCX re-parse) |
| gate | `NEEDS_REVIEW` — correct: single-student-marked source cannot auto-verify |

## Bugs found by the real fixture and fixed

1. **Two-column interleaving** — lines sorted by (y,x) mixed left/right columns;
   out-of-order numbers were dropped by the forward-numbering rule (8/23 detected).
   Fixed: line-center x clustering splits columns; numbering is per-column.
   Skewed photos break coverage-gutter detection — centers still cluster.
2. **Missing question bboxes** — items carried `line_bboxes` but no union `bbox`;
   `Question.source.bbox` was always None, disabling region extension and
   question-crop recognition. Fixed: normalized 1000-grid union bbox per item.
3. **No sub-question/descriptive anchors** — `논술형 N.`, `N-M.` patterns added.
4. **Occluded numbers dropped questions** — grading circles fused numbers into
   `O`-prefixed text (`10`→`O`), backward reads (`16`→`6`), detached bare digits.
   Ambiguous anchors now open `?`-labeled blocks with `anchor_ambiguous`
   provenance — the question is captured for review, the number never invented.
   Guards reject choice values, lone grading marks, and handwriting residue.
5. **EasyOCR path crash** — cv2.imread cannot open non-ASCII absolute paths
   (`D:\플랫폼\...`); adapter now passes an ndarray loaded via PIL.

## New capability

- **Second independent observer**: EasyOCR (Apache-2.0 code; CRAFT+CRNN stack,
  genuinely different engine family from PaddleOCR). Opt-in `EXAMDNA_EASYOCR=1`,
  wired via `ocr.get_providers()` / `vision.get_page_extractors()`.
  26 ATUs auto-verified by exact two-engine agreement; 17 real conflicts kept visible.

## Quantified OCR bench (real damaged pages vs gold expected.json)

`eval/bench` run on `golden-001-replay` (same exam), recorded in
`docs/handoff/evidence/bench/run_1789953399.json`:

| provider | char_exact | critical tokens | source_hallucination | elapsed |
|---|---|---|---|---|
| paddleocr | 0.194 | **142/172 = 82.6%** | 309 | 321s |
| easyocr | 0.136 | **122/172 = 70.9%** | 141 | 101s |

Reading: page-level char_exact is dominated by handwriting/figure noise the
print layer is meant to exclude; critical-token exactness is the meaningful
signal. Neither engine alone reaches release quality — which is exactly why
the two-observer + fail-closed review design exists. These are dev-split
numbers on ONE exam — not a general accuracy claim.

## Known limitations (honest)

- Q4 now recovered: the masked-number box (grading ink fused to "4." —
  detection box, no recognized text) is absorbed into its same-row body
  line as a masked_anchor -> captured as ?mark1 for review. All 31
  question units detected. missing_numbers still lists [4,10,16]
  honestly — ambiguous anchors never claim a real number.
- `missing_condition`/`unverified` remain high by design: OCR-only evidence
  cannot auto-verify critical fields; human review is the release path.
- Bench metrics not yet computed for this family (expected.json exists for
  golden_001 capture only).
- HWP/HWPX proof on this document requires the Hancom environment (NOT_RUN here).

## HTTP service E2E (service_e2e_simwon.json)

Full production path exercised over real HTTP — no legacy `run_pipeline`
shortcut: uvicorn -> `POST /api/tenants` -> `POST /api/uploads` (5 real
pages, multipart) -> the upload handler's embedded worker
(`jobs.worker.run_once` inside the server process) -> canonical revision ->
review items -> eligibility -> draft artifact download.

| step | result |
|---|---|
| upload | 200 — job + document + manifest ids |
| worker (PaddleOCR+EasyOCR env flags) | job `NEEDS_REVIEW` (review handoff, fail-closed) |
| revisions | 2 (upload + pipeline output) |
| canonical issues | 1 blocking issue raised |
| content checks | `SCHEMA_REFERENTIAL_INTEGRITY` PASSED, `content_ready=false` (unresolved fields block release) |
| review items API | **124 items**, `missing_numbers=[4,10,16]` — identical to the legacy-path run |
| artifacts | 3 DRAFT registered (hwpx / hwp / pdf) |
| draft download | 200 + byte-exact (hwpx 6,131 B / hwp 29,184 B / pdf 18,856 B) |

Regression: `backend/tests/test_service_e2e.py` runs the same path through
TestClient with mock providers (upload -> intercepted worker spawn -> real
`run_once` -> NEEDS_REVIEW -> review items -> `content_ready=false`).

## Masked-number confirmation (reviewer renumber path)

Exercised over real HTTP against the persisted service_e2e document
(`doc_8dc95bea7fcb`, 31 questions, three masked anchors):

| action | result |
|---|---|
| `SetField number ?6 -> 16` (unique `?` label) | 200, new revision, label becomes "16" |
| `SetField number ?mark1 -> 4` (label shared by two questions on legacy data) | **409 AMBIGUOUS_TARGET** — refused rather than editing the wrong question |
| `SetField number q_b7550f31899b -> 4` (page-3 masked anchor, by id) | 200 |
| `SetField number q_82393f7950d8 -> 10` (page-1 masked anchor, by id) | 200 |
| post-confirmation read model | labels 4/10/16 present, `missing_numbers` recomputed to `[]`, `unresolved_labels` `[]` |

Defects found by this verification and fixed in 5ad82a2:

- `SetField number` originally wrote the positional `number` field
  (dense 1..N sequence), so every real confirmation collided
  (NUMBER_EXISTS). It now confirms the printed number via `label`;
  positional ordering is untouched.
- `?`-labels were deduplicated per page — "?mark1" occurred twice in
  one document, making the label unresolvable. Ambiguous labels are
  now unique document-wide in `segmenter.py`.
- `missing_numbers` was a static pipeline snapshot; review-items now
  recomputes it from current labels and reports `unresolved_labels`.

Frontend: `renumberQuestion()` in `lib/api.ts` (revisions -> head ->
If-Match CAS) + inline "번호 확정" control on `?`-labeled review cards.
