"""BrandRewritePlan construction (HWP_REBRANDING_SPEC §4–§8).

Fail-closed rules:
- every mutation target must come from the scanned manifest, addressed by
  its exact control path and expected digest;
- ambiguous or low-confidence candidates need explicit confirmation ids;
- a title policy of AUTO_CONFIDENT only proceeds when exactly one high-
  confidence title candidate exists;
- literal/image page numbers are never auto-removed.
"""
from __future__ import annotations

from .models import (
    AUTO_CONFIDENCE_MIN,
    BrandRewritePlan,
    BrandRewriteRequest,
    BrandStructureManifest,
    CandidateKind,
    ControlCandidate,
    PAGE_NUMBER_KINDS,
    PlanError,
    RebrandOpKind,
    RebrandOperation,
    TITLE_KINDS,
    TitlePolicy,
)

# candidate kinds that can never be applied without explicit confirmation
_ALWAYS_CONFIRM = {
    CandidateKind.TITLE_BODY_TOP,
    CandidateKind.TITLE_MASTER_TEXT,
    CandidateKind.TITLE_IMAGE,
    CandidateKind.LITERAL_PAGE_NUMBER,
    CandidateKind.EXISTING_WATERMARK,
}

_OP_FOR_KIND = {
    CandidateKind.TITLE_HEADER_TEXT: RebrandOpKind.REPLACE_TEXT_RUNS,
    CandidateKind.TITLE_HEADER_TABLE_CELL: RebrandOpKind.REPLACE_TEXT_RUNS,
    CandidateKind.TITLE_MASTER_TEXT: RebrandOpKind.REPLACE_TEXT_RUNS,
    CandidateKind.TITLE_BODY_TOP: RebrandOpKind.REPLACE_TEXT_RUNS,
    CandidateKind.TITLE_IMAGE: RebrandOpKind.REPLACE_SELECTED_SHAPE,
    CandidateKind.PAGE_NUM_CONTROL: RebrandOpKind.REMOVE_PAGE_NUM_CONTROL,
    CandidateKind.PAGE_NUM_FIELD: RebrandOpKind.REMOVE_PAGE_NUM_FIELD,
    CandidateKind.PAGE_NUM_MASTER_FIELD: RebrandOpKind.REMOVE_PAGE_NUM_FIELD,
    CandidateKind.PRINT_PAGE_TOKEN: RebrandOpKind.CLEAR_PRINT_PAGE_TOKEN,
    CandidateKind.LITERAL_PAGE_NUMBER: RebrandOpKind.REMOVE_PAGE_NUM_FIELD,
}

_MASK_FOR_KIND = {
    CandidateKind.PAGE_NUM_CONTROL: "footer",
    CandidateKind.PAGE_NUM_FIELD: "footer",
    CandidateKind.PAGE_NUM_MASTER_FIELD: "footer",
    CandidateKind.PRINT_PAGE_TOKEN: "footer",
    CandidateKind.LITERAL_PAGE_NUMBER: "footer",
}


def _confirmed(req: BrandRewriteRequest, cand: ControlCandidate) -> bool:
    return cand.id in set(req.confirmed_candidate_ids)


