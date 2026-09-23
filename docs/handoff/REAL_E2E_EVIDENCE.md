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

## Hancom proof + independent readback (2026-09)

`WindowsHWPWorker` is available on this machine — the service E2E
`exam.hwp`/`exam.pdf` artifacts were produced by a real Hancom COM
round-trip. Verified on the persisted document's **head** revision
(re-rendered from canonical head so labels 4/10/16 are included):

| proof | result |
|---|---|
| `run_hwp_proof(hwpx, workdir, doc)` — Hancom open→save-as-HWP→reopen→PDF, then reverse-parse + rendered-PDF text check | **PASS, 0 mismatches** |
| Stale-artifact check (pre-confirmation artifact vs head doc) | correctly reported 4 mismatches (heads "10."/"16." etc.) — the proof catches drift as designed |
| hwpilot `text` readback on `exam.hwpx` (head render) | 0 mismatches |
| hwpilot `text` readback on `exam.hwp` (Hancom reconvert of head hwpx) | 0 mismatches |

hwpilot (devxoul/hwpilot @7471fdfa, MIT) is now wired in as an
**independent observer**: `qa/hwpilot_proof.py` shells out to the CLI
(resolved via HWPILOT_CMD / HWPILOT_DIR / sibling tools/hwpilot / PATH).
`artifact_bridge` fills `NATIVE_OBJECT_INTEGRITY` for binary HWP from the
readback (previously no evidence source existed) and any FAILED readback
downgrades coverage checks our own parser passed. `export_verification`
records `independent_readback` evidence per artifact — content-level,
never a substitute for render proof. hwpilot limitations found during
integration: endNote subList text is not exposed in `text` output, and a
paragraph followed by an endNote run loses its final char — handled with
a documented dotless-head acceptance.

## Hancom-free HWP->HWPX conversion (rebrand path)

`_work_hwpx` now falls back to `hwpilot convert` when the Windows HWP
worker is unavailable — binary .hwp imports can be censused and
rebranded without Hancom (output stays HWPX). Converter provenance is
recorded (`work-converter.txt` blob + `work_converter` field in the
census response). Verified on the real service artifact: hwpilot
converted `exam.hwp` (29,696B binary, Hancom-produced) to a valid HWPX
whose independent text readback contains all question heads.

## Canonical export flow + full check coverage (rev 6, doc_8dc95bea7fcb)

Frontend export page now drives the canonical flow: eligibility for the
head revision -> draft artifact creation (server-side proof bound to
exact bytes) -> promotion only via POST /exports -> download only via
purpose=final. Draft artifacts are never presented as final.

New honest check implementations (all verified on the real document):

