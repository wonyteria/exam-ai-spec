"""RESTORE-12 — real OCR → structured question segmentation.

Locks: PaddlePageExtractor turns line-level OCR candidates into
extract_page items (label/body/choices/points) with per-line
provenance; ordering follows geometry, not input order; header
furniture and out-of-sequence numbers never become question anchors;
the provider stays opt-in (EXAMDNA_PADDLE_PAGE) and absent by default.
"""
from __future__ import annotations

from document.models import Candidate
from providers.vision.paddle_page import (
    PaddlePageExtractor,
    segment_questions,
)


def _line(text, x=10, y=0, conf=0.9):
    return Candidate(
        provider="paddleocr",
        value=text,
        confidence=conf,
        meta={"bbox_px": [x, y, x + 200, y + 20]},
    )


def test_segments_questions_in_reading_order():
    lines = [
        _line("2025학년도 중간고사", y=0),       # header — dropped
        _line("2. 다음 식의 값은? [3점]", y=300),
        _line("② 4", y=380),
        _line("① 3", y=360),                     # out of input order
        _line("1. 수식을 계산하시오", y=100),
        _line("③ 5", y=400),
    ]
    items, dropped = segment_questions(lines)
    assert dropped == 1
    assert [it["label"] for it in items] == ["1", "2"]
    q2 = items[1]
    assert "다음 식의 값은?" in q2["body"]
    assert q2["points"] == 3
    assert q2["choices"]["①"] == "3"
    assert q2["choices"]["②"] == "4"
    assert q2["choices"]["③"] == "5"
    assert len(q2["line_bboxes"]) == 4


def test_header_lines_never_become_anchors():
    lines = [
        _line("2025학년도2학기 중간고사", y=0),   # 4-digit — not an anchor
        _line("학번 : 20408 이름 : 홍길동", y=30),
        _line("1. 첫 번째 문제", y=100),
    ]
    items, dropped = segment_questions(lines)
    assert [it["label"] for it in items] == ["1"]
    assert dropped == 2


def test_out_of_sequence_number_not_an_anchor():
    lines = [
        _line("3. 세 번째", y=0),
        _line("1. 첫 번째", y=100),
    ]
    items, dropped = segment_questions(lines)
    # "1." after "3." is backward — still anchored only if it moves
    # forward? 1 < 3 → treated as body line of question 3.
    assert len(items) == 1
    assert items[0]["label"] == "3"
    assert "1. 첫 번째" in items[0]["body"]


def test_items_carry_provenance_and_confidence():
    lines = [
        _line("1. 문제", y=0, conf=0.95),
        _line("① 답", y=40, conf=0.7),
    ]
    items, _ = segment_questions(lines)
    assert items[0]["line_conf"] == 0.7
    assert all(len(b) == 4 for b in items[0]["line_bboxes"])


def test_empty_input_returns_empty():
    assert segment_questions([]) == ([], 0)


def test_extract_page_wraps_items_in_candidate(tmp_path):
    import numpy as np
    from PIL import Image

    img = tmp_path / "p.png"
    Image.fromarray(np.full((10, 10), 255, dtype=np.uint8)).save(img)

    class FakeOCR:
        def recognize_text(self, image):
            return [_line("1. 문제 본문", y=0), _line("① 2", y=40)]

    extractor = PaddlePageExtractor(ocr=FakeOCR())
    cands = extractor.extract_page(img)
    assert len(cands) == 1
    cand = cands[0]
    assert cand.provider == "paddle-page"
    assert cand.meta["kind"] == "page_extraction"
    assert cand.meta["input_sha256"]
    item = cand.value[0]
    assert item["label"] == "1"
    assert item["choices"] == {"①": "2"}


def test_provider_is_opt_in_only(monkeypatch):
    import providers.vision as vision

    monkeypatch.delenv("EXAMDNA_PADDLE_PAGE", raising=False)
    assert vision.get_page_extractor() is None
    monkeypatch.setenv("EXAMDNA_PADDLE_PAGE", "1")
    assert isinstance(vision.get_page_extractor(), PaddlePageExtractor)
