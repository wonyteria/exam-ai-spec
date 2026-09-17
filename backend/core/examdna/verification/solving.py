from __future__ import annotations

from document.models import Answer, LogicFlag, Solution, TextSpan
from ..context import PipelineContext


def run(ctx: PipelineContext) -> None:
    """Solve each question to prove the restored problem is well-formed."""
    solved = 0
    for question in ctx.document.questions:
        problem = {
            "number": question.number,
            "type": question.type.value,
            "body": [span.text for span in question.body],
            "equations": [eq.latex for eq in question.equations],
            "choices": {
                c.label: " ".join(s.text for s in c.body) for c in question.choices
            },
        }
        for solver in ctx.providers.solver:
            cand = solver.solve(problem)
            if cand.value.get("solved"):
                question.answer = Answer(value=cand.value.get("answer"))
                steps = cand.value.get("steps") or []
                if steps:
                    question.solution = Solution(
                        steps=[TextSpan(text=str(s)) for s in steps]
                    )
                solved += 1
                break
        else:
            question.verification.logic_flags.append(
                LogicFlag(
                    kind="unsolvable_question",
                    detail="solver가 정답을 확정하지 못함",
                )
            )
    ctx.emit("solving", f"{solved}/{len(ctx.document.questions)} 문항 풀이 완료")
