from __future__ import annotations

from document.models import LogicFlag, Question


def verify_question(question: Question) -> list[LogicFlag]:
    """MathGuard + QuestionLogic Guard hooks.

    Skeleton: structural checks only — a multiple-choice question needs
    choices, a question needs some content. Curriculum/symbol rules from
    guides/mathematics/*.md plug in here.
    """
    flags: list[LogicFlag] = []
    if not question.body and not question.equations and not question.figures:
        flags.append(
            LogicFlag(kind="missing_condition", detail="문항 본문이 비어 있음")
        )
    if question.type.value == "multiple_choice" and not question.choices:
        flags.append(
            LogicFlag(kind="missing_condition", detail="객관식인데 선택지가 없음")
        )
    return flags
