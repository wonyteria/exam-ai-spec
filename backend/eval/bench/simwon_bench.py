"""심원중 샘플 question-centric restoration benchmark.

Runs the recognition slice of the pipeline on the 5 sample images and
measures question-granularity results:

  - question_number_recall : recognized numbered questions / expected (31)
  - status distribution    : AUTO_RESTORED / AUTO_CORRECTED /
                             NEEDS_USER_REVIEW / BLOCKED counts
  - auto_restored_ratio    : (AUTO_RESTORED + AUTO_CORRECTED) / total
  - review_ratio           : NEEDS_USER_REVIEW / total
  - wrongly_finalized      : AUTO_* questions flagged by the gate
  - per-stage / per-question / total timing
  - field accuracy         : body/choice/critical-token vs expected.json
                             (dev-only gold; the HWP is never a runtime
                             input — expected.json is a transcription)

    .venv/bin/python -m eval.bench.simwon_bench [--images DIR] [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

from core.examdna.context import PipelineContext, Providers
from core.examdna.executor import run_stages
from core.examdna.pipeline import STAGES
from document.models import Document, QuestionStatus
from document.restoration import refresh_document_status
from jobs.models import Job
from jobs.store import Store

SAMPLES = (
    Path(__file__).resolve().parents[3]
    / "samples" / "심원중 샘플"
)
EXPECTED_QUESTIONS = 31
# Rendering/export/gate are artifact stages — the bench measures the
# restoration slice only.
BENCH_STAGES = {
    "capability_preflight", "preprocessing", "source_integrity",
    "student_trace", "print_layer", "reconstruction", "segmentation",
    "recognition", "source_verification", "constraint_correction",
    "logic_verification", "solving", "question_status",
}


def _providers() -> Providers:
    """Operational provider chain; local LLM only when the env opts in.
    No external API is ever used for real exam images — the local
    provider URL guard refuses non-local base URLs anyway."""
    import os

    if os.environ.get("EXAMDNA_ENABLE_LOCAL_LLM") != "1":
        return Providers()
    try:
        from jobs.runner import default_providers

        return default_providers()
    except Exception:
        return Providers()


def _ctx(workdir: Path, store: Store) -> PipelineContext:
    job = Job(id="bench_simwon", document_id="bench_simwon")
    return PipelineContext(
        document=Document(), job=job, store=store, workdir=workdir,
        providers=_providers(), event_sink=lambda *a: None,
    )


def run(images_dir: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    workdir = out_dir / "work"
    uploads = workdir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    store = Store(out_dir / "store")
    for img in sorted(images_dir.glob("*.jpg")):
        shutil.copy(img, uploads / img.name)

    ctx = _ctx(workdir, store)
    stage_times: dict[str, float] = {}
    stage_status: dict[str, str] = {}
    t0 = time.time()

    contracts = [s for s in STAGES if s.name in BENCH_STAGES]
    from core.examdna import executor as _ex

    orig = _ex.STAGES
    _ex.STAGES = contracts
    try:
        records = run_stages(ctx)
    finally:
        _ex.STAGES = orig
    total_s = time.time() - t0
    for rec in records:
        stage_status[rec.name] = rec.status.value
        stage_times[rec.name] = getattr(rec, "duration_s", None) or 0.0

    doc = ctx.document
    # The gate stage is out of scope for this bench — mark the doc as
    # reviewed-but-not-final so restoration_status derives honestly.
    if doc.verification.status == "IN_PROGRESS":
        doc.verification.status = "NEEDS_REVIEW"
    refresh_document_status(doc)

    questions = []
    atu_status_counts: dict[str, int] = {}
    for q in doc.questions:
        q_atu: dict[str, int] = {}
        for a in q.atus:
            key = a.status.value
            q_atu[key] = q_atu.get(key, 0) + 1
            atu_status_counts[key] = atu_status_counts.get(key, 0) + 1
        questions.append({
            "id": q.id,
            "number": q.number,
            "label": q.label,
            "status": q.restoration.status.value,
            "confidence": q.restoration.confidence,
            "issues": len(q.restoration.issues),
            "corrections": [c.rule for c in q.restoration.corrections],
            "atu_status": q_atu,
        })

    counts: dict[str, int] = {}
    for q in questions:
        counts[q["status"]] = counts.get(q["status"], 0) + 1

    numeric = sum(
        1 for q in questions
        if (q["label"] or "").isdigit()
        or (q["label"] or "").count("-") == 1
        or (q["label"] or "").startswith("논술형")
    )
    auto = counts.get("AUTO_RESTORED", 0) + counts.get("AUTO_CORRECTED", 0)
    total_q = len(questions)
    n = max(total_q, 1)

    # Optional gold comparison (expected.json next to the images —
    # development/evaluation only, never a runtime input).
    field_accuracy = None
    unmatched: list[dict] = []
    gold_path = images_dir / "expected.json"
    if gold_path.exists():
        from eval.bench.metrics import question_metrics

        gold = {str(g.get("number")): g
                for g in json.loads(gold_path.read_text())["questions"]}
        rows = []
        for q in doc.questions:
            g = gold.get(str(q.label))
            pred = {
                "body": " ".join(s.text for s in q.body),
                "choices": {
                    c.label: " ".join(s.text for s in c.body)
                    for c in q.choices
                },
                "points": q.points,
                "answer": q.answer.value if q.answer else None,
                "figure_text": " ".join(
                    [str(f.topology) + " "
                     + (f.scene.model_dump_json() if f.scene else "")
                     for f in q.figures]
                    + [str(c.value)
                       for a in q.atus
                       if a.field == "figure"
                       or str(a.field or "").startswith("equation:")
                       for c in a.candidates]
                ),
            }
            row = question_metrics(pred, g) if g else {
                "number": q.label, "note": "no gold entry",
            }
            row["_pred"] = pred
            row["_gold"] = g
            row["_status"] = q.restoration.status.value
            row["_issues"] = [
                f"{i.field}:{i.reason}" for i in q.restoration.issues
            ]
            if g:
                rows.append(row)
            else:
                unmatched.append(row)
        if rows:
            def _avg(key):
                vals = [r[key] for r in rows if r[key] is not None]
                return sum(vals) / len(vals) if vals else None

            def _frac(key):
                vals = [r[key] for r in rows if r[key] is not None]
                return (
                    sum(1 for v in vals if v) / len(vals) if vals else None
                )

            field_accuracy = {
                "matched_questions": len(rows),
                "unmatched_questions": [
                    r["number"] for r in unmatched
                ],
                "_unmatched_rows": unmatched,
                "body_exact_avg": _avg("body_exact"),
                "choice_exact_avg": _avg("choice_exact"),
                "points_accuracy": _frac("points_match"),
                "answer_accuracy": _frac("answer_match"),
                "figure_label_recall_avg": _avg("figure_label_recall"),
                "critical_token_recall": (
                    sum(r["critical_matched"] for r in rows)
                    / max(1, sum(r["critical_total"] for r in rows))
                    if sum(r["critical_total"] for r in rows) else None
                ),
                "per_question": rows,
            }

    return {
        "benchmark": "simwon_question_restoration",
        "images": sorted(p.name for p in images_dir.glob("*.jpg")),
        "expected_questions": EXPECTED_QUESTIONS,
        "recognized_questions": total_q,
        "question_number_recall": numeric / EXPECTED_QUESTIONS,
        "status_counts": counts,
        "auto_restored_ratio": auto / n,
        "review_ratio": counts.get("NEEDS_USER_REVIEW", 0) / n,
        "blocked_ratio": counts.get("BLOCKED", 0) / n,
        "wrongly_auto_finalized": (
            doc.verification.gate.get("unresolved", 0)
            if doc.verification.gate else 0
        ),
        "doc_restoration_status": doc.verification.restoration_status,
        "total_seconds": round(total_s, 2),
        "per_question_seconds": round(total_s / n, 2),
        "stage_seconds": stage_times,
        "stage_status": stage_status,
        "field_accuracy": field_accuracy,
        "atu_status_counts": atu_status_counts,
        "questions": questions,
    }


def write_comparison_report(result: dict, out_path: Path) -> Path:
    """Per-question pred-vs-gold markdown report — the review artifact the
    benchmark directive requires (문항별 비교 리포트)."""
    fa = result.get("field_accuracy") or {}
    rows = fa.get("per_question") or []
    lines = [
        "# 심원중 benchmark — per-question comparison",
        "",
        f"- recall: {result.get('question_number_recall')}",
        f"- recognized: {result.get('recognized_questions')}"
        f" / expected {result.get('expected_questions')}",
        f"- status: {result.get('status_counts')}",
        f"- doc: {result.get('doc_restoration_status')}",
        f"- body_exact_avg: {fa.get('body_exact_avg')}",
        f"- choice_exact_avg: {fa.get('choice_exact_avg')}",
        f"- points_accuracy: {fa.get('points_accuracy')}",
        f"- answer_accuracy: {fa.get('answer_accuracy')}",
        f"- figure_label_recall_avg: {fa.get('figure_label_recall_avg')}",
        f"- critical_token_recall: {fa.get('critical_token_recall')}",
        f"- unmatched pred questions: {fa.get('unmatched_questions')}",
        "",
    ]
    for r in rows:
        pred, gold = r.get("_pred") or {}, r.get("_gold") or {}
        lines.append(f"## Q{r.get('number')} [{r.get('_status')}]")
        scores = {
            k: r.get(k) for k in (
                "body_exact", "choice_exact", "points_match",
                "answer_match", "figure_label_recall",
            )
        }
        lines.append(f"- scores: {scores}")
        lines.append(
            f"- critical: {r.get('critical_matched')}/"
            f"{r.get('critical_total')} "
            f"(+{r.get('critical_extra')} extra)"
        )
        issues = r.get("_issues") or []
        if issues:
            lines.append(f"- issues: {', '.join(issues)}")
        lines.append(f"- GOLD body: {gold.get('body', '')}")
        lines.append(f"- PRED body: {pred.get('body', '')}")
        if gold.get("choices"):
            lines.append(f"- GOLD choices: {gold['choices']}")
            lines.append(f"- PRED choices: {pred.get('choices', {})}")
        if gold.get("figure_labels"):
            lines.append(f"- GOLD fig: {gold['figure_labels']}")
            lines.append(
                f"- PRED fig: {pred.get('figure_text', '')[:200]}"
            )
        lines.append("")
    unmatched_rows = fa.get("_unmatched_rows") or []
    for r in unmatched_rows:
        pred = r.get("_pred") or {}
        lines.append(f"## {r.get('number')} [UNMATCHED — no gold entry]")
        lines.append(f"- PRED body: {pred.get('body', '')[:300]}")
        lines.append("")
    report = out_path.parent / "comparison_report.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", type=Path, default=SAMPLES)
    ap.add_argument(
        "--out", type=Path,
        default=Path(__file__).resolve().parent / "out" / "simwon",
    )
    args = ap.parse_args()
    result = run(args.images, args.out)
    out_path = args.out / "simwon_bench.json"
    report_path = write_comparison_report(result, out_path)
    # strip embedded pred/gold payloads from the JSON summary (they live in
    # the markdown report)
    fa = result.get("field_accuracy") or {}
    for r in fa.get("per_question") or []:
        r.pop("_pred", None)
        r.pop("_gold", None)
        r.pop("_status", None)
        r.pop("_issues", None)
    fa.pop("_unmatched_rows", None)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(
        {k: v for k, v in result.items() if k != "questions"},
        ensure_ascii=False, indent=2,
    ))
    print(f"\n-> {out_path}")


if __name__ == "__main__":
    main()
