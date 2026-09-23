from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import jobs.runner as runner
from jobs.store import Store


@pytest.fixture(autouse=True)
def no_real_providers(monkeypatch):
    """Tests never call real AI providers — every cloud/local adapter
    factory is stubbed so ambient env keys (OPENAI_API_KEY etc.) can't
    leak a real client into a test run."""
    monkeypatch.setattr(runner, "_gemini_provider", lambda: None)
    monkeypatch.setattr(runner, "_openai_provider", lambda *a, **kw: None)
    monkeypatch.setattr(runner, "_local_provider", lambda *a, **kw: None)
    monkeypatch.setattr(runner, "_local_vision_provider", lambda: None)
    monkeypatch.setenv("EXAMDNA_ENABLE_LOCAL_PAGE_RESTORE", "0")


@pytest.fixture()
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "data")


@pytest.fixture()
def sample_png(tmp_path: Path) -> Path:
    img = Image.new("RGB", (800, 600), "white")
    path = tmp_path / "page1.png"
    img.save(path)
    return path
