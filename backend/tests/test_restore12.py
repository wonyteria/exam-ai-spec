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
    # "1." after "3." is backward — possibly a circled higher number
    # misread (grading marks). Kept as an ambiguous anchor for review
    # rather than silently folded into the previous question's body.
    assert [it["label"] for it in items] == ["3", "?1"]
    assert "첫 번째" in items[1]["body"]


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


def _lines_two_column():
    """Real-exam shape: left column Q1–Q3, right column Q4–Q6, with
    header/footer furniture. Line list is deliberately input-shuffled —
    ordering must come from geometry."""
    def L(text, x0, x1, y):
        return _line(text, x=x0, y=y) if False else Candidate(
            provider="paddleocr", value=text, confidence=0.9,
            meta={"bbox_px": [x0, y, x1, y + 20]},
        )
    return [
        L("시험지 제목", 10, 900, 0),            # full-width header
        L("1. 첫 번째 [3점]", 10, 300, 100),
        L("본문 1", 10, 400, 130),
        L("2. 두 번째", 10, 300, 300),
        L("① 1 ② 2", 10, 400, 330),
        L("3. 세 번째", 10, 300, 500),
        L("4. 네 번째", 550, 900, 100),          # right column
        L("본문 4", 550, 900, 130),
        L("5. 다섯 번째 [4점]", 550, 900, 300),
        L("6. 여섯 번째", 550, 900, 500),
        L("하단 푸터", 550, 900, 900),
    ]


def test_two_column_reading_order():
    items, dropped = segment_questions(_lines_two_column())
    assert [it["label"] for it in items] == ["1", "2", "3", "4", "5", "6"]
    # Interleaved numbering must not drop right-column questions.
    assert items[3]["body"].startswith("네 번째")
    assert items[4]["points"] == 4
    assert dropped == 1  # header; footer lands in last block's body
    assert items[5]['body'].endswith('푸터')


def test_single_column_unaffected_by_gutter_detection():
    # All lines start near the left edge — no gutter → single column.
    lines = [_line(f"{i}. 문항 {i}", y=i * 100) for i in range(1, 12)]
    items, _ = segment_questions(lines)
    assert [it["label"] for it in items] == [str(i) for i in range(1, 12)]


def test_subquestion_and_descriptive_anchors():
    def L(text, x0, x1, y):
        return Candidate(provider="paddleocr", value=text, confidence=0.9,
                         meta={"bbox_px": [x0, y, x1, y + 20]})
    lines = [
        L("논술형 2. 내접원에 대하여", 10, 400, 100),
        L("다음 물음에 답하시오. [7점]", 10, 400, 130),
        L("2-1. 점 I와의 접점을 연결한", 10, 400, 300),
        L("∠PRQ의 크기를 구하시오. [3점]", 10, 400, 330),
        L("2-2. ∠CRQ:∠ARP=3:2일 때", 10, 400, 500),
        L("2-3. ∠CRQ의 크기를 이용하여", 10, 400, 700),
    ]
    items, _ = segment_questions(lines)
    assert [it["label"] for it in items] == ["논술2", "2-1", "2-2", "2-3"]
    assert items[1]["points"] == 3


def test_items_get_normalized_bbox(tmp_path):
    import numpy as np
    from PIL import Image

    img = tmp_path / "p.png"
    Image.fromarray(np.full((100, 200), 255, dtype=np.uint8)).save(img)

    class FakeOCR:
        def recognize_text(self, image):
            return [
                Candidate(provider="paddleocr", value="1. 문제", confidence=0.9,
                          meta={"bbox_px": [10, 10, 100, 30]}),
                Candidate(provider="paddleocr", value="① 2", confidence=0.9,
                          meta={"bbox_px": [10, 40, 80, 60]}),
            ]

    cands = PaddlePageExtractor(ocr=FakeOCR()).extract_page(img)
    item = cands[0].value[0]
    bb = item["bbox"]
    assert bb == {"xmin": 50.0, "ymin": 100.0, "xmax": 500.0, "ymax": 600.0}


def test_occluded_number_becomes_ambiguous_anchor():
    """A circled number OCR'd as 'O' or a backward number still opens a
    block — the question is captured for review instead of dropped."""
    def L(text, x0, x1, y):
        return Candidate(provider="paddleocr", value=text, confidence=0.9,
                         meta={"bbox_px": [x0, y, x1, y + 20]})
    lines = [
        L("15. 평행사변형 문제 [5점]", 10, 300, 100),
        L("① 하나", 10, 300, 130),
        # "16." occluded by a grading circle → read as "6."
        L("6. 형행사변형 ABCD에서 EF는", 10, 300, 300),
        L("수직이등분선이다.", 10, 300, 330),
    ]
    items, _ = segment_questions(lines)
    assert [it["label"] for it in items] == ["15", "?6"]
    assert "수직이등분선" in items[1]["body"]


def test_bare_digit_opens_ambiguous_block():
    def L(text, x0, x1, y):
        return Candidate(provider="paddleocr", value=text, confidence=0.9,
                         meta={"bbox_px": [x0, y, x1, y + 20]})
    lines = [
        L("3. 세 번째 문제 [3점]", 10, 300, 100),
        L("4", 10, 30, 300),                        # detached circled number
        L("직각삼각형의 합동조건에 대한 설명으로", 10, 400, 330),
        L("옳은 것만을 고른 것은? [4점]", 10, 400, 360),
    ]
    items, _ = segment_questions(lines)
    assert [it["label"] for it in items] == ["3", "?4"]
    assert items[1]["points"] == 4


def test_circled_O_anchor_captured():
    def L(text, x0, x1, y):
        return Candidate(provider="paddleocr", value=text, confidence=0.9,
                         meta={"bbox_px": [x0, y, x1, y + 20]})
    lines = [
        L("9. 아홉 번째 [3점]", 10, 300, 100),
        L("OAB=AC인 이등변삼각형에서", 10, 400, 300),   # ⑩ read as O
        L("① 1 ② 2", 10, 300, 330),
    ]
    items, _ = segment_questions(lines)
    assert len(items) == 2
    assert items[1]["label"].startswith("?")
    assert "OAB=AC" in items[1]["body"]  # verbatim, nothing invented


def test_ambiguous_anchor_guards_reject_furniture():
    """Choice values, lone grading marks, and handwritten residues at the
    left edge must NOT open question blocks."""
    def L(text, x0, x1, y):
        return Candidate(provider="paddleocr", value=text, confidence=0.9,
                         meta={"bbox_px": [x0, y, x1, y + 20]})
    lines = [
        L("18. 열여덟 번째 [3점]", 10, 300, 100),
        L("① 63 ② 72", 10, 300, 130),
        L("63", 10, 40, 200),                       # bare choice value
        L("④", 10, 40, 230),                        # marker — not bodyish
        L("98", 10, 40, 260),                       # another bare value
        L("⑤ 104", 10, 100, 290),
        L("18", 10, 40, 400),                       # grading residue
        L("36+64=100", 10, 200, 430),               # math-only next line
        L("O 외심에서 세 꼭짓점에 이르는 거리는", 10, 400, 500),  # 'O' + space
        L("OA = OB", 10, 200, 600),                 # choice, no hangul
    ]
    items, _ = segment_questions(lines)
    assert [it["label"] for it in items] == ["18"]
