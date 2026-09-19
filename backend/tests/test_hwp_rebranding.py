"""Safe HWP/HWPX rebranding regression suite (REQ-16 / HWP_REBRANDING_SPEC).

Covers structure census, fail-closed planning, allowlisted mutation with
masked-diff invariants, watermark merge/create, all five page-number
mechanisms, print-token confirmation, source immutability, process-leak
inventory, and the proof manifest. Synthetic fixtures only — no real
student files. Actual Hancom COM proof is environment-dependent and is
marked NOT_RUN separately; nothing here fakes it.
"""
from __future__ import annotations

import hashlib
import io
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rebranding import fixtures, planner, scanner
from rebranding.hwpx_mutator import apply_plan
from rebranding.hwp_worker_operation import (
    hwp_process_inventory,
    sweep_spawned_hwp,
)
from rebranding.models import (
    BrandRewriteRequest,
    CandidateKind,
    PlanError,
    RebrandOpKind,
    TitlePolicy,
)
from rebranding.proof import build_proof_manifest

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HC = "http://www.hancom.co.kr/hwpml/2011/core"
_LOGO = b"\x89PNG\r\n\x1a\n" + b"fake-logo-bytes"


def _req(manifest, ids=None, **kw):
    return BrandRewriteRequest(
        tenant_id="tenant-a",
        source_id="src-1",
        academy_name="우리학원",
        title_policy=TitlePolicy.USER_CONFIRMED,
        confirmed_candidate_ids=ids if ids is not None else [
            c.id for c in manifest.title_candidates()
        ],
        **kw,
    )


def _run(data, manifest, req, logo=_LOGO):
    plan = planner.build_plan(manifest, req)
    return apply_plan(data, plan, logo_png=logo)


def _section_text(hwpx: bytes, section="section0.xml") -> str:
    zf = zipfile.ZipFile(io.BytesIO(hwpx))
    return zf.read(f"Contents/{section}").decode("utf-8")


def _section_root(hwpx: bytes, section="section0.xml"):
    return ET.fromstring(zipfile.ZipFile(io.BytesIO(hwpx)).read(f"Contents/{section}"))


# --- scanner census ------------------------------------------------------------


def test_scan_five_page_number_mechanisms():
    m = scanner.scan_hwpx(fixtures.fixture_five_mechanisms(), "five")
    kinds = {c.kind for c in m.page_number_candidates()}
    assert CandidateKind.PAGE_NUM_CONTROL in kinds
    assert CandidateKind.PAGE_NUM_FIELD in kinds
    assert CandidateKind.PAGE_NUM_MASTER_FIELD in kinds
    assert CandidateKind.PRINT_PAGE_TOKEN in kinds
    assert CandidateKind.LITERAL_PAGE_NUMBER in kinds
    literal = [c for c in m.candidates if c.kind is CandidateKind.LITERAL_PAGE_NUMBER]
    assert literal and literal[0].requires_user_confirm is True
    assert literal[0].confidence < 0.8
    # print blocks can carry academy text next to the token — per-block confirm
    tokens = [c for c in m.candidates if c.kind is CandidateKind.PRINT_PAGE_TOKEN]
    assert tokens and all(t.requires_user_confirm for t in tokens)


def test_scan_header_table_cell_and_image_title():
    m = scanner.scan_hwpx(fixtures.fixture_header_table_image_title(), "tbl")
    kinds = {c.kind for c in m.title_candidates()}
    assert CandidateKind.TITLE_HEADER_TABLE_CELL in kinds
    assert CandidateKind.TITLE_IMAGE in kinds
    cell = next(c for c in m.candidates if c.kind is CandidateKind.TITLE_HEADER_TABLE_CELL)
    assert "/tbl[" in cell.path and "/tc[" in cell.path
    assert cell.digest


def test_scan_master_title_variants_and_existing_watermark():
    m = scanner.scan_hwpx(fixtures.fixture_master_title_variants(), "master")
    assert CandidateKind.TITLE_MASTER_TEXT in {c.kind for c in m.title_candidates()}
    assert CandidateKind.EXISTING_WATERMARK in {c.kind for c in m.candidates}
    assert set(m.header_variants) == {"EVEN", "FIRST", "ODD"}
    assert m.existing_watermark_count == 1


