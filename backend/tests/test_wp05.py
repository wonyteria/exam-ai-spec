"""WP05 contract tests: math AST -> HWP equation script (11pt, style
tokens), figure scene/table/graph objects with strict validation, and
the MATH_FIGURE_SEMANTIC_CONSISTENCY canonical check."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from canonical.models import ChangeOp, CheckState
from canonical.service import MutationService
from canonical.store import CanonicalStore
from document.math_ast import (
    HWP_BASE_UNIT_11PT,
    MathParseError,
    UnsupportedMathError,
    latex_to_hwp,
    parse_latex,
    to_hwp_script,
)
from document.models import (
    ATU,
    ATUKind,
    Answer,
    Document,
    Equation,
    Figure,
    FigureRelation,
    Question,
    SourceRef,
)
from document.scene import (
    FigureScene,
    Graph,
    GraphAxis,
    GraphSeries,
    ScenePrimitive,
    SceneRelation,
    Table,
    validate_graph,
    validate_scene,
    validate_table,
)
from tenancy.db import TenancyDB


# --- math AST -> HWP script --------------------------------------------------------


def test_base_unit_is_11pt():
    assert HWP_BASE_UNIT_11PT == 1100
    assert latex_to_hwp("x+1")["baseUnit"] == 1100


@pytest.mark.parametrize(
    "latex,expected",
    [
        ("x^2+y^2=1", "x^{2} + y^{2} = 1"),
        (r"\frac{a}{b}", "{a} over {b}"),
        (r"\sqrt{x+1}", "sqrt{x + 1}"),
        (r"\sqrt[3]{8}", "root 3 of {8}"),
        ("x_i", "x_{i}"),
        ("x^2_i", "x^{2}_{i}"),
        (r"2 \times 3 = 6", "2 TIMES 3 = 6"),
        (r"x \le 5", "x <= 5"),
        (r"a \ne b", "a != b"),
        (r"\angle ABC", "angl A B C"),
        (r"\triangle ABC", "tri A B C"),
        (r"AB \parallel CD", "A B paral C D"),
        (r"l \perp m", "l perp m"),
        (r"90^\circ", "90^{deg}"),
        (r"\overline{AB}", "overbar {A B}"),
    ],
)
def test_latex_to_hwp_script(latex, expected):
    assert latex_to_hwp(latex)["script"] == expected


def test_numbers_italic_units_roman():
    """Numbers/vars emit bare (italic default); units wrap in rm{}."""
    out = latex_to_hwp("3 cm")["script"]
    assert out == "3 rm{cm}"
    out = latex_to_hwp(r"5 \mathrm{kg}")["script"]
    assert "rm{kg}" in out
    node = parse_latex("3 cm")
    styles = {c.kind: c.style for c in node.children}
    assert styles["num"] == "it" and styles["unit"] == "rm"


def test_hangul_text_is_roman():
    out = latex_to_hwp("3 원")["script"]
    assert out == "3 rm{원}"


def test_unsupported_constructs_fail_loudly():
    with pytest.raises(UnsupportedMathError):
        parse_latex(r"\begin{matrix} a & b \end{matrix}")
    with pytest.raises(UnsupportedMathError):
        parse_latex(r"\int_0^1 x dx")
    with pytest.raises(UnsupportedMathError):
        parse_latex(r"\vec{v}")
    with pytest.raises(UnsupportedMathError):
        parse_latex(r"\unknowncmd{x}")
    with pytest.raises(MathParseError):
        parse_latex("")
    with pytest.raises(MathParseError):
        parse_latex("x + }")


# --- scene / table / graph validation -----------------------------------------------


def _valid_scene() -> FigureScene:
    return FigureScene(
        primitives=[
            ScenePrimitive(id="A", kind="point", props={"x": 0, "y": 0}),
            ScenePrimitive(id="B", kind="point", props={"x": 4, "y": 0}),
            ScenePrimitive(id="C", kind="point", props={"x": 4, "y": 3}),
            ScenePrimitive(id="AB", kind="segment", refs=["A", "B"]),
            ScenePrimitive(id="BC", kind="segment", refs=["B", "C"]),
            ScenePrimitive(id="ra", kind="right_angle_mark", refs=["B"]),
        ],
        relations=[
            SceneRelation(kind="right_angle", refs=["B", "AB", "BC"]),
            SceneRelation(kind="perpendicular", refs=["AB", "BC"]),
        ],
        labels={"A": "A", "B": "B", "C": "C"},
    )


def test_valid_scene_passes():
    assert validate_scene(_valid_scene()) == []


def test_scene_rejects_unknown_primitive():
    s = _valid_scene()
    s.primitives.append(ScenePrimitive(id="evil", kind="bezier_bomb"))
    assert any("unknown primitive kind" in e for e in validate_scene(s))


def test_scene_rejects_dangling_refs():
    s = _valid_scene()
    s.relations.append(SceneRelation(kind="parallel", refs=["AB", "GHOST"]))
    assert any("missing" in e for e in validate_scene(s))
    s2 = _valid_scene()
    s2.labels["GHOST"] = "X"
    assert any("missing" in e for e in validate_scene(s2))


def test_scene_rejects_nonfinite_and_malicious():
    s = _valid_scene()
    s.primitives[0].props["x"] = math.nan
    assert any("non-finite" in e for e in validate_scene(s))
    s.primitives[0].props["x"] = math.inf
    assert any("non-finite" in e for e in validate_scene(s))
    s.primitives[0].props["x"] = 1e9
    assert any("out-of-range" in e for e in validate_scene(s))
    huge = FigureScene(
        primitives=[
            ScenePrimitive(id=f"p{i}", kind="point") for i in range(500)
        ]
    )
    assert any("too many primitives" in e for e in validate_scene(huge))


def test_scene_rejects_short_stroke_refs_and_dup_ids():
    s = FigureScene(
        primitives=[
            ScenePrimitive(id="A", kind="point"),
            ScenePrimitive(id="A", kind="point"),
            ScenePrimitive(id="s", kind="segment", refs=["A"]),
        ]
    )
    errs = validate_scene(s)
    assert any("duplicate" in e for e in errs)
    assert any("needs 2 refs" in e for e in errs)


def test_table_and_graph_validation():
    assert validate_table(Table(header=["a", "b"], rows=[["1", "2"]])) == []
    bad = Table(header=["a", "b"], rows=[["1"]])
    assert any("header has" in e for e in validate_table(bad))
    assert validate_table(Table(rows=[["1"]])) != []  # no header

    g = Graph(
        x_axis=GraphAxis(label="x", ticks=[0, 1, 2, 3]),
        y_axis=GraphAxis(label="y", ticks=[0, 5, 10]),
        series=[GraphSeries(name="f", points=[[0, 0], [1, 5]])],
    )
    assert validate_graph(g) == []
    g.x_axis.ticks = [0, 2, 1]
    assert any("increasing" in e for e in validate_graph(g))
    g.x_axis.ticks = [0, 1, 2]
    g.series[0].points = [[0, math.inf]]
    assert any("non-finite" in e for e in validate_graph(g))


# --- canonical check ----------------------------------------------------------------


@pytest.fixture()
def cstore(tmp_path):
    s = CanonicalStore(tmp_path / "canonical.db")
    yield s
    s.close()


@pytest.fixture()
def service(cstore, tmp_path):
    t = TenancyDB(tmp_path / "tenancy.db")
    yield MutationService(cstore, t)
    t.close()


def _doc_with_math(tenant="tn_1") -> Document:
    d = Document(tenant_id=tenant)
    q = Question(
        number=1,
        label="1",
        answer=Answer(value="2"),
        atus=[ATU(kind=ATUKind.QUESTION_NUMBER, value="1")],
        equations=[Equation(latex=r"\frac{x}{2}=3")],
        figures=[
            Figure(
                scene=_valid_scene(),
                source=SourceRef(page=0),
            )
        ],
    )
    d.questions.append(q)
    return d


def test_math_figure_check_passes(service):
    doc = _doc_with_math()
    rev = service.create_revision(doc, "tn_1", "alice")
    checks = {c.check_kind: c for c in service.run_checks(rev.id)}
    assert checks["MATH_FIGURE_SEMANTIC_CONSISTENCY"].state == CheckState.PASSED
    # equation object gained its HWP formula during revision normalization
    rev_doc = Document.model_validate(service.store.get_revision(rev.id).content_json)
    assert "over" in rev_doc.questions[0].equations[0].hwp_formula


def test_invalid_equation_fails_and_blocks(service, cstore):
    doc = _doc_with_math()
    doc.questions[0].equations[0].latex = r"\begin{matrix}x\end{matrix}"
    rev = service.create_revision(doc, "tn_1", "alice")
    checks = {c.check_kind: c for c in service.run_checks(rev.id)}
    chk = checks["MATH_FIGURE_SEMANTIC_CONSISTENCY"]
    assert chk.state == CheckState.FAILED
    assert "unsupported" in chk.result_summary.lower()
    assert any(
        i.kind == "MATH_FIGURE_SEMANTIC_CONSISTENCY"
        for i in cstore.list_issues(rev.id, blocking_only=True)
    )


def test_figure_without_source_evidence_fails(service):
    doc = _doc_with_math()
    doc.questions[0].figures[0].source = None
    rev = service.create_revision(doc, "tn_1", "alice")
    checks = {c.check_kind: c for c in service.run_checks(rev.id)}
    assert checks["MATH_FIGURE_SEMANTIC_CONSISTENCY"].state == CheckState.FAILED


def test_declared_relations_without_scene_fail(service):
    doc = _doc_with_math()
    fig = doc.questions[0].figures[0]
    fig.scene = None
    fig.relations = [FigureRelation(kind="parallel", elements=["AB", "CD"])]
    rev = service.create_revision(doc, "tn_1", "alice")
    checks = {c.check_kind: c for c in service.run_checks(rev.id)}
    chk = checks["MATH_FIGURE_SEMANTIC_CONSISTENCY"]
    assert chk.state == CheckState.FAILED
    assert "no scene" in chk.result_summary


def test_malicious_scene_rejected_by_check(service, cstore):
    doc = _doc_with_math()
    doc.questions[0].figures[0].scene = FigureScene(
        primitives=[
            ScenePrimitive(id="x", kind="point", props={"v": math.nan}),
            ScenePrimitive(id="y", kind="segment", refs=["x", "GHOST"]),
        ]
    )
    rev = service.create_revision(doc, "tn_1", "alice")
    checks = {c.check_kind: c for c in service.run_checks(rev.id)}
    chk = checks["MATH_FIGURE_SEMANTIC_CONSISTENCY"]
    assert chk.state == CheckState.FAILED
    assert any(
        i.kind == "MATH_FIGURE_SEMANTIC_CONSISTENCY"
        for i in cstore.list_issues(rev.id, blocking_only=True)
    )


def test_equation_object_edit_creates_revision(service, cstore):
    """SetField on the question's `equations` list edits the real equation
    objects; the new revision re-derives hwp_formula from new latex."""
    doc = _doc_with_math()
    rev = service.create_revision(doc, "tn_1", "alice")
    qid = doc.questions[0].id
    rev2 = service.apply(
        "tn_1", "alice", doc.id, rev.id,
        [
            ChangeOp(
                op="SetField",
                target_id=qid,
                field="equations",
                value=[{"latex": "x^2 = 9"}],
            )
        ],
        route="changes",
    )
    assert rev2.revision_no == 2
    rev_doc = Document.model_validate(cstore.get_revision(rev2.id).content_json)
    eq = rev_doc.questions[0].equations[0]
    assert eq.latex == "x^2 = 9"
    assert eq.hwp_formula == "x^{2} = 9"
    # content hash changed -> dependent checks were invalidated on rev2 seed
    assert rev2.content_hash != rev.content_hash
