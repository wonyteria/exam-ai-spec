"""Semantic checks, structural diff, and review overlay for FigureScene
(RESTORE-06).

`validate_scene` proves a scene is *well-formed data*; this module proves
it is *internally consistent geometry*: marks must be backed by relations
and vice versa, intersection points must lie on both strokes, and a scene
diff is computed structurally — primitive kinds, relation triples, and
label text — never by pixel IoU, which cannot tell a missing right-angle
mark from a rendering artifact.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Optional

from document.scene import FigureScene


@dataclass
class SceneIssue:
    kind: str          # mark_without_relation | relation_without_mark | ...
    detail: str
    refs: list[str]


def check_scene(scene: FigureScene) -> list[SceneIssue]:
    """Semantic consistency checks — every mark/relation pair must agree."""
    issues: list[SceneIssue] = []
    by_id = {p.id: p for p in scene.primitives}

    rel_index: dict[str, set[frozenset]] = {}
    for r in scene.relations:
        rel_index.setdefault(r.kind, set()).add(frozenset(r.refs))

    def has_rel(kinds: tuple[str, ...], refs: list[str]) -> bool:
        wanted = frozenset(refs)
        for k in kinds:
            for rs in rel_index.get(k, ()):
                if wanted <= rs or rs <= wanted:
                    return True
        return False

    for p in scene.primitives:
        if p.kind == "right_angle_mark":
            if not has_rel(("right_angle", "perpendicular"), p.refs):
                issues.append(SceneIssue(
                    "mark_without_relation",
                    f"right-angle mark {p.id!r} has no right_angle/perpendicular relation",
                    list(p.refs),
                ))
        elif p.kind == "parallel_mark":
            if not has_rel(("parallel",), p.refs):
                issues.append(SceneIssue(
                    "mark_without_relation",
                    f"parallel mark {p.id!r} has no parallel relation",
                    list(p.refs),
                ))
        elif p.kind == "equal_mark":
            if not has_rel(("equal_length", "equal_angle", "congruent"), p.refs):
                issues.append(SceneIssue(
                    "mark_without_relation",
                    f"equal mark {p.id!r} has no equality relation",
                    list(p.refs),
                ))
        elif p.kind == "angle_mark":
            deg = p.props.get("deg")
            if isinstance(deg, (int, float)) and abs(deg - 90) < 1:
                if not has_rel(("right_angle", "perpendicular"), p.refs):
                    issues.append(SceneIssue(
                        "right_angle_unmarked_relation",
                        f"angle mark {p.id!r} measures ~90° without a right-angle relation",
                        list(p.refs),
                    ))
        elif p.kind == "label":
            if not scene.labels.get(p.id):
                issues.append(SceneIssue(
                    "label_without_text",
                    f"label primitive {p.id!r} carries no text",
                    [p.id],
                ))
        elif p.kind == "hatch":
            for ref in p.refs:
                if by_id.get(ref) is None or by_id[ref].kind not in (
                    "polygon", "circle"
                ):
                    issues.append(SceneIssue(
                        "hatch_without_shape",
                        f"hatch {p.id!r} does not ref a fillable shape ({ref!r})",
                        [p.id, ref],
                    ))

    # A printed relation with no corresponding mark is a likely lost mark.
    mark_kinds = {
        "right_angle": ("right_angle_mark", "angle_mark"),
        "perpendicular": ("right_angle_mark",),
        "parallel": ("parallel_mark",),
        "equal_length": ("equal_mark",),
    }
    for r in scene.relations:
        marks = mark_kinds.get(r.kind)
        if not marks:
            continue
        has_mark = any(
            p.kind in marks and frozenset(p.refs) & frozenset(r.refs)
            for p in scene.primitives
        )
        if not has_mark:
            issues.append(SceneIssue(
                "relation_without_mark",
                f"{r.kind} relation on {sorted(r.refs)} has no printed mark",
                list(r.refs),
            ))

    # An intersection point must sit on both strokes.
    on_lines = rel_index.get("on_line", set())
    for r in scene.relations:
        if r.kind != "intersection" or len(r.refs) < 3:
            continue
        s1, s2, pt = r.refs[0], r.refs[1], r.refs[2]
        for stroke in (s1, s2):
            if frozenset((stroke, pt)) not in on_lines:
                issues.append(SceneIssue(
                    "intersection_not_on_line",
                    f"intersection point {pt!r} lacks on_line({pt!r},{stroke!r})",
                    list(r.refs),
                ))
    return issues


def diff_scenes(expected: FigureScene, actual: FigureScene) -> list[str]:
    """Structural semantic diff between two scenes.

    Compares the primitive-kind census, the relation multiset, and label
    text — the things a correct restoration must reproduce. Returns a
    list of mismatches; empty means semantically identical. Geometry-only
    similarity (IoU, pixel overlap) is deliberately NOT accepted as proof.
    """
    mismatches: list[str] = []

    exp_kinds = Counter(p.kind for p in expected.primitives)
    act_kinds = Counter(p.kind for p in actual.primitives)
    for kind in sorted(set(exp_kinds) | set(act_kinds)):
        e, a = exp_kinds.get(kind, 0), act_kinds.get(kind, 0)
        if e != a:
            mismatches.append(f"primitive {kind}: expected {e}, got {a}")

    exp_rels = Counter((r.kind, tuple(sorted(r.refs))) for r in expected.relations)
    act_rels = Counter((r.kind, tuple(sorted(r.refs))) for r in actual.relations)
    for key in sorted(set(exp_rels) | set(act_rels)):
        e, a = exp_rels.get(key, 0), act_rels.get(key, 0)
        if e != a:
            mismatches.append(f"relation {key[0]}{key[1]}: expected {e}, got {a}")

    # Label text: compare on shared primitive ids plus the sorted text
    # multiset so renamed ids still surface text changes.
    exp_labels = Counter(expected.labels.values())
    act_labels = Counter(actual.labels.values())
    if exp_labels != act_labels:
        missing = exp_labels - act_labels
        extra = act_labels - exp_labels
        for text, n in sorted(missing.items()):
            mismatches.append(f"label text missing: {text!r} x{n}")
        for text, n in sorted(extra.items()):
            mismatches.append(f"label text extra: {text!r} x{n}")
    return mismatches


def render_overlay(scene: FigureScene, width: int, height: int):
    """Draw the scene graph as a translucent overlay for human review —
    review evidence, not a restoration renderer."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    by_id = {p.id: p for p in scene.primitives}

    def xy(ref: str):
        p = by_id.get(ref)
        if p is None:
            return None
        x, y = p.props.get("x"), p.props.get("y")
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            return (float(x), float(y))
        return None

    colors = {
        "point": (30, 30, 30, 220),
        "segment": (200, 40, 40, 200),
        "line": (200, 40, 40, 160),
        "ray": (200, 40, 40, 160),
        "polyline": (200, 40, 40, 200),
        "curve": (200, 40, 160, 200),
        "arc": (200, 40, 160, 200),
        "circle": (40, 120, 220, 200),
        "polygon": (40, 120, 220, 160),
        "angle_mark": (230, 160, 0, 220),
        "right_angle_mark": (230, 160, 0, 220),
        "parallel_mark": (120, 60, 220, 220),
        "equal_mark": (120, 60, 220, 220),
        "hatch": (60, 180, 120, 120),
        "label": (20, 20, 20, 230),
        "axis": (80, 80, 80, 200),
        "tick": (80, 80, 80, 200),
    }

    for p in scene.primitives:
        color = colors.get(p.kind, (0, 200, 0, 200))
        pts = [xy(r) for r in p.refs]
        pts = [pt for pt in pts if pt]
        if p.kind == "point":
            c = xy(p.id) or (p.props.get("x"), p.props.get("y"))
            if c and c[0] is not None:
                r = 3
                draw.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], fill=color)
        elif p.kind in ("segment", "line", "ray", "polyline", "curve") and len(pts) >= 2:
            draw.line(pts, fill=color, width=3)
        elif p.kind == "arc" and len(pts) >= 2:
            draw.line(pts, fill=color, width=2)
        elif p.kind == "circle":
            cx, cy = p.props.get("cx"), p.props.get("cy")
            if (cx is None or cy is None) and pts:
                cx, cy = pts[0]
            rad = p.props.get("r") or p.props.get("radius")
            if isinstance(cx, (int, float)) and isinstance(cy, (int, float)) and rad:
                draw.ellipse(
                    [cx - rad, cy - rad, cx + rad, cy + rad], outline=color, width=2
                )
        elif p.kind == "polygon" and len(pts) >= 3:
            draw.polygon(pts, outline=color)
        elif p.kind == "hatch" and pts:
            # sparse hatch strokes inside the referenced shape's extent
            xs = [pt[0] for pt in pts]
            ys = [pt[1] for pt in pts]
            x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
            step = max(6, int((x1 - x0) / 12) or 6)
            x = x0 - (y1 - y0)
            while x < x1:
                draw.line(
                    [(max(x, x0), y1), (min(x + (y1 - y0), x1), y0)],
                    fill=color, width=1,
                )
                x += step
        elif p.kind in ("angle_mark", "right_angle_mark") and pts:
            cx, cy = pts[0]
            s = 10
            if p.kind == "right_angle_mark":
                draw.rectangle([cx, cy, cx + s, cy + s], outline=color, width=2)
            else:
                draw.arc([cx - s, cy - s, cx + s, cy + s], 0, 360, fill=color, width=2)
        elif p.kind in ("parallel_mark", "equal_mark") and pts:
            cx, cy = pts[0]
            for i, off in enumerate((-4, 4)[: int(p.props.get("ticks", 1)) + 1]):
                draw.line([(cx + off, cy - 6), (cx + off + 4, cy + 6)], fill=color, width=2)
        elif p.kind == "label" and pts:
            draw.text(pts[0], scene.labels.get(p.id, "?"), fill=color)

    return img
