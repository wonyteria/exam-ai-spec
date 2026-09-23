"""Derive question- and document-level restoration status.

Status precedence (highest wins):
  USER_CONFIRMED  — human explicitly confirmed; refresh never downgrades
  USER_EDITED     — human applied a structured op; recomputed: if the
                    edit left unresolved issues the question returns to
                    NEEDS_USER_REVIEW
  BLOCKED         — nothing usable was recognized at all
  NEEDS_USER_REVIEW — unresolved ATUs, logic flags, or recorded issues
  AUTO_CORRECTED  — clean, but deterministic fixes were applied
  AUTO_RESTORED   — clean, no fixes needed
"""
from __future__ import annotations

from document.models import (
    ATU,
    ATUKind,
    DocRestorationStatus,
    Document,
    FieldIssue,
    Question,
    QuestionStatus,
    VerificationStatus,
)

_RESOLVED_ATU = {
    VerificationStatus.AUTO_VERIFIED,
    VerificationStatus.HUMAN_VERIFIED,
}

# Reasons produced from ATU state — rebuilt on every refresh so a human
# resolution clears its issue. Other reasons (occlusion, print/handwriting
# overlap, recorded at flag time) persist until the field is edited.
_ATU_REASONS = {"conflict", "unverified", "unreadable", "sign_ambiguity"}


def atu_issues(atu: ATU) -> list[FieldIssue]:
    """FieldIssues implied by one ATU's current state."""
    field = atu.field or atu.kind.value
    out: list[FieldIssue] = []
    if atu.status == VerificationStatus.CONFLICT:
        out.append(FieldIssue(
            field=field, reason="conflict",
            detail=atu.note or "후보 간 불일치"))
    elif atu.status == VerificationStatus.UNREADABLE:
        out.append(FieldIssue(
            field=field, reason="unreadable", detail="인식 후보 없음"))
    elif atu.status == VerificationStatus.UNVERIFIED:
        detail = "단일 출처 후보" if atu.candidates else "후보 없음"
        if atu.kind in (ATUKind.LENGTH, ATUKind.ANGLE, ATUKind.FIGURE_LABEL):
            detail = "도형 길이·각도·라벨 미확정 — " + detail
        elif atu.kind in (ATUKind.NUMBER, ATUKind.POINTS):
            detail = "의미를 바꿀 수 있는 숫자 — " + detail
        out.append(FieldIssue(field=field, reason="unverified",
                              detail=detail))
    if atu.kind in (ATUKind.NUMBER, ATUKind.CHOICE):
        vals = {str(c.value).strip() for c in atu.candidates}
        for v in list(vals):
            if v.startswith("-") and v[1:] in vals:
                out.append(FieldIssue(
                    field=field, reason="sign_ambiguity",
                    detail=f"부호 불일치 후보: {sorted(vals)}"))
                break
    return out


def refresh_question_status(q: Question) -> QuestionStatus:
    """Recompute confidence + issues-derived status. USER_CONFIRMED is
    sticky; USER_EDITED is re-evaluated (an edit may still leave issues).
    Returns the resulting status (also written back to the question)."""
    current = q.restoration.status
    if current == QuestionStatus.USER_CONFIRMED:
        return current

    with_candidates = [a for a in q.atus if a.candidates]
    verified = [a for a in with_candidates if a.status in _RESOLVED_ATU]
    q.restoration.confidence = (
        len(verified) / len(with_candidates) if with_candidates else 0.0
    )

    # Rebuild ATU-derived issues; keep environmental flags (overlap,
    # occluded body) recorded by the correction stage.
    kept = [i for i in q.restoration.issues if i.reason not in _ATU_REASONS]
    fresh: list[FieldIssue] = []
    for atu in q.atus:
        fresh.extend(atu_issues(atu))
    seen = {(i.field, i.reason, i.detail) for i in kept}
    q.restoration.issues = kept + [
        i for i in fresh if (i.field, i.reason, i.detail) not in seen
    ]

    has_content = bool(q.body or q.choices or q.equations or q.figures)
    if not q.atus and not has_content:
        q.restoration.status = QuestionStatus.BLOCKED
        return q.restoration.status

    unresolved = any(
        a.status
        in (
            VerificationStatus.UNVERIFIED,
            VerificationStatus.CONFLICT,
            VerificationStatus.UNREADABLE,
        )
        for a in q.atus
    )
    needs_review = bool(
        unresolved or q.restoration.issues or q.verification.logic_flags
    )
    if needs_review:
        q.restoration.status = QuestionStatus.NEEDS_USER_REVIEW
    elif current == QuestionStatus.USER_EDITED:
        q.restoration.status = QuestionStatus.USER_EDITED
    elif q.restoration.corrections:
        q.restoration.status = QuestionStatus.AUTO_CORRECTED
    else:
        q.restoration.status = QuestionStatus.AUTO_RESTORED
    return q.restoration.status


def refresh_document_status(doc: Document) -> str:
    """RESTORED_BEST_EFFORT ⇢ some BLOCKED but nothing awaiting a human;
    NEEDS_USER_REVIEW ⇢ at least one question needs a human decision;
    READY_FOR_FINAL_EXPORT ⇢ everything resolved.
    IN_PROGRESS is preserved while the pipeline is still running."""
    if doc.verification.status == "IN_PROGRESS":
        return doc.verification.restoration_status
    questions = list(doc.questions)
    if not questions:
        doc.verification.restoration_status = (
            DocRestorationStatus.RESTORED_BEST_EFFORT.value
        )
        return doc.verification.restoration_status
    statuses = {q.restoration.status for q in questions}
    if QuestionStatus.NEEDS_USER_REVIEW in statuses:
        doc.verification.restoration_status = (
            DocRestorationStatus.NEEDS_USER_REVIEW.value
        )
    elif QuestionStatus.BLOCKED in statuses:
        doc.verification.restoration_status = (
            DocRestorationStatus.RESTORED_BEST_EFFORT.value
        )
    else:
        doc.verification.restoration_status = (
            DocRestorationStatus.READY_FOR_FINAL_EXPORT.value
        )
    return doc.verification.restoration_status


def status_counts(doc: Document) -> dict[str, int]:
    counts = {s.value: 0 for s in QuestionStatus}
    for q in doc.questions:
        counts[q.restoration.status.value] += 1
    counts["total"] = len(doc.questions)
    return counts
