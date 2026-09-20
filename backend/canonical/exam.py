"""RESTORE-19 — Canonical Exam format (spec §27).

The canonical serialization every exporter reads — HWP/PDF/DOCX are
render targets, never the truth. Shape per spec:

  Exam:     exam_id, school, grade, semester, year, exam_type,
            subject, pages, questions, layout, source, revision,
            verification
  Question: question_id, number, type, stem, conditions, choices,
            math_objects, figure_graphs, problem_graph, score,
            answer_space, answer, solution, source_evidence,
            verification, question_dna

Deterministic: same Document + revision -> same digest.
"""
from __future__ import annotations

from typing import Any, Optional

from document.models import Document
from .models import canonical_json, sha256_json


def _spans(spans) -> str:
    return " ".join(s.text for s in spans).strip()


def _question_exam(q) -> dict[str, Any]:
    stem = _spans(q.body)
    conditions = []
    if q.problem_graph:
        conditions = list(q.problem_graph.get("conditions", []))
    return {
        "question_id": q.id,
        "number": q.number,
        "label": q.label or str(q.number),
        "type": q.type.value,
        "stem": stem,
        "conditions": conditions,
        "choices": [
            {"label": c.label, "body": _spans(c.body)} for c in q.choices
        ],
        "math_objects": [
            {"id": e.id, "latex": e.latex, "hwp_formula": e.hwp_formula}
            for e in q.equations
        ],
        "figure_graphs": [
            f.scene.model_dump() if f.scene else f.topology
            for f in q.figures
        ],
        "problem_graph": q.problem_graph,
        "score": q.points,
        "answer_space": getattr(q, "answer_space_lines", None),
        "answer": q.answer.value if q.answer else None,
        "solution": (
            [s.text for s in q.solution.steps] if q.solution else []
        ),
        "solution_concepts": (
            list(q.solution.concepts) if q.solution else []
        ),
        "source_evidence": (
            {"page": q.source.page, "bbox": q.source.bbox.model_dump() if q.source.bbox else None}
            if q.source
            else None
        ),
        "verification": q.verification.model_dump(),
        "question_dna": q.question_dna,
    }


def build_canonical_exam(
    doc: Document,
    revision: Optional[str] = None,
    layout: Optional[dict] = None,
) -> dict[str, Any]:
    """Serialize a Document into the spec-shaped Canonical Exam."""
    meta = doc.metadata
    exam = {
        "exam_id": doc.id,
        "school": meta.school,
        "grade": meta.grade,
        "semester": meta.semester,
        "year": meta.year,
        "exam_type": meta.exam_type,
        "subject": meta.subject,
        "pages": [
            {
                "index": p.index,
                "page_role": p.page_role,
                "sha256": p.sha256,
                "source_asset_id": p.source_asset_id,
                "source_page_id": p.source_page_id,
            }
            for p in doc.pages
        ],
        "questions": [_question_exam(q) for q in sorted(
            doc.questions, key=lambda x: (x.number, x.label or "")
        )],
        "layout": layout or {},
        "source": {
            "page_count": len(doc.pages),
            "asset_ids": sorted(
                {p.source_asset_id for p in doc.pages if p.source_asset_id}
            ),
        },
        "revision": revision,
        "verification": doc.verification.model_dump(),
        "tenant_id": doc.tenant_id,
        "brand_id": doc.brand_id,
        "version": doc.version,
    }
    exam["digest"] = canonical_exam_digest(exam)
    return exam


def canonical_exam_digest(exam: dict[str, Any]) -> str:
    """Digest over content only — revision/digest fields excluded so the
    same content yields the same digest across re-serialization."""
    payload = {
        k: v for k, v in exam.items() if k not in {"digest", "revision"}
    }
    return sha256_json(payload)


def canonical_exam_json(exam: dict[str, Any]) -> str:
    return canonical_json(exam)
