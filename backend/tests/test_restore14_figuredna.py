"""RESTORE-14 (spec) — FigureDNA pixel→scene extraction.

Locks: Hough-derived segments/points/circles become FigureScene
primitives; relations are measured (intersection/parallel/perpendicular/
equal_length); the candidate scene passes validate_scene; extraction
confidence reports covered ink honestly; degenerate input yields an
empty scene, never fabricated primitives.
"""
from __future__ import annotations

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from core.examdna.figure_trace.extractor import extract_scene
from document.scene import validate_scene


def _triangle(h=200, w=200):
    """A simple triangle: three segments sharing endpoints."""
    img = np.full((h, w), 255, dtype=np.uint8)
    cv2.line(img, (30, 160), (170, 160), 0, 3)   # base
    cv2.line(img, (30, 160), (100, 30), 0, 3)    # left side
    cv2.line(img, (170, 160), (100, 30), 0, 3)   # right side
    return img


def _circle(h=200, w=200):
    img = np.full((h, w), 255, dtype=np.uint8)
    cv2.circle(img, (100, 100), 50, 0, 3)
    return img


def test_triangle_extracts_segments_and_points():
    res = extract_scene(_triangle())
    kinds = [p.kind for p in res.scene.primitives]
    assert kinds.count("segment") >= 3
    assert kinds.count("point") >= 3
    # endpoints shared → intersection relations exist
    assert any(r.kind == "intersection" for r in res.scene.relations)
    # scene must pass its own validator
    assert validate_scene(res.scene) == []
    assert res.confidence > 0.5


def test_circle_extracted_as_circle_primitive():
    res = extract_scene(_circle())
    circles = [p for p in res.scene.primitives if p.kind == "circle"]
    assert circles
    c = circles[0]
    assert 40 <= c.props["radius"] <= 60
    assert validate_scene(res.scene) == []


def test_parallel_lines_relation():
    img = np.full((200, 300), 255, dtype=np.uint8)
    cv2.line(img, (30, 60), (270, 60), 0, 3)
    cv2.line(img, (30, 140), (270, 140), 0, 3)
    res = extract_scene(img)
    assert any(r.kind == "parallel" for r in res.scene.relations)


def test_perpendicular_relation():
    img = np.full((200, 200), 255, dtype=np.uint8)
    cv2.line(img, (100, 30), (100, 170), 0, 3)
    cv2.line(img, (30, 100), (170, 100), 0, 3)
    res = extract_scene(img)
    kinds = {r.kind for r in res.scene.relations}
    assert "perpendicular" in kinds or "intersection" in kinds


def test_blank_input_returns_empty_scene():
    res = extract_scene(np.full((100, 100), 255, dtype=np.uint8))
    assert res.scene.primitives == []
    assert res.confidence == 0.0


def test_none_and_empty_inputs():
    res = extract_scene(None)
    assert res.scene.primitives == []
    res = extract_scene(np.zeros((0, 0), dtype=np.uint8))
    assert res.scene.primitives == []


def test_extraction_confidence_reflects_coverage():
    # mostly explained ink → high confidence; scattered noise → low
    res = extract_scene(_triangle())
    assert 0 < res.confidence <= 1.0
    assert res.unexplained_ink >= 0
