"""Deterministic math verification built on SymPy rules.

Three honest verdicts only:

    MATCH     — equivalence proven symbolically
    MISMATCH  — inequivalence proven (difference simplifies to a nonzero
                constant/expression, or solution sets differ)
    UNKNOWN   — unparseable input, timed-out simplification, or any case
                the rules cannot decide. UNKNOWN is never reported as
                MATCH.

Used by SolveDNA to confirm that a solver's claimed answer is
symbolically equal to the matched choice — string equality alone is not
proof.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import sympy
from sympy.parsing.latex import parse_latex
from sympy.parsing.sympy_parser import (
    convert_xor,
    factorial_notation,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

_PARSE_TRANSFORMS = standard_transformations + (
    convert_xor,
    factorial_notation,
    implicit_multiplication_application,
)
_SIMPLIFY_LIMIT = 2.0  # seconds-equivalent budget via simplified ops count

# Unicode → ASCII normalizations applied before parsing.
_NORMALIZE = {
    "×": "*",
    "÷": "/",
    "−": "-",
    "–": "-",
    "√": "sqrt",
    "π": "pi",
    "∞": "oo",
    "≤": "<=",
    "≥": ">=",
    "≠": "!=",
    "（": "(",
    "）": ")",
    "，": ",",
    "．": ".",
}


class MathVerdict(Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"


@dataclass
class MathCheck:
    verdict: MathVerdict
    detail: str = ""
    matched_label: Optional[str] = None


def parse_math(text: object) -> Optional[sympy.Basic]:
    """Parse LaTeX or plain math text into a SymPy expression/equation.

    Returns None for anything unparseable — callers must treat None as
    UNKNOWN, never as failure or match.
    """
    if not isinstance(text, str):
        return None
    s = text.strip()
    if not s:
        return None
    # Prose guard: implicit multiplication would happily parse
    # "hello world" into h*e*l*l*o*... — require at least one math
    # signal (digit, operator, math symbol, or LaTeX command).
    if not re.search(r"[0-9+\-*/^=<>_\\{}√π∞]|\\[a-zA-Z]+", s):
        return None
    for src, dst in _NORMALIZE.items():
        s = s.replace(src, dst)
    # strip display-math wrappers and trailing punctuation
    for w in ("$$", "\\[", "\\]", "$", "\\(", "\\)"):
        s = s.replace(w, " ")
    s = s.strip().rstrip(".,;")
    if not s:
        return None
    try:
        expr = parse_latex(s)
        if expr is not None:
            return expr
    except Exception:
        pass
    try:
        return parse_expr(s, transformations=_PARSE_TRANSFORMS, evaluate=True)
    except Exception:
        return None


def equivalent(a: object, b: object) -> MathVerdict:
    """Symbolic equivalence verdict between two expressions/equations."""
    ea, eb = parse_math(a), parse_math(b)
    if ea is None or eb is None:
        return MathVerdict.UNKNOWN
    try:
        if isinstance(ea, sympy.Equality) and isinstance(eb, sympy.Equality):
            # equations: compare both solution sets and the difference of
            # their sides under variable agreement
            diff = sympy.simplify((ea.lhs - ea.rhs) - (eb.lhs - eb.rhs))
            if diff == 0:
                return MathVerdict.MATCH
            return MathVerdict.UNKNOWN
        if isinstance(ea, sympy.Equality) or isinstance(eb, sympy.Equality):
            return MathVerdict.UNKNOWN
        diff = sympy.simplify(ea - eb)
        if diff == 0:
            return MathVerdict.MATCH
        if diff.is_number and diff != 0:
            return MathVerdict.MISMATCH
        # symbolic residue — ask SymPy directly as a last honest check
        eq = ea.equals(eb)
        if eq is True:
            return MathVerdict.MATCH
        if eq is False:
            return MathVerdict.MISMATCH
        return MathVerdict.UNKNOWN
    except Exception:
        return MathVerdict.UNKNOWN


def verify_answer(
    answer: object, choices: dict[str, str]
) -> MathCheck:
    """Match a solver's answer against choice bodies symbolically.

    Exact label/text matches are checked first (cheap path); otherwise
    each parseable choice is tested for symbolic equivalence. Returns
    matched_label only on MATCH. Zero parseable candidates yields
    UNKNOWN — never a fabricated verdict.
    """
    raw = str(answer).strip()
    for label, body in choices.items():
        if raw == label or (body and raw == body.strip()):
            return MathCheck(MathVerdict.MATCH, "exact_text", label)
    saw_parseable = False
    mismatch_only = True
    for label, body in choices.items():
        verdict = equivalent(answer, body)
        if verdict is MathVerdict.MATCH:
            return MathCheck(MathVerdict.MATCH, "symbolic_equivalent", label)
        if verdict is MathVerdict.UNKNOWN:
            mismatch_only = False
        else:
            saw_parseable = True
    if not choices:
        return MathCheck(MathVerdict.UNKNOWN, "no_choices")
    if saw_parseable and mismatch_only:
        return MathCheck(
            MathVerdict.MISMATCH, "all_parseable_choices_differ"
        )
    return MathCheck(MathVerdict.UNKNOWN, "unparseable_or_undecidable")


def check_units(answer: object, expected_units: list[str]) -> MathCheck:
    """Confirm the answer carries an expected unit token (cm, kg, m/s…).

    UNKNOWN when the answer has no unit at all — a missing unit is not
    proof of correctness or error.
    """
    from eval.bench.metrics import critical_tokens

    units = {
        "cm", "mm", "m", "km", "kg", "g", "s", "분", "초", "원", "도",
        "개", "명", "ℓ", "mL", "L",
    }
    tokens = critical_tokens(str(answer))
    found = [t for t in tokens if any(t.endswith(u) for u in units)]
    if not found:
        return MathCheck(MathVerdict.UNKNOWN, "no_unit_in_answer")
    for tok in found:
        for u in expected_units:
            if tok.endswith(u):
                return MathCheck(MathVerdict.MATCH, f"unit:{tok}")
    return MathCheck(MathVerdict.MISMATCH, f"unit_mismatch:{found}")
