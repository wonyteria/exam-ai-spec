"""Gold-reference access gate (Master Spec §3, RESTORE-10B).

Rule: DAMAGED INPUT ONLY → RESTORATION → RESULT FREEZE → GOLD ACCESS →
COMPARISON. Everything in the reconstruction path is forbidden from
reading these locations; only this module may open them. The boundary
is enforced by tests/golden/test_gold_isolation.py which scans backend
source for gold-path references outside this package.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]

# Locations that are entirely gold (holdout material must never be
# touched by reconstruction code).
GOLD_ROOTS: tuple[Path, ...] = (
    REPO_ROOT / "samples" / "gold",
    REPO_ROOT / "docs" / "handoff" / "evidence" / "holdout",
)
# Filenames that are gold regardless of directory — expected answers,
# reference drafts, answer keys. Damaged INPUT pages (page*.jpg) are
# deliberately NOT gold: they are what the pipeline is allowed to see.
GOLD_FILENAMES = {
    "expected.json",
    "gold.json",
    "answer_key.json",
    "reference_draft.json",
}


def is_gold_path(path: Path | str) -> bool:
    p = Path(path)
    try:
        resolved = p.resolve()
    except OSError:
        resolved = p
    for root in GOLD_ROOTS:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return p.name in GOLD_FILENAMES


def load_expected(sample_dir: Path | str) -> dict[str, Any]:
    """Load expected.json — benchmark runner only."""
    p = Path(sample_dir) / "expected.json"
    if not is_gold_path(p):
        raise PermissionError(
            f"{p} is not a registered gold location — refuse to load"
        )
    return json.loads(p.read_text(encoding="utf-8"))


def damaged_inputs(sample_dir: Path | str) -> list[Path]:
    """Damaged page images of a sample — the ONLY thing handed to the
    reconstruction path."""
    p = Path(sample_dir)
    return sorted(p.glob("page*.jpg")) + sorted(p.glob("page*.png"))
