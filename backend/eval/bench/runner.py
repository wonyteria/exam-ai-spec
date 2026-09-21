"""Benchmark runner (RESTORE-10B).

Runs provider adapters over dev-split fixtures and records per-item
metrics. Results are append-only JSONL + a run record compatible with
eval.report — abstentions and unavailability are recorded as NOT_RUN,
never dropped from the denominator.
"""
from __future__ import annotations

import json
import time
import tracemalloc
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from eval import report as eval_report
from eval import splits
from eval.bench import fixtures, gold, metrics

ProviderFactory = Callable[[], Any]


def ocr_provider_registry() -> dict[str, ProviderFactory]:
    """Available OCR observers. A factory raising on unavailable deps is
    fine — the runner records NOT_RUN rather than skipping the row."""
    reg: dict[str, ProviderFactory] = {}

    def _paddle():
        from providers.ocr.paddle import PaddleOCRProvider

        return PaddleOCRProvider()

    reg["paddleocr"] = _paddle

    def _easyocr():
        from providers.ocr.easyocr_adapter import EasyOCRProvider

        return EasyOCRProvider()

    reg["easyocr"] = _easyocr

    def _mock():
        from providers.mock import MockOCRProvider

        return MockOCRProvider()

    reg["mock"] = _mock
    return reg


def run_ocr_benchmark(
    family_ids: Iterable[str],
    provider_names: Optional[list[str]] = None,
    *,
    commit: str = "unknown",
    worker_version: str = "local",
) -> dict[str, Any]:
    """Page-level OCR benchmark over dev-split fixtures with gold
    answers. Returns a run dict (eval.report shape) plus per-item rows."""
    reg = fixtures.load_registry()
    split_hash = splits.registry_hash(reg)
    registry = ocr_provider_registry()
    names = provider_names or list(registry)

    items = [
        f"{fam}::{name}" for fam in family_ids for name in names
    ]
    run = eval_report.new_run(
        commit=commit,
        benchmark_version="restore10b-1",
        split_hash=split_hash,
        provider_config=",".join(names),
        worker_version=worker_version,
        items=items,
        split="dev",
    )
    rows: list[dict[str, Any]] = []
    for fam in family_ids:
        try:
            fdir = fixtures.fixture_path(fam)
        except (PermissionError, KeyError) as exc:
            for name in names:
                eval_report.record(run, f"{fam}::{name}", "NOT_RUN", str(exc))
                rows.append({"family": fam, "provider": name,
                             "status": "NOT_RUN", "detail": str(exc)})
            continue
        expected = gold.load_expected(fdir) if fdir.is_dir() else None
        gold_text = _gold_text(expected) if expected else ""
        pages = gold.damaged_inputs(fdir) if fdir.is_dir() else [fdir]
        for name in names:
            item = f"{fam}::{name}"
            try:
                provider = registry[name]()
            except Exception as exc:  # unavailable dependency → NOT_RUN
                eval_report.record(run, item, "NOT_RUN", f"unavailable: {exc}")
                rows.append({"family": fam, "provider": name,
                             "status": "NOT_RUN", "detail": str(exc)})
                continue
            tracemalloc.start()
            t0 = time.time()
            try:
                texts = []
                for page in pages:
                    cands = provider.recognize_text(page)
                    texts.extend(str(c.value) for c in cands)
                pred = "\n".join(texts)
            except Exception as exc:  # noqa: BLE001
                # unavailable dependency is NOT_RUN, not a quality FAIL
                st = ("NOT_RUN" if "unavailable" in type(exc).__name__.lower()
                      or "unavailable" in str(exc).lower() else "FAIL")
                eval_report.record(run, item, st, str(exc))
                rows.append({"family": fam, "provider": name,
                             "status": st, "detail": str(exc)})
                continue
            finally:
                elapsed = time.time() - t0
                _cur, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
            row = _score_row(fam, name, pred, gold_text, elapsed, peak)
            rows.append(row)
            if row["char_exact"] is None:
                status = "REVIEW"  # no gold — ran but unscored
            else:
                status = "PASS" if row["char_exact"] > 0 else "FAIL"
            eval_report.record(
                run, item, status,
                detail=json.dumps(row, ensure_ascii=False),
            )
            row["status"] = status
    eval_report.finalize(run)
    run["rows"] = rows
    return run


def _gold_text(expected: dict[str, Any]) -> str:
    parts = []
    for q in expected.get("questions", []):
        parts.append(str(q.get("body", "")))
        ch = q.get("choices") or {}
        parts.extend(str(v) for v in ch.values())
        parts.append(str(q.get("points", "")))
    return "\n".join(parts)


def _score_row(fam, name, pred, gold_text, elapsed, peak) -> dict[str, Any]:
    ce = metrics.char_exact(pred, gold_text) if gold_text else None
    matched, total, extra = metrics.critical_token_exact(pred, gold_text)
    return {
        "family": fam,
        "provider": name,
        "status": "PASS",
        "char_exact": ce,
        "critical_matched": matched,
        "critical_total": total,
        "critical_exact_rate": (matched / total) if total else None,
        "source_hallucination": extra,
        "elapsed_s": round(elapsed, 3),
        "peak_bytes": peak,
    }


def write_run(run: dict, out_dir: Path) -> tuple[Path, Path]:
    """Persist JSONL rows + run record."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rid = f"{int(time.time())}"
    rows_path = out_dir / f"bench_{rid}.jsonl"
    with rows_path.open("w", encoding="utf-8") as fh:
        for row in run.get("rows", []):
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    run_path = out_dir / f"run_{rid}.json"
    run_path.write_text(
        json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return rows_path, run_path
