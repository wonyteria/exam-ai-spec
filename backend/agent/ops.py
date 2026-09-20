"""RESTORE-25 — Exam Agent MVP.

The agent never edits the document directly: natural-language requests
are translated into typed `ChangeOp`s (canonical operations), a diff
preview is produced, and the caller applies them through
`CanonicalService.apply` — which creates a revision. Undo/redo and
digest pinning come from the canonical layer, not the agent.

Supported commands (Korean-first):
  "3번과 7번 바꿔줘"            -> SwapQuestions
  "5번을 맨 뒤로 / 맨 앞으로"   -> MoveQuestion
  "도형 문제를 뒤로 보내줘"      -> ReorderQuestions (figures last)
  "서술형을 마지막에 넣어줘"     -> ReorderQuestions (descriptive last)
  "20문제를 15문제로 줄여줘"     -> RemoveQuestion (trailing, previewed)
  "제목을 '...'로 바꿔줘"        -> SetMetadata(title)
  "학원 스타일 X 적용해줘"       -> SetStyle(brand_id)
Unrecognized commands return a proposal with `recognized=False` —
never a silent no-op.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from canonical.models import ChangeOp
from document.models import Document


@dataclass
class AgentProposal:
    command: str
    ops: list[ChangeOp] = field(default_factory=list)
    recognized: bool = True
    explanation: str = ""
    preview: list[str] = field(default_factory=list)  # human-readable diff


def _order_labels(doc: Document) -> list[str]:
    return [q.label or str(q.number) for q in doc.questions]


def _resolve(doc: Document, token: str) -> Optional[str]:
    token = token.strip().rstrip("번")
    for q in doc.questions:
        if str(q.number) == token or q.label == token:
            return q.id
    return None


def parse_command(doc: Document, command: str) -> AgentProposal:
    cmd = command.strip()
    p = AgentProposal(command=cmd)

    m = re.search(r"(\d+)번(?:과|하고)?\s*(\d+)번?\s*(?:순서를?\s*)?바꿔", cmd)
    if m:
        a, b = _resolve(doc, m.group(1)), _resolve(doc, m.group(2))
        if a and b:
            p.ops = [
                ChangeOp(op="SwapQuestions", target_id=a, value=b,
                         reason=cmd)
            ]
            p.explanation = f"{m.group(1)} ↔ {m.group(2)} 위치 교환"
        else:
            p.recognized = False
            p.explanation = "대상 문항을 찾을 수 없습니다"
        return _with_preview(doc, p)

    m = re.search(r"(\d+)번?을?\s*맨?\s*(뒤|앞)(?:으)?로", cmd)
    if m:
        target = _resolve(doc, m.group(1))
        if target:
            pos = len(doc.questions) - 1 if m.group(2) == "뒤" else 0
            p.ops = [
                ChangeOp(op="MoveQuestion", target_id=target, value=pos,
                         reason=cmd)
            ]
            p.explanation = f"{m.group(1)}번 → {'맨 뒤' if pos else '맨 앞'}"
        else:
            p.recognized = False
            p.explanation = "대상 문항을 찾을 수 없습니다"
        return _with_preview(doc, p)

    if re.search(r"도형.*뒤로", cmd):
        with_fig = [q.id for q in doc.questions if not q.figures]
        figs = [q.id for q in doc.questions if q.figures]
        if figs:
            p.ops = [
                ChangeOp(op="ReorderQuestions", value=with_fig + figs,
                         reason=cmd)
            ]
            p.explanation = "도형 문항을 뒤로 재배치"
            return _with_preview(doc, p)

    if re.search(r"서술형.*(마지막|뒤)", cmd):
        obj = [
            q.id for q in doc.questions
            if q.type.value == "multiple_choice"
        ]
        desc = [q.id for q in doc.questions if q.id not in set(obj)]
        if desc:
            p.ops = [
                ChangeOp(op="ReorderQuestions", value=obj + desc,
                         reason=cmd)
            ]
            p.explanation = "서술형을 마지막으로 재배치"
            return _with_preview(doc, p)

    m = re.search(r"(\d+)\s*문제를?\s*(\d+)\s*문제로?\s*줄여", cmd)
    if m:
        keep = int(m.group(2))
        if 0 < keep < len(doc.questions):
            extras = doc.questions[keep:]
            for q in extras:
                p.ops.append(
                    ChangeOp(op="RemoveQuestion", target_id=q.id,
                             reason=cmd)
                )
            p.explanation = (
                f"뒤쪽 {len(extras)}문항 제거 → {keep}문항"
            )
            return _with_preview(doc, p)

    m = re.search(r"제목을?\s*['\"]([^'\"]+)['\"]", cmd)
    if m:
        p.ops = [
            ChangeOp(op="SetMetadata", field="title", value=m.group(1),
                     reason=cmd)
        ]
        p.explanation = f"제목 → {m.group(1)}"
        return _with_preview(doc, p)

    m = re.search(r"스타일\s*(\S+)\s*(을|를)?\s*적용", cmd)
    if m:
        p.ops = [
            ChangeOp(op="SetStyle", field="brand_id",
                     value=m.group(1), reason=cmd)
        ]
        p.explanation = f"스타일 → {m.group(1)}"
        return _with_preview(doc, p)

    p.recognized = False
    p.explanation = "지원하지 않는 명령 — 사람이 확인 필요"
    return p


def _with_preview(doc: Document, p: AgentProposal) -> AgentProposal:
    """Describe the resulting order/field diff before apply — the caller
    shows this, gets approval, then calls service.apply (revisioned)."""
    before = _order_labels(doc)
    p.preview = [f"before: {before}"]
    for op in p.ops:
        if op.op in ("MoveQuestion", "SwapQuestions", "ReorderQuestions"):
            p.preview.append(f"op: {op.op} {op.target_id or ''} -> {op.value}")
        elif op.op == "RemoveQuestion":
            p.preview.append(f"op: remove {op.target_id}")
        else:
            p.preview.append(f"op: {op.op} {op.field or ''} = {op.value}")
    return p
