# WP02 Report — canonical revision·검증·지속 작업 계약

Date: 2026-09-21
Commit base: WP01 `3e2dab1`

## Scope delivered

### Canonical model + store (`backend/canonical/`)

- `models.py` — DocumentRecord (lifecycle state + version), Revision (mode:
  UPLOAD/RESTORE/EDIT/UNDO/REVIEW, parent + restores links, distinct
  content/style/solution hashes), CheckRun (state machine
  NOT_RUN→RUNNING→PASSED/FAILED/NOT_APPLICABLE, input digest, stale
  invalidation), Issue (severity/blocking/state), Artifact (DRAFT→
  FINAL_ELIGIBLE→FINAL/SUPERSEDED/REJECTED, per-format sha256 + page count),
  ArtifactProof (bound to exact artifact bytes), JobV2 (durable job with
  lease owner/token/expiry/heartbeat/attempt_count), JobEventRecord
  (monotonic seq per job), IdempotencyRecord, Checkpoint.
- `store.py` — SQLite-backed transactional store. All multi-row writes are
  atomic (`BEGIN IMMEDIATE`). Key operations:
  - `create_revision` — increments `revision_no`, links parent, updates
    document head in one transaction.
  - `claim_job` — atomically claims QUEUED/RETRY_SCHEDULED/WAITING_WORKER,
    and RUNNING jobs whose lease expired (crash reclaim without waiting for
    the sweeper), issuing a fresh fencing token and bumping attempt_count.
  - `heartbeat` / `_check_write_fence` — every stage commit and terminal
    transition must present the current lease token; mismatched or expired
    tokens raise `StaleWorkerError` (STALE_LEASE).
  - `commit_job_stage` — checkpoint + event in one transaction.
  - `finish_job` — terminal transition. Non-CANCELLED finishes after a
    cancel request raise ALREADY_CANCELLED (cancel wins the race); the
    lease-owning worker can still close the job as CANCELLED.
  - `request_cancel` — cooperative cancellation flag; cancel after terminal
    raises ALREADY_COMPLETED.
  - `recover_expired_leases` — sweeper returning orphaned jobs to
    RETRY_SCHEDULED.
  - `events_since` / `max_event_seq` — durable, cursor-resumable event log.
  - `idempotency_lookup` / `save_idempotency` — request-hash comparison.

### Policy (`backend/canonical/policy.py`)

- Required content checks for restore documents:
  SCHEMA_REFERENTIAL_INTEGRITY, SOURCE_REGION_COVERAGE,
  ORIGINAL_SOURCE_FIDELITY, QUESTION_CHOICE_SCORE_COMPLETENESS,
  MATH_FIGURE_SEMANTIC_CONSISTENCY, SOLVE_TWO_INDEPENDENT_AGREEMENT,
  ANSWER_SOLUTION_LOGIC, CURRICULUM_COMPLIANCE, REQUIRED_CONTENT_COVERAGE,
  BLOCKING_ISSUES_CLOSED.
- Per-format required artifact checks; HWP additionally requires
  HWP_ACTUAL_REOPEN. Unimplemented checks stay NOT_RUN → fail-closed.
- `policy_digest` binds the required-check set to each revision/eligibility
  computation.

### Mutation service (`backend/canonical/service.py`)

- `create_revision` (UPLOAD/RESTORE seeding), `apply` (CAS via If-Match
  revision id, per-field expected_old_digest for field-level conflicts,
  idempotency key replay/conflict, audit, check invalidation on content
  change), `undo` (creates a NEW revision with restores_revision_id —
  history is never overwritten).
- `run_checks` — implemented validators:
  SCHEMA_REFERENTIAL_INTEGRITY (schema + duplicate ids),
  QUESTION_CHOICE_SCORE_COMPLETENESS (numeric labels, positive points),
  SOURCE_REGION_COVERAGE (fields without ATUs fail → blocking issue).
  Remaining required checks stay NOT_RUN until their verifiers land in
  WP04/WP05 — final promotion is therefore impossible today, by design.
  BLOCKING_ISSUES_CLOSED aggregates check states + open blocking issues.
