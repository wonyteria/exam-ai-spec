"""DOCX renderer (RESTORE-22) — python-docx (MIT).

Mirrors the HWPX plan: same LayoutPlan slots, choices, equations,
answer space, and endnote answers — so a DOCX export carries the same
verified content as the HWPX artifact.
"""
from __future__ import annotations

import io

from docx import Document as DocxDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH

from renderers.brand import get_brand
from renderers.plan import LayoutPlan, build_plan


def render_docx(
    document,
    title: str = "시험지",
    output_mode: str = "STUDENT_WITH_ENDNOTES",
    brand_id: str | None = None,
) -> bytes:
    plan = build_plan(document, output_mode=output_mode, title=title)
    brand = get_brand(brand_id or document.brand_id)

    out = DocxDocument()
    head = out.add_paragraph()
    head.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = head.add_run(brand.header_text or plan.title)
    run.bold = True
    run.font.size = None

    q_by_id = {q.id: q for q in document.questions}
    endnotes = {e.question_id: (i + 1, e) for i, e in enumerate(plan.endnotes)}
    for slot in plan.slots:
        q = q_by_id[slot.question_id]
        _question(out, q, slot, endnotes.get(q.id))

    if plan.output_mode in {"ANSWER_SOLUTION", "TEACHER"}:
        _solutions(out, plan)
    if plan.output_mode == "TEACHER":
        _teacher_meta(out, document)

    buf = io.BytesIO()
    out.save(buf)
    return buf.getvalue()


def _question(out: DocxDocument, q, slot, endnote) -> None:
    body = " ".join(s.text for s in q.body).strip()
    head = f"{slot.label}. {body}"
    if q.points:
        head += f"  [{q.points:g}점]"
    p = out.add_paragraph(head)
    p.runs[0].bold = True
    for eq in q.equations:
        script = eq.latex or eq.hwp_formula or ""
        if script:
            out.add_paragraph("  " + script)
    for ch in q.choices:
        text = " ".join(s.text for s in ch.body).strip()
        out.add_paragraph(f"  {ch.label} {text}")
    for _ in range(slot.answer_lines):
        out.add_paragraph("  ______________________________")
    if endnote:
        _, entry = endnote
        out.add_paragraph(f"  ※ 정답은 미주 {entry.number}번 참조")


def _solutions(out: DocxDocument, plan: LayoutPlan) -> None:
    p = out.add_paragraph("정답 및 해설")
    p.runs[0].bold = True
    for entry in plan.endnotes:
        text = f"[미주 {entry.number}] {entry.label}번 정답: {entry.answer}"
        if entry.explanation:
            text += f" — {entry.explanation}"
        out.add_paragraph(text)


def _teacher_meta(out: DocxDocument, document) -> None:
    for q in document.questions:
        meta = q.meta or {}
        parts = [
            f"문항 {q.number}",
            f"유형={q.type.value}",
        ]
        if getattr(q, "curriculum", None) and q.curriculum.grade:
            parts.append(f"학년={q.curriculum.grade}")
        if meta.get("difficulty") is not None:
            parts.append(f"난이도={meta['difficulty']}")
        if getattr(q, "source", None) is not None:
            parts.append(f"출처페이지={q.source.page}")
        out.add_paragraph("  ".join(parts))
