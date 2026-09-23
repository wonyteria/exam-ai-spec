"""AcademyProfile persistence — one JSON document per tenant.

Profiles are presentation config, not exam content: a small JSON store
per tenant is sufficient and keeps them out of the canonical revision
system (which tracks Document content, not academy preferences).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

from .profile import AcademyProfile


class AcademyProfileStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, tenant_id: str) -> Path:
        safe = "".join(c for c in tenant_id if c.isalnum() or c in "-_")
        return self.root / f"{safe}.json"

    def _read(self, tenant_id: str) -> dict[str, dict]:
        path = self._path(tenant_id)
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, tenant_id: str, data: dict[str, dict]) -> None:
        self._path(tenant_id).write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list(self, tenant_id: str) -> list[AcademyProfile]:
        with self._lock:
            return [
                AcademyProfile.model_validate(v)
                for v in self._read(tenant_id).values()
            ]

    def get(
        self, tenant_id: str, academy_id: str
    ) -> Optional[AcademyProfile]:
        with self._lock:
            raw = self._read(tenant_id).get(academy_id)
        return AcademyProfile.model_validate(raw) if raw else None

    def upsert(self, tenant_id: str, profile: AcademyProfile) -> None:
        with self._lock:
            data = self._read(tenant_id)
            data[profile.academy_id] = profile.model_dump()
            self._write(tenant_id, data)

    def delete(self, tenant_id: str, academy_id: str) -> bool:
        with self._lock:
            data = self._read(tenant_id)
            if academy_id not in data:
                return False
            del data[academy_id]
            self._write(tenant_id, data)
            return True
