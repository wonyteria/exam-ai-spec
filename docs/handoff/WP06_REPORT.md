# WP06 Report — 검토 확정·AI 편집·버전·undo/redo

Date: 2026-09-21
Commit base: WP05 `c0746a4`

## Scope delivered

### Expanded op vocabulary (`canonical/models.py`, `service.py`)

- New typed ops: `SetBody`, `SetChoice` (by label, creates the choice if
  absent), `SetEquation` (by index, bounds-checked), `AddQuestion`
  (missing-question recovery — appended + re-sorted, never merged into a
  duplicate number/label → `QUESTION_EXISTS` conflict), `RemoveQuestion`.
- `ChangeOp.propagate` — opt-in shared-stem propagation: `SetBody` /
  `SetField(figure)` on a parent also applies to direct children
  (`parent_id == target.id`); every propagated target is recorded in the
  change summary for audit.
- `SetField(field="type")` now coerces to `QuestionType` — the snapshot
  holds the enum, not a raw string.

### Edit safety invariants (`canonical/service.py`)

- **Label-conflict safety**: `_find_question` resolves exact id first,
  then number/label — a target matching **more than one question** fails
  `AMBIGUOUS_TARGET` (409). A label colliding with another question's
  number can no longer silently edit the wrong question.
- **No-op rejection**: an op set that changes none of the three hash
  families raises `ValidationError` — the history only records real
  state transitions.
- **VERIFIED_FINAL discard**: any successful edit resets
  `verification.status` to `NEEDS_REVIEW` — past answers/final status
  must be re-earned by post-edit checks. Answer edits already
  invalidate the solution-hash family (solver checks → stale).
- **Atomicity**: ops are validated inside `service.apply` — a plan with
  one bad target fails entirely; head never moves on partial plans.

### AI edit plans

- `core/examdna/editing.py` `ops_to_change_ops` — translates provider
  `{question, field, choice, index, value}` ops into `ChangeOp`s;
  unmappable ops return in `skipped` with reasons (never silently
  applied).
- `POST /api/v1/tenants/{t}/documents/{d}/edits` — provider proposes
  via `edit_ops` (first reasoning provider with the capability;
  OpenAI adapter already implements it), server validates and applies
  atomically under If-Match CAS + idempotency. `strict=true` rejects
  plans containing any unmappable op. No planner → 503
  `NO_EDIT_PROVIDER`; empty plan → 422 `EMPTY_EDIT_PLAN`.
- `POST /api/v1/tenants/{t}/documents/{d}/redo` — restores the
  pre-undo head; only valid when head is an undo revision, else 409
  `NOTHING_TO_REDO`.

### Review resolution → canonical (legacy routes fixed)

- `POST /api/documents/{id}/review-items/{atu_id}` — now routes through
  `MutationService.apply(ResolveATU)` when a canonical record exists
  (revision + invalidation + audit); flat-document fallback preserved.
  Also fixed a latent `NameError`: `store` was never injected.
- `POST /api/documents/{id}/edits` — canonical path uses
  `ops_to_change_ops` + `service.apply`; the provider is now any
  reasoning provider with `edit_ops` (was Gemini-only, which also broke
  when `google-genai` was absent). Same `store` fix.

## Evidence (backend `pytest tests` — 127 passed)

`tests/test_wp06.py` (16 tests):

- `test_resolve_atu_confirmed_value_in_revision` — confirmed value
  lands in the stored snapshot (확정값 = 출력값).
- `test_ops_to_change_ops_translation` — 5 ops mapped, 2 skipped.
- `test_edit_plan_atomicity_no_partial_mutation` — mixed good/bad plan
  fails entirely; head unchanged.
- `test_edit_ops_applied` — SetBody/SetChoice/SetAnswer land correctly.
- `test_set_equation_index` — index edit + out-of-range 422.
- `test_edit_discards_verified_final` — VERIFIED_FINAL → NEEDS_REVIEW.
- `test_answer_edit_invalidates_solver_checks` — solution-hash family
  goes stale.
- `test_label_conflict_does_not_touch_wrong_question` —
  AMBIGUOUS_TARGET.
- `test_concurrent_tabs_second_apply_409` — stale If-Match → 409.
- `test_noop_ops_rejected` — no new revision minted.
- `test_invalid_op_rejected` — `id`/`body` SetField blocked.
- `test_history_persists_across_reload` — fresh service sees revisions
  [1,2] and can undo.
- `test_undo_then_redo` — answer 1→2→(undo)1→(redo)2.
- `test_redo_on_non_undo_head_409` — NOTHING_TO_REDO.
- `test_propagate_setbody_to_children` — opt-in propagation only.
- `test_add_question_recovery` — sorted insert + duplicate conflict.

Full suite: **127 passed** (was 111 after WP05; +16 WP06).

## Boundaries / pending

- Re-extraction recovery (re-run pipeline stage for a question region)
  is pipeline orchestration, not a canonical op — tracked under the
  review UX work (WP09).
- `issue.resolve` already creates a ResolveATU revision and closes the
  issue; batch issue resolution remains a client loop.
- The legacy `/edits` endpoint uses the current head as implicit
  If-Match (back-compat); the v1 endpoint requires explicit If-Match —
  concurrent-tab safety evidence applies to v1.