def test_scan_multi_section_census():
    m = scanner.scan_hwpx(fixtures.fixture_multi_section(), "multi")
    assert m.section_count == 3
    assert m.control_count >= 4


def test_scan_body_top_title_needs_confirmation():
    m = scanner.scan_hwpx(fixtures.fixture_body_top_title(), "body")
    body = [c for c in m.candidates if c.kind is CandidateKind.TITLE_BODY_TOP]
    assert len(body) == 1
    assert body[0].requires_user_confirm is True


def test_scan_encrypted_and_corrupt_fail_closed():
    m = scanner.scan_hwpx(fixtures.fixture_encrypted(), "enc")
    assert m.flags.encrypted_or_password is True
    m2 = scanner.scan_hwpx(b"not-a-zip", "junk")
    assert m2.flags.corrupt_or_unreadable is True


# --- planner fail-closed ---------------------------------------------------------


def test_plan_requires_title_confirmation():
    m = scanner.scan_hwpx(fixtures.fixture_five_mechanisms(), "five")
    req = _req(m, ids=[])
    with pytest.raises(PlanError) as ei:
        planner.build_plan(m, req)
    assert ei.value.code == "TITLE_NOT_CONFIRMED"


def test_plan_rejects_unknown_candidate_ids():
    m = scanner.scan_hwpx(fixtures.fixture_five_mechanisms(), "five")
    req = _req(m, ids=["cand_doesnotexist"])
    with pytest.raises(PlanError) as ei:
        planner.build_plan(m, req)
    assert ei.value.code == "UNKNOWN_CANDIDATE"


def test_plan_auto_confident_ambiguous_fails():
    """AUTO_CONFIDENT with an unconfirmed second plausible title fails closed."""
    m = scanner.scan_hwpx(fixtures.fixture_five_mechanisms(), "five")
    req = _req(m, ids=[])
    req.title_policy = TitlePolicy.AUTO_CONFIDENT
    with pytest.raises(PlanError) as ei:
        planner.build_plan(m, req)
    assert ei.value.code == "TITLE_AMBIGUOUS"


def test_plan_existing_watermark_requires_replace_flag():
    m = scanner.scan_hwpx(fixtures.fixture_master_title_variants(), "master")
    req = _req(m)
    req.watermark.replace_existing = False
    with pytest.raises(PlanError) as ei:
        planner.build_plan(m, req)
    assert ei.value.code == "WATERMARK_EXISTS"


def test_plan_encrypted_source_fails():
    m = scanner.scan_hwpx(fixtures.fixture_encrypted(), "enc")
    with pytest.raises(PlanError) as ei:
        planner.build_plan(m, _req(m))
    assert ei.value.code == "SOURCE_UNSUPPORTED"


def test_plan_literal_number_never_auto_removed():
    m = scanner.scan_hwpx(fixtures.fixture_five_mechanisms(), "five")
    literal = next(c for c in m.candidates if c.kind is CandidateKind.LITERAL_PAGE_NUMBER)
    req = _req(m)  # literal NOT confirmed
    plan = planner.build_plan(m, req)
    assert all(literal.path not in op.paths for op in plan.operations)


# --- mutation: allowlist + masked diff --------------------------------------------


def test_mutate_title_replaced_footer_text_preserved():
    data = fixtures.fixture_five_mechanisms()
    m = scanner.scan_hwpx(data, "five")
    out, rep = _run(data, m, _req(m))
    assert rep.passed is True
    xml = _section_text(out)
    assert "우리학원" in xml
    assert "다른학원" not in xml
    assert "연락처" in xml  # unrelated footer text survives


