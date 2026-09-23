"""Question-scoped natural-language edit parsing.

Every instruction is scoped to ONE target question (the API resolves the
target first). A number mentioned in the instruction must match that
question — "11번 …" sent to question 5 is rejected as ambiguous, never
applied to the whole document.

Supported intents:
  - choice body edit      "①번 보기를 -35로 수정해"
  - body replace          "본문을 …로 수정해"
  - body rewrite (LLM)    "문장만 자연스럽게 정리해"
                        "DC 길이를 묻는 문장으로 정리해"
  - points                "배점을 5점으로 수정해"
  - answer                "정답을 3번으로 수정해"
  - equation              "수식을 x^2+1로 수정해" (index 0)
  - figure label          "이 도형의 오른쪽 길이를 10cm로 수정해"
  - confirm               "이 문항 확인 완료"

`rewrite` intents are returned to the caller — generating the new text is
the API layer's job (local model only).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from canonical.models import ChangeOp
from document.models import Question, QuestionStatus

_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"
# "N번" is a question reference only when NOT immediately followed by
# 으로/로 — "정답을 3번으로" makes 3번 a value, "11번 ①번을" makes 11번
# the question.
_NUM_RE = r"(\d+)(?:-(\d+))?\s*번(?!\s*(?:으로|로))"


@dataclass
class QuestionEditPlan:
    recognized: bool
    ops: list[ChangeOp] = field(default_factory=list)
    rewrite: Optional[dict] = None       # {"field": "body", "hint": str}
    explanation: str = ""
    needs_clarification: bool = False


def _target_mismatch(question: Question, instruction: str) -> Optional[str]:
    """If the instruction names a question, it must be this one — a
    mismatch is ambiguity, not an edit of a different question."""
    m = re.search(_NUM_RE, instruction)
    if not m:
        return None
    wanted = m.group(1) + ("-" + m.group(2) if m.group(2) else "")
    label = (question.label or str(question.number)).strip()
    if wanted != label and wanted != str(question.number):
        return (
            f"지시가 {wanted}번 문항을 가리키지만 대상은 "
            f"{label}번 문항입니다. 대상 문항을 확인해 주세요."
        )
    return None


def _choice_label(question: Question, instruction: str) -> Optional[str]:
    """① / 1번 / '첫번째' style choice references inside an instruction
    that is already question-scoped."""
    m = re.search(rf"([{_CIRCLED}])번?\s*(?:보기|선택지)?", instruction)
    if m:
        return m.group(1)
    m = re.search(r"(?<!\d)(\d{1,2})\s*번\s*(?:보기|선택지)", instruction)
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(_CIRCLED):
            return _CIRCLED[idx]
    return None


def parse_question_edit(question: Question, instruction: str) -> QuestionEditPlan:
    text = (instruction or "").strip()
    if not text:
        return QuestionEditPlan(False, explanation="지시가 비어 있습니다.")

    mismatch = _target_mismatch(question, text)
    if mismatch:
        return QuestionEditPlan(
            False, explanation=mismatch, needs_clarification=True)

    target = question.id

    if re.search(r"확인 완료|확정|문제\s*없", text):
        return QuestionEditPlan(
            True,
            ops=[ChangeOp(op="SetQuestionStatus", target_id=target,
                          value=QuestionStatus.USER_CONFIRMED.value)],
            explanation="문항을 확정합니다.",
        )

    # choice edit: "①번 보기를 X로", "⑤번을 9cm, 10cm, 15cm로"
    m = re.search(
        rf"([{_CIRCLED}]|\d{{1,2}})\s*번?\s*(?:보기|선택지)?(?:을|를)\s*"
        r"(.+?)(?:으로|로)\s*(?:수정|바꿔|고쳐|변경|해줘|해주세요|해|줘|주세요)*\s*$",
        text,
    )
    if m and ("보기" in text or "선택지" in text
              or m.group(1) in _CIRCLED or re.search(r"\d번", text)):
        raw = m.group(1)
        if raw in _CIRCLED:
            label = raw
        else:
            idx = int(raw) - 1
            label = _CIRCLED[idx] if 0 <= idx < len(_CIRCLED) else None
        if label is None:
            return QuestionEditPlan(
                False, explanation=f"선택지 번호 {raw}를 해석할 수 없습니다.",
                needs_clarification=True)
        value = m.group(2).strip().strip("\"'")
        return QuestionEditPlan(
            True,
            ops=[ChangeOp(op="SetChoice", target_id=target, field=label,
                          value=value)],
            explanation=f"{label}번 선택지를 '{value}'로 수정합니다.",
        )

    m = re.search(r"배점(?:을|를)?\s*(\d+)\s*점?", text)
    if m:
        return QuestionEditPlan(
            True,
            ops=[ChangeOp(op="SetPoints", target_id=target,
                          value=int(m.group(1)))],
            explanation=f"배점을 {m.group(1)}점으로 수정합니다.",
        )

    m = re.search(r"정답(?:을|를)?\s*(.+?)(?:으로|로)\s*(?:수정|바꿔|고쳐|변경|해줘|해주세요|해|줘|주세요)*\s*$", text)
    if m:
        value = m.group(1).strip().strip("\"'")
        return QuestionEditPlan(
            True,
            ops=[ChangeOp(op="SetAnswer", target_id=target, value=value)],
            explanation=f"정답을 '{value}'로 수정합니다.",
        )

    # figure label edit: "도형의 오른쪽 길이를 10cm로"
    m = re.search(
        r"도형.{0,12}?([가-힣A-Za-z]{1,8})\s*(?:길이|각도|라벨)(?:을|를)?\s*"
        r"(.+?)(?:으로|로)\s*(?:수정|바꿔|고쳐|변경|해줘|해주세요|해|줘|주세요)*\s*$",
        text,
    )
    if m:
        name, value = m.group(1), m.group(2).strip().strip("\"'")
        return QuestionEditPlan(
            True,
            ops=[ChangeOp(op="SetField", target_id=target,
                          field="figure_label",
                          value={"name": name, "label": value})],
            explanation=f"도형 '{name}' 표기를 '{value}'로 수정합니다.",
        )

    m = re.search(r"수식(?:을|를)?\s*(.+?)(?:으로|로)\s*(?:수정|바꿔|고쳐|변경|해줘|해주세요|해|줘|주세요)*\s*$", text)
    if m:
        value = m.group(1).strip().strip("\"'")
        return QuestionEditPlan(
            True,
            ops=[ChangeOp(op="SetEquation", target_id=target, field="0",
                          value=value)],
            explanation="수식을 수정합니다.",
        )

    # body replace: "본문을 X로 수정해"
    m = re.search(r"본문(?:을|를)?\s*(.+?)(?:으로|로)\s*(?:수정|바꿔|고쳐|변경|해줘|해주세요|해|줘|주세요)*\s*$", text)
    if m:
        value = m.group(1).strip().strip("\"'")
        return QuestionEditPlan(
            True,
            ops=[ChangeOp(op="SetBody", target_id=target, value=value)],
            explanation="본문을 수정합니다.",
        )

    # body rewrite (needs the local model): "문장만 자연스럽게 정리해",
    # "DC 길이를 묻는 문장으로 정리해"
    if re.search(r"정리|다듬|자연스럽|고쳐\s*줘|매끄럽", text):
        return QuestionEditPlan(
            True,
            rewrite={"field": "body", "hint": text},
            explanation="본문을 자연스럽게 정리합니다 (로컬 모델).",
        )

    return QuestionEditPlan(
        False,
        explanation="지시를 해석할 수 없습니다. 예: '①번 보기를 -35로 수정해'",
        needs_clarification=True,
    )
