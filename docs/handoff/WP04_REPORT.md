# WP04 Report — 운영 AI 어댑터·추출·원본/풀이 검증

Date: 2026-09-21
Commit base: WP03 `8ac09b4`

## Scope delivered

### Operational OpenAI adapter (`backend/providers/openai/`)

- Responses API adapter implementing the full provider surface:
  `extract_page`, `detect_regions`, `recognize_text`, `solve`,
  `solve_batch`, `edit_ops`, `complete`.
- **Schema-constrained output**: every structured call uses
  `text.format = {"type": "json_schema", "strict": True}` with strict
  schemas (`_PAGE_SCHEMA`, `_EXTRACT_SCHEMA`, `_SOLVE_BATCH_SCHEMA`, …).
  Dynamic-key objects (choices) are transported as `{label,text}` arrays
  (strict mode requires `additionalProperties: false`) and normalized
  back to `{label: text}` mappings (`_choices_to_dict`).
- Images sent as base64 PNG data-URLs (`_image_content`); `BBox` regions
  crop before upload.
- Prompt constants are shared with the Gemini adapter (`_PAGE_PROMPT`,
  `_SOLVE_PROMPT`, …) so prompt changes apply consistently.
- `solve`/`solve_batch` accept `run` — run 1 appends "독립 검증 2회차"
  to the prompt, so the second pass is a **different prompt → different
  call**, never a cache key replay posing as an independent opinion
  (02/A34).

### Telemetry + budget (`backend/providers/telemetry.py`)

- `CallRecord`: ts, provider, model, method, `prompt_sha256`,
  `input_sha256`, schema_version, outcome (`ok|cache|retry|error|
  refused|budget_exceeded`), attempts, latency, token usage, error class.
- `Telemetry` — thread-safe append-only log; `EXAMDNA_MAX_CALLS` /
  `max_calls` budget enforced **before** dispatch (`BudgetExceeded`).
  `cache` outcomes do not consume the call budget.
- `get_telemetry()` — process-wide log persisted to
  `$EXAMDNA_DATA/telemetry/ai_calls.jsonl` when configured.
- `hash_payload` — deterministic digest of prompt+input; image bytes
  hash to their digest, never logged raw.

### Provider selection (`backend/jobs/runner.py`)

- `default_providers()`: local providers are the base chain; **OpenAI is
  inserted first in every role (incl. `solver` via `OPENAI_MODEL_SOLVER`)
  when `OPENAI_API_KEY` is configured** — the operational default.
- **Gemini is opt-in only** (`EXAMDNA_ENABLE_GEMINI=1`); it is never
  auto-inserted. `google-genai` absence degrades gracefully
  (ImportError → skipped).
- Developer Codex stays a separate QA tool — not in the operational
  provider chain.
- Provider construction failures stay inside the guarded worker path —
  jobs go FAILED, the worker thread survives.

### Same-field candidate merge (`core/examdna/recognition/runner.py`)

- `_field_atu`: a second provider's value for the same `(kind, field)`
  is appended as a **candidate on the existing ATU**, not a duplicate
  ATU. Disagreement marks the ATU `CONFLICT` — extraction is not
  self-verifying; conflicts surface for review.
- One `extract_page` call per page still covers detection+extraction
  (`_page_extractions` stash); per-question retries only for inadequate
  fields (`_extraction_adequate`), max 3 attempts per provider.

### Solver-backed canonical checks (`canonical/service.py`)

- `run_checks(revision_id, providers=None)` — when a solver with
  `solve_batch` is present, one shared verification pass runs both
  independent rounds (run=0/run=1) per document, then:
  - `SOLVE_TWO_INDEPENDENT_AGREEMENT` — run0 vs run1 answers must agree
    per question; no comparable results → FAILED ("independent pass
    missing"); disagreements → FAILED + blocking issue.
  - `ANSWER_SOLUTION_LOGIC` — recorded answers vs solver output; no
    recorded answers or no shared ids → FAILED; mismatches → FAILED +
    blocking issue. Circled digits normalized (③ ↔ 3).
- Without a capable solver the checks stay **NOT_RUN** — fail-closed,
  never auto-PASSED. The local `StubMathSolverProvider` (no
  `solve_batch`) is filtered out rather than crashing the worker.
- Wired into both callers: durable worker (`jobs/worker.py` passes
  `ctx.providers`) and the v1 `checks/run` endpoint (builds
  `default_providers()`, degrading to NOT_RUN if provider init fails).

## Evidence (backend `pytest tests` — 80 passed)

`tests/test_wp04.py` (16 tests, no network — fake clients/stubs):

- `test_two_independent_runs_agree` — run 0 and run 1 both issued
  (`solver.runs == [0, 1]`); agreement → PASSED.
- `test_independent_disagreement_fails_and_blocks` — run1 differs →
  FAILED + blocking issue.
- `test_missing_second_run_fails` — 누락 회차 → FAILED.
- `test_solver_checks_not_run_without_provider` — fail-closed NOT_RUN.
- `test_answer_solution_mismatch_detected` — wrong recorded answer →
  FAILED + blocking issue.
- `test_seeded_baseline_seven_wrong_detected` — **7 wrong baseline
  answers all flagged**.
- `test_circled_digit_normalization` — ③ vs 3 → PASSED.
- `test_same_field_candidates_merge_and_conflict` — 서로 다른 후보 →
  one ATU, CONFLICT.
- `test_openai_strict_schema_and_solve_batch` — `strict: true` JSON
  schema + model passed through.
- `test_openai_run_prompts_differ_independence` — run 0 vs run 1
  payloads differ (cache replay ≠ inference).
- `test_openai_retries_429_then_succeeds` — 429, 503 → retry; outcome
  `retry`, attempts=3, usage recorded.
- `test_openai_non_retryable_error_recorded` — 400 → contained,
  outcome `error`.
- `test_openai_json_error_contained` — non-JSON output → unsolved
  candidate, no crash.
- `test_openai_budget_enforced` — `max_calls=1` → second call
  `budget_exceeded`, unsolved.
- `test_openai_telemetry_records_call_metadata` — model/method/
  prompt+input hashes/usage.
- `test_cache_replay_is_not_an_independent_run` — `outcome="cache"`
  records don't consume the call budget.

Full suite: **80 passed** (was 64 after WP03; +16 WP04).

## Dependency changes

- `openai` added to `backend/pyproject.toml` (installed 3.16.1).
- `pypdfium2` declared in WP03.

## Boundaries / pending

- `CURRICULUM_COMPLIANCE`, `REQUIRED_CONTENT_COVERAGE`,
  `ORIGINAL_SOURCE_FIDELITY`, `MATH_FIGURE_SEMANTIC_CONSISTENCY` remain
  NOT_RUN — land with WP05 (equation/figure semantics).
- Real OpenAI inference requires `OPENAI_API_KEY`; no network was used
  in tests. New-inference vs cache-replay outcomes are recorded as
  separate telemetry outcomes for reporting.
- `answer → endnote` materialization and grade-appropriate explanations
  are WP07.