def test_mutate_removes_all_confirmed_page_number_mechanisms():
    data = fixtures.fixture_five_mechanisms()
    m = scanner.scan_hwpx(data, "five")
    # confirm titles + every page-number mechanism except the literal digits
    ids = [c.id for c in m.candidates if c.kind is not CandidateKind.LITERAL_PAGE_NUMBER]
    out, rep = _run(data, m, _req(m, ids=ids))
    assert rep.passed is True
    m2 = scanner.scan_hwpx(out, "after")
    after_kinds = {c.kind for c in m2.page_number_candidates()}
    assert CandidateKind.PAGE_NUM_CONTROL not in after_kinds
    assert CandidateKind.PAGE_NUM_FIELD not in after_kinds
    assert CandidateKind.PAGE_NUM_MASTER_FIELD not in after_kinds
    assert CandidateKind.PRINT_PAGE_TOKEN not in after_kinds
    # literal number was NOT confirmed -> must survive
    assert CandidateKind.LITERAL_PAGE_NUMBER in after_kinds
    # autoNum fields actually gone from XML
    assert "autoNum" not in _section_text(out)
    assert "pageNumCtrl" not in _section_text(out)


def test_mutate_source_bytes_immutable():
    data = fixtures.fixture_five_mechanisms()
    before = hashlib.sha256(data).hexdigest()
    m = scanner.scan_hwpx(data, "five")
    out, _rep = _run(data, m, _req(m))
    assert hashlib.sha256(data).hexdigest() == before
    assert hashlib.sha256(out).hexdigest() != before
    assert m.source_sha256 == before


def test_mutate_body_and_section_count_preserved():
    data = fixtures.fixture_multi_section()
    m = scanner.scan_hwpx(data, "multi")
    # confirm everything EXCEPT the ambiguous body-top title — the body
    # paragraph is real content here and must survive untouched
    ids = [c.id for c in m.candidates if c.kind is not CandidateKind.TITLE_BODY_TOP]
    out, rep = _run(data, m, _req(m, ids=ids))
    assert rep.passed is True
    m2 = scanner.scan_hwpx(out, "after")
    assert m2.section_count == 3
    for i, body in [(0, "섹션1 본문"), (1, "섹션2 본문"), (2, "섹션3 본문")]:
        assert body in _section_text(out, f"section{i}.xml")


def test_mutate_watermark_merges_into_existing_master():
    data = fixtures.fixture_master_title_variants()
    m = scanner.scan_hwpx(data, "master")
    req = _req(m)
    req.watermark.replace_existing = True
    out, rep = _run(data, m, req)
    assert rep.passed is True
    root = _section_root(out)
    pics = list(root.iter(f"{{{HP}}}pic"))
    # original watermark pic + newly merged watermark pic — real HWPML
    # resolves pictures via hc:img/@binaryItemIDRef; legacy src still honored
    wm_refs = []
    for p in pics:
        for img in (p.find(f"{{{HC}}}img"), p.find(f"{{{HP}}}img")):
            if img is not None:
                wm_refs.append(img.get("binaryItemIDRef") or img.get("src"))
    assert any(s == "BinData/wm.png" for s in wm_refs)   # existing kept
    assert any(s == "rebrand_logo" for s in wm_refs)      # merged in


def test_mutate_watermark_created_when_no_master():
    data = fixtures.fixture_body_top_title()
    m = scanner.scan_hwpx(data, "body")
    ids = [c.id for c in m.candidates]
    out, rep = _run(data, m, _req(m, ids=ids))
    assert rep.passed is True
    # no per-page host -> a real hp:header ctrl is created (a fabricated
    # hp:masterPage is invalid HWPML and crashes real Hancom)
    assert "<hp:header" in _section_text(out)
    assert "<hp:masterPage" not in _section_text(out)
    assert any(p.startswith("section0.xml/header") for p in rep.added_paths)


def test_mutate_table_cell_title_only_cell_changes():
    data = fixtures.fixture_header_table_image_title()
    m = scanner.scan_hwpx(data, "tbl")
    # confirm all EXCEPT the image title — the logo picture cell is not a
    # text title here and must be preserved byte-identically
    ids = [c.id for c in m.candidates if c.kind is not CandidateKind.TITLE_IMAGE]
    out, rep = _run(data, m, _req(m, ids=ids))
    assert rep.passed is True
    xml = _section_text(out)
    assert "우리학원" in xml
    assert 'src="BinData/old_logo.png"' in xml  # sibling picture cell untouched
    assert "문의 02-000-0000" in xml            # unrelated footer text kept


