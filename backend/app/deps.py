from __future__ import annotations

import os
from pathlib import Path

from canonical.store import CanonicalStore
from jobs.store import Store
from storage.local import LocalObjectStore
from tenancy.db import TenancyDB

_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_store: Store | None = None
_tenancy: TenancyDB | None = None
_objects: LocalObjectStore | None = None
_canonical: CanonicalStore | None = None
_profiles = None
_agent_history = None


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


def get_canonical() -> CanonicalStore:
    global _canonical
    if _canonical is None:
        _canonical = CanonicalStore(data_dir() / "canonical.db")
    return _canonical


def get_profiles():
    """Academy profile store — presentation config, not exam content."""
    global _profiles
    if _profiles is None:
        from academy.store import AcademyProfileStore

        _profiles = AcademyProfileStore(data_dir() / "profiles")
    return _profiles


def get_agent_history():
    """Per-document agent turn log (command -> proposal -> revision)."""
    global _agent_history
    if _agent_history is None:
        from agent.history import AgentHistory

        _agent_history = AgentHistory(data_dir() / "agent_history")
    return _agent_history


def reset() -> None:
    """Test hook: drop cached singletons (e.g. after EXAMDNA_DATA changes)."""
    global _store, _tenancy, _objects, _canonical, _profiles, _agent_history
    if _tenancy is not None:
        _tenancy.close()
    if _canonical is not None:
        _canonical.close()
    _store = _tenancy = _objects = _canonical = _profiles = _agent_history = None
