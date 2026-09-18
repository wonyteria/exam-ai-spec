# WP07 Report — 레이아웃·브랜드·미주·렌더러

Date: 2026-09-21
Commit base: WP06 `9e4c5c0`

## Scope delivered

### Common layout plan (`renderers/plan.py`)

- `build_plan(document, output_mode, title)` → `LayoutPlan`: the single
  source of layout truth consumed by all three renderers — no renderer
  invents layout, and nothing is a stack of pixel-counted blank lines.
- `Slot`s: objective questions land on a 2-column × row-paired grid
  (`column`/`row`/`pair` fields); long/descriptive questions become
  full-width `descriptive`/`shared_child` slots with computed
  `answer_lines`.
- `EndnoteEntry` list covers **every scored unit** — question number,
  label, answer, explanation — one per scored slot, in order.
- Output modes: `STUDENT` (no answers anywhere), `STUDENT_WITH_ENDNOTES`,
  `ANSWER_SOLUTION`, `TEACHER` (adds per-question verification status).

### Brand registry (`renderers/brand.py`)

- `get_brand(brand_id)` → `BrandTemplate` (header text, accent color,
  body font). Unknown ids fall back to `default` — never raises.
- Brand is presentation-only: it changes `header.xml` (accent charPr)
  and the body header paragraph — the semantic content hash is
  untouched, and a brand swap produces identical question bodies.

### HWPX renderer (`renderers/hwpx/renderer.py`) — real objects

Rewritten to emit XML that mirrors HWP's own output (diffed against a
file produced by HWP 2020 itself — the earlier hand-rolled XML crashed
HWP's loader; the corrected structure opens cleanly via
`HWPFrame.HwpObject.Open`).

- `<hp:equation>` as a real shape object (direct `hp:run` child, the
  same element HWP writes for `EquationCreate`): `baseUnit="1100"` (11pt),
  `lineMode="CHAR"`, `font="HYhwpEQ"`, `<hp:script>` carrying the
  HWP formula from `math_ast` (`hwp_formula`, or converted from LaTeX
  on the fly). Unserializable input → object dropped, never raw LaTeX.
- `<hp:endNote>` inside `<hp:ctrl>` for every scored unit — marker at
  the question head, `<hp:subList>` body holds `label. 정답: … — 해설`
  with an `hp:autoNum numType="ENDNOTE"` anchor.
- `<hp:tbl>` answer-space box for descriptive questions — a bordered
  single-cell table (borderFill id=2), not blank-paragraph stacking.
- `<hp:colPr type="NEWSPAPER" colCount="2">` newspaper columns for the
  objective grid (1 when no objective slots exist).
- `secPr` copied field-for-field from real HWP output (`noteSpacing`
  `belowLine`/`aboveLine`, `hp:numbering`, `hp:placement`, `endNotePr`).
- Correct package plumbing: `hv:HCFVersion` version.xml,
  `ha:HWPApplicationSetting` settings.xml, OCF container with the right
  `hpf` namespace + `Preview/PrvText.txt` rootfile, `application/xml`
  media types in `content.hpf`, empty `odf:manifest`.

### Web preview (`renderers/web/preview.py`)

- Same `build_plan`: objective grid renders as a 2-col HTML grid with
  row pairing; descriptive slots get ruled answer areas.
- `output_mode` gates endnote/answer-solution/teacher blocks; brand
  accent color + header text applied. Teacher-only verification status.

### PDF renderer (`renderers/pdf/renderer.py`)

- Plan-driven line layout with real pagination (`/Count N` pages).
- Type0 CJK font (`HYGoThic-Medium` + `UniKS-UCS2-H` CMap) — Korean text
  is emitted as UTF-16BE hex strings, never Latin-1 `?` replacement.

### Export API (`app/api/documents.py`)

- `GET /api/documents/{id}/export` accepts `output_mode` and `brand_id`
  query params, threaded through to every renderer.

## Evidence (backend `pytest tests` — 143 passed)

`tests/test_wp07.py` (16 tests):

- `test_objective_grid_and_row_pairing` — 2-col × row-pair slot
  assignment.
- `test_descriptive_answer_space` — descriptive → wide slot + answer
  lines.
- `test_shared_child_full_width` — shared-stem children span columns.
- `test_student_mode_carries_no_endnotes` — STUDENT plan has no
  endnote entries.
- `test_endnote_covers_all_scored_units` — every scored unit maps to
  exactly one endnote entry.
- `test_plan_invariant_detects_missing_endnote` — tampered plan fails
  its own invariant check.
- `test_hwpx_real_endnote_and_equation_objects` — `<hp:endNote ` count
  == scored units; `<hp:equation … baseUnit="1100"` + `<hp:script>`.
- `test_hwpx_two_column_layout` — `colCount="2"` newspaper column def.
- `test_hwpx_student_mode_hides_answers` — no answer/explanation text
  in student output.
- `test_hwpx_answer_solution_mode` — endnotes + 정답 및 해설 section.
- `test_hwpx_teacher_mode_shows_verification` — teacher-only status
  block.
- `test_hwpx_unparseable_equation_dropped_not_leaked` — unsupported
  input drops the object; no raw LaTeX in the package.
- `test_brand_change_same_content` — three brands → identical body
  text, different headers; unknown id → default.
- `test_web_preview_modes` — shared plan + mode gating in HTML.
- `test_pdf_unicode_and_modes` — UTF-16BE Korean hex strings, no `?`.
- `test_pdf_pagination` — multi-page `/Count`.

Live HWP proof (this session): a generated `.hwpx` containing
equations, endnotes, and an answer-space table was opened via
`HWPFrame.HwpObject.Open` on real Hancom Office 2020 — `Open` returned
True. This also fixed a regression found by
`test_batch_efficiency.py` (pipeline → `run_hwp_proof`): the previous
hand-rolled XML crashed HWP's loader (`0x800706be`); mirroring HWP's
own serialization fixed it.

Full suite: **143 passed** (was 127 after WP06; +16 WP07).

## Boundaries / pending

- HWPX opens cleanly in HWP, but the full Open→SaveAs→reopen proof loop
  and HWP→PDF conversion via Hancom are WP08 (real worker + artifact
  proof binding).
- `hp:linesegarray` is not emitted — HWP recomputes line segments on
  open; visual row-alignment is enforced via the shared plan, but the
  rendered-diff check (renderer output vs plan) is part of WP08's
  format proof.
- Figures render as `[그림]` captions + scene-derived text; vector
  `hp:rect`/`hp:line` scene drawing from the WP05 scene graph is not
  yet emitted.
- `SOLVE_TWO_INDEPENDENT_AGREEMENT` etc. still gate final export —
  output modes only shape rendering, not eligibility.
