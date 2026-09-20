"""RESTORE-05 — source truth: independent-evidence consensus only.

Locks: a single provider (any confidence), a retried provider, and a
family of paired reference HWPs each count as ONE source; only >=2
independent sources agreeing on the exact value yield AUTO_VERIFIED;
disagreement stays CONFLICT; human verdicts are never re-litigated.
"""
from __future__ import annotations

from core.examdna.source_truth import consensus
from core.examdna.context import PipelineContext, Providers
from document.models import (
    ATU,
    ATUKind,
    Candidate,
    Document,
    Question,
    VerificationStatus,
)
from jobs.models import Job


def _ctx(doc):
    return PipelineContext(
        document=doc,
        job=Job(id="j", document_id=doc.id),
        store=None,
        workdir=None,
        providers=Providers(),
        event_sink=lambda *a: None,
    )


def _atu(*candidates: tuple[str, object]) -> ATU:
    atu = ATU(kind=ATUKind.TEXT_TOKEN, field="body")
    for provider, value in candidates:
        atu.candidates.append(
            Candidate(provider=provider, value=value, confidence=0.99)
        )
    return atu


def _run(atu: ATU) -> ATU:
    doc = Document(tenant_id="t")
    q = Question(number=1, label="1")
    q.atus.append(atu)
    doc.questions.append(q)
    consensus.run(_ctx(doc))
    return atu


def test_single_high_confidence_never_auto_verifies():
    atu = _run(_atu(("ocr", "42")))
    assert atu.status == VerificationStatus.UNVERIFIED
    assert atu.note == "single_source"
    assert atu.value is None


def test_same_provider_retry_is_one_source():
    atu = _run(_atu(("ocr", "42"), ("ocr", "42"), ("ocr", "42")))
    assert atu.status == VerificationStatus.UNVERIFIED


def test_two_independent_providers_agree():
    atu = _run(_atu(("paddle", "42"), ("openai", "42")))
    assert atu.status == VerificationStatus.AUTO_VERIFIED
    assert atu.value == "42"
    assert "independent_sources:2" in atu.note


def test_paired_references_are_one_evidence_family():
    # Two academies' HWP copies agreeing is still one source (spec 3.1).
    atu = _run(_atu(("reference:seum", "42"), ("reference:jinsu", "42")))
    assert atu.status == VerificationStatus.UNVERIFIED


def test_reference_plus_provider_verifies():
    atu = _run(_atu(("reference:seum", "42"), ("paddle", "42")))
    assert atu.status == VerificationStatus.AUTO_VERIFIED


def test_disagreement_is_conflict_not_majority():
    # 2-vs-1 must not resolve by majority.
    atu = _run(_atu(("a", "42"), ("b", "42"), ("c", "43")))
    assert atu.status == VerificationStatus.CONFLICT
    assert atu.value is None
    assert "conflict:" in atu.note


def test_no_candidates_unreadable():
    atu = _run(_atu())
    assert atu.status == VerificationStatus.UNREADABLE


def test_human_verdict_never_overridden():
    atu = _atu(("a", "41"), ("b", "43"))
    atu.status = VerificationStatus.HUMAN_VERIFIED
    atu.value = "41"
    _run(atu)
    assert atu.status == VerificationStatus.HUMAN_VERIFIED
    assert atu.value == "41"
