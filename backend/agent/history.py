"""Agent conversation history — per-turn audit + revision linkage.

Every chat command is recorded as a turn BEFORE anything is applied:
command text, parsed ChangeOps, recognition status, preview, and the
If-Match revision the proposal was computed against. When the client
approves and submits the ops through /changes, the resulting revision id
is written back onto the turn — the audit trail reads
command -> proposal -> revision end to end.

Storage: one JSONL file per document under data/agent_history/ —
append-only, no schema migration needed.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional


class AgentHistory:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, doc_id: str) -> Path:
        safe = "".join(c for c in doc_id if c.isalnum() or c in "-_")
        return self.root / f"{safe}.jsonl"

    def record_turn(
        self,
        doc_id: str,
        user_id: str,
        command: str,
        proposal: Any,
        if_match: Optional[str],
    ) -> dict:
        turn = {
            "id": uuid.uuid4().hex[:12],
            "doc_id": doc_id,
            "user_id": user_id,
            "ts": time.time(),
            "command": command,
            "recognized": bool(proposal.recognized),
            "explanation": proposal.explanation,
            "preview": list(proposal.preview),
            "ops": [op.model_dump() for op in proposal.ops],
            "pending_action": getattr(proposal, "pending_action", None),
            "base_revision_id": if_match,
            "applied_revision_id": None,
        }
        with self._path(doc_id).open("a", encoding="utf-8") as f:
            f.write(json.dumps(turn, ensure_ascii=False) + "\n")
        return turn

    def link_revision(
        self, doc_id: str, turn_id: str, revision_id: str
    ) -> bool:
        """Attach the applied revision to its proposal turn."""
        path = self._path(doc_id)
        if not path.exists():
            return False
        lines = path.read_text(encoding="utf-8").splitlines()
        for i in range(len(lines) - 1, -1, -1):
            if not lines[i].strip():
                continue
            turn = json.loads(lines[i])
            if turn.get("id") == turn_id:
                turn["applied_revision_id"] = revision_id
                lines[i] = json.dumps(turn, ensure_ascii=False)
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                return True
        return False

    def list_turns(self, doc_id: str, limit: int = 100) -> list[dict]:
        path = self._path(doc_id)
        if not path.exists():
            return []
        turns = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return turns[-limit:]
