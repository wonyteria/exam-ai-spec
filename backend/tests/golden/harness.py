from __future__ import annotations

from typing import Any

from document.models import Document


def compare_golden(expected: dict[str, Any], actual: Document) -> dict[str, Any]:
    """EXPECTED vs ACTUAL regression comparison (GOLDEN_SAMPLE_001).

    Any previously-correct ATU that now differs is a P0 regression.
    """
    actual_by_number = {q.number: q for q in actual.questions}
    report: dict[str, Any] = {"questions": [], "matched": 0, "mismatched": 0, "missing": 0}

    for eq in expected.get("questions", []):
        number = eq["number"]
        actual_q = actual_by_number.get(number)
        entry: dict[str, Any] = {"number": number, "fields": {}}
        if actual_q is None:
            entry["status"] = "missing"
            report["missing"] += 1
        else:
            entry["status"] = "compared"
            for field, exp_value in eq.items():
                if field == "number" or exp_value is None:
                    continue
                actual_value = _extract(actual_q, field)
                ok = actual_value == exp_value
                entry["fields"][field] = {
                    "expected": exp_value,
                    "actual": actual_value,
                    "match": ok,
                }
                report["matched" if ok else "mismatched"] += 1
        report["questions"].append(entry)

    report["regression"] = report["mismatched"] > 0 or report["missing"] > 0
    return report


def _extract(question, field: str):
    if field == "body":
        return " ".join(s.text for s in question.body)
    if field == "points":
        return question.points
    if field == "choices":
        return {c.label: " ".join(s.text for s in c.body) for c in question.choices}
    if field == "answer":
        return question.answer.value if question.answer else None
    return getattr(question, field, None)
