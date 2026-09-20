"""Benchmark metrics (Master Spec §34/§46).

Every metric is computed against the frozen denominator of gold items —
abstention never counts as success. SOURCE_HALLUCINATION and
PRINT_DESTRUCTION are first-class failure modes, not footnotes.
"""
from __future__ import annotations

import re
from typing import Any, Optional

import numpy as np

# --- text -----------------------------------------------------------------

_WS = re.compile(r"\s+")
# critical tokens: digits/decimals, operators/relations, units, degrees,
# choice labels, negation markers
_CRITICAL = re.compile(
    r"\d+(?:\.\d+)?\s*(?:cm|mm|km|kg|mL|m|g|L|°|%)?"  # number(+unit)
    r"|[+\-×÷=≠<>≤≥∥⟂°]"
    r"|[①②③④⑤]"
    r"|없|아닌|않"
)


def norm_text(s: str) -> str:
    return _WS.sub("", str(s))


def char_exact(pred: str, gold: str) -> float:
    """1.0 when normalized strings match exactly; else 1 - CER-ish edit
    ratio clipped at 0."""
    p, g = norm_text(pred), norm_text(gold)
    if p == g:
        return 1.0
    if not g:
        return 0.0
    # Levenshtein via DP on short strings; fallback ratio for long ones
    if len(g) > 2000 or len(p) > 2000:
        import difflib

        return difflib.SequenceMatcher(None, p, g).ratio()
    d = _levenshtein(p, g)
    return max(0.0, 1.0 - d / max(len(g), 1))


def _levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def critical_tokens(text: str) -> list[str]:
    return _CRITICAL.findall(norm_text(text))


def critical_token_exact(pred: str, gold: str) -> tuple[int, int, int]:
    """(matched, gold_total, pred_extra). pred_extra counts tokens the
    prediction invented — feeds SOURCE_HALLUCINATION."""
    g, p = critical_tokens(gold), critical_tokens(pred)
    gp, pp = sorted(g), sorted(p)
    matched = 0
    i = j = 0
    while i < len(gp) and j < len(pp):
        if gp[i] == pp[j]:
            matched += 1
            i += 1
            j += 1
        elif gp[i] < pp[j]:
            i += 1
        else:
            j += 1
    return matched, len(g), max(0, len(p) - matched)


def source_hallucination(pred_text: str, gold_text: str) -> int:
    """Count of critical tokens present in prediction but absent in gold —
    invented numbers/operators/units are the dangerous hallucination."""
    _m, _g, extra = critical_token_exact(pred_text, gold_text)
    return extra


# --- question-level --------------------------------------------------------


def question_metrics(pred_q: dict, gold_q: dict) -> dict[str, Any]:
    """Per-question comparison against an expected.json entry."""
    body = char_exact(pred_q.get("body", ""), gold_q.get("body", ""))
    gold_choices = gold_q.get("choices", {})
    pred_choices = pred_q.get("choices", {})
    if isinstance(pred_choices, list):
        pred_choices = {
            c.get("label"): " ".join(
                s.get("text", "") for s in c.get("body", [])
            ) if isinstance(c.get("body"), list) else str(c.get("body"))
            for c in pred_choices
        }
    choice_scores = []
    for label, gtext in gold_choices.items():
        ptext = pred_choices.get(label, "")
        choice_scores.append(char_exact(str(ptext), str(gtext)))
    matched, total, extra = critical_token_exact(
        pred_q.get("body", "") + " " + " ".join(map(str, pred_choices.values())),
        gold_q.get("body", "") + " " + " ".join(map(str, gold_choices.values())),
    )
    return {
        "number": gold_q.get("number"),
        "body_exact": body,
        "choice_exact": (
            sum(choice_scores) / len(choice_scores) if choice_scores else None
        ),
        "points_match": pred_q.get("points") == gold_q.get("points"),
        "critical_matched": matched,
        "critical_total": total,
        "critical_extra": extra,
        "hallucinated_tokens": extra,
        "answer_match": (
            str(pred_q.get("answer") or "") == str(gold_q.get("answer") or "")
        ),
    }


# --- layer metrics (synthetic ground truth) ---------------------------------


def layer_metrics(
    masks: dict[str, np.ndarray], gt: dict[str, np.ndarray]
) -> dict[str, float]:
    """masks: predicted class masks (bool arrays). gt: ground-truth masks
    with keys print / handwriting / grading / overlap.

    PRINT_DESTRUCTION = print pixels predicted as removable
    (handwriting/grading) / all print pixels — the highest-penalty error.
    """
    g_print = gt["print"].astype(bool)
    g_hand = gt["handwriting"].astype(bool)
    g_over = gt.get("overlap", np.zeros_like(g_print)).astype(bool)
    p_print = masks.get("print", np.zeros_like(g_print)).astype(bool)
    p_hand = masks.get("handwriting", np.zeros_like(g_print)).astype(bool)
    p_over = masks.get("overlap", np.zeros_like(g_print)).astype(bool)
    p_removable = p_hand | masks.get("grading", np.zeros_like(g_print)).astype(bool)

    def _div(a, b):
        return float(a / b) if b else 0.0

    return {
        "print_recall": _div((p_print & g_print).sum(), g_print.sum()),
        "handwriting_precision": _div((p_hand & g_hand).sum(), p_hand.sum()),
        "overlap_recall": _div((p_over & g_over).sum(), g_over.sum()),
        "print_destruction_rate": _div(
            (p_removable & g_print).sum(), g_print.sum()
        ),
    }
