"""Immutable source/page hash binding (Phase 1).

Every stage downstream operates on bytes that must provably be the
bytes uploaded. Before preprocessing we re-hash each page's original
asset and compare it to the hash recorded at ingest; a mismatch fails
the stage rather than producing restoration evidence against the wrong
source.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from core.examdna.context import PipelineContext


def run(ctx: PipelineContext) -> None:
    doc = ctx.document
    if not doc.pages:
        raise RuntimeError("source_integrity: document has no pages")

    mismatched: list[int] = []
    recorded = 0
    verified = 0
    for page in doc.pages:
        path = ctx.resolve_uri(page.original.uri)
        data = Path(path).read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if page.sha256:
            if actual != page.sha256:
                mismatched.append(page.index)
            else:
                verified += 1
        else:
            # Legacy/sample pages may lack the ingest hash — bind it now
            # rather than skipping the check for the whole document.
            page.sha256 = actual
            recorded += 1
        # Variant hashes from preprocessing are evidence too; keep them
        # consistent with the bytes on disk.
        for name, uri in page.original.variants.items():
            vbytes = Path(ctx.resolve_uri(uri)).read_bytes()
            vsha = hashlib.sha256(vbytes).hexdigest()
            expected = page.original.variant_sha256.get(name)
            if expected and expected != vsha:
                if page.index not in mismatched:
                    mismatched.append(page.index)
            else:
                page.original.variant_sha256.setdefault(name, vsha)

    evidence: dict[str, Any] = {
        "pages": len(doc.pages),
        "verified": verified,
        "bound_now": recorded,
        "mismatched": mismatched,
    }
    ctx.metric("source_integrity", "pages_verified", verified)
    ctx.metric("source_integrity", "pages_bound", recorded)
    ctx.metric("source_integrity", "pages_mismatched", len(mismatched))
    ctx.emit(
        "source_integrity",
        f"source hashes verified={verified} bound={recorded} "
        f"mismatched={len(mismatched)}",
    )
    if mismatched:
        raise RuntimeError(
            f"source_integrity: {len(mismatched)} page hash mismatch "
            f"on pages {mismatched}"
        )
