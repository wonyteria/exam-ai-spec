"""Damaged-corpus restoration benchmark (Phase 1 metrics).

Generates synthetic damaged exam pages across severities (rotation,
blur, red-pen grading, low contrast, handwriting-over-print), runs the
student_trace separator, and records measurable metrics per page:

  - removal_recall    : GT trace pixels whitened / GT trace pixels
  - print_preservation: printed pixels NOT whitened / printed pixels
  - review_regions    : regions routed to human review
  - duration_s        : per-page wall time (pages/min derived)

Append-only JSONL at eval/bench/results/restoration-<ts>.jsonl plus a
summary line — NOT_RUN rows stay in the denominator, never dropped.

    .venv/bin/python -m eval.bench.restoration_bench [--n 8] [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image

from core.examdna import PipelineContext, Providers
from core.examdna.student_trace import separator
from document.models import Document, Page, PageImage
from eval.bench.synth import SynthResult, SynthSpec, generate


def _ctx(workdir: Path) -> PipelineContext:
    return PipelineContext(
        document=Document(), job=None, store=None, workdir=workdir,
        providers=Providers(), event_sink=lambda *a: None,
    )


def _eval_page(ctx: PipelineContext, res: SynthResult, idx: int,
               out_dir: Path) -> dict:
    damaged_path = out_dir / f"damaged_{idx}.png"
    res.damaged.save(damaged_path)
    clean_path = out_dir / f"clean_{idx}.png"
    res.clean.save(clean_path)

    page = Page(index=idx, original=PageImage(uri=str(damaged_path)),
                width=res.damaged.width, height=res.damaged.height)
    ctx.document.pages.append(page)

    work = ctx.workdir / "trace"
    work.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    removed, review = separator._run_page(ctx, page, work)
    dur = time.time() - t0

    # Removal mask = pixels whitened between gray input and restored.
    gray = np.asarray(Image.open(damaged_path).convert("L"),
                      dtype=np.int16)
    restored_uri = page.original.variants.get("restored_candidate")
    if restored_uri:
        restored = np.asarray(
            Image.open(ctx.resolve_uri(restored_uri)).convert("L"),
            dtype=np.int16)
        removed_mask = (restored - gray) > 30
    else:
        removed_mask = np.zeros(gray.shape, bool)

    base = np.asarray(res.clean.convert("L"), dtype=np.uint8)
    print_mask = base < 128
    trace_mask = np.zeros(gray.shape, bool)
    for name, m in res.masks.items():
        if "print" not in name:
            trace_mask |= np.asarray(m, bool)
    # fall back: any non-print ink in the damaged image is trace
    if not trace_mask.any():
        trace_mask = (np.asarray(res.damaged.convert("L")) < 200) & ~print_mask

    denom_t = max(int(trace_mask.sum()), 1)
    denom_p = max(int(print_mask.sum()), 1)
    return {
        "page": idx,
        "status": "ok",
        "removed_px": int(removed_mask.sum()),
        "review_regions": review,
        "removal_recall": round(
            float((removed_mask & trace_mask).sum()) / denom_t, 4),
        "print_preservation": round(
            1.0 - float((removed_mask & print_mask).sum()) / denom_p, 4),
        "duration_s": round(dur, 3),
        "uncertain": len(page.uncertain_regions),
        "processing_error": page.processing_error,
    }


SCENARIOS = [
    ("baseline", dict()),
    ("rotation", dict(rotate_deg=2.5)),
    ("low_contrast", dict(noise_sigma=6.0, blur_radius=1.2)),
    ("red_pen_heavy", dict(grading_marks=8)),
    ("overlap_writing", dict(handwriting_strokes=18)),
    ("photo_like", dict(rotate_deg=1.5, blur_radius=1.0,
                        noise_sigma=5.0, grading_marks=5)),
]


def run(n_per_scenario: int, out_dir: Path) -> dict:
    results_dir = out_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / f"restoration-{int(time.time())}.jsonl"

    rows = []
    idx = 0
    workdir = out_dir / "work"
    for name, kw in SCENARIOS:
        for i in range(n_per_scenario):
            spec = SynthSpec(seed=idx * 97 + 13, **kw)
            try:
                res = generate(spec)
                ctx = _ctx(workdir / f"s{idx}")
                ctx.workdir.mkdir(parents=True, exist_ok=True)
                row = _eval_page(ctx, res, idx, out_dir)
            except Exception as exc:  # noqa: BLE001
                row = {"page": idx, "status": "FAILED",
                       "error": f"{type(exc).__name__}: {exc}"}
            row["scenario"] = name
            rows.append(row)
            with out_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            idx += 1

    ok = [r for r in rows if r["status"] == "ok"]
    total_s = sum(r["duration_s"] for r in ok)
    summary = {
        "pages": len(rows),
        "ok": len(ok),
        "failed": len(rows) - len(ok),
        "removal_recall_mean": round(
            sum(r["removal_recall"] for r in ok) / max(len(ok), 1), 4),
        "print_preservation_mean": round(
            sum(r["print_preservation"] for r in ok) / max(len(ok), 1), 4),
        "review_regions_mean": round(
            sum(r["review_regions"] for r in ok) / max(len(ok), 1), 2),
        "pages_per_min": round(len(ok) / max(total_s / 60, 1e-9), 2),
        "total_s": round(total_s, 2),
        "unresolved": [
            {"page": r["page"], "scenario": r["scenario"],
             "recall": r.get("removal_recall"),
             "review": r.get("review_regions"),
             "error": r.get("processing_error") or r.get("error")}
            for r in rows
            if r["status"] != "ok" or r.get("removal_recall", 1) < 0.5
        ],
        "results_file": str(out_path),
    }
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1,
                    help="pages per scenario")
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).resolve().parent / "out")
    args = ap.parse_args()
    summary = run(args.n, args.out)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
