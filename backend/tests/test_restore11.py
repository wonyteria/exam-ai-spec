"""RESTORE-11 — LayerDNA 14-class taxonomy.

Locks: the six RESTORE-04 names remain as aliases over the same ids;
colored ink splits into GRADING_MARK / RED_PEN / BLUE_PEN / HIGHLIGHTER;
overlap splits into writing vs grading overlap; faint residue is
PAPER_ARTIFACT (preserved, never removable); ambiguous ink above the
recording floor is UNKNOWN (review); PRINT_MATH upgrades print
components that intersect supplied math regions. Removal policy is
unchanged — only confident non-overlapping annotation ink is whitened.
"""
from __future__ import annotations

import numpy as np

from core.examdna.student_trace.layers import (
    ANNOTATION_CLASSES,
    REVIEW_CLASSES,
    LayerClass,
    classify_layers,
)


def _ring(h=200, w=400, center=(100, 100), r=60, t=5):
    yy, xx = np.mgrid[0:h, 0:w]
    d2 = (yy - center[0]) ** 2 + (xx - center[1]) ** 2
    return (d2 < r * r) & (d2 > (r - t) ** 2)


def _canvas(h=200, w=400):
    gray = np.full((h, w), 200, dtype=np.uint8)
    rgb = np.stack([gray] * 3, axis=2).copy()
    return gray, rgb


CANONICAL = {
    "BACKGROUND",
    "PRINT_TEXT",
    "PRINT_FIGURE",
    "GRADING_MARK",
    "BLACK_PEN",
    "PENCIL",
    "PRINT_WRITING_OVERLAP",
    "PRINT_GRADING_OVERLAP",
    "BLUE_PEN",
    "RED_PEN",
    "HIGHLIGHTER",
    "PRINT_MATH",
    "PAPER_ARTIFACT",
    "UNKNOWN",
}


def test_taxonomy_has_14_classes_with_backward_aliases():
    assert {c.name for c in LayerClass} == CANONICAL
    assert len(list(LayerClass)) == 14
    # RESTORE-04 aliases resolve to the canonical members.
    assert LayerClass.PRINT is LayerClass.PRINT_TEXT
    assert LayerClass.GRADING is LayerClass.GRADING_MARK
    assert LayerClass.PEN is LayerClass.BLACK_PEN
    assert LayerClass.OVERLAP is LayerClass.PRINT_WRITING_OVERLAP


def test_policy_sets_cover_taxonomy_safely():
    # Every ink class is either a removable candidate, a review class, or
    # preserved print/paper/background — nothing falls through.
    removable = set(ANNOTATION_CLASSES)
    review = set(REVIEW_CLASSES)
    preserved = {
        LayerClass.BACKGROUND,
        LayerClass.PRINT_TEXT,
        LayerClass.PRINT_FIGURE,
        LayerClass.PRINT_MATH,
        LayerClass.PAPER_ARTIFACT,
    }
    assert removable | review | preserved == set(LayerClass)
    assert removable.isdisjoint(review)
    assert removable.isdisjoint(preserved)
    # PAPER_ARTIFACT and UNKNOWN are never removal candidates.
    assert LayerClass.PAPER_ARTIFACT in preserved
    assert LayerClass.UNKNOWN in review


def test_large_red_mark_is_grading_mark():
    gray, rgb = _canvas()
    ring = _ring(200, 400, (100, 200), 70, 4)
    rgb[ring] = (200, 20, 20)
    gray[ring] = 110
    ev = classify_layers(gray, rgb)
    comps = [c for c in ev.components if c.layer == LayerClass.GRADING_MARK]
    assert comps and all(c.removable for c in comps)


def test_small_red_stroke_is_red_pen():
    gray, rgb = _canvas()
    # bbox diagonal ~99: above the shape floor (70), below grading size (120)
    stroke = _ring(200, 400, (100, 200), 35, 4)
    rgb[stroke] = (200, 20, 20)
    gray[stroke] = 110
    ev = classify_layers(gray, rgb)
    comps = [c for c in ev.components if c.layer == LayerClass.RED_PEN]
    assert comps and all(c.removable for c in comps)


def test_blue_stroke_is_blue_pen():
    gray, rgb = _canvas()
    stroke = _ring(200, 400, (100, 200), 35, 4)
    rgb[stroke] = (30, 60, 210)
    gray[stroke] = 110
    ev = classify_layers(gray, rgb)
    comps = [c for c in ev.components if c.layer == LayerClass.BLUE_PEN]
    assert comps and all(c.removable for c in comps)


