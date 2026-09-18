from __future__ import annotations

import os
from pathlib import Path

from jobs.store import Store
from storage.local import LocalObjectStore
from tenancy.db import TenancyDB

_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_store: Store | None = None
_tenancy: TenancyDB | None = None
_objects: LocalObjectStore | None = None


def data_dir() -> Path:
    """Resolved at call time so tests/operators can point EXAMDNA_DATA
    elsewhere without re-importing modules."""
    return Path(os.environ.get("EXAMDNA_DATA", _DEFAULT_DATA_DIR))


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store(data_dir())
    return _store


def get_tenancy() -> TenancyDB:
    global _tenancy
    if _tenancy is None:
        _tenancy = TenancyDB(data_dir() / "tenancy.db")
    return _tenancy


def get_object_store() -> LocalObjectStore:
    global _objects
    if _objects is None:
        _objects = LocalObjectStore(data_dir() / "objects")
    return _objects


def reset() -> None:
    """Test hook: drop cached singletons (e.g. after EXAMDNA_DATA changes)."""
    global _store, _tenancy, _objects
    if _tenancy is not None:
        _tenancy.close()
    _store = _tenancy = _objects = None
