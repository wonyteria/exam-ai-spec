"""Evaluation run record and release-gate evaluation (RESTORE-09).

Every eval run records commit + benchmark version + split hash +
provider config + worker version (handoff-08 §7). Results are per-item
PASS/FAIL/REVIEW/REJECT/NOT_RUN — a NOT_RUN is never a pass, and the
denominator is the declared item set, so abstention cannot inflate the
score. The release gate additionally reports review inflow and
unresolved limitations; a sealed holdout that was opened for fixes must
be moved to regression (handled at the registry level, not here).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

STATUSES = ("PASS", "FAIL", "REVIEW", "REJECT", "NOT_RUN")
_REQUIRED_META = (
    "commit",
    "benchmark_version",
    "split_hash",
    "provider_config",
    "worker_version",
)


def new_run(
    commit: str,
    benchmark_version: str,
    split_hash: str,
    provider_config: str,
    worker_version: str,
    items: list[str],
    split: str = "holdout",
) -> dict[str, Any]:
    """An eval run declares its full item set upfront — the denominator
    is frozen before results are filled in."""
    return {
        "commit": commit,
        "benchmark_version": benchmark_version,
        "split_hash": split_hash,
        "provider_config": provider_config,
        "worker_version": worker_version,
        "split": split,
        "declared_items": list(items),
        "results": {},  # item_id -> {status, detail, critical}
        "limitations": [],
    }


def record(run: dict, item_id: str, status: str,
           detail: str = "", critical: bool = False) -> None:
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    if item_id not in run["declared_items"]:
        raise KeyError(f"{item_id!r} not in declared items — add it to the "
                       "run upfront; post-hoc denominators are forbidden")
    run["results"][item_id] = {
        "status": status, "detail": detail, "critical": critical,
    }


def finalize(run: dict) -> dict:
    """Fill undeclared results as NOT_RUN — never silently passed."""
    for item in run["declared_items"]:
        run["results"].setdefault(
            item, {"status": "NOT_RUN", "detail": "not evaluated", "critical": False}
        )
    return run


def summarize(run: dict) -> dict[str, Any]:
    """Metrics, separated by outcome — never a single averaged score."""
    results = run.get("results", {})
    counts = {s: 0 for s in STATUSES}
    critical_fail = 0
    critical_open = 0
    for r in results.values():
        counts[r["status"]] += 1
        if r["status"] in ("FAIL", "REJECT") and r.get("critical"):
            critical_fail += 1
        if r["status"] in ("REVIEW", "NOT_RUN") and r.get("critical"):
            critical_open += 1
    total = len(run.get("declared_items", []))
    judged = counts["PASS"] + counts["FAIL"] + counts["REJECT"]
    return {
        "split": run.get("split"),
        "total_declared": total,
        "counts": counts,
        "auto_exact_rate": (counts["PASS"] / total) if total else 0.0,
        "review_inflow_rate": (
            (counts["REVIEW"] + counts["NOT_RUN"]) / total if total else 0.0
        ),
        "critical_failures": critical_fail,
        "critical_unresolved": critical_open,
        "judged_items": judged,
    }


def evaluate_release_gate(run: dict) -> dict[str, Any]:
    """Release decision: every counter must be clean AND every required
    piece of evidence must exist. Returns a structured verdict, never
    just a bool — unmet requirements are listed, not hidden."""
    missing_meta = [k for k in _REQUIRED_META if not run.get(k)]
    s = summarize(run)
    blockers: list[str] = []
    if missing_meta:
        blockers.append(f"missing run metadata: {missing_meta}")
    if run.get("split") != "holdout":
        blockers.append("release gate must run on the sealed holdout split")
    if s["total_declared"] == 0:
        blockers.append("no declared items")
    if s["counts"]["NOT_RUN"] or s["counts"]["REVIEW"]:
        blockers.append(
            f"unresolved items: NOT_RUN={s['counts']['NOT_RUN']} "
            f"REVIEW={s['counts']['REVIEW']}"
        )
    if s["counts"]["FAIL"] or s["counts"]["REJECT"]:
        blockers.append(
            f"failed items: FAIL={s['counts']['FAIL']} "
            f"REJECT={s['counts']['REJECT']}"
        )
    if s["critical_failures"] or s["critical_unresolved"]:
        blockers.append(
            f"critical: failures={s['critical_failures']} "
            f"unresolved={s['critical_unresolved']}"
        )
    return {
        "release": "BLOCKED" if blockers else "PASS",
        "blockers": blockers,
        "summary": s,
        "limitations": run.get("limitations", []),
    }


def write_report(run: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