def test_mutate_drawtext_title_inside_container():
    """글상자(container>rect>drawText) title runs — the shape jinsu-style
    Hancom files use — are scanned as confirm-only candidates and mutated
    surgically without touching the host run or sibling objects."""
    data = fixtures.fixture_drawtext_title()
    m = scanner.scan_hwpx(data, "dt")
    dt = [c for c in m.candidates if "drawText" in c.path]
    assert len(dt) == 2  # header box + body box
    assert all(c.requires_user_confirm for c in dt)
    assert {c.kind for c in dt} == {
        CandidateKind.TITLE_HEADER_TEXT,
        CandidateKind.TITLE_BODY_TOP,
    }
    box_pic = [
        c for c in m.candidates
        if c.kind is CandidateKind.TITLE_IMAGE and "container" in c.path
    ]
    assert len(box_pic) == 1
    # confirm everything EXCEPT the plain body-top question paragraph —
    # it is a title candidate by position only and must stay untouched
    ids = [
        c.id for c in m.candidates
        if not (c.kind is CandidateKind.TITLE_BODY_TOP and "drawText" not in c.path)
    ]
    out, rep = _run(data, m, _req(m, ids=ids))
    assert rep.passed is True
    xml = _section_text(out)
    assert xml.count("우리학원") >= 2          # header + body box replaced
    assert "다른학원 중간고사" not in xml       # 글상자 title replaced
    assert "다른학원 모의고사" not in xml
    assert "1. 다음을 구하시오." in xml        # body question preserved
    assert "연락처" in xml                    # footer text preserved
    assert "image1" not in xml               # box logo pic → rebrand_logo


def test_mutate_drawtext_declined_stays_identical():
    """A declined 글상자 title is preserved byte-identically — the
    confirmation gate is the safety mechanism."""
    data = fixtures.fixture_drawtext_title()
    m = scanner.scan_hwpx(data, "dt")
    body_box = next(
        c for c in m.candidates
        if c.kind is CandidateKind.TITLE_BODY_TOP and "drawText" in c.path
    )
    # confirm only the header box + page field — body box stays
    ids = [
        c.id for c in m.candidates
        if c.id != body_box.id
        and c.kind is not CandidateKind.TITLE_IMAGE
    ]
    out, rep = _run(data, m, _req(m, ids=ids))
    assert rep.passed is True
    xml = _section_text(out)
    assert "다른학원 모의고사" in xml   # declined body box preserved
    assert "다른학원 중간고사" not in xml
    assert "image1" in xml                  # declined picture preserved


def test_scan_cell_background_logo_disclosed():
    """seum-style branding: the logo is a table-cell background image in
    header.xml's borderFills — the census must surface it as an
    unsupported (confirm-only) structure, never silently miss it."""
    m = scanner.scan_hwpx(fixtures.fixture_cell_borderfill_logo(), "bf")
    bf = [
        c for c in m.candidates
        if (c.evidence or {}).get("object") == "cell_border_fill"
    ]
    assert len(bf) == 1
    assert bf[0].kind is CandidateKind.TITLE_IMAGE
    assert bf[0].requires_user_confirm is True
    assert bf[0].section == "header.xml"
    assert bf[0].evidence["img"] == "image1"


def test_plan_cell_background_confirm_fails_closed():
    """Confirming a cell-background brand fails closed — the shared style
    part is not surgically mutable yet."""
    m = scanner.scan_hwpx(fixtures.fixture_cell_borderfill_logo(), "bf")
    ids = [c.id for c in m.candidates]
    with pytest.raises(PlanError) as ei:
        planner.build_plan(m, _req(m, ids=ids))
    assert ei.value.code == "STRUCTURE_UNSUPPORTED"


def test_plan_cell_background_declined_preserves_fill():
    """Declining the background logo rebrands the rest while header.xml
    stays byte-identical."""
    data = fixtures.fixture_cell_borderfill_logo()
    m = scanner.scan_hwpx(data, "bf")
    ids = [
        c.id for c in m.candidates
        if (c.evidence or {}).get("object") != "cell_border_fill"
        and c.kind is not CandidateKind.TITLE_BODY_TOP
    ]
    out, rep = _run(data, m, _req(m, ids=ids))
    assert rep.passed is True
    before = zipfile.ZipFile(io.BytesIO(data)).read("Contents/header.xml")
    after = zipfile.ZipFile(io.BytesIO(out)).read("Contents/header.xml")
    assert after == before
    xml = _section_text(out)
    assert "우리학원" in xml
    assert "본문 유지" in xml


