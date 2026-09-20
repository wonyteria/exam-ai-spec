"""Figure scene graph, table, and graph objects + validation (WP05).

A `FigureScene` is a data-only description of an exam figure: primitive
elements (points, segments, circles, marks, labels) plus geometric
relations (right-angle, parallel, equal-length). It is never rendered by
executing model output — `validate_scene` rejects anything outside the
allowed primitive/relation vocabulary, dangling references, non-finite
coordinates, or oversized payloads (malicious/invalid scenes must fail,
not be prettified into a pass — A08/S04).
"""
from __future__ import annotations

import math
from typing import Any, Optional

from pydantic import BaseModel, Field

# -- allowed vocabulary ----------------------------------------------------------

POINT_PRIMITIVES = {"point"}
STROKE_PRIMITIVES = {"segment", "line", "ray", "polyline", "arc", "curve"}
SHAPE_PRIMITIVES = {"circle", "polygon"}
MARK_PRIMITIVES = {
    "angle_mark",        # ∠ at a vertex (optionally right-angle)
    "right_angle_mark",  # ┐
    "parallel_mark",     # arrow ticks on parallel lines
    "equal_mark",        # equal-length tick marks
    "hatch",             # hatching inside a shape (refs the shape)
}
TEXT_PRIMITIVES = {"label", "axis", "tick"}

ALLOWED_PRIMITIVES = (
    POINT_PRIMITIVES
    | STROKE_PRIMITIVES
    | SHAPE_PRIMITIVES
    | MARK_PRIMITIVES
    | TEXT_PRIMITIVES
)

ALLOWED_RELATIONS = {
    "right_angle",      # (vertex, arm1, arm2)
    "parallel",         # (stroke, stroke)
    "perpendicular",    # (stroke, stroke)
    "equal_length",     # (stroke, stroke)
    "equal_angle",      # (vertex mark, vertex mark)
    "on_line",          # (point, stroke)
    "on_circle",        # (point, circle)
    "congruent",        # (shape, shape)
    "midpoint",         # (point, segment)
    "intersection",     # (stroke, stroke, point) — the point is their crossing
    "tangent",          # (stroke, circle)
}

# hard caps — a scene is exam-figure sized, never arbitrary model output
MAX_PRIMITIVES = 200
MAX_RELATIONS = 100
MAX_LABEL_LEN = 200
MAX_COORD = 1e6

# minimum ref counts per primitive kind
_REFS_REQUIRED = {
    "segment": 2, "line": 2, "ray": 2, "polyline": 2, "arc": 2, "curve": 2,
    "circle": 1, "polygon": 3,
    "angle_mark": 1, "right_angle_mark": 1, "parallel_mark": 1,
    "equal_mark": 1, "hatch": 1, "label": 0, "axis": 1, "tick": 1,
    "point": 0,
}


class ScenePrimitive(BaseModel):
    id: str
    kind: str
    refs: list[str] = Field(default_factory=list)
    # numeric props only: coords (x,y), radius, angle deg, tick count…
    props: dict[str, Any] = Field(default_factory=dict)


class SceneRelation(BaseModel):
    kind: str
    refs: list[str] = Field(default_factory=list)


class FigureScene(BaseModel):
    primitives: list[ScenePrimitive] = Field(default_factory=list)
    relations: list[SceneRelation] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)  # primitive id -> text


class Table(BaseModel):
    header: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class GraphAxis(BaseModel):
    label: str = ""
    ticks: list[float] = Field(default_factory=list)
    min: Optional[float] = None
    max: Optional[float] = None


class GraphSeries(BaseModel):
    name: str = ""
    points: list[list[float]] = Field(default_factory=list)


class Graph(BaseModel):
    x_axis: GraphAxis = Field(default_factory=GraphAxis)
    y_axis: GraphAxis = Field(default_factory=GraphAxis)
    series: list[GraphSeries] = Field(default_factory=list)


# -- validation ------------------------------------------------------------------


def _finite(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(value) or abs(value) > MAX_COORD:
            errors.append(f"{path}: non-finite or out-of-range number")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _finite(v, f"{path}[{i}]", errors)
    elif isinstance(value, dict):
        for k, v in value.items():
            _finite(v, f"{path}.{k}", errors)


def validate_scene(scene: FigureScene) -> list[str]:
    """Return a list of errors; empty = valid. Pure data checks — no
    execution, no rendering."""
    errors: list[str] = []
    if len(scene.primitives) > MAX_PRIMITIVES:
        errors.append(f"too many primitives ({len(scene.primitives)}>{MAX_PRIMITIVES})")
    if len(scene.relations) > MAX_RELATIONS:
        errors.append(f"too many relations ({len(scene.relations)}>{MAX_RELATIONS})")

    ids: set[str] = set()
    for p in scene.primitives:
        if not p.id:
            errors.append("primitive with empty id")
        if p.id in ids:
            errors.append(f"duplicate primitive id {p.id!r}")
        ids.add(p.id)
        if p.kind not in ALLOWED_PRIMITIVES:
            errors.append(f"unknown primitive kind {p.kind!r} on {p.id!r}")
            continue
        need = _REFS_REQUIRED.get(p.kind, 0)
        if len(p.refs) < need:
            errors.append(
                f"{p.id!r} ({p.kind}) needs {need} refs, has {len(p.refs)}"
            )
        _finite(p.props, f"{p.id}.props", errors)

    for r in scene.relations:
        if r.kind not in ALLOWED_RELATIONS:
            errors.append(f"unknown relation kind {r.kind!r}")
            continue
        if not r.refs:
            errors.append(f"relation {r.kind} with no refs")
        for ref in r.refs:
            if ref not in ids:
                errors.append(f"relation {r.kind} references missing {ref!r}")

    for ref in scene.labels:
        if ref not in ids:
            errors.append(f"label targets missing primitive {ref!r}")
        if len(scene.labels[ref]) > MAX_LABEL_LEN:
            errors.append(f"label on {ref!r} exceeds {MAX_LABEL_LEN} chars")
    return errors


def validate_table(table: Table) -> list[str]:
    errors: list[str] = []
    if not table.header:
        errors.append("table has no header")
    width = len(table.header)
    if width > 50 or len(table.rows) > 200:
        errors.append("table exceeds size cap")
    for i, row in enumerate(table.rows):
        if len(row) != width:
            errors.append(f"row {i} has {len(row)} cells, header has {width}")
    return errors


def validate_graph(graph: Graph) -> list[str]:
    errors: list[str] = []
    for name, axis in (("x", graph.x_axis), ("y", graph.y_axis)):
        _finite(axis.ticks, f"{name}_axis.ticks", errors)
        if any(
            b <= a for a, b in zip(axis.ticks, axis.ticks[1:])
        ):
            errors.append(f"{name}_axis ticks not strictly increasing")
        if axis.min is not None and axis.max is not None:
            _finite([axis.min, axis.max], f"{name}_axis.range", errors)
            if axis.min >= axis.max:
                errors.append(f"{name}_axis min>=max")
    for i, s in enumerate(graph.series):
        for j, pt in enumerate(s.points):
            _finite(pt, f"series[{i}].points[{j}]", errors)
            if len(pt) != 2:
                errors.append(f"series[{i}].points[{j}] is not [x,y]")
    return errors