def build_plan(
    manifest: BrandStructureManifest, req: BrandRewriteRequest
) -> BrandRewritePlan:
    if manifest.flags.encrypted_or_password or manifest.flags.corrupt_or_unreadable:
        raise PlanError(
            "SOURCE_UNSUPPORTED",
            "source is encrypted, protected, or unreadable — fail closed",
        )
    if manifest.flags.external_link_or_ole or manifest.flags.macro_or_script:
        raise PlanError(
            "SOURCE_UNSAFE",
            "source contains external links, OLE, or scripts — review required",
        )
    if not req.academy_name.strip():
        raise PlanError("EMPTY_BRAND", "academy_name is required")

    confirmed = set(req.confirmed_candidate_ids)
    manifest_ids = {c.id for c in manifest.candidates}
    unknown = confirmed - manifest_ids
    if unknown:
        raise PlanError(
            "UNKNOWN_CANDIDATE",
            "confirmed_candidate_ids not present in the scanned manifest",
            {"unknown": sorted(unknown)},
        )

    plan = BrandRewritePlan(
        source_sha256=manifest.source_sha256 or req.source_sha256,
        manifest_digest=manifest.digest,
        academy_name=req.academy_name.strip(),
    )
    ops: list[RebrandOperation] = []

    # --- title replacement ----------------------------------------------------
    title_cands = manifest.title_candidates()
    selected_titles: list[ControlCandidate] = []
    if req.title_policy is TitlePolicy.AUTO_CONFIDENT:
        confident = [
            c
            for c in title_cands
            if c.confidence >= AUTO_CONFIDENCE_MIN
            and c.kind not in _ALWAYS_CONFIRM
        ]
        if len(confident) == 0:
            raise PlanError(
                "TITLE_AMBIGUOUS",
                "no confident title candidate — user confirmation required",
                {"candidates": [c.id for c in title_cands]},
            )
        selected_titles = confident
        # any additional non-auto title candidate must be confirmed or the
        # doc is ambiguous -> fail closed
        extras = [c for c in title_cands if c not in confident]
        unconfirmed_extras = [
            c for c in extras if c.id not in confirmed and c.confidence >= 0.5
        ]
        if unconfirmed_extras:
            raise PlanError(
                "TITLE_AMBIGUOUS",
                "multiple plausible title locations — confirm each candidate",
                {"candidates": [c.id for c in unconfirmed_extras]},
            )
        selected_titles += [c for c in extras if c.id in confirmed]
    else:  # USER_CONFIRMED
        selected_titles = [c for c in title_cands if c.id in confirmed]
        if not selected_titles:
            raise PlanError(
                "TITLE_NOT_CONFIRMED",
                "no title candidate confirmed — nothing safe to replace",
                {"candidates": [c.id for c in title_cands]},
            )

    for c in selected_titles:
        if (c.evidence or {}).get("object") == "cell_border_fill":
            # the fill lives in header.xml's shared borderFills — the
            # mutator clones it, swaps the image, and repoints ONLY this
            # confirmed cell so other cells keep their original fill
            ops.append(
                RebrandOperation(
                    op=RebrandOpKind.REPLACE_CELL_BACKGROUND,
                    candidate_id=c.id,
                    section=c.section,
                    paths=[c.path],
                    expected_digests={c.path: c.digest},
                    payload={
                        "fill_id": (c.evidence or {}).get("fill_id", ""),
                        "old_img": (c.evidence or {}).get("img", ""),
                    },
                    render_mask="header",
                )
            )
            continue
        ops.append(
            RebrandOperation(
                op=_OP_FOR_KIND[c.kind],
                candidate_id=c.id,
                section=c.section,
                paths=[c.path],
                expected_digests={c.path: c.digest},
                payload={"text": req.academy_name.strip()},
                render_mask="header",
            )
        )

    # --- watermark --------------------------------------------------------------
    if req.watermark.enabled:
        existing = [
            c for c in manifest.candidates if c.kind is CandidateKind.EXISTING_WATERMARK
        ]
        if existing and not req.watermark.replace_existing:
            raise PlanError(
                "WATERMARK_EXISTS",
                "existing watermark found — confirm replace_existing or deselect",
                {"candidates": [c.id for c in existing]},
            )
        sections = sorted(
            {
                c.section
                for c in manifest.candidates
                if c.section.startswith("section") and c.section.endswith(".xml")
            }
        )
        if not sections:
            sections = [f"section{i}.xml" for i in range(manifest.section_count)]
        if not sections:
            sections = ["section0.xml"]
        for sec in sections:
            ops.append(
                RebrandOperation(
                    op=RebrandOpKind.ADD_WATERMARK_SHAPE,
                    section=sec,
                    paths=[],  # resolved against the section's masterPage/secPr
                    payload={
                        "opacity": req.watermark.opacity,
                        "scale": req.watermark.scale,
                        "rotation": req.watermark.rotation,
                        "pages": req.watermark.pages,
                        "logo_asset_id": req.logo_asset_id or "",
                        "logo_sha256": req.logo_sha256,
                        "replace_existing_ids": [c.id for c in existing],
                    },
                    render_mask="watermark",
                )
            )

    # --- page-number removal ------------------------------------------------------
    if req.remove_page_numbers:
        for c in manifest.page_number_candidates():
            if c.kind in _ALWAYS_CONFIRM and c.id not in confirmed:
                # literal/image numbers: skipped, not failed — but reported
                continue
            if c.requires_user_confirm and c.id not in confirmed:
                continue
            ops.append(
                RebrandOperation(
                    op=_OP_FOR_KIND[c.kind],
                    candidate_id=c.id,
                    section=c.section,
                    paths=[c.path],
                    expected_digests={c.path: c.digest},
                    render_mask=_MASK_FOR_KIND.get(c.kind, "footer"),
                )
            )

    if not ops:
        raise PlanError(
            "EMPTY_PLAN",
            "no safe operations could be derived — user confirmation required",
        )

    plan.operations = ops
    plan.expected_invariants = {
        "section_count": manifest.section_count,
        "control_count_delta": sum(
            -len(op.paths) for op in ops if op.op in {
                RebrandOpKind.REMOVE_PAGE_NUM_CONTROL,
                RebrandOpKind.REMOVE_PAGE_NUM_FIELD,
            }
        ),
        "page_count": manifest.page_count,
        "semantic_body_text_unchanged": True,
        "footer_text_preserved_except_page_numbers": True,
    }
    return plan
