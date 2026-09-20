"""Corpus family splits and leakage control (RESTORE-09 / handoff-08 §4).

The split unit is the *family* — school/year/exam/question origin group.
A blank source, several students' handwritten copies, the answer key,
crops and rotations of the same exam are ONE family. A family lives in
exactly one split (dev | regression | holdout); a sealed holdout family
must declare when it was sealed and may share no asset hash with any
non-holdout split.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

SPLITS = ("dev", "regression", "holdout")
HOLDOUT = "holdout"


def load_registry(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def registry_hash(registry: dict[str, Any]) -> str:
    """Stable identity of the split definition — recorded on every eval
    run so results can be traced to the exact corpus partition."""
    canon = json.dumps(registry, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def validate_registry(registry: dict[str, Any]) -> list[str]:
    """Structural + leakage errors. Empty = clean."""
    errors: list[str] = []
    seen_families: dict[str, str] = {}
    holdout_assets: set[str] = set()
    open_assets: set[str] = set()

    for fam in registry.get("families", []):
        fid = fam.get("family_id")
        split = fam.get("split")
        if not fid:
            errors.append("family without family_id")
            continue
        if split not in SPLITS:
            errors.append(f"{fid}: unknown split {split!r}")
            continue
        if fid in seen_families:
            errors.append(
                f"{fid}: appears in both {seen_families[fid]!r} and {split!r}"
            )
        seen_families[fid] = split

        assets = set(fam.get("asset_sha256", []))
        if split == HOLDOUT:
            if not fam.get("sealed_at"):
                errors.append(f"{fid}: holdout family must record sealed_at")
            holdout_assets |= assets
        else:
            open_assets |= assets

    # Content-level leakage: an asset hash in both holdout and open splits
    # is contamination regardless of the declared family.
    for sha in sorted(holdout_assets & open_assets):
        errors.append(f"asset {sha[:16]}… leaks across holdout and open splits")
    return errors


def family_split(registry: dict[str, Any], family_id: str) -> Optional[str]:
    for fam in registry.get("families", []):
        if fam.get("family_id") == family_id:
            return fam.get("split")
    return None


def assets_for_split(registry: dict[str, Any], split: str) -> set[str]:
    return {
        sha
        for fam in registry.get("families", [])
        if fam.get("split") == split
        for sha in fam.get("asset_sha256", [])
    }