def test_translucent_highlight_is_highlighter():
    gray, rgb = _canvas()
    # thin diagonal swipe — sparse enough to pass the shape floor
    for i in range(0, 160):
        y, x = 60 + i // 2, 60 + i
        rgb[y : y + 3, x : x + 3] = (240, 240, 110)
        gray[y : y + 3, x : x + 3] = 200
    ev = classify_layers(gray, rgb)
    comps = [c for c in ev.components if c.layer == LayerClass.HIGHLIGHTER]
    assert comps


def test_faint_residue_is_paper_artifact_and_preserved():
    gray = np.full((200, 400), 200, dtype=np.uint8)
    smudge = np.zeros((200, 400), dtype=bool)
    smudge[60:110, 60:160] = True  # large faint stain
    gray[smudge] = 185             # margin 15 < STROKE_MARGIN, > ARTIFACT_MARGIN
    ev = classify_layers(gray)
    comps = [c for c in ev.components if c.layer == LayerClass.PAPER_ARTIFACT]
    assert comps
    assert all(not c.removable for c in comps)
    assert not (ev.removal_mask & smudge).any()


def test_ambiguous_small_ink_is_unknown_and_reviewed():
    gray, rgb = _canvas()
    blob = np.zeros((200, 400), dtype=bool)
    blob[80:88, 80:88] = True      # 64px — above UNKNOWN_MIN_AREA, below shape floor
    rgb[blob] = (200, 20, 20)
    gray[blob] = 110
    ev = classify_layers(gray, rgb)
    comps = [c for c in ev.components if c.layer == LayerClass.UNKNOWN]
    assert comps
    assert all(not c.removable for c in comps)
    assert (ev.review_mask & blob).any()


def test_colored_overlap_is_grading_overlap_class():
    gray, rgb = _canvas()
    gray[95:105, 20:380] = 20                       # printed rule
    ring = _ring(200, 400, (100, 200), 60, 4)
    rgb[ring] = (200, 20, 20)                       # red mark crossing print
    gray[ring] = 110
    ev = classify_layers(gray, rgb)
    comps = [
        c for c in ev.components
        if c.layer == LayerClass.PRINT_GRADING_OVERLAP
    ]
    assert comps and all(not c.removable for c in comps)
    # preserved — overlap pixels stay, print stays
    assert not (ev.removal_mask & ring).any()


def test_writing_overlap_class_unchanged():
    gray = np.full((200, 400), 200, dtype=np.uint8)
    gray[95:105, 20:380] = 20
    gray[_ring(200, 400, (100, 200), 60)] = 80      # pencil ring on print
    ev = classify_layers(gray)
    comps = [
        c for c in ev.components
        if c.layer == LayerClass.PRINT_WRITING_OVERLAP
    ]
    assert comps and all(not c.removable for c in comps)


def test_print_math_upgrade_via_math_regions():
    gray = np.full((200, 400), 200, dtype=np.uint8)
    gray[80:95, 50:70] = 30        # glyph blob inside math region
    gray[150:165, 50:70] = 30      # glyph blob outside
    ev = classify_layers(gray, math_regions=[(40, 70, 60, 40)])
    assert (ev.class_map == int(LayerClass.PRINT_MATH)).any()
    # the outside blob stays PRINT_TEXT
    assert ev.class_map[150:165, 50:70].max() == int(LayerClass.PRINT_TEXT)
    # no region supplied -> PRINT_MATH never assigned
    ev2 = classify_layers(gray)
    assert not (ev2.class_map == int(LayerClass.PRINT_MATH)).any()


def test_classes_still_disjoint_and_removal_confined():
    gray, rgb = _canvas(300, 400)
    gray[40:46, 30:370] = 15
    gray[80:95, 50:70] = 30
    ring = _ring(300, 400, (200, 250), 70, 4)
    rgb[ring] = (200, 20, 20)
    gray[ring] = 110
    ev = classify_layers(gray, rgb)
    assert ev.class_map.dtype == np.uint8
    assert ev.removal_mask.sum() > 0
    assert not (ev.removal_mask & (gray < 55)).any()
    assert not (ev.removal_mask & ev.review_mask).any()
