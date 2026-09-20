from __future__ import annotations

from document.models import LogicFlag, Question


def verify_question(question: Question) -> list[LogicFlag]:
    """MathGuard + QuestionLogic Guard (RESTORE-15 ProblemDNA).

    Structural checks plus deterministic semantic contradictions:
    - a question needs some content
    - multiple choice needs >=2 *distinct* choices — two choice bodies
      proven symbolically equivalent (SymPy) are a logic conflict, not
      a formatting quirk
    - a nonpositive score is a contradiction
    """
    flags: list[LogicFlag] = []
    if not question.body and not question.equations and not question.figures:
        flags.append(
            LogicFlag(kind="missing_condition", detail="문항 본문이 비어 있음")
        )
    if question.type.value == "multiple_choice":
        if len(question.choices) < 2:
            flags.append(
                LogicFlag(
                    kind="missing_condition",
                    detail="객관식인데 선택지가 2개 미만",
                )
            )
        else:
            dup = _duplicate_choices(question)
            if dup:
                flags.append(
                    LogicFlag(
                        kind="logic_conflict",
                        detail=f"선택지 기호 등가 중복: {', '.join(dup)}",
                    )
                )
    if question.points is not None and question.points <= 0:
        flags.append(
            LogicFlag(
                kind="logic_conflict",
                detail=f"배점이 0 이하: {question.points}",
            )
        )
    return flags


def _duplicate_choices(question: Question) -> list[str]:
    """Pairs of choice labels whose bodies are proven symbolically equal.
    Only MATCH counts — UNKNOWN keeps the choice pair unflagged."""
    from core.examdna.math.checker import MathVerdict, equivalent

    bodies = [
        (c.label, " ".join(s.text for s in c.body).strip())
        for c in question.choices
    ]
    dup: list[str] = []
    for i in range(len(bodies)):
        for j in range(i + 1, len(bodies)):
            la, ta = bodies[i]
            lb, tb = bodies[j]
            if not ta or not tb:
                continue
            if ta == tb or equivalent(ta, tb) is MathVerdict.MATCH:
                dup.append(f"{la}≡{lb}")
    return dup
