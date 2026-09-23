# Phase 1 implementation map — restoration architecture contracts

Status: implemented + verified (549 backend tests pass). Phases 2–5 not started.

## Contracts (what exists now)

| Stage | File | Requires | Evidence |
|---|---|---|---|
| capability_preflight | `core/examdna/preflight.py` | — | `preflight.json` per job: solver slots (name/model/endpoint/json_mode), ocr_audit engine-module probe, trace_detect, docx_render (soffice), hwp_worker (win32 only) |
| source_integrity | `core/examdna/source_integrity.py` | — | sha256 re-verified vs ingest `Page.sha256`; missing hash is bound; variant_sha256 re-checked; mismatch → FAILED |
| preprocessing → recognition | existing | — | unchanged |
| source_verification | `source_truth/consensus.py` | `ocr_audit` | BLOCKED when only stub OCR |
| solving | `verification/solving.py` | `solver` | per-context-group units; `unit_failures` metric |
| rendering / export_verification / zero_typo_gate | existing | — | unchanged |

## Mechanics

- `stage_contract.py`: `StageStatus` (PENDING/RUNNING/SUCCEEDED/NEEDS_REVIEW/BLOCKED/FAILED/CANCELLED) + legal-transition table + `StageContract`/`StageRecord`.
- `executor.py`: `run_stages(ctx, on_stage_start, on_stage_end, should_cancel)` — shared by `jobs/runner.py` and `jobs/worker.py`; records appended to `<job_dir>/stage_records.jsonl`.
- BLOCKED → `ctx.stage_blocked` latch → job can only end NEEDS_REVIEW, never COMPLETED.
- `context_groups.py`: shared-stem children = one group; singletons otherwise; `run_units` isolates per-group exceptions.
- Solving is now per-context-group (no 10-question chunks at the pipeline level; a group >10 may still chunk inside the provider).
- json_mode support is learned once per provider/model via a `max_tokens=1` probe (≤15s); unsupported servers never pay a generation-length timeout again.
- External providers are never probed — recorded as configured; local endpoints re-validated through the localhost/LAN allowlist.

## Verified behavior

- No providers → `source_verification`+`solving` BLOCKED, job NEEDS_REVIEW, evidence in stage_records.jsonl.
- Live local endpoint → solver available, models enumerated, json_mode=False learned in ~15s.
- One crashed solve unit → sibling questions still answered; failed unit flagged `unsolvable_question`.
- Tampered page bytes → source_integrity FAILED, pipeline stops.

## Not yet (Phases 2–5)

- Document-level validators/review artifact, scheduler/fairness/backpressure,
  UI stage gating, damage-matrix benchmarks, concurrency load tests.
- `deskewed` variant routing still blocked by coordinate-space (inverse
  transform utils exist in `spatial.py`).
