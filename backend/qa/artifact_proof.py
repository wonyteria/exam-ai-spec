"""Artifact proof binding (RESTORE-07/08).

A proof is bound to the exact bytes it ran on: `bind_artifact_proof`
records the artifact's SHA-256 with the proof outcome, and
`verify_artifact_proof` re-hashes the file — a stale or mutated artifact
can never inherit an earlier proof. Status is one of PASS / FAILED /
NOT_RUN; NOT_RUN is never a pass.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional


def bind_artifact_proof(
    path: Path,
    status: str,
    mismatch_count: Optional[int] = None,
    detail: Optional[str] = None,
) -> dict:
    """Record a proof verdict bound to the artifact's exact bytes."""
    return {
        "artifact": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "status": status,
        "mismatch_count": mismatch_count,
        "detail": detail,
    }


def verify_artifact_proof(path: Path, binding: dict) -> bool:
    """Re-check that the artifact on disk is the bytes the proof ran on
    and that the proof passed. Anything else fails closed."""
    if binding.get("status") != "PASS":
        return False
    if not path.exists():
        return False
    return hashlib.sha256(path.read_bytes()).hexdigest() == binding.get("sha256")
