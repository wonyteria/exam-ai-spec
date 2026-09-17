from __future__ import annotations

from document.models import Answer, LogicFlag, Solution, TextSpan
from ..context import PipelineContext


def run(ctx: PipelineContext) -> None:
    """Solve each question to prove the restored problem is well-formed.

    Every question is solved twice; the answers must agree or the question
    is flagged ambiguous_answer instead of trusting a single solve.
    """
    solved = 0
    attempted = 0
    for question in ctx.document.questions:
        if not (question.body or question.equations or question.figures):
            continue
        attempted += 1
        problem = _problem(question)
        answers: list[object] = []
        steps: list[str] = []
        for solver in ctx.providers.solver:
            for _ in range(2):
                cand = solver.solve(problem)
                if cand.value.get("solved"):
                    answers.append(cand.value.get("answer"))
                    steps = cand.value.get("steps") or steps

        if not answers:
            question.verification.logic_flags.append(
                LogicFlag(kind="unsolvable_question", detail="solver가 정답을 확정하지 못함")
            )
            continue

        unique = {repr(a) for a in answers}
        if len(unique) > 1:
            question.verification.logic_flags.append(
                LogicFlag(kind="ambiguous_answer", detail=f"풀이 결과 불일치: {answers}")
            )
            continue

        normalized, matched = _normalize_answer(answers[0], question)
        question.answer = Answer(value=normalized)
        if steps:
            question.solution = Solution(steps=[TextSpan(text=str(s)) for s in steps])
        if not matched:
            question.verification.logic_flags.append(
                LogicFlag(
                    kind="ambiguous_answer",
                    detail=f"정답 {normalized!r}이 선택지와 일치하지 않음",
                )
            )
            continue
        solved += 1

    ctx.emit("solving", f"{solved}/{attempted} 문항 풀이 완료")


def _problem(question) -> dict:
    return {
        "number": question.number,
        "type": question.type.value,
        "body": [span.text for span in question.body],
        "equations": [eq.latex for eq in question.equations],
        "choices": {
            c.label: " ".join(s.text for s in c.body) for c in question.choices
        },
        "figures": [f.topology.get("description") for f in question.figures],
    }


def _normalize_answer(raw, question) -> tuple[object, bool]:
    """Match solver output to a choice label or choice text."""
    if not question.choices:
        return raw, True
    for c in question.choices:
        if str(raw).strip() == c.label:
            return c.label, True
        text = " ".join(s.text for s in c.body).strip()
        if text and text == str(raw).strip():
            return c.label, True
    return raw, False
