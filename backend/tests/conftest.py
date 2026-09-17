from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jobs.store import Store


@pytest.fixture()
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "data")


@pytest.fixture()
def sample_png(tmp_path: Path) -> Path:
    img = Image.new("RGB", (800, 600), "white")
    path = tmp_path / "page1.png"
    img.save(path)
    return path
