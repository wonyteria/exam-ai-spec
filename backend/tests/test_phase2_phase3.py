"""Phase 2/3 — agent command coverage, academy profile store, DOCX proof.

Locks the chat surface contract: field edits parse into typed ChangeOps
(natural language never applies directly), ambiguous input stays
unrecognized, duplicates start unverified, and DOCX artifacts get
server-side proof binding like HWPX/PDF.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from academy.profile import AcademyProfile, apply_style
from academy.store import AcademyProfileStore
from agent.history import AgentHistory
from agent.ops import parse_command
from canonical.models import ChangeOp
from canonical.service import MutationService
from canonical.store import CanonicalStore
from document.models import (
    Answer, Choice, Document, Question, QuestionType, TextSpan,
)
from jobs.artifact_bridge import docx_checks
from tenancy.db import TenancyDB


def _doc(tenant="tn_1") -> Document:
    d = Document(tenant_id=tenant)
    d.questions.extend([
        Question(
            number=1, label="1", points=4,
            type=QuestionType.MULTIPLE_CHOICE,
            body=[TextSpan(text="다음 중 옳은 것은?")],
            choices=[
                Choice(label="①", body=[TextSpan(text="가")]),
                Choice(label="②", body=[TextSpan(text="나")]),
            ],
            answer=Answer(value="①"),
        ),
        Question(number=2, label="2", body=[TextSpan(text="서술하라")]),
    ])
    return d


# --- agent command parsing -------------------------------------------------------


class TestAgentFieldCommands:
    def test_points(self):
        p = parse_command(_doc(), "1번 배점을 5점으로")
        assert p.recognized and p.ops[0].op == "SetPoints"
        assert p.ops[0].value == 5

    def test_answer(self):
        p = parse_command(_doc(), "1번 정답을 ②로")
        assert p.recognized and p.ops[0].op == "SetAnswer"
        assert p.ops[0].value == "②"

    def test_body(self):
        p = parse_command(_doc(), "1번 본문을 '고른 것은?'으로")
        assert p.recognized and p.ops[0].op == "SetBody"
        assert p.ops[0].value == "고른 것은?"

    def test_solution(self):
        p = parse_command(_doc(), "1번 해설을 '답은 ①이다'")
        assert p.recognized and p.ops[0].op == "SetSolution"

    def test_choice(self):
        p = parse_command(_doc(), "1번 2번 보기를 '다'로")
        assert p.recognized and p.ops[0].op == "SetChoice"
        assert p.ops[0].field == "②"  # positional label resolves to ②

    def test_equation(self):
        p = parse_command(_doc(), "1번 수식을 'x^3=8'")
        assert p.recognized and p.ops[0].op == "SetEquation"

    def test_duplicate(self):
        p = parse_command(_doc(), "1번 문제 복제")
        assert p.recognized and p.ops[0].op == "DuplicateQuestion"

    def test_type_change(self):
        p = parse_command(_doc(), "1번을 서술형으로")
        assert p.recognized and p.ops[0].op == "SetField"
        assert p.ops[0].value == "descriptive"

    def test_difficulty(self):
        p = parse_command(_doc(), "1번 난이도 상")
        assert p.recognized and p.ops[0].op == "SetField"
        assert p.ops[0].field == "difficulty"

    def test_output_mode(self):
        p = parse_command(_doc(), "교사용 모드로")
        assert p.recognized and p.ops[0].op == "SetMetadata"
        assert p.ops[0].value == "TEACHER"

    def test_variant_generation_is_pending_action(self):
        p = parse_command(_doc(), "비슷한 문제 3개 만들어")
        assert p.recognized
        assert p.ops == []  # generation never mutates silently
        assert p.pending_action["kind"] == "generate_variants"
        assert p.pending_action["count"] == 3

    def test_ambiguous_stays_unrecognized(self):
        p = parse_command(_doc(), "이거 좀 더 어렵게 해줘")
        assert not p.recognized and p.ops == []


# --- apply path: new ops are real mutations --------------------------------------


@pytest.fixture()
def service(tmp_path):
    cs = CanonicalStore(tmp_path / "canonical.db")
    tn = TenancyDB(tmp_path / "tenancy.db")
    svc = MutationService(cs, tn)
    yield svc
    cs.close()
    tn.close()


def test_duplicate_question_via_apply(service, tmp_path):
    doc = _doc()
    rev = service.create_revision(doc, "tn_1", "alice")
    head = service.store.get_head_revision(doc.id)
    rev2 = service.apply(
        "tn_1", "alice", doc.id, head.id,
        [ChangeOp(op="DuplicateQuestion", target_id=doc.questions[0].id)],
        route="changes",
    )
    out = Document.model_validate(rev2.content_json)
    assert len(out.questions) == 3
    dup = out.questions[-1]
    assert dup.number == 3
    # Verification never carries over to a fresh copy.
    assert all(a.status.value != "HUMAN_VERIFIED" for a in dup.atus)


def test_setfield_difficulty_and_output_mode(service):
    doc = _doc()
    service.create_revision(doc, "tn_1", "alice")
    head = service.store.get_head_revision(doc.id)
    rev2 = service.apply(
        "tn_1", "alice", doc.id, head.id,
        [
            ChangeOp(op="SetField", target_id=doc.questions[0].id,
                     field="difficulty", value="상"),
            ChangeOp(op="SetMetadata", field="output_mode",
                     value="TEACHER"),
        ],
        route="changes",
    )
    out = Document.model_validate(rev2.content_json)
    assert out.questions[0].question_dna["difficulty"] == "상"
    assert out.metadata.output_mode == "TEACHER"


# --- academy profile store -------------------------------------------------------


class TestProfileStore:
    def test_crud_roundtrip(self, tmp_path):
        store = AcademyProfileStore(tmp_path / "profiles")
        p = AcademyProfile(
            academy_id="a1", academy_name="시그마수학",
            columns=1, output_mode="TEACHER",
            colors={"accent": "#1a4a8a"},
        )
        store.upsert("t1", p)
        got = store.get("t1", "a1")
        assert got.academy_name == "시그마수학"
        assert got.columns == 1 and got.output_mode == "TEACHER"
        assert store.get("t1", "missing") is None
        assert [x.academy_id for x in store.list("t1")] == ["a1"]
        # Tenant isolation — another tenant sees nothing.
        assert store.list("t2") == []
        assert store.delete("t1", "a1")
        assert store.get("t1", "a1") is None

    def test_preview_bundle(self, tmp_path):
        profile = AcademyProfile(academy_id="a1", academy_name="학원")
        bundle = apply_style(Document(), profile)
        assert bundle["header_text"] == "학원"
        assert bundle["columns"] == 2


# --- agent history: turn -> revision linkage --------------------------------------


def test_agent_history_turn_and_link(tmp_path):
    hist = AgentHistory(tmp_path / "hist")
    doc = _doc()
    proposal = parse_command(doc, "1번 배점을 5점으로")
    turn = hist.record_turn("doc1", "alice", "1번 배점을 5점으로",
                            proposal, "rev_base")
    assert turn["recognized"] and turn["applied_revision_id"] is None

    assert hist.link_revision("doc1", turn["id"], "rev_applied")
    turns = hist.list_turns("doc1")
    assert turns[0]["applied_revision_id"] == "rev_applied"
    assert turns[0]["base_revision_id"] == "rev_base"
    # Unrecognized commands are recorded too (NEEDS_REVIEW audit).
    bad = parse_command(doc, "뭔가 이상한 말")
    hist.record_turn("doc1", "alice", "뭔가 이상한 말", bad, "rev_base")
    assert hist.list_turns("doc1")[1]["recognized"] is False


# --- DOCX artifact proof ----------------------------------------------------------


def test_docx_render_and_proof(tmp_path):
    from renderers.docx.renderer import render_docx

    doc = _doc()
    blob = render_docx(doc, output_mode="STUDENT_WITH_ENDNOTES")
    path = tmp_path / "exam.docx"
    path.write_bytes(blob)

    checks = docx_checks(path, doc)
    assert checks["FORMAT_OPEN_VALIDITY"] == "PASSED"
    assert checks["ARTIFACT_SEMANTIC_COVERAGE"] == "PASSED"
    assert checks["ARTIFACT_HASH_BINDING"] == "PASSED"
    assert checks["OUTPUT_MODE_CONTENT_POLICY"] == "PASSED"

    # A tampered/mismatched document fails coverage — never a silent pass.
    other = _doc()
    other.questions[0].body = [TextSpan(text="전혀 다른 본문 xyz")]
    assert docx_checks(path, other)["ARTIFACT_SEMANTIC_COVERAGE"] == "FAILED"


def test_docx_checks_in_policy():
    """DOCX carries the same required visual proof as PDF — a docx that
    was never rendered must stay non-final (fail-closed policy)."""
    from canonical.policy import restore_policy

    required = restore_policy().required_artifact_checks_by_format
    assert "RENDERED_TEXT_VISUAL_MATCH" in required["docx"]
    assert "LAYOUT_STYLE_BOUNDS" in required["docx"]
    # Same surface as PDF, plus nothing extra that cannot be proven.
    assert set(required["docx"]) == set(required["pdf"])


def test_docx_without_render_stays_not_run(tmp_path):
    """No docx->pdf render => visual checks NOT_RUN => the format can
    never claim FINAL_ELIGIBLE on inference alone."""
    from renderers.docx.renderer import render_docx

    path = tmp_path / "exam.docx"
    path.write_bytes(render_docx(_doc()))
    checks = docx_checks(path, _doc())
    assert checks["FORMAT_OPEN_VALIDITY"] == "PASSED"
    assert checks["RENDERED_TEXT_VISUAL_MATCH"] == "NOT_RUN"
    assert checks["LAYOUT_STYLE_BOUNDS"] == "NOT_RUN"
    # Every required key is present and honestly reported.
    from canonical.policy import restore_policy

    required = restore_policy().required_artifact_checks_by_format["docx"]
    assert set(checks) == set(required)


def test_docx_render_fills_visual_checks(tmp_path):
    """With a real render of these exact bytes, the visual checks can
    pass — proven, not inferred."""
    from qa.hwp_proof import pdf_text  # noqa: F401  (exists check)
    from renderers.docx.renderer import render_docx
    from renderers.pdf import render_pdf

    doc = _doc()
    docx_path = tmp_path / "exam.docx"
    docx_path.write_bytes(render_docx(doc))
    # Simulate the rendered bytes (what soffice would produce).
    pdf_path = tmp_path / "exam.pdf"
    pdf_path.write_bytes(render_pdf(doc))
    checks = docx_checks(docx_path, doc, pdf_path=pdf_path)
    assert checks["RENDERED_TEXT_VISUAL_MATCH"] in ("PASSED", "FAILED")
    assert checks["LAYOUT_STYLE_BOUNDS"] in ("PASSED", "FAILED")


def test_render_docx_pdf_missing_renderer_returns_none(tmp_path,
                                                       monkeypatch):
    """No soffice on this machine => None, never a fabricated render."""
    from jobs.artifact_bridge import render_docx_pdf
    import shutil

    monkeypatch.setattr(shutil, "which", lambda *a: None)
    monkeypatch.setattr(Path, "exists", lambda self: False)
    docx = tmp_path / "x.docx"
    docx.write_bytes(b"pk")
    assert render_docx_pdf(docx, tmp_path / "x.pdf") is None
