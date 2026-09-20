"""RESTORE-24 QuestionDNA + RESTORE-27 Difficulty Engine.

Spec §40: subject, grade, semester, chapter, unit, concepts,
problem_type, required_skills, solution_steps, difficulty,
calculation_complexity, condition_count, figure_complexity,
trap_elements, answer_type, estimated_time.

Difficulty is a deterministic feature score — never an LLM guess:
solution_steps, calculation load, concept count, condition count,
reasoning depth (nested ops), expression complexity, figure
complexity, and trap elements each contribute.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from document.models import Question

_TRAP_PATTERNS = re.compile(r"아닌|없는|않는|not\b|옳지|틀린", re.I)


def _calc_complexity(q: Question) -> tuple[int, list[str]]:
    """Total sympy op count across equations + skills (op names)."""
    try:
        from core.examdna.math.checker import parse_math
        from core.examdna.math.checker import MathVerdict  # noqa: F401
    except Exception:
        return 0, []
    ops = 0
    skills: set[str] = set()
    for eq in q.equations:
        expr = parse_math(eq.latex or eq.hwp_formula or "")
        if expr is None:
            continue
        try:
            import sympy as sp

            ops += int(sp.count_ops(expr))
            skills.update(
                type(node).__name__ for node in sp.preorder_traversal(expr)
            )
        except Exception:
            ops += 1
    return ops, sorted(skills)


def _figure_complexity(q: Question) -> int:
    best = 0
    for f in q.figures:
        n = 0
        if f.scene is not None:
            n = len(f.scene.primitives) + len(f.scene.relations)
        elif f.topology:
            n = len(f.topology)
        best = max(best, n)
    return best


def _trap_elements(q: Question) -> list[str]:
    traps: list[str] = []
    text = " ".join(s.text for s in q.body)
    if _TRAP_PATTERNS.search(text):
        traps.append("negation")
    for c in q.choices:
        body = " ".join(s.text for s in c.body)
        if _TRAP_PATTERNS.search(body):
            traps.append(f"negation_in_choice:{c.label}")
        if re.search(r"-\d|\(.*\)", body):
            traps.append(f"sign_or_paren:{c.label}")
    return sorted(set(traps))


def _answer_type(q: Question) -> str:
    if q.type.value == "multiple_choice":
        return "choice"
    if q.answer and isinstance(q.answer.value, (int, float)):
        return "numeric"
    if q.answer and q.answer.value is not None:
        return "expression" if any(
            ch in str(q.answer.value) for ch in "=+-*/^x"
        ) else "text"
    return "unknown"


def difficulty_score(features: dict[str, Any]) -> float:
    """0..5 deterministic score from structural features only."""
    score = 0.0
    score += min(1.5, 0.3 * features.get("solution_steps", 0))
    score += min(1.5, 0.05 * features.get("calculation_complexity", 0))
    score += min(0.8, 0.2 * features.get("condition_count", 0))
    score += min(0.8, 0.15 * len(features.get("concepts", [])))
    score += min(0.5, 0.1 * features.get("figure_complexity", 0))
    score += min(0.5, 0.25 * len(features.get("trap_elements", [])))
    return round(score, 2)


def difficulty_band(score: float) -> str:
    """RESTORE-27: score → 하/중/상 for composition specs like 상5/중7/하3."""
    if score < 1.2:
        return "하"
    if score < 2.6:
        return "중"
    return "상"


def estimated_minutes(features: dict[str, Any]) -> float:
    base = 1.0
    base += 0.8 * features.get("solution_steps", 0)
    base += 0.05 * features.get("calculation_complexity", 0)
    base += 0.5 * features.get("figure_complexity", 0)
    return round(base, 1)


def derive_dna(
    q: Question,
    subject: str = "mathematics",
    grade: str = "",
    semester: Optional[int] = None,
) -> dict[str, Any]:
    calc_ops, skills = _calc_complexity(q)
    concepts = sorted(set(q.curriculum.concepts))
    if q.solution:
        concepts = sorted(set(concepts) | set(q.solution.concepts))
    conditions = 0
    if q.problem_graph:
        conditions = len(q.problem_graph.get("conditions", []))
    conditions += len(q.equations)
    features: dict[str, Any] = {
        "subject": q.curriculum.subject if hasattr(q.curriculum, "subject") else subject,
        "grade": q.curriculum.grade or grade,
        "semester": semester,
        "chapter": q.curriculum.unit or None,
        "unit": q.curriculum.unit or None,
        "concepts": concepts,
        "problem_type": q.type.value,
        "required_skills": skills,
        "solution_steps": len(q.solution.steps) if q.solution else 0,
        "calculation_complexity": calc_ops,
        "condition_count": conditions,
        "figure_complexity": _figure_complexity(q),
        "trap_elements": _trap_elements(q),
        "answer_type": _answer_type(q),
        "choice_count": len(q.choices),
    }
    features["difficulty"] = difficulty_score(features)
    features["difficulty_band"] = difficulty_band(features["difficulty"])
    features["estimated_time"] = estimated_minutes(features)
    return features