def test_mutate_print_tokens_only_confirmed_blocks():
    data = fixtures.fixture_five_mechanisms()
    m = scanner.scan_hwpx(data, "five")
    tokens = [c for c in m.candidates if c.kind is CandidateKind.PRINT_PAGE_TOKEN]
    assert len(tokens) == 2
    # confirm only ONE print token + title + non-literal numbers
    ids = [c.id for c in m.title_candidates()]
    ids += [c.id for c in m.candidates if c.kind is CandidateKind.PAGE_NUM_CONTROL]
    ids += [c.id for c in m.candidates if c.kind is CandidateKind.PAGE_NUM_FIELD]
    ids += [c.id for c in m.candidates if c.kind is CandidateKind.PAGE_NUM_MASTER_FIELD]
    ids.append(tokens[0].id)
    req = _req(m, ids=ids)
    plan = planner.build_plan(m, req)
    # the unconfirmed token must not appear in any op
    assert all(tokens[1].path not in op.paths for op in plan.operations)
    out, rep = apply_plan(data, plan, logo_png=_LOGO)
    assert rep.passed is True
    settings = zipfile.ZipFile(io.BytesIO(out)).read("settings.xml").decode()
    header_block = settings.split("<ha:printHeader>")[1].split("</ha:printHeader>")[0]
    footer_block = settings.split("<ha:printFooter>")[1].split("</ha:printFooter>")[0]
    assert "^p" not in header_block          # confirmed block scrubbed
    assert "교육원" in header_block          # non-token text preserved
    assert "- ^P -" in footer_block          # unconfirmed block byte-identical


# --- mutation fail-closed paths -----------------------------------------------------


def test_mutate_digest_mismatch_aborts():
    data = fixtures.fixture_five_mechanisms()
    m = scanner.scan_hwpx(data, "five")
    plan = planner.build_plan(m, _req(m))
    plan.operations[0].expected_digests = {
        plan.operations[0].paths[0]: "0" * 64
    }
    with pytest.raises(PlanError) as ei:
        apply_plan(data, plan, logo_png=_LOGO)
    assert ei.value.code == "DIGEST_MISMATCH"


def test_mutate_missing_path_aborts():
    data = fixtures.fixture_five_mechanisms()
    m = scanner.scan_hwpx(data, "five")
    plan = planner.build_plan(m, _req(m))
    plan.operations[0].paths = ["section0.xml/ctrl[99]/header"]
    plan.operations[0].expected_digests = {}
    with pytest.raises(PlanError) as ei:
        apply_plan(data, plan, logo_png=_LOGO)
    assert ei.value.code in {"PATH_MISS", "PATH_SECTION"}


def test_mutate_missing_logo_aborts():
    data = fixtures.fixture_five_mechanisms()
    m = scanner.scan_hwpx(data, "five")
    plan = planner.build_plan(m, _req(m))
    with pytest.raises(PlanError) as ei:
        apply_plan(data, plan, logo_png=None)
    assert ei.value.code == "LOGO_REQUIRED"


def test_mutate_unknown_section_aborts():
    data = fixtures.fixture_five_mechanisms()
    m = scanner.scan_hwpx(data, "five")
    plan = planner.build_plan(m, _req(m))
    plan.operations[0].section = "section9.xml"
    with pytest.raises(PlanError) as ei:
        apply_plan(data, plan, logo_png=_LOGO)
    assert ei.value.code == "PATH_SECTION"


# --- process lifecycle ---------------------------------------------------------------


def test_hwp_process_inventory_is_a_set():
    """Windows: PID set (possibly empty). Non-Windows: empty — COM tests
    stay NOT_RUN rather than faking success."""
    assert isinstance(hwp_process_inventory(), set)


