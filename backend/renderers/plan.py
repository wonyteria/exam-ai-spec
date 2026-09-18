"""Common layout plan shared by every renderer (WP07 / REQ-15·16·19).

Renderers never invent layout — they consume a `LayoutPlan` built from
the structural document and are verified against it (픽셀 기반 임의 줄
쌓기 금지). Default objective layout: 2 columns × 2 questions per
column with row pairing; descriptive questions take full width plus a
proportional answer space. Every slot records the source label so a
rendered page traces back to the canonical question.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from document.models import Document, Question

# Output modes (policy `output_mode` values).
OUTPUT_MODES = {
    "STUDENT",                # questions only — answers never exposed
    "STUDENT_WITH_ENDNOTES",  # questions + answers/explanations as endnotes
    "ANSWER_SOLUTION",        # questions + 정답·해설 section
    "TEACHER",                # ANSWER_SOLUTION + verification metadata
}

# Descriptive questions get an answer area proportional to points
# (기본 배점당 행 수 — renderer maps it to ruled space, not pixels).
ANSWER_LINES_PER_POINT = 2
MIN_ANSWER_LINES = 6


@dataclass
class Slot:
    """One question's place in the plan."""

    question_id: str
    number: int
    label: str
    kind: str  # objective | descriptive | shared_child
    column: Optional[int] = None  # 0/1 for objective grid
    row: Optional[int] = None
    answer_lines: int = 0  # >0 for descriptive slots
    source_label: str = ""  # original printed label (provenance)


@dataclass
class EndnoteEntry:
    """Answer + grade-level explanation for one scored unit — emitted as
    an actual endnote object in supporting formats."""

    number: int
    label: str
    question_id: str
    answer: str
    explanation: str


@dataclass
class LayoutPlan:
    output_mode: str
    columns: int
    slots: list[Slot] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)  # row-paired slot question ids
    endnotes: list[EndnoteEntry] = field(default_factory=list)
    title: str = "시험지"
    brand_id: Optional[str] = None


def is_objective(q: Question) -> bool:
    return q.type.value == "multiple_choice" and not q.parent_id


def build_plan(
    doc: Document,
    output_mode: str = "STUDENT_WITH_ENDNOTES",
    title: str = "시험지",
) -> LayoutPlan:
    """Build the layout plan from the canonical document."""
    if output_mode not in OUTPUT_MODES:
        raise ValueError(f"unknown output_mode {output_mode!r}")
    plan = LayoutPlan(
        output_mode=output_mode,
        columns=2,
        title=title,
        brand_id=doc.brand_id,
    )

    questions = sorted(doc.questions, key=lambda q: q.number)
    col, row = 0, 0
    for q in questions:
        if q.parent_id:
            # shared-stem child (e.g. 2-1): full-width, tied to parent
            plan.slots.append(
                Slot(
                    question_id=q.id,
                    number=q.number,
                    label=q.label or str(q.number),
                    kind="shared_child",
                    answer_lines=_answer_lines(q),
                    source_label=q.label or str(q.number),
                )
            )
            continue
        if is_objective(q):
            slot = Slot(
                question_id=q.id,
                number=q.number,
                label=q.label or str(q.number),
                kind="objective",
                column=col,
                row=row,
                source_label=q.label or str(q.number),
            )
            plan.slots.append(slot)
            # 2 questions per column per row: (0,r), (0,r+1) | (1,r), (1,r+1)
            if col == 0:
                plan.rows.append([q.id])
                col = 1
            else:
                plan.rows[-1].append(q.id)
                col = 0
                row += 1
        else:
            plan.slots.append(
                Slot(
                    question_id=q.id,
                    number=q.number,
                    label=q.label or str(q.number),
                    kind="descriptive",
                    answer_lines=_answer_lines(q),
                    source_label=q.label or str(q.number),
                )
            )

    if output_mode in {"STUDENT_WITH_ENDNOTES", "ANSWER_SOLUTION", "TEACHER"}:
        plan.endnotes = collect_endnotes(doc)
    return plan


def _answer_lines(q: Question) -> int:
    if q.points:
        return max(MIN_ANSWER_LINES, q.points * ANSWER_LINES_PER_POINT)
    return MIN_ANSWER_LINES


def collect_endnotes(doc: Document) -> list[EndnoteEntry]:
    """Every scored unit gets an endnote: answer + grade-appropriate
    explanation. Missing answers stay explicit '(미확정)' — coverage is
    complete; the export gate decides whether that's allowed to ship."""
    out: list[EndnoteEntry] = []
    for q in sorted(doc.questions, key=lambda x: x.number):
        if not q.points:
            continue
        answer = (
            str(q.answer.value)
            if q.answer is not None and q.answer.value is not None
            else "(미확정)"
        )
        steps = (
            [s.text for s in q.solution.steps]
            if q.solution is not None
            else []
        )
        out.append(
            EndnoteEntry(
                number=q.number,
                label=q.label or str(q.number),
                question_id=q.id,
                answer=answer,
                explanation=" ".join(steps) if steps else "(풀이 없음)",
            )
        )
    return out


def slot_for(plan: LayoutPlan, question_id: str) -> Optional[Slot]:
    return next((s for s in plan.slots if s.question_id == question_id), None)


def plan_text_invariants(plan: LayoutPlan, doc: Document) -> list[str]:
    """Structural checks renderers must satisfy — used by tests and by
    export verification to compare output against the plan."""
    errors: list[str] = []
    qids = {q.id for q in doc.questions}
    slot_ids = [s.question_id for s in plan.slots]
    if len(slot_ids) != len(set(slot_ids)):
        errors.append("duplicate question in plan")
    missing = qids - set(slot_ids)
    if missing:
        errors.append(f"questions missing from plan: {sorted(missing)}")
    scored = [q for q in doc.questions if q.points]
    if plan.output_mode != "STUDENT":
        covered = {e.question_id for e in plan.endnotes}
        uncovered = [q.number for q in scored if q.id not in covered]
        if uncovered:
            errors.append(f"scored units without endnote: {uncovered}")
    elif plan.endnotes:
        errors.append("STUDENT mode must not carry endnotes")
    if plan.output_mode == "STUDENT":
        for q in doc.questions:
            if is_objective(q) is False and q.points:
                s = slot_for(plan, q.id)
                if s and s.answer_lines <= 0:
                    errors.append(f"descriptive q{q.number} has no answer space")
    return errors
