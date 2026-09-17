from __future__ import annotations

import os
from pathlib import Path

from jobs.store import Store

DATA_DIR = Path(os.environ.get("EXAMDNA_DATA", Path(__file__).resolve().parent.parent / "data"))

_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store(DATA_DIR)
    return _store