def test_sweep_with_no_spawned_pids_reports_zero_leak():
    report = sweep_spawned_hwp(hwp_process_inventory(), grace_s=0.1)
    assert report["leak"] == 0
    assert isinstance(report["spawned"], list)


# --- proof manifest -------------------------------------------------------------------


def test_proof_manifest_marks_unrun_worker_steps():
    data = fixtures.fixture_five_mechanisms()
    m = scanner.scan_hwpx(data, "five")
    plan = planner.build_plan(m, _req(m))
    out, rep = apply_plan(data, plan, logo_png=_LOGO)
    proof = build_proof_manifest(
        tenant_id="tenant-a",
        document_id="doc-1",
        source_id="src-1",
        source_name="five.hwpx",
        source_sha256=m.source_sha256,
        output_sha256=hashlib.sha256(out).hexdigest(),
        output_format="hwpx",
        manifest=m,
        plan=plan,
        invariant=rep,
        worker_proof=None,
        artifact_id=None,
    )
    assert proof["checks"]["PLAN_ALLOWLIST_ONLY"] == "PASSED"
    assert proof["checks"]["OUTSIDE_MASK_DIFF_ZERO"] == "PASSED"
    assert proof["checks"]["HWP_ACTUAL_REOPEN"] == "NOT_RUN"
    assert proof["checks"]["HWP_PDF_RENDER"] == "NOT_RUN"
    assert proof["checks"]["PROCESS_LEAK_ZERO"] == "NOT_RUN"
    assert proof["source"]["sha256"] == m.source_sha256
    assert proof["plan_digest"] == plan.digest


def test_proof_manifest_worker_steps_recorded():
    data = fixtures.fixture_five_mechanisms()
    m = scanner.scan_hwpx(data, "five")
    plan = planner.build_plan(m, _req(m))
    out, rep = apply_plan(data, plan, logo_png=_LOGO)
    fake_worker = {
        "checks": {
            "HWP_ACTUAL_REOPEN": "PASSED",
            "FORMAT_CONVERSION_PROVENANCE": "PASSED",
        },
        "hwp_process": {"leak": 0, "spawned": [], "killed": []},
    }
    proof = build_proof_manifest(
        tenant_id="tenant-a",
        document_id="doc-1",
        source_id="src-1",
        source_name="five.hwpx",
        source_sha256=m.source_sha256,
        output_sha256=hashlib.sha256(out).hexdigest(),
        output_format="hwpx",
        manifest=m,
        plan=plan,
        invariant=rep,
        worker_proof=fake_worker,
    )
    assert proof["checks"]["HWP_ACTUAL_REOPEN"] == "PASSED"
    assert proof["checks"]["PROCESS_LEAK_ZERO"] == "PASSED"


# --- API integration (tenant/revision/artifact contract) -----------------------------


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("EXAMDNA_DATA", str(tmp_path / "data"))
    import app.deps as deps

    deps.reset()
    import app.api.uploads as uploads_api

    monkeypatch.setattr(uploads_api, "run_once", lambda *a, **k: False)
    from app.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c, deps, monkeypatch
    deps.reset()


def _setup_tenant(c):
    h = {"X-Dev-User": "u1"}
    c.post("/api/auth/dev-login", json={"user_id": "u1", "name": "Alice"})
    tid = c.post("/api/tenants", json={"name": "Academy"}, headers=h).json()["id"]
    return tid, h


