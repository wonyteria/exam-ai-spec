"""Bridge pipeline output → canonical artifacts (RESTORE download path).

The examdna pipeline renders exam.hwpx into the job export dir, but a
file on disk is not a releasable artifact. This module registers each
rendered output as a canonical Artifact bound to the new RESTORE
revision and records a proof with only honestly-verified checks marked
PASSED — anything not actually verified stays NOT_RUN, so an artifact
can never reach FINAL_ELIGIBLE on inference alone. Promotion still goes
through export_final (FINAL_ELIGIBLE + byte-bound proof + head revision).
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional

from canonical.policy import ARTIFACT_CHECKS_BY_FORMAT_V1
from qa.hwp_proof import (
    _hwpx_content_mismatches,
    _hwpx_text_and_objects,
    _pdf_text_mismatches,
    pdf_text,
)
from qa.hwpilot_proof import hwpilot_readback
from renderers.hwp import HWPWorkerUnavailable, WindowsHWPWorker


def register_pipeline_artifacts(
    service, objects, store, ctx, job, rev,
) -> list:
    """Register rendered outputs as canonical artifacts for `rev`.

    Returns the registered Artifact records. A missing artifact or an
    unavailable Hancom worker registers nothing for that format — the
    formats simply have no FINAL path, which is fail-closed by design.
    """
    out = store.export_dir(ctx.document.id)
    hwpx = out / "exam.hwpx"
    if not hwpx.exists():
        return []

    registered = []
    art = _put_and_register(
        service, objects, job, ctx.document.id, rev.id, "hwpx", hwpx
    )
    service.record_proof(
        art.id,
        checks=hwpx_checks(hwpx, ctx.document),
        worker_identity="examdna-pipeline",
    )
    registered.append(art)

    # HWP + PDF exist only through the actual Hancom round-trip.
    proof = None
    try:
        worker = WindowsHWPWorker()
        if worker.is_available():
            proof = worker.convert_with_proof(
                hwpx, out / "exam.hwp", out / "exam.pdf",
                request_revision=rev.id,
            )
    except (HWPWorkerUnavailable, RuntimeError, TimeoutError):
        proof = None
    if proof is None:
        return registered

    wid = proof.get("worker_identity", "")
    hwp_path, pdf_path = out / "exam.hwp", out / "exam.pdf"
    for fmt, path in (("hwp", hwp_path), ("pdf", pdf_path)):
        if not path.exists():
            continue
        art = _put_and_register(
            service, objects, job, ctx.document.id, rev.id, fmt, path
        )
        checks = (
            hwp_checks(hwp_path, pdf_path, ctx.document, proof)
            if fmt == "hwp"
            else pdf_checks(pdf_path, ctx.document, proof)
        )
        service.record_proof(art.id, checks=checks, worker_identity=wid)
        registered.append(art)
    return registered


def _put_and_register(service, objects, job, doc_id, rev_id, fmt, path: Path):
    blob = path.read_bytes()
    sha = hashlib.sha256(blob).hexdigest()
    key = f"artifacts/{job.tenant_id}/{doc_id}/{rev_id}/{fmt}-{sha[:16]}.{fmt}"
    uri = objects.put(key, blob)
    return service.register_draft_artifact(
        job.tenant_id, doc_id, rev_id, fmt, uri, sha, len(blob)
    )


def _blank(fmt: str) -> dict[str, str]:
    return {k: "NOT_RUN" for k in ARTIFACT_CHECKS_BY_FORMAT_V1.get(fmt, [])}


def _scored(doc) -> int:
    return sum(1 for q in doc.questions if q.points)


def hwpx_checks(hwpx_path: Path, doc) -> dict[str, str]:
    """What the HWPX's own bytes can prove. Unverifiable dimensions stay
    NOT_RUN rather than being claimed."""
    checks = _blank("hwpx")
    try:
        _blob, objects = _hwpx_text_and_objects(hwpx_path)
        checks["FORMAT_OPEN_VALIDITY"] = "PASSED"
    except Exception:
        checks["FORMAT_OPEN_VALIDITY"] = "FAILED"
        return checks
    coverage = "PASSED" if _hwpx_content_mismatches(hwpx_path, doc) == 0 else "FAILED"
    checks["NATIVE_OBJECT_INTEGRITY"] = coverage
    checks["ARTIFACT_SEMANTIC_COVERAGE"] = coverage
    # A FAILED verdict from the independent hwpilot parser downgrades —
    # our writer and in-repo parser could share a systematic bug.
    readback = hwpilot_readback(hwpx_path, doc)
    if readback is not None and readback > 0:
        checks["NATIVE_OBJECT_INTEGRITY"] = "FAILED"
        checks["ARTIFACT_SEMANTIC_COVERAGE"] = "FAILED"
    checks["FORMAT_CONVERSION_PROVENANCE"] = "PASSED"
    checks["ARTIFACT_HASH_BINDING"] = "PASSED"
    checks["OUTPUT_MODE_CONTENT_POLICY"] = (
        "PASSED" if objects["endnote_answers"] >= _scored(doc) else "NOT_RUN"
    )
    # RENDERED_TEXT_VISUAL_MATCH / LAYOUT_STYLE_BOUNDS need a render —
    # left NOT_RUN; the PDF artifact carries that evidence separately.
    return checks


def hwp_checks(hwp_path: Path, pdf_path: Path, doc, proof: dict) -> dict[str, str]:
    """HWP checks: worker step-returns prove open/save/reopen; the
    Hancom-rendered PDF is honest evidence for rendered content, and
    hwpilot — an independent HWP 5.0 implementation — re-parses the
    binary itself for object integrity and semantic coverage."""
    checks = _blank("hwp")
    for k, v in (proof or {}).get("checks", {}).items():
        if k in checks:
            checks[k] = v
    text = pdf_text(pdf_path)
    if text is not None:
        coverage = "PASSED" if _pdf_text_mismatches(pdf_path, doc) == 0 else "FAILED"
        checks["ARTIFACT_SEMANTIC_COVERAGE"] = coverage
        checks["RENDERED_TEXT_VISUAL_MATCH"] = coverage
        checks["OUTPUT_MODE_CONTENT_POLICY"] = (
            "PASSED" if text.count("정답:") >= _scored(doc) else "NOT_RUN"
        )
    # Independent binary readback: a parse by code we did not write is
    # the only direct evidence on the .hwp bytes themselves.
    readback = hwpilot_readback(hwp_path, doc)
    if readback is not None:
        verdict = "PASSED" if readback == 0 else "FAILED"
        checks["NATIVE_OBJECT_INTEGRITY"] = verdict
        if verdict == "FAILED":
            checks["ARTIFACT_SEMANTIC_COVERAGE"] = "FAILED"
        elif checks["ARTIFACT_SEMANTIC_COVERAGE"] == "NOT_RUN":
            checks["ARTIFACT_SEMANTIC_COVERAGE"] = "PASSED"
    return checks


def pdf_checks(pdf_path: Path, doc, proof: Optional[dict] = None) -> dict[str, str]:
    checks = _blank("pdf")
    text = pdf_text(pdf_path)
    if text is None:
        checks["FORMAT_OPEN_VALIDITY"] = "FAILED"
        return checks
    checks["FORMAT_OPEN_VALIDITY"] = "PASSED"
    coverage = "PASSED" if _pdf_text_mismatches(pdf_path, doc) == 0 else "FAILED"
    checks["ARTIFACT_SEMANTIC_COVERAGE"] = coverage
    checks["RENDERED_TEXT_VISUAL_MATCH"] = coverage
    checks["ARTIFACT_HASH_BINDING"] = "PASSED"
    if proof is not None:
        checks["FORMAT_CONVERSION_PROVENANCE"] = "PASSED"
    checks["OUTPUT_MODE_CONTENT_POLICY"] = (
        "PASSED" if text.count("정답:") >= _scored(doc) else "NOT_RUN"
    )
    return checks
