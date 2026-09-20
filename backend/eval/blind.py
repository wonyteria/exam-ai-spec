"""RESTORE-20 — Blind Evaluation sealing.

Predictions are sealed (content-hashed, timestamped) BEFORE gold is
read. Scoring then compares the sealed predictions to gold via the
gold-gated loader — proving the pipeline could not have peeked.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


def seal_predictions(predictions: dict[str, Any], out_path: Path) -> dict:
    """Freeze predictions: write them plus a binding seal record.
    Returns the seal {sha256, sealed_at, count}."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(
        predictions, sort_keys=True, ensure_ascii=False
    ).encode("utf-8")
    sha = hashlib.sha256(blob).hexdigest()
    out_path.write_bytes(blob)
    seal = {
        "sha256": sha,
        "sealed_at": time.time(),
        "item_count": len(predictions),
        "path": str(out_path),
    }
    (out_path.parent / f"{out_path.stem}.seal.json").write_text(
        json.dumps(seal, indent=2), encoding="utf-8"
    )
    return seal


def verify_seal(predictions_path: Path, seal: dict) -> bool:
    """Re-hash a sealed predictions file — any post-seal edit breaks
    the binding and scoring must refuse to proceed."""
    blob = predictions_path.read_bytes()
    return hashlib.sha256(blob).hexdigest() == seal.get("sha256")


def load_sealed(predictions_path: Path, seal: dict) -> dict[str, Any]:
    if not verify_seal(predictions_path, seal):
        raise ValueError(
            "sealed predictions were modified after sealing — "
            "blind evaluation integrity violated"
        )
    return json.loads(predictions_path.read_text(encoding="utf-8"))