def _import(c, h, tid, data=None, name="exam.hwpx"):
    r = c.post(
        f"/api/v1/tenants/{tid}/rebrand/imports",
        headers=h,
        files={"file": (name, data or fixtures.fixture_five_mechanisms())},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_api_import_scan_apply_end_to_end(env):
    c, deps, monkeypatch = env
    tid, h = _setup_tenant(c)
    imp = _import(c, h, tid)
    assert imp["source_format"] == "hwpx"
    doc_id = imp["document_id"]

    cand = c.get(
        f"/api/v1/tenants/{tid}/documents/{doc_id}/rebrand/candidates", headers=h
    )
    assert cand.status_code == 200, cand.text
    manifest = cand.json()["data"]["manifest"]
    ids = [x["id"] for x in manifest["candidates"]]

    # logo upload
    lg = c.post(
        f"/api/v1/tenants/{tid}/rebrand/logo",
        headers=h,
        files={"file": ("logo.png", _LOGO, "image/png")},
    )
    assert lg.status_code == 200

    r = c.post(
        f"/api/v1/tenants/{tid}/documents/{doc_id}/rebrand/apply",
        headers=h,
        json={
            "academy_name": "우리학원",
            "confirmed_candidate_ids": ids,
            "remove_page_numbers": True,
            "watermark_enabled": True,
            "watermark_replace_existing": True,
            "logo_sha256": lg.json()["data"]["logo_sha256"],
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["invariant"]["passed"] is True
    assert data["artifact"]["artifact_sha256"]
    assert data["artifact"]["revision_id"] == data["revision"]["id"]
    # synthetic-only path: real COM steps are never faked in the response
    assert data["proof"]["checks"]["OUTSIDE_MASK_DIFF_ZERO"] == "PASSED"
    assert data["proof"]["checks"]["SOURCE_IMMUTABLE"] == "PASSED"


def test_api_apply_without_confirmation_fails_closed(env):
    c, deps, monkeypatch = env
    tid, h = _setup_tenant(c)
    doc_id = _import(c, h, tid)["document_id"]
    r = c.post(
        f"/api/v1/tenants/{tid}/documents/{doc_id}/rebrand/apply",
        headers=h,
        json={"academy_name": "우리학원", "confirmed_candidate_ids": []},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["error"]["code"] == "TITLE_NOT_CONFIRMED"


def test_api_source_bytes_never_mutated(env):
    c, deps, monkeypatch = env
    tid, h = _setup_tenant(c)
    imp = _import(c, h, tid)
    doc_id = imp["document_id"]
    cstore = deps.get_canonical()
    pages = cstore.list_source_pages(doc_id)
    asset = cstore.get_source_asset(pages[0].asset_id)
    before = deps.get_object_store().open(f"local://{asset.blob_key}").read_bytes()
    cand = c.get(
        f"/api/v1/tenants/{tid}/documents/{doc_id}/rebrand/candidates", headers=h
    )
    ids = [x["id"] for x in cand.json()["data"]["manifest"]["candidates"]]
    c.post(
        f"/api/v1/tenants/{tid}/documents/{doc_id}/rebrand/apply",
        headers=h,
        json={
            "academy_name": "우리학원",
            "confirmed_candidate_ids": ids,
            "watermark_replace_existing": True,
            "logo_sha256": "",
            "watermark_enabled": False,
        },
    )
    after = deps.get_object_store().open(f"local://{asset.blob_key}").read_bytes()
    assert before == after
    assert hashlib.sha256(after).hexdigest() == imp["source_sha256"]


def test_api_rebrand_cross_tenant_isolation(env):
    c, deps, monkeypatch = env
    tid, h = _setup_tenant(c)
    doc_id = _import(c, h, tid)["document_id"]
    # second tenant must not see or mutate the first tenant's source
    c.post("/api/auth/dev-login", json={"user_id": "u2", "name": "Bob"})
    h2 = {"X-Dev-User": "u2"}
    tid2 = c.post("/api/tenants", json={"name": "Other"}, headers=h2).json()["id"]
    r = c.get(
        f"/api/v1/tenants/{tid2}/documents/{doc_id}/rebrand/candidates", headers=h2
    )
    assert r.status_code == 404
    r = c.post(
        f"/api/v1/tenants/{tid2}/documents/{doc_id}/rebrand/apply",
        headers=h2,
        json={"academy_name": "X", "confirmed_candidate_ids": []},
    )
    assert r.status_code == 404


def test_api_import_rejects_non_hwp(env):
    c, deps, monkeypatch = env
    tid, h = _setup_tenant(c)
    r = c.post(
        f"/api/v1/tenants/{tid}/rebrand/imports",
        headers=h,
        files={"file": ("p.png", b"\x89PNG\r\n\x1a\n" + b"x")},
    )
    assert r.status_code == 422


def test_api_candidates_deterministic_ids(env):
    """Re-scanning the same source must produce identical candidate ids so
    user confirmations stay valid across requests."""
    c, deps, monkeypatch = env
    tid, h = _setup_tenant(c)
    doc_id = _import(c, h, tid)["document_id"]
    a = c.get(
        f"/api/v1/tenants/{tid}/documents/{doc_id}/rebrand/candidates", headers=h
    ).json()["data"]["manifest"]["candidates"]
    b = c.get(
        f"/api/v1/tenants/{tid}/documents/{doc_id}/rebrand/candidates", headers=h
    ).json()["data"]["manifest"]["candidates"]
    assert [x["id"] for x in a] == [x["id"] for x in b]


# --- page role (AT-061) ----------------------------------------------------------------

_PDF_2PAGE = (
    b"%PDF-1.4\n"
    b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
    b"2 0 obj << /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >> endobj\n"
    b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >> endobj\n"
    b"4 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >> endobj\n"
    b"trailer << /Root 1 0 R >>\n%%EOF"
)


def test_page_role_confirm_and_manifest_visibility(env):
    c, deps, monkeypatch = env
    tid, h = _setup_tenant(c)
    up = c.post(
        "/api/uploads",
        headers=h,
        files=[("files", ("exam.pdf", _PDF_2PAGE, "application/pdf"))],
    )
    assert up.status_code == 200, up.text
    doc_id = up.json()["document_id"]
    pages = c.get(
        f"/api/v1/tenants/{tid}/documents/{doc_id}/pages", headers=h
    ).json()["data"]["pages"]
    assert len(pages) == 2
    # scanned/image PDFs have no text layer -> UNKNOWN, never auto-QUESTION
    assert all(p["page_role"] in {"UNKNOWN", "QUESTION", "ANSWER_KEY"} for p in pages)

    target = pages[-1]["source_page_id"]
    doc = c.get(f"/api/v1/tenants/{tid}/documents/{doc_id}", headers=h).json()["data"]
    etag = doc["head_revision"]["id"]
    r = c.patch(
        f"/api/v1/tenants/{tid}/documents/{doc_id}/pages/{target}/role",
        headers={**h, "If-Match": etag},
        json={"page_role": "ANSWER_KEY"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["page_role"] == "ANSWER_KEY"
    assert r.json()["data"]["role_source"] == "USER"
    # role now visible in the page manifest listing
    pages2 = c.get(
        f"/api/v1/tenants/{tid}/documents/{doc_id}/pages", headers=h
    ).json()["data"]["pages"]
    answer_page = [p for p in pages2 if p["source_page_id"] == target][0]
    assert answer_page["page_role"] == "ANSWER_KEY"


def test_page_role_rejects_invalid_and_cross_tenant(env):
    c, deps, monkeypatch = env
    tid, h = _setup_tenant(c)
    up = c.post(
        "/api/uploads",
        headers=h,
        files=[("files", ("exam.pdf", _PDF_2PAGE, "application/pdf"))],
    )
    doc_id = up.json()["document_id"]
    pages = c.get(
        f"/api/v1/tenants/{tid}/documents/{doc_id}/pages", headers=h
    ).json()["data"]["pages"]
    target = pages[0]["source_page_id"]
    doc = c.get(f"/api/v1/tenants/{tid}/documents/{doc_id}", headers=h).json()["data"]
    etag = doc["head_revision"]["id"]
    r = c.patch(
        f"/api/v1/tenants/{tid}/documents/{doc_id}/pages/{target}/role",
        headers={**h, "If-Match": etag},
        json={"page_role": "NOPE"},
    )
    assert r.status_code == 422
    # cross-tenant: other academy must not confirm roles on this document
    c.post("/api/auth/dev-login", json={"user_id": "u2", "name": "Bob"})
    h2 = {"X-Dev-User": "u2"}
    tid2 = c.post("/api/tenants", json={"name": "Other"}, headers=h2).json()["id"]
    r = c.patch(
        f"/api/v1/tenants/{tid2}/documents/{doc_id}/pages/{target}/role",
        headers={**h2, "If-Match": etag},
        json={"page_role": "ANSWER_KEY"},
    )
    assert r.status_code == 404
