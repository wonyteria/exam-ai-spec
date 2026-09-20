# RESTORE-09: blind evaluation / holdout release gate

## What was built

- `backend/eval/splits.py` — family-level corpus split registry.
  - Split unit is the family (school/year/exam origin group), per handoff-08 §4.
  - `validate_registry` catches: a family in two splits, an asset hash shared
    across holdout/open splits (content-level leakage), holdout families
    missing `sealed_at`.
  - `registry_hash` gives every eval run a stable split identity.
- `backend/eval/report.py` — eval run record + release gate.
  - Runs declare the full item set upfront; post-hoc items are rejected.
  - `finalize` fills missing results as `NOT_RUN` — never silent passes.
  - `summarize` reports separated counts (PASS/FAIL/REVIEW/REJECT/NOT_RUN),
    auto-exact rate against the frozen denominator, review-inflow rate,
    critical failure/unresolved counts.
  - `evaluate_release_gate` returns BLOCKED with explicit blockers unless a
    sealed holdout run is complete with zero unresolved/failed items and all
    run metadata present.
- `docs/handoff/evidence/CORPUS_SPLITS.json` — seeded registry. All current
  fixtures are `dev`; **holdout is empty by design**.
- `backend/tests/test_restore09.py` — 14 tests incl. live validation of the
  seeded registry.

## Honest status

- No sealed holdout corpus exists yet. The release gate therefore evaluates
  to **BLOCKED** — this is the correct, fail-closed outcome.
- The 99.5% machine-exactness and 99% full-exam-completion targets are
  **NOT_RUN / unmeasured**. The 248-test local regression suite is dev-split
  evidence only and does not demonstrate release readiness.
- Next step (outside code): curator provisions ≥30 independent exams /
  ≥1,000 grading units as a sealed holdout; independent QA runs the gate.

## Regression

- `pytest tests/test_restore09.py` — 14 passed.
- Full backend suite — see commit log.
