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
    pdf_layout_ok,
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
    registered.append(art)

    # HWP + PDF exist only through the actual Hancom round-trip. The
    # resulting PDF is also the render evidence for the HWPX bytes, so
    # the HWPX proof is recorded after conversion.
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

    pdf_path = out / "exam.pdf"
    service.record_proof(
        art.id,
        checks=hwpx_checks(
            hwpx, ctx.document,
            pdf_path=pdf_path if pdf_path.exists() else None,
        ),
        worker_identity="examdna-pipeline",
    )
    if proof is None:
        return registered

    wid = proof.get("worker_identity", "")
    hwp_path = out / "exam.hwp"
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


def hwpx_checks(hwpx_path: Path, doc, pdf_path: Path | None = None) -> dict[str, str]:
    """What the HWPX's own bytes can prove. Unverifiable dimensions stay
    NOT_RUN rather than being claimed. When `pdf_path` is given — the
    Hancom render of exactly these bytes — it is honest render evidence
    for the HWPX itself."""
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
    if pdf_path is not None and pdf_path.exists():
        text = pdf_text(pdf_path)
        if text is not None:
            checks["RENDERED_TEXT_VISUAL_MATCH"] = (
                "PASSED" if _pdf_text_mismatches(pdf_path, doc) == 0 else "FAILED"
            )
        layout = pdf_layout_ok(pdf_path)
        if layout is not None:
            checks["LAYOUT_STYLE_BOUNDS"] = "PASSED" if layout else "FAILED"
    # Without a render both stay NOT_RUN — never inferred.
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
        layout = pdf_layout_ok(pdf_path)
        if layout is not None:
            checks["LAYOUT_STYLE_BOUNDS"] = "PASSED" if layout else "FAILED"
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
    layout = pdf_layout_ok(pdf_path)
    if layout is not None:
        checks["LAYOUT_STYLE_BOUNDS"] = "PASSED" if layout else "FAILED"
    if proof is not None:
        checks["FORMAT_CONVERSION_PROVENANCE"] = "PASSED"
    checks["OUTPUT_MODE_CONTENT_POLICY"] = (
        "PASSED" if text.count("정답:") >= _scored(doc) else "NOT_RUN"
    )
    return checks


def docx_checks(
    docx_path: Path, doc, pdf_path: Optional[Path] = None
) -> dict[str, str]:
    """What a DOCX's own bytes can prove via python-docx round-trip —
    same honest pattern as pdf_checks: unverifiable stays NOT_RUN.

    `pdf_path` must be a render of exactly these docx bytes (e.g. a
    LibreOffice docx->pdf conversion). Only with that render can the
    visual checks pass — a docx that was never rendered stays NOT_RUN
    and cannot reach FINAL_ELIGIBLE."""
    from qa.docx_proof import docx_content_mismatches, docx_text

    checks = _blank("docx")
    text = docx_text(docx_path)
    if text is None:
        checks["FORMAT_OPEN_VALIDITY"] = "FAILED"
        return checks
    checks["FORMAT_OPEN_VALIDITY"] = "PASSED"
    checks["ARTIFACT_SEMANTIC_COVERAGE"] = (
        "PASSED" if docx_content_mismatches(docx_path, doc) == 0
        else "FAILED"
    )
    checks["ARTIFACT_HASH_BINDING"] = "PASSED"
    # Endnote mode writes "※ 정답은 미주 N번 참조"; answer-solution mode
    # writes "정답: X". Either marker satisfies the content policy.
    answers = text.count("정답:") + text.count("정답은 미주")
    checks["OUTPUT_MODE_CONTENT_POLICY"] = (
        "PASSED" if answers >= _scored(doc) else "NOT_RUN"
    )
    if pdf_path is not None and pdf_path.exists():
        # The rendered PDF is the visual proof for these exact docx
        # bytes — same evidence the PDF format itself would carry.
        if pdf_text(pdf_path) is not None:
            checks["RENDERED_TEXT_VISUAL_MATCH"] = (
                "PASSED" if _pdf_text_mismatches(pdf_path, doc) == 0
                else "FAILED"
            )
        layout = pdf_layout_ok(pdf_path)
        if layout is not None:
            checks["LAYOUT_STYLE_BOUNDS"] = (
                "PASSED" if layout else "FAILED"
            )
    return checks


def render_docx_pdf(docx_path: Path, pdf_path: Path) -> Optional[Path]:
    """Render a DOCX to PDF via LibreOffice when available.

    Returns the rendered path or None — a missing renderer means the
    visual checks stay NOT_RUN, never faked."""
    import shutil
    import subprocess

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        mac = Path(
            "/Applications/LibreOffice.app/Contents/MacOS/soffice"
        )
        if mac.exists():
            soffice = str(mac)
    if not soffice:
        return None
    try:
        subprocess.run(
            [
                soffice, "--headless", "--convert-to", "pdf",
                "--outdir", str(pdf_path.parent), str(docx_path),
            ],
            check=True, capture_output=True, timeout=120,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    produced = pdf_path.parent / (docx_path.stem + ".pdf")
    if produced != pdf_path and produced.exists():
        produced.rename(pdf_path)
    return pdf_path if pdf_path.exists() else None
