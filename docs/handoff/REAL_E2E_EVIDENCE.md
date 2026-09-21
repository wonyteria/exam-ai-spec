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

## Known limitations (honest)

- Q4 anchor still missed: detached number landed inside figure region, not at
  column edge. Its body text merged into a neighboring block — visible in review.
- `missing_condition`/`unverified` remain high by design: OCR-only evidence
  cannot auto-verify critical fields; human review is the release path.
- Bench metrics not yet computed for this family (expected.json exists for
  golden_001 capture only).
- HWP/HWPX proof on this document requires the Hancom environment (NOT_RUN here).
