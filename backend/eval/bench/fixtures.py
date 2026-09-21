"""Fixture loader bound to the corpus split registry (RESTORE-10B).

Benchmarks may only run on dev/regression families. A holdout family —
or anything not declared in CORPUS_SPLITS.json — is refused. This keeps
"looked at holdout to tune" structurally impossible through this path.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from eval import splits

REPO_ROOT = Path(__file__).resolve().parents[3]
SPLITS_PATH = (
    REPO_ROOT / "docs" / "handoff" / "evidence" / "CORPUS_SPLITS.json"
)

# dev-split sample directories, declared per family. A family may have
# several capture sets of the same exam (same gold, different photos) —
# list them all; expected.json is read from the first entry.
FAMILY_DIRS: dict[str, list[Path]] = {
    "golden-001-replay": [
        REPO_ROOT / "samples" / "golden_001",
        REPO_ROOT / "samples" / "simwon_2025_mid2",
    ],
    "gyenam-2025-imagepdf": [
        REPO_ROOT
        / "backend" / "data" / "local_evidence" / "restore00"
        / "workdir" / "gyenam_source.pdf"
    ],
}


def load_registry() -> dict[str, Any]:
    return splits.load_registry(SPLITS_PATH)


def benchable_families() -> list[str]:
    """Families usable for development benchmarks: dev + regression only."""
    reg = load_registry()
    errors = splits.validate_registry(reg)
    if errors:
        raise RuntimeError(f"corpus registry invalid: {errors}")
    return [
        f["family_id"]
        for f in reg["families"]
        if f.get("split") in ("dev", "regression")
    ]


def fixture_path(family_id: str) -> Path:
    """Primary fixture directory (gold lookups). Use fixture_dirs for all
    capture sets of a family."""
    return fixture_dirs(family_id)[0]


def fixture_dirs(family_id: str) -> list[Path]:
    reg = load_registry()
    split = splits.family_split(reg, family_id)
    if split == "holdout":
        raise PermissionError(
            f"{family_id} is a sealed holdout family — not runnable here"
        )
    if split is None:
        raise KeyError(f"{family_id} not declared in corpus registry")
    p = FAMILY_DIRS.get(family_id)
    if p is None:
        raise KeyError(f"{family_id} has no declared fixture directory")
    return p
