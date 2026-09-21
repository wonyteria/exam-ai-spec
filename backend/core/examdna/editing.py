"""Natural-language document editing.

A provider turns the user's instruction into structured ops; this module
applies them to the Document with provenance ATUs so the edit trail is
auditable and the ZERO TYPO gate still governs export.
"""
from __future__ import annotations

from typing import Any

from document.models import (
    ATU,
    ATUKind,
    Answer,
    Candidate,
    Choice,
    Document,
    Equation,
    Question,
    QuestionType,
    Solution,
    TextSpan,
    VerificationStatus,
)

_ATU_FIELD = {
    "body": (ATUKind.TEXT_TOKEN, "body"),
    "points": (ATUKind.POINTS, "points"),
    "type": (ATUKind.TEXT_TOKEN, "type"),
    "figure": (ATUKind.TEXT_TOKEN, "figure"),
    "answer": (ATUKind.TEXT_TOKEN, "answer"),
    "solution": (ATUKind.TEXT_TOKEN, "solution"),
}


def summarize(doc: Document) -> list[dict]:
    """Compact per-question view sent to the provider for edit planning."""
    return [
        {
            "question": q.label or str(q.number),
            "type": q.type.value,
            "points": q.points,
            "body": " ".join(s.text for s in q.body),
            "choices": {
                c.label: " ".join(s.text for s in c.body) for c in q.choices
            },
            "equations": [e.latex for e in q.equations],
            "answer": q.answer.value if q.answer else None,
        }
        for q in doc.questions
    ]


def ops_to_change_ops(ops: list[dict]):
    """Translate provider edit-plan ops into canonical ChangeOps (WP06).

    The server re-validates every op: unknown fields/missing targets are
    returned in `skipped` with a reason — they are never silently applied
    or partially merged. The caller applies the surviving set atomically
    through MutationService.apply."""
    from canonical.models import ChangeOp

    change_ops: list[ChangeOp] = []
    skipped: list[dict] = []
    for op in ops:
        target = str(op.get("question") or "").strip()
        field = op.get("field")
        value = op.get("value")
        if not target:
            skipped.append({**op, "reason": "no question target"})
            continue
        if field == "body":
            change_ops.append(
                ChangeOp(op="SetBody", target_id=target, value=value)
            )
        elif field == "choice":
            label = str(op.get("choice") or "")
            if not label:
                skipped.append({**op, "reason": "choice label missing"})
                continue
            change_ops.append(
                ChangeOp(
                    op="SetChoice", target_id=target, field=label, value=value
                )
            )
        elif field == "points":
            change_ops.append(
                ChangeOp(op="SetPoints", target_id=target, value=value)
            )
        elif field == "answer":
            change_ops.append(
                ChangeOp(op="SetAnswer", target_id=target, value=value)
            )
        elif field == "solution":
            change_ops.append(
                ChangeOp(op="SetSolution", target_id=target, value=value)
            )
        elif field == "type":
            change_ops.append(
                ChangeOp(op="SetField", target_id=target, field="type", value=value)
            )
        elif field == "equation":
            change_ops.append(
                ChangeOp(
                    op="SetEquation",
                    target_id=target,
                    field=str(op.get("index", 0)),
                    value=value,
                )
            )
        else:
            skipped.append({**op, "reason": f"unsupported field {field!r}"})
    return change_ops, skipped


def apply_ops(doc: Document, ops: list[dict]) -> dict:
    """Apply structured edit ops; returns applied/skipped lists."""
    applied: list[dict] = []
    skipped: list[dict] = []
    for op in ops:
        question = _find_question(doc, op.get("question"))
        if question is None:
            skipped.append({**op, "reason": "문항을 찾을 수 없음"})
            continue
        try:
            field, value = _apply(question, op)
        except (KeyError, ValueError, TypeError) as exc:
            skipped.append({**op, "reason": str(exc)})
            continue
        applied.append({"question": op.get("question"), "field": field, "value": value})
    if applied:
        doc.version += 1
    return {"applied": applied, "skipped": skipped}


def _find_question(doc: Document, label: Any) -> Question | None:
    target = str(label or "").strip()
    for q in doc.questions:
        if target in (q.label, str(q.number)):
            return q
    return None


def _apply(question: Question, op: dict) -> tuple[str, Any]:
    field = str(op.get("field", ""))
    value = op.get("value")

    if field == "body":
        question.body = [TextSpan(text=str(value))]
    elif field == "choice":
        label = str(op.get("choice", ""))
        choice = next((c for c in question.choices if c.label == label), None)
        if choice is None:
            choice = Choice(label=label)
            question.choices.append(choice)
        choice.body = [TextSpan(text=str(value))]
        _provenance(question, ATUKind.CHOICE, f"choice:{label}", value)
        return f"choice:{label}", value
    elif field == "points":
        value = int(value)
        question.points = value
    elif field == "answer":
        question.answer = Answer(value=value)
    elif field == "solution":
        steps = (
            [str(s) for s in value.get("steps", [])]
            if isinstance(value, dict)
            else [s for s in str(value).splitlines() if s.strip()]
        )
        question.solution = Solution(
            steps=[TextSpan(text=s) for s in steps],
            concepts=(
                [str(c) for c in value.get("concepts", [])]
                if isinstance(value, dict)
                else []
            ),
        )
    elif field == "type":
        value = QuestionType(str(value))
        question.type = value
    elif field == "equation":
        index = int(op.get("index", 0))
        while len(question.equations) <= index:
            question.equations.append(Equation())
        question.equations[index].latex = str(value)
        _provenance(question, ATUKind.MATH_SYMBOL, f"equation:{index}", value)
        return f"equation:{index}", value
    elif field == "figure":
        if question.figures:
            question.figures[0].topology["description"] = str(value)
    else:
        raise ValueError(f"지원하지 않는 필드: {field!r}")

    kind, atu_field = _ATU_FIELD[field]
    _provenance(question, kind, atu_field, value)
    return field, value


def _provenance(question: Question, kind: ATUKind, field: str, value: Any) -> None:
    """Record the human-requested edit as a verified ATU."""
    atu = ATU(
        kind=kind,
        field=field,
        source=question.source,
        status=VerificationStatus.HUMAN_VERIFIED,
        value=value,
    )
    atu.candidates.append(
        Candidate(provider="human-edit", value=value, confidence=1.0, meta={})
    )
    question.atus.append(atu)
