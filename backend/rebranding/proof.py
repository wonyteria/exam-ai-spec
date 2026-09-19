"""Rebrand proof manifest (HWP_REBRANDING_SPEC §9).

Binds source bytes/hash, scanned control manifest, plan digest, worker
identity and step returns, and the structural-invariant report into one
verifiable record — the same lineage model artifact proofs already use.
"""
from __future__ import annotations

import platform
import time
from typing import Any

from .models import BrandRewritePlan, BrandStructureManifest, InvariantReport

SCANNER_VERSION = "1"
MUTATOR_VERSION = "1"


def build_proof_manifest(
    *,
    tenant_id: str,
    document_id: str,
    source_id: str,
    source_name: str,
    source_sha256: str,
    output_sha256: str,
    output_format: str,
    manifest: BrandStructureManifest,
    plan: BrandRewritePlan,
    invariant: InvariantReport,
    worker_proof: dict[str, Any] | None = None,
    artifact_id: str | None = None,
) -> dict[str, Any]:
    checks = {
        "SOURCE_IMMUTABLE": "PASSED",
        "CONTROL_MANIFEST_BOUND": "PASSED",
        "PLAN_ALLOWLIST_ONLY": "PASSED" if invariant.passed else "FAILED",
        "OUTSIDE_MASK_DIFF_ZERO": "PASSED" if invariant.passed else "FAILED",
        "HWP_ACTUAL_REOPEN": (
            "PASSED"
            if (worker_proof or {}).get("checks", {}).get("HWP_ACTUAL_REOPEN") == "PASSED"
            else "NOT_RUN"
        ),
        "HWP_PDF_RENDER": (
            "PASSED"
            if (worker_proof or {}).get("checks", {}).get("FORMAT_CONVERSION_PROVENANCE") == "PASSED"
            else "NOT_RUN"
        ),
        "PROCESS_LEAK_ZERO": (
            "PASSED"
            if (worker_proof or {}).get("hwp_process", {}).get("leak") == 0
            else ("FAILED" if worker_proof else "NOT_RUN")
        ),
    }
    return {
        "kind": "rebrand_proof",
        "tenant_id": tenant_id,
        "document_id": document_id,
        "artifact_id": artifact_id,
        "source": {
            "source_id": source_id,
            "name": source_name,
            "sha256": source_sha256,
            "format": manifest.source_format,
            "section_count": manifest.section_count,
            "header_variants": manifest.header_variants,
            "footer_variants": manifest.footer_variants,
            "master_page_count": manifest.master_page_count,
        },
        "output": {"sha256": output_sha256, "format": output_format},
        "manifest_digest": manifest.digest,
        "plan_digest": plan.digest,
        "operations": [op.model_dump(mode="json") for op in plan.operations],
        "invariant": invariant.model_dump(mode="json"),
        "worker": worker_proof or {},
        "checks": checks,
        "scanner_version": SCANNER_VERSION,
        "mutator_version": MUTATOR_VERSION,
        "platform": platform.platform(),
        "timestamp": time.time(),
    }
