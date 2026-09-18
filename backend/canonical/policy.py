from __future__ import annotations

from .models import RevisionMode, VerificationPolicySnapshot

# Required content checks from 02_ARCHITECTURE_CONTRACTS §7.1.
# The list is fixed by policy version — a missing capability registers
# UNAVAILABLE and blocks final; it never shrinks the list.
CONTENT_CHECKS_V1 = [
    "SCHEMA_REFERENTIAL_INTEGRITY",
    "SOURCE_REGION_COVERAGE",
    "ORIGINAL_SOURCE_FIDELITY",
    "QUESTION_CHOICE_SCORE_COMPLETENESS",
    "MATH_FIGURE_SEMANTIC_CONSISTENCY",
    "SOLVE_TWO_INDEPENDENT_AGREEMENT",
    "ANSWER_SOLUTION_LOGIC",
    "CURRICULUM_COMPLIANCE",
    "REQUIRED_CONTENT_COVERAGE",
    "BLOCKING_ISSUES_CLOSED",
]

CONTENT_CHECKS_EDIT_EXTRA = ["APPROVED_EDIT_CONFORMANCE"]

ARTIFACT_CHECKS_BY_FORMAT_V1 = {
    "hwpx": [
        "FORMAT_OPEN_VALIDITY",
        "NATIVE_OBJECT_INTEGRITY",
        "ARTIFACT_SEMANTIC_COVERAGE",
        "RENDERED_TEXT_VISUAL_MATCH",
        "LAYOUT_STYLE_BOUNDS",
        "FORMAT_CONVERSION_PROVENANCE",
        "OUTPUT_MODE_CONTENT_POLICY",
        "ARTIFACT_HASH_BINDING",
    ],
    "hwp": [
        "FORMAT_OPEN_VALIDITY",
        "NATIVE_OBJECT_INTEGRITY",
        "ARTIFACT_SEMANTIC_COVERAGE",
        "RENDERED_TEXT_VISUAL_MATCH",
        "LAYOUT_STYLE_BOUNDS",
        "FORMAT_CONVERSION_PROVENANCE",
        "HWP_ACTUAL_REOPEN",
        "OUTPUT_MODE_CONTENT_POLICY",
        "ARTIFACT_HASH_BINDING",
    ],
    "pdf": [
        "FORMAT_OPEN_VALIDITY",
        "ARTIFACT_SEMANTIC_COVERAGE",
        "RENDERED_TEXT_VISUAL_MATCH",
        "LAYOUT_STYLE_BOUNDS",
        "OUTPUT_MODE_CONTENT_POLICY",
        "ARTIFACT_HASH_BINDING",
    ],
}


def restore_policy(output_mode: str = "STUDENT_WITH_ENDNOTES") -> VerificationPolicySnapshot:
    return VerificationPolicySnapshot(
        policy_id="EXAM_CONTENT_RESTORE_V1",
        version="1",
        mode=RevisionMode.RESTORE,
        output_mode=output_mode,
        required_content_checks=list(CONTENT_CHECKS_V1),
        required_artifact_checks_by_format={
            k: list(v) for k, v in ARTIFACT_CHECKS_BY_FORMAT_V1.items()
        },
        validator_versions={"schema": "1", "completeness": "1"},
        minimum_solver_attempts=2,
    )


def edit_policy(output_mode: str = "STUDENT_WITH_ENDNOTES") -> VerificationPolicySnapshot:
    p = restore_policy(output_mode)
    p.policy_id = "EXAM_CONTENT_EDIT_V1"
    p.mode = RevisionMode.EDIT
    p.required_content_checks = CONTENT_CHECKS_V1 + CONTENT_CHECKS_EDIT_EXTRA
    return p
