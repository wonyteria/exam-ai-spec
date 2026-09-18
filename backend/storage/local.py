from __future__ import annotations

import re
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Protocol


class UnsafeKeyError(ValueError):
    pass


_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


def sanitize_filename(name: str) -> str:
    """Reduce an untrusted filename to a safe single path segment.

    Strips path separators, drive letters, ADS streams, control chars and
    leading dots. Falls back to "file" if nothing safe remains (REQ-25).
    """
    name = unicodedata.normalize("NFKC", name or "")
    name = name.replace("\\", "/").split("/")[-1]
    name = name.split(":")[-1]  # drop drive letters / ADS
    name = "".join(c for c in name if c.isprintable())
    name = name.lstrip(".").strip()
    if not name or not _SAFE_SEGMENT.match(name):
        stem = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80].strip("._")
        name = stem or "file"
    return name


def check_key(key: str) -> PurePosixPath:
    """Validate an object-storage key: relative POSIX path, no traversal,
    no ADS/drive segments, no empty segments."""
    p = PurePosixPath(key)
    if p.is_absolute() or not key:
        raise UnsafeKeyError(f"unsafe key: {key!r}")
    for part in p.parts:
        if part in {"", ".", ".."} or ":" in part or "\\" in part:
            raise UnsafeKeyError(f"unsafe key: {key!r}")
        if not _SAFE_SEGMENT.match(part):
            raise UnsafeKeyError(f"unsafe key segment: {part!r}")
    return p


class ObjectStore(Protocol):
    """Private blob storage contract (ADR-0001). Objects are never served
    directly; API endpoints re-check authorization then read via open()."""

    def put(self, key: str, data: bytes) -> str: ...
    def open(self, uri: str) -> Path: ...
    def exists(self, uri: str) -> bool: ...
    def key_for(self, uri: str) -> str: ...


class LocalObjectStore:
    """Filesystem adapter rooted under a private directory. `uri` values
    are `local://` + key so callers never construct filesystem paths."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, data: bytes) -> str:
        p = check_key(key)
        target = self.root.joinpath(*p.parts)
        resolved = target.resolve()
        if self.root.resolve() not in resolved.parents:
            raise UnsafeKeyError(f"unsafe key: {key!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return f"local://{p.as_posix()}"

    def open(self, uri: str) -> Path:
        key = self.key_for(uri)
        p = check_key(key)
        target = self.root.joinpath(*p.parts)
        resolved = target.resolve()
        if self.root.resolve() not in resolved.parents and resolved != self.root.resolve():
            raise UnsafeKeyError(f"unsafe uri: {uri!r}")
        return resolved

    def exists(self, uri: str) -> bool:
        try:
            return self.open(uri).exists()
        except UnsafeKeyError:
            return False

    def key_for(self, uri: str) -> str:
        if not uri.startswith("local://"):
            raise UnsafeKeyError(f"not a local uri: {uri!r}")
        return uri[len("local://"):]
