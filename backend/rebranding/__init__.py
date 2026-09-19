"""Safe rebranding of existing HWP/HWPX exam files (REQ-16).

Pipeline: immutable source -> structure census -> user-confirmed plan ->
allowlisted mutation on a copy -> invariant proof -> real Hancom COM proof.
"""
from .models import (
    BrandRewritePlan,
    BrandRewriteRequest,
    BrandStructureManifest,
    CandidateKind,
    ControlCandidate,
    InvariantReport,
    PlanError,
    RebrandOpKind,
    RebrandOperation,
    TitlePolicy,
    WatermarkSpec,
)
from .planner import build_plan
from .scanner import scan_hwpx

__all__ = [
    "BrandRewritePlan",
    "BrandRewriteRequest",
    "BrandStructureManifest",
    "CandidateKind",
    "ControlCandidate",
    "InvariantReport",
    "PlanError",
    "RebrandOpKind",
    "RebrandOperation",
    "TitlePolicy",
    "WatermarkSpec",
    "build_plan",
    "scan_hwpx",
]
