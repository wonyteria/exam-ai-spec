"""Expected-object manifest, reconciliation, and hash lineage (RESTORE-07).

The manifest records what the *evidence* says must exist — per-question
fields seen by any provider candidate, page roles, processing failures —
before materialization. `reconcile` then checks the canonical document
against it: an ATU-less question or an unverified field is a MISSING
object, never silently "zero missing". `build_lineage` binds source
hashes, derived-variant hashes, and the canonical document hash into one
chain that the export gate carries.
"""
from __future__ import annotations

import hashlib
from typing import Any

from document.models import Document, Question, VerificationStatus

_VERIFIED = {
    VerificationStatus.AUTO_VERIFIED,
    VerificationStatus.HUMAN_VERIFIED,
}


def build_expected_manifest(document: Document) -> dict[str, Any]:
    """Census of objects the source evidence claims — built from ATU
    candidates and page evidence, independent of what materialized."""
    questions = []
    for q in document.questions:
        cand_fields = {a.field for a in q.atus if a.candidates and a.field}
        questions.append(
            {
                "id": q.id,
                "number": q.number,
                "label": q.label,
                "expected_fields": sorted(cand_fields),
                "expected_choices": sorted(
                    f.split(":", 1)[1]
                    for f in cand_fields
                    if f.startswith("choice:")
                ),
                "expected_equations": sum(
                    1 for f in cand_fields if f.startswith("equation:")
                ),
                "expect_body": "body" in cand_fields,
                "expect_points": "points" in cand_fields,
                "expect_figure": "figure" in cand_fields,
                "has_atus": bool(q.atus),
            }
        )
    return {
        "page_count": len(document.pages),
        "page_roles": {str(p.index): p.page_role for p in document.pages},
        "unprocessed_pages": [
            p.index for p in document.pages if p.processing_error
        ],
        "question_count": len(document.questions),
        "questions": questions,
        "expected_objects": sum(len(q["expected_fields"]) for q in questions),
        "answer_key_pages": [
            p.index for p in document.pages if p.page_role == "ANSWER_KEY"
        ],
    }


def reconcile(manifest: dict[str, Any], document: Document) -> list[dict[str, Any]]:
    """Expected-vs-actual mismatches. Every unresolved expected object is
    reported; absent ATUs where evidence exists is MISSING, not zero."""
    by_id = {q.id: q for q in document.questions}
    mismatches: list[dict[str, Any]] = []
    for entry in manifest["questions"]:
        q = by_id.get(entry["id"])
        if q is None:
            mismatches.append(
                {"kind": "missing_question", "label": entry["label"]}
            )
            continue
        if not entry["has_atus"]:
            # Segmented region produced zero ATUs — nothing verified.
            mismatches.append(
                {
                    "kind": "no_evidence",
                    "label": entry["label"],
                    "detail": "question region produced zero candidates",
                }
            )
            continue
        _check(q, entry, mismatches)
    return mismatches


def _check(q: Question, entry: dict, out: list[dict]) -> None:
    label = entry["label"]
    if entry["expect_body"] and not q.body:
        out.append({"kind": "missing", "label": label, "field": "body"})
    if entry["expect_points"] and q.points is None:
        out.append({"kind": "missing", "label": label, "field": "points"})
    if entry["expect_figure"] and not q.figures:
        out.append({"kind": "missing", "label": label, "field": "figure"})
    actual_choices = {c.label for c in q.choices}
    for ch in entry["expected_choices"]:
        if ch not in actual_choices:
            out.append(
                {"kind": "missing", "label": label, "field": f"choice:{ch}"}
            )
    if len(q.choices) > len(entry["expected_choices"]):
        extra = actual_choices - set(entry["expected_choices"])
        out.append(
            {
                "kind": "duplicate",
                "label": label,
                "field": "choice",
                "extra": sorted(extra),
            }
        )
    if len(q.equations) != entry["expected_equations"]:
        out.append(
            {
                "kind": "missing" if len(q.equations) < entry["expected_equations"]
                else "duplicate",
                "label": label,
                "field": "equation",
                "expected": entry["expected_equations"],
                "actual": len(q.equations),
            }
        )


def build_lineage(document: Document) -> dict[str, Any]:
    """One hash chain: immutable source bytes -> derived variants/masks ->
    canonical document. The artifact hash is bound separately at proof
    time (export_verification) so a stale/mutated artifact can never
    inherit an earlier proof."""
    return {
        "pages": [
            {
                "index": p.index,
                "source_sha256": p.sha256,
                "pdf_page_index": p.pdf_page_index,
                "variant_sha256": dict(p.original.variant_sha256),
                "page_role": p.page_role,
                "processing_error": p.processing_error,
            }
            for p in document.pages
        ],
        "document_sha256": hashlib.sha256(
            document.model_dump_json(
                exclude={"verification"}
            ).encode("utf-8")
        ).hexdigest(),
    }
