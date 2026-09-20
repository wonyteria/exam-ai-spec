"""RESTORE-06 — FigureGraph semantics: marks↔relations consistency,
structural scene diff (never IoU), and a review overlay renderer.
"""
from __future__ import annotations

import numpy as np

from document.scene import FigureScene, ScenePrimitive, SceneRelation, validate_scene
from document.scene_semantics import check_scene, diff_scenes, render_overlay


def _triangle_scene() -> FigureScene:
    return FigureScene(
        primitives=[
            ScenePrimitive(id="A", kind="point", props={"x": 10, "y": 10}),
            ScenePrimitive(id="B", kind="point", props={"x": 110, "y": 10}),
            ScenePrimitive(id="C", kind="point", props={"x": 10, "y": 90}),
            ScenePrimitive(id="AB", kind="segment", refs=["A", "B"]),
            ScenePrimitive(id="BC", kind="segment", refs=["B", "C"]),
            ScenePrimitive(id="CA", kind="segment", refs=["C", "A"]),
            ScenePrimitive(id="ra", kind="right_angle_mark", refs=["A", "AB", "CA"]),
            ScenePrimitive(id="lB", kind="label", refs=["B"]),
            ScenePrimitive(id="h", kind="hatch", refs=["tri"]),
            ScenePrimitive(id="tri", kind="polygon", refs=["A", "B", "C"]),
        ],
        relations=[
            SceneRelation(kind="right_angle", refs=["AB", "CA", "A"]),
        ],
        labels={"lB": "B", "A": "A", "C": "C"},
    )


def test_consistent_scene_passes_semantic_check():
    scene = _triangle_scene()
    assert validate_scene(scene) == []
    assert check_scene(scene) == []


def test_mark_without_relation_flagged():
    scene = _triangle_scene()
    scene.relations = []  # mark present, relation gone
    issues = check_scene(scene)
    assert any(i.kind == "mark_without_relation" for i in issues)


def test_relation_without_mark_flagged():
    scene = _triangle_scene()
    scene.primitives = [p for p in scene.primitives if p.id != "ra"]
    issues = check_scene(scene)
    assert any(i.kind == "relation_without_mark" for i in issues)


def test_intersection_requires_on_line():
    scene = FigureScene(
        primitives=[
            ScenePrimitive(id="P", kind="point", props={"x": 5, "y": 5}),
            ScenePrimitive(id="Q", kind="point", props={"x": 95, "y": 5}),
            ScenePrimitive(id="R", kind="point", props={"x": 5, "y": 95}),
            ScenePrimitive(id="S", kind="point", props={"x": 95, "y": 95}),
            ScenePrimitive(id="X", kind="point", props={"x": 50, "y": 50}),
            ScenePrimitive(id="l1", kind="line", refs=["P", "S"]),
            ScenePrimitive(id="l2", kind="line", refs=["Q", "R"]),
        ],
        relations=[SceneRelation(kind="intersection", refs=["l1", "l2", "X"])],
    )
    assert validate_scene(scene) == []
    issues = check_scene(scene)
    assert any(i.kind == "intersection_not_on_line" for i in issues)

    scene.relations += [
        SceneRelation(kind="on_line", refs=["X", "l1"]),
        SceneRelation(kind="on_line", refs=["X", "l2"]),
    ]
    assert not [i for i in check_scene(scene)
                if i.kind == "intersection_not_on_line"]


def test_diff_scenes_structural_not_visual():
    a = _triangle_scene()
    b = _triangle_scene()
    assert diff_scenes(a, b) == []

    # A missing right-angle mark is a semantic loss even if pixels overlap.
    c = _triangle_scene()
    c.primitives = [p for p in c.primitives if p.id != "ra"]
    mismatches = diff_scenes(a, c)
    assert any("right_angle_mark" in m for m in mismatches)

    # Label text changes surface even when geometry is identical.
    d = _triangle_scene()
    d.labels["lB"] = "D"
    assert any("label text" in m for m in diff_scenes(a, d))


def test_overlay_renders_review_image():
    scene = _triangle_scene()
    img = render_overlay(scene, 200, 200)
    arr = np.asarray(img)
    assert (arr[..., 3] > 0).any()  # something was drawn


def test_invalid_scene_flags_question_and_gates():
    """A malformed/contradictory scene can never ride through materialize."""
    from document.models import ATU, ATUKind, Candidate, Document, Question, VerificationStatus
    from core.examdna.source_truth import consensus
    from core.examdna.context import PipelineContext, Providers
    from jobs.models import Job
    from document.verification import evaluate_gate

    bad_scene = _triangle_scene().model_dump()
    bad_scene["relations"] = []  # mark without relation -> semantic issue
    fig_value = {"description": "삼각형", "scene": bad_scene}
    doc = Document(tenant_id="t")
    q = Question(number=1, label="1")
    atu = ATU(
        kind=ATUKind.TEXT_TOKEN, field="figure",
        candidates=[
            Candidate(provider="a", value=fig_value),
            Candidate(provider="b", value=fig_value),
        ],
    )
    q.atus.append(atu)
    doc.questions.append(q)

    ctx = PipelineContext(
        document=doc, job=Job(id="j", document_id=doc.id), store=None,
        workdir=None, providers=Providers(), event_sink=lambda *a: None,
    )
    consensus.run(ctx)

    fig = q.figures[0]
    assert fig.scene is not None
    assert fig.topology["issues"]
    gate = evaluate_gate(doc)
    assert gate.invalid_figure == 1
    assert not gate.passed