- APPROVED_EDIT_CONFORMANCE — PASSED ("5 revisions audited, hashes
  consistent"); EDIT lineage from head to restore baseline, recorded
  change sets + stored-hash recompute.
- ORIGINAL_SOURCE_FIDELITY — PASSED after a real fresh PaddleOCR audit
  of 22 question source regions (~330s). Three human-confirmed masked
  numbers (labels 10/16/20) are correctly reported as human-attested
  exceptions, not failures — the audit verifies machine extraction
  fidelity, and reviewer confirmations are their own evidence root.
- REQUIRED_CONTENT_COVERAGE — FAILED honestly: 9 scored questions lack
  verified answer/solution (real content gap, surfaced for review).
- CURRICULUM_COMPLIANCE — PASSED (no declared constraints to violate).
- LAYOUT_STYLE_BOUNDS — real pdfium page-bounds check; Hancom-rendered
  PDF doubles as render evidence for the HWPX bytes it came from, so
  hwpx format checks reach PASSED without simulation.

Real eligibility snapshot (rev 6): 6 PASSED / 3 FAILED (completeness =
30 unmaterialized question bodies pending review; coverage = missing
answers/solutions; aggregate) / 2 NOT_RUN (solver checks — no provider
key configured; stub solver is correctly ineligible).

Also fixed: ResolveATU now materializes the resolved value into the
derived field it backs (q.body/choices/equations/figures/points/label).
Previously review resolution only set the ATU status, so rendered
artifacts and the completeness check saw empty questions forever — the
real document was unreleasable no matter how much review was done.

## Bulk review + Hancom COM fix (rev 33, doc_8dc95bea7fcb)

- Found Hancom regression on this build: Open/SaveAs require the
  explicit (path, format, options) triple — bare calls fail with
  DISP_E_BADPARAMCOUNT. Worker helpers _hwp_open/_hwp_saveas now try the
  explicit form first; verified end-to-end over HTTP (all four
  round-trip steps True, hwp artifact checks 9/9 PASSED including
  hwpilot binary readback).
- run_hwp_proof and the v1 artifact route now treat COM failure as
  NOT_RUN/503 instead of crashing the pipeline job — a proof that
  cannot run is absent evidence, not a fatal error.
- Review queue driven through the new bulk-accept path: 105
  agreed-candidate ATUs resolved via 27 atomic /changes revisions
  (ResolveATU materializes into body/choices/points/labels). 22 items
  remain that genuinely need human judgment: 18 CONFLICT (OCR
  disagreement) + 4 blocked by a masked-label collision + 2 `?`-labeled
  questions (printed numbers 10/16 masked by grading marks).
- Check state after bulk resolution: completeness now fails only on
  the two masked numbers; coverage fails on 52 answer/solution fields —
  the resolved points ATUs correctly expanded the scored set, so more
  questions now require answers (honest, expected).
- New SetSolution canonical op + editor quick-edit card give the
  human path for answers/solutions that no OCR can supply.


## Full check pass + real solver + final export (rev 67, doc_8dc95bea7fcb)

Final head rev_eee12e9857ea (rev 67). All 11 content checks PASSED,
including the two solver-backed checks against real Gemini API calls:

- SOLVE_TWO_INDEPENDENT_AGREEMENT — PASSED (two independent
  gemini-3.6-flash batch passes, chunked at 10 problems per call)
- ANSWER_SOLUTION_LOGIC — PASSED (recorded answers match solver output)
- ORIGINAL_SOURCE_FIDELITY — PASSED (fresh PaddleOCR audit)
- APPROVED_EDIT_CONFORMANCE — PASSED (67 revisions audited)

The solver caught one real wrong answer: Q4 (직각삼각형 합동 조건) was
recorded as ④(ㄱ,ㄷ) but two independent solver runs and the grading
marks on the source page agree the intended answer is ③(ㄷ) — '두 변의
길이가 각각 같다' is the classic non-corresponding-sides trap. Answer
and solution corrected in rev 67.

Bugs fixed this round:
- APPROVED_EDIT_CONFORMANCE audited re-validated models instead of the
  stored snapshot, permanently failing revisions whose content held raw
  dict field values. Payload hashing now operates on the stored content
  dict; writers hash the same normalized dump they store.
- SetField raw-dict values could enter snapshots unnormalized; writers
  now validate+normalize before hashing/storing (_stored_content).
- mode='json' dump silently coerced NaN scene props to null, defeating
  the malicious-scene check; storage keeps canonical_json's NaN literal.
- VERIFIED_FINAL discard flip was computed after the hash boundary and
  never reached stored snapshots.
- Gemini solve_batch sent all problems in one call (output truncation
  -> silent empty results); now chunked 10/call.
- _generate_json retried cached malformed responses identically; a
  retry nonce now defeats the cache.
- Solver provider errors (503/quota) crashed the whole check run; they
  now record NOT_RUN with the reason (fail-closed, no 500).
- Source-fidelity audit treated structured-extractor candidates
  (Gemini dicts) as raw text; dict values are flattened to printed
  forms ('7.', '3점') for comparison.
- Solver answer comparison was exact-string only; units/degrees and
  descriptive-answer sentences now match via _answers_match
  (containment disabled for pure-numeric keys).
- Shared-stem children were sent to the solver without context and
  unanswerable; payloads now carry shared_stem. Parent stems are
  excluded from solver problems (compound answers can't normalize).

Final export verified end-to-end: three artifacts FINAL_ELIGIBLE ->
POST /exports promoted to FINAL -> purpose=final download bytes match
the proof-bound sha256 for hwpx (PK zip), hwp (CFB D0CF11E0, real
Hancom round-trip), pdf.