- `register_draft_artifact` / `record_proof` (proof must bind to the
  artifact's exact sha256; complete required proof → FINAL_ELIGIBLE),
  `export_final` (requires head-revision match + FINAL_ELIGIBLE + bound
  proof per artifact; promotes to FINAL and audits).
- `compute_eligibility` — content_ready + per-format final_eligible view.

### Durable worker (`backend/jobs/worker.py`)

- `run_once` claims a job, heartbeats on a background thread, and runs the
  existing ExamDNA stages under the lease. Stage starts/progress are
  committed as fenced checkpoints/events via the PipelineContext event
  sink. Cancel is checked between stages. Terminal states:
  SUCCEEDED / FAILED / CANCELLED / COMPLETED_REVIEW_HANDOFF (review handoff
  is terminal — the job releases its slot, the document carries the review
  state). A stale worker's writes are fenced out; it commits nothing.
- After the pipeline, the restored document is committed as a RESTORE
  revision and implemented checks run — every head revision carries its
  verification record.

### API

- `backend/app/api/v1.py` — contract surface:
  documents, revisions, `POST .../changes` (If-Match + Idempotency-Key),
  undo, issues/resolve, checks/run, eligibility, artifacts (draft register),
  proofs, exports, artifact download (FINAL only — drafts are not
  downloadable), job get/retry/events (SSE with `Last-Event-ID` resume).
  Error envelope: `{error: {code, message, details, retryable}}` with
  404/409/422/428 mapping.
- `backend/app/api/jobs.py` — legacy `/api/jobs/*` now translates v2 jobs
  into the existing frontend shape (state map → UPLOADED/RUNNING/COMPLETED/
  NEEDS_REVIEW/FAILED/CANCELLED; SSE `{stage,message,level}` + `{done}`).
- `backend/app/api/uploads.py` — upload now creates the canonical document
  + RESTORE-ready durable job and spawns `run_once` (test-seam preserved).

### PipelineContext (`backend/core/examdna/context.py`)

- `resolve_uri()` maps `local://` object URIs through the private object
  store; plain paths pass through.
- `event_sink` routes stage events to the durable log when present.

## Contract evidence (tests)

`backend/tests/test_canonical.py` — 16 tests, all green:

- `test_stale_if_match_is_409` — stale If-Match → REVISION_CONFLICT with
  current_revision_id in details.
- `test_missing_if_match_is_428` — missing precondition → 428.
- `test_undo_creates_new_revision_not_overwrite` — undo is revision+1 with
  restores link; prior revisions immutable.
- `test_content_change_invalidates_checks` — dependent checks marked
  stale/not-applicable on content change.
- `test_field_digest_conflict` — stale field digest → FIELD_CONFLICT.
- `test_idempotency_replay_and_conflict` — same key+payload replays stored
  response; same key+different payload → IDEMPOTENCY_CONFLICT.
- `test_unrun_checks_block_final` — required checks NOT_RUN →
  content_ready False, all formats not final-eligible (fail-closed).
- `test_failed_check_creates_blocking_issue` — ATU-less fields fail
  SOURCE_REGION_COVERAGE and open a blocking issue.
- `test_final_export_requires_proof_binding` — draft export rejected,
  partial proof rejected, bound complete proof + green checks → FINAL;
  export against superseded revision rejected.
- `test_job_claim_heartbeat_commit`, `test_stale_worker_cannot_commit_
  after_lease_loss` — fencing token enforced; expired lease reclaimable;
  old worker cannot commit or finish.
- `test_cancel_vs_commit_race`, `test_cancel_after_complete_is_409` —
  cancel wins; terminal states are final.
- `test_lease_recovery` — sweeper requeues orphaned jobs.
- `test_events_seq_and_replay` — monotonic seq, cursor replay.

Also fixed during WP02:

- `jobs/runner.py` — `_gemini_provider` now tolerates missing `google-genai`
  (constructor inside try); provider failure can't kill the worker thread
  (provider construction moved inside the guarded block in `worker.py`).
- `canonical/store.py` — `finish_job` fence rewritten so a cancel-requested
  job can still reach CANCELLED terminal state (previously unreachable).

## Verification

- `python -m pytest tests` — **52 passed** (36 prior + 16 new).
- Manual API smoke (`tests/smoke_wp02.py`): upload → canonical doc +
  durable job → worker stages → RESTORE revision → checks → eligibility
  fail-closed; SSE cursor stream and legacy job translation verified.

## Known boundaries

- Most required checks are intentionally unimplemented (NOT_RUN) — final
  export is unreachable until WP04/WP05 verifiers land. This is fail-closed
  by design, not a gap.
- The in-process worker thread is a dev-mode executor; the queue contract
  (lease/fencing/recovery) is process-agnostic and ready for a dedicated
  worker service.
- AIHub/외부 평가 코퍼스는 여전히 미확보 — 본 WP의 검증은 계약 테스트이며
  품질 오라클이 아니다 (ADR-0006 경계 유지).
