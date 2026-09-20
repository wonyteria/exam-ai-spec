"""RESTORE-07 — expected manifest reconciliation + hash-bound proof gate.

Locks: expected objects come from candidate evidence (ATU=0 is never
"zero missing"); reconcile reports missing/duplicate fields separately;
VERIFIED_FINAL requires artifact_proof=PASS bound to exact bytes — a
mutated artifact invalidates the proof.
"""
from __future__ import annotations

from document.manifest import (
    build_expected_manifest,
    build_lineage,
    reconcile,
)
from document.models import (
    ATU,
    ATUKind,
    Candidate,
    Choice,
    Document,
    Page,
    PageImage,
    Question,
    TextSpan,
    VerificationStatus,
)
from document.verification import evaluate_gate
from qa.artifact_proof import bind_artifact_proof, verify_artifact_proof

V = VerificationStatus


def _q(number=1, label="1"):
    return Question(number=number, label=label)


def _verified_atu(kind, field, value):
    return ATU(
        kind=kind,
        field=field,
        value=value,
        status=V.AUTO_VERIFIED,
        candidates=[
            Candidate(provider="a", value=value),
            Candidate(provider="b", value=value),
        ],
    )


def test_manifest_records_expected_objects_from_candidates():
    doc = Document(tenant_id="t")
    q = _q()
    q.atus = [
        _verified_atu(ATUKind.TEXT_TOKEN, "body", "문제"),
        _verified_atu(ATUKind.POINTS, "points", 4),
        _verified_atu(ATUKind.CHOICE, "choice:①", "가"),
        _verified_atu(ATUKind.CHOICE, "choice:②", "나"),
        _verified_atu(ATUKind.MATH_SYMBOL, "equation:0", "x^2"),
    ]
    doc.questions.append(q)
    doc.pages.append(Page(index=0, original=PageImage(uri="p.png"),
                          page_role="ANSWER_KEY"))

    m = build_expected_manifest(doc)
    assert m["question_count"] == 1
    assert m["expected_objects"] == 5
    e = m["questions"][0]
    assert e["expected_choices"] == ["①", "②"]
    assert e["expected_equations"] == 1
    assert m["answer_key_pages"] == [0]


def test_reconcile_reports_missing_and_duplicate():
    doc = Document(tenant_id="t")
    q = _q()
    q.atus = [
        _verified_atu(ATUKind.TEXT_TOKEN, "body", "문제"),
        _verified_atu(ATUKind.POINTS, "points", 4),
        _verified_atu(ATUKind.CHOICE, "choice:①", "가"),
        _verified_atu(ATUKind.CHOICE, "choice:②", "나"),
    ]
    # Materialize only partially: body set, points/choice② dropped.
    q.body.append(TextSpan(text="문제"))
    q.choices.append(Choice(label="①"))
    doc.questions.append(q)

    m = build_expected_manifest(doc)
    issues = reconcile(m, doc)
    kinds = {(i["kind"], i.get("field")) for i in issues}
    assert ("missing", "points") in kinds
    assert ("missing", "choice:②") in kinds


def test_zero_atu_question_is_missing_not_zero():
    doc = Document(tenant_id="t")
    doc.questions.append(_q())  # segmented region, zero candidates
    m = build_expected_manifest(doc)
    issues = reconcile(m, doc)
    assert issues == [
        {
            "kind": "no_evidence",
            "label": "1",
            "detail": "question region produced zero candidates",
        }
    ]
    report = evaluate_gate(doc)
    assert report.manifest_mismatch == 1
    assert not report.passed


def test_gate_blocks_without_proof_and_counts_pages():
    doc = Document(tenant_id="t")
    q = _q()
    q.atus = [_verified_atu(ATUKind.NUMBER, "number", 1)]
    q.body.append(TextSpan(text="t"))
    doc.questions.append(q)
    doc.pages.append(
        Page(index=0, original=PageImage(uri="p.png"),
             processing_error="raster failed")
    )
    report = evaluate_gate(doc, artifact_proof="PASS")
    assert report.unprocessed_pages == 1
    assert not report.passed  # unprocessed page blocks the gate

    report2 = evaluate_gate(doc)  # default: NOT_RUN
    assert report2.artifact_proof == "NOT_RUN"
    assert not report2.passed

    assert report.lineage["pages"][0]["processing_error"] == "raster failed"
    assert len(report.lineage["document_sha256"]) == 64


def test_artifact_proof_binds_exact_bytes(tmp_path):
    art = tmp_path / "exam.hwpx"
    art.write_bytes(b"payload-v1")
    binding = bind_artifact_proof(art, "PASS", mismatch_count=0)
    assert verify_artifact_proof(art, binding)

    # Mutated/stale artifact must not inherit the proof.
    art.write_bytes(b"payload-v2-mutated")
    assert not verify_artifact_proof(art, binding)

    # A NOT_RUN binding never verifies, even on unchanged bytes.
    binding = bind_artifact_proof(art, "NOT_RUN", detail="worker_unavailable")
    assert not verify_artifact_proof(art, binding)

    # Missing artifact fails closed.
    assert not verify_artifact_proof(tmp_path / "gone.hwpx", binding)


def test_full_gate_pass_with_bound_proof(tmp_path):
    doc = Document(tenant_id="t")
    q = _q()
    q.atus = [_verified_atu(ATUKind.NUMBER, "number", 1)]
    q.body.append(TextSpan(text="t"))
    doc.questions.append(q)
    art = tmp_path / "exam.hwpx"
    art.write_bytes(b"final-bytes")
    binding = bind_artifact_proof(art, "PASS", mismatch_count=0)
    report = evaluate_gate(doc, artifact_proof=binding["status"])
    assert report.passed
    assert verify_artifact_proof(art, binding)
