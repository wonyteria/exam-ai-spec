"""Pinned defects of the seeded golden baseline (WP00 / A33 / S02 / S10).

`samples/golden_001/expected.json` is a *seeded replay fixture*, not an
approved golden oracle. These tests record exactly which seeded values are
known-wrong so nobody mistakes the seeded baseline for ground truth, and so
the discrepancy is caught if anyone "fixes" the seeded data without going
through the F2 review path.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "golden_001"

pytestmark = pytest.mark.skipif(
    not (SAMPLES / "expected.json").exists(), reason="golden fixtures missing"
)


def _load(name: str) -> dict:
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))


def test_seeded_expected_marked_as_replay_fixture():
    expected = _load("expected.json")
    assert expected["provenance"]["kind"] == "seeded_replay_fixture"


def test_seeded_wrong_answers_match_reference_draft_exactly():
    """The seeded baseline is wrong at exactly Q2,4,8,9,10,14,20 — and only
    there. Guarded so an accidental 'silent fix' or new drift is detected."""
    expected = _load("expected.json")
    reference = _load("reference_draft.json")

    seeded = {q["number"]: q.get("answer") for q in expected["questions"]}
    correct = {int(k): v for k, v in reference["mcq_independent_answers"].items()}

    diffs = {n for n in range(1, 21) if seeded.get(n) != correct.get(n)}
    assert diffs == {2, 4, 8, 9, 10, 14, 20}
    for n, fix in reference["seeded_expected_known_defects"]["wrong_answers"].items():
        n = int(n)
        assert seeded[n] == fix["seeded"]
        assert correct[n] == fix["correct"]


def test_seeded_structure_is_not_the_acceptance_shape():
    """Seeded rows/points differ from the required 31-node/28-leaf/100-point
    structure, so row count alone can never be a pass criterion (S03)."""
    expected = _load("expected.json")
    reference = _load("reference_draft.json")

    seeded_rows = len(expected["questions"])
    seeded_points = sum(q.get("points") or 0 for q in expected["questions"])
    required = reference["structure"]

    assert seeded_rows != required["total_nodes_including_parents"]
    assert seeded_points != required["total_points"]
    assert required["scored_leaves"] == 28
    assert required["major_questions"] == 23


def test_reference_draft_not_usable_as_model_input():
    reference = _load("reference_draft.json")
    assert reference["provenance"]["must_not_feed_model_input"] is True
    assert reference["status"] == "F2_DRAFT_PENDING_INDEPENDENT_REVIEW"
