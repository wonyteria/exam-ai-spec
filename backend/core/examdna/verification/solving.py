from __future__ import annotations

from document.models import Answer, LogicFlag, Solution, TextSpan
from ..context import PipelineContext


def run(ctx: PipelineContext) -> None:
    """Solve each question to prove the restored problem is well-formed.

    Batched: all problems go to solve_batch in two consensus runs; questions
    absent from the batch response fall back to per-question solves. Answers
    must agree or the question is flagged ambiguous_answer.
    """
    stem_ids = {q.parent_id for q in ctx.document.questions if q.parent_id}
    targets = [
        q
        for q in ctx.document.questions
        if q.id not in stem_ids and (q.body or q.equations or q.figures)
    ]
    problems = {q.id: _problem(q, ctx.document) for q in targets}

    # run -> question id -> result dict
    runs: list[dict[str, dict]] = []
    for run_i in range(2):
        results: dict[str, dict] = {}
        for solver in ctx.providers.solver:
            if hasattr(solver, "solve_batch"):
                for cand in _solve_batch(solver, list(problems.values()), run_i):
                    for item in cand.value if isinstance(cand.value, list) else []:
                        if isinstance(item, dict):
                            results.setdefault(_result_key(item, problems), item)
        runs.append(results)

    # per-question fallback for anything the batch didn't cover
    answered = {k for r in runs for k in r}
    for q in targets:
        key = str(q.label or q.number)
        if key in answered:
            continue
        for solver in ctx.providers.solver:
            if not hasattr(solver, "solve"):
                continue
            for run_i, run in enumerate(runs):
                if key in run:
                    continue
                cand = _solve_single(solver, problems[q.id], run_i)
                if cand.value.get("solved"):
                    run[key] = cand.value

    solved = 0
    for q in targets:
        key = str(q.label or q.number)
        answers = [
            r[key].get("answer")
            for r in runs
            if key in r and r[key].get("solved")
        ]
        steps = next(
            (r[key].get("steps") for r in runs if key in r and r[key].get("steps")),
            None,
        )
        if not answers:
            q.verification.logic_flags.append(
                LogicFlag(kind="unsolvable_question", detail="solver가 정답을 확정하지 못함")
            )
            continue
        if len({repr(a) for a in answers}) > 1:
            q.verification.logic_flags.append(
                LogicFlag(kind="ambiguous_answer", detail=f"풀이 결과 불일치: {answers}")
            )
            continue
        normalized, matched = _normalize_answer(answers[0], q)
        q.answer = Answer(value=normalized)
        if steps:
            q.solution = Solution(steps=[TextSpan(text=str(s)) for s in steps])
        if not matched:
            q.verification.logic_flags.append(
                LogicFlag(
                    kind="ambiguous_answer",
                    detail=f"정답 {normalized!r}이 선택지와 일치하지 않음",
                )
            )
            continue
        solved += 1

    ctx.emit("solving", f"{solved}/{len(targets)} 문항 풀이 완료")


def _solve_batch(solver, problems: list[dict], run: int):
    try:
        return solver.solve_batch(problems, run)
    except TypeError:
        return solver.solve_batch(problems)


def _solve_single(solver, problem: dict, run: int):
    try:
        return solver.solve(problem, run)
    except TypeError:
        return solver.solve(problem)


def _result_key(item: dict, problems: dict[str, dict]) -> str:
    """Batch results echo the problem's number field (label)."""
    return str(item.get("number", ""))


def _problem(question, document=None) -> dict:
    problem = {
        "number": question.label or question.number,
        "type": question.type.value,
        "body": [span.text for span in question.body],
        "equations": [eq.latex for eq in question.equations],
        "choices": {
            c.label: " ".join(s.text for s in c.body) for c in question.choices
        },
        "figures": [f.topology.get("description") for f in question.figures],
    }
    if document is not None and question.parent_id:
        parent = next((p for p in document.questions if p.id == question.parent_id), None)
        if parent:
            problem["shared_stem"] = {
                "body": [span.text for span in parent.body],
                "equations": [eq.latex for eq in parent.equations],
                "figures": [f.topology.get("description") for f in parent.figures],
            }
    return problem


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
