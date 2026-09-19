"""Structure census for existing HWPX sources (HWP_REBRANDING_SPEC §5 step 3).

Parses every `Contents/section*.xml` control tree plus `settings.xml` print
tokens and produces a BrandStructureManifest with *exact control paths* —
the only addressing mode the mutator accepts. Nothing here mutates bytes.
"""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from xml.etree import ElementTree as ET

from .models import (
    AUTO_CONFIDENCE_MIN,
    BrandStructureManifest,
    CandidateKind,
    ControlCandidate,
    SourceFlags,
)

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_HH_NS = "http://www.hancom.co.kr/hwpml/2011/head"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
OPF = "http://www.idpf.org/2007/opf"

_NS = {"hp": HP, "hs": HS, "opf": OPF}

_SECTION_RE = re.compile(r"^Contents/section(\d+)\.xml$")
_PAGE_NUM_TEXT_RE = re.compile(r"^\s*[-–—\[\(]?\s*\d+\s*[-–—\]\)]?\s*$")
_PRINT_TOKEN_RE = re.compile(r"\^[pPnN]")

# control kinds we inventory (tag local-name -> layer classification later)
_CTRL_TAGS = {
    "header",
    "footer",
    "footNote",
    "endNote",
    "autoNum",
    "newNum",
    "pageNumCtrl",
    "pageNum",
    "masterPage",
    "fieldBegin",
    "fieldEnd",
    "secPr",
}

_IMG_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _cand_id(kind: str, section: str, path: str, digest: str) -> str:
    """Deterministic candidate id — the same source always scans to the
    same ids, so user confirmations survive a re-scan."""
    raw = f"{kind}|{section}|{path}|{digest}"
    return "cand_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _el_digest(el: ET.Element) -> str:
    return hashlib.sha256(ET.tostring(el, encoding="utf-8")).hexdigest()


def _text_of(el: ET.Element) -> str:
    return "".join(t.text or "" for t in el.iter(f"{{{HP}}}t"))


def _iter_controls(root: ET.Element):
    """Yield (path, element) for every *section-level* control: hp:ctrl
    elements that are direct children of direct body-paragraph runs.
    Field controls nested inside header/footer/master subLists are NOT
    counted here — they are addressed through run-level paths so indices
    stay stable and unambiguous."""
    idx = 0
    for p in list(root):
        if p.tag != f"{{{HP}}}p":
            continue
        for run in p.findall(f"{{{HP}}}run"):
            for ctrl in run.findall(f"{{{HP}}}ctrl"):
                for child in list(ctrl):
                    name = _local(child.tag)
                    if name in _CTRL_TAGS:
                        yield f"ctrl[{idx}]/{name}", child
                idx += 1


def _direct_text(run: ET.Element) -> str:
    """Only the run's own hp:t text — text nested inside tables, pictures,
    or field controls does NOT belong to the run and must not make an
    object-hosting run look like a title."""
    return "".join(t.text or "" for t in run.findall(f"{{{HP}}}t"))


def _sublist_para_runs(container: ET.Element):
    """Yield (path_suffix, run_element, direct_text) for text runs inside
    the control's hp:subList paragraphs."""
    sub = container.find(f"{{{HP}}}subList")
    if sub is None:
        return
    for pi, p in enumerate(sub.findall(f"{{{HP}}}p")):
        for ri, run in enumerate(p.findall(f"{{{HP}}}run")):
            yield f"sublist/p[{pi}]/run[{ri}]", run, _direct_text(run)


def _nested_tables(container: ET.Element):
    for ti, tbl in enumerate(container.iter(f"{{{HP}}}tbl")):
        yield ti, tbl


def _named_children(el: ET.Element):
    """(segment, child) for each direct child, indexing siblings by local
    tag name — the same indexing the mutator's named-child step resolves."""
    counts: dict[str, int] = {}
    for child in list(el):
        name = _local(child.tag)
        idx = counts.get(name, 0)
        counts[name] = idx + 1
        yield f"{name}[{idx}]", child


def _walk_drawtext(scope: ET.Element, prefix: str):
    """(path_suffix, run, direct_text) for text runs inside hp:drawText
    drawing objects (글상자) nested anywhere below `scope` — paths index
    same-named siblings so the mutator resolves them exactly."""
    for seg, child in _named_children(scope):
        cpath = f"{prefix}/{seg}"
        if _local(child.tag) == "drawText":
            sub = child.find(f"{{{HP}}}subList")
            if sub is None:
                continue
            for pi, p in enumerate(sub.findall(f"{{{HP}}}p")):
                for ri, run in enumerate(p.findall(f"{{{HP}}}run")):
                    yield f"{cpath}/sublist/p[{pi}]/run[{ri}]", run, _direct_text(run)
        else:
            yield from _walk_drawtext(child, cpath)


def _container_drawtext_runs(control: ET.Element, base: str):
    """(full_path, run, direct_text) for 글상자(drawText) text runs hosted
    by containers inside a header/footer/masterPage control's direct
    subList runs."""
    sub = control.find(f"{{{HP}}}subList")
    if sub is None:
        return
    for pi, p in enumerate(sub.findall(f"{{{HP}}}p")):
        for ri, run in enumerate(p.findall(f"{{{HP}}}run")):
            for ci, cont in enumerate(run.findall(f"{{{HP}}}container")):
                host = f"{base}/sublist/p[{pi}]/run[{ri}]"
                for dt_path, dt_run, dt_text in _walk_drawtext(
                    cont, f"container[{ci}]"
                ):
                    yield f"{host}/{dt_path}", dt_run, dt_text


def _is_page_field(el: ET.Element) -> bool:
    """autoNum numType=PAGE or fieldBegin type=PAGE/_PAGE variants."""
    name = _local(el.tag)
    if name == "autoNum":
        return (el.get("numType") or "").upper() in {
            "PAGE",
            "PAGE_NUMBER",
            "TOTAL_PAGE",
        }
    if name == "fieldBegin":
        return "PAGE" in (el.get("type") or "").upper()
    return False


def _find_page_fields(container: ET.Element) -> list[tuple[str, ET.Element]]:
    """(sublist path, element) of dynamic page-number fields inside a
    header/footer/masterPage container."""
    out: list[tuple[str, ET.Element]] = []
    sub = container.find(f"{{{HP}}}subList")
    if sub is None:
        return out
    for pi, p in enumerate(sub.findall(f"{{{HP}}}p")):
        for ri, run in enumerate(p.findall(f"{{{HP}}}run")):
            for ci, ctrl in enumerate(run.findall(f"{{{HP}}}ctrl")):
                for child in list(ctrl):
                    if _is_page_field(child):
                        out.append((f"sublist/p[{pi}]/run[{ri}]/ctrl[{ci}]/{_local(child.tag)}", child))
            for child in list(run):
                if _is_page_field(child):
                    out.append((f"sublist/p[{pi}]/run[{ri}]/{_local(child.tag)}", child))
    return out


def _find_literal_numbers(container: ET.Element) -> list[tuple[str, ET.Element, str]]:
    """Footer text runs that are *just* a number — literal page numbers are
    never auto-removed; they need per-page recurrence evidence + user
    confirmation."""
    out = []
    for path, run, text in _sublist_para_runs(container):
        if text.strip() and _PAGE_NUM_TEXT_RE.match(text.strip()):
            out.append((path, run, text.strip()))
    return out


def _find_pictures(container: ET.Element) -> list[tuple[str, ET.Element]]:
    out = []
    sub = container.find(f"{{{HP}}}subList")
    scope = sub if sub is not None else container
    for pi, pic in enumerate(scope.iter(f"{{{HP}}}pic")):
        out.append((f"pic[{pi}]", pic))
    return out


def _is_watermark_pic(pic: ET.Element) -> bool:
    """A master-page picture anchored to the paper, centered, behind text —
    treated as an existing watermark (spec §7)."""
    pos = pic.find(f"{{{HP}}}pos")
    comment = pic.find(f"{{{HP}}}shapeComment")
    comment_text = (comment.text or "") if comment is not None else ""
    if "watermark" in comment_text.lower() or "워터마크" in comment_text:
        return True
    if pos is not None and (pos.get("vertRelTo") or "").upper() == "PAPER":
        return True
    z = pic.get("zOrder")
    try:
        if z is not None and int(z) < 0:
            return True
    except ValueError:
        pass
    return False


def scan_hwpx(data: bytes, source_name: str = "") -> BrandStructureManifest:
    """Census an HWPX package. Raises ValueError on unreadable input —
    callers map that to fail-closed flags instead of mutating."""
    manifest = BrandStructureManifest(
        source_name=source_name,
        source_sha256=hashlib.sha256(data).hexdigest(),
        source_format="hwpx",
    )
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        manifest.flags.corrupt_or_unreadable = True
        return manifest

    names = set(zf.namelist())
    if "mimetype" not in names:
        manifest.flags.unsupported_format = True
    section_names = sorted(
        (n for n in names if _SECTION_RE.match(n)),
        key=lambda n: int(_SECTION_RE.match(n).group(1)),  # type: ignore[union-attr]
    )
    if not section_names:
        manifest.flags.corrupt_or_unreadable = True
        return manifest

    flags = manifest.flags
    header_variants: set[str] = set()
    footer_variants: set[str] = set()
    body_top_done = False

    # cell background images live in Contents/header.xml borderFills —
    # branding can hide there (seum-style logo cell). Census them so the
    # user sees every brand structure; the mutator clones the fill and
    # repoints only the confirmed cell.
    fill_images: dict[str, tuple[str, str]] = {}  # borderFill id -> (img ref, img digest)
    if "Contents/header.xml" in names:
        try:
            head_root = ET.fromstring(zf.read("Contents/header.xml"))
            for bf in head_root.iter(f"{{{_HH_NS}}}borderFill"):
                bid = bf.get("id")
                for im in bf.iter():
                    if _local(im.tag) == "img" and bid:
                        ref = im.get("binaryItemIDRef") or im.get("src") or ""
                        fill_images[bid] = (ref, _el_digest(im))
                        break
        except ET.ParseError:
            pass

    for s_name in section_names:
        sec_label = s_name.split("/")[-1]
        raw = zf.read(s_name)
        lowered = raw.decode("utf-8", errors="ignore")
        if "OLEObject" in lowered or "oleObject" in lowered:
            flags.external_link_or_ole = True
        if "<script" in lowered or "macro" in lowered.lower():
            flags.macro_or_script = True
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            flags.corrupt_or_unreadable = True
            continue

        for base_path, child in _iter_controls(root):
            name = _local(child.tag)
            base = f"{sec_label}/{base_path}"
            manifest.control_count += 1
            digest = _el_digest(child)

            if name == "header":
                apply_type = (child.get("applyPageType") or "BOTH").upper()
                header_variants.add(apply_type)
                _inventory_header_footer(
                    manifest, child, base, sec_label, "header", apply_type,
                    digest, fill_images,
                )
            elif name == "footer":
                apply_type = (child.get("applyPageType") or "BOTH").upper()
                footer_variants.add(apply_type)
                _inventory_header_footer(
                    manifest, child, base, sec_label, "footer", apply_type,
                    digest, fill_images,
                )
            elif name == "masterPage":
                manifest.master_page_count += 1
                _inventory_master(manifest, child, base, sec_label, digest, fill_images)
            elif name == "pageNumCtrl":
                manifest.candidates.append(
                    ControlCandidate(
                        id=_cand_id(CandidateKind.PAGE_NUM_CONTROL.value, sec_label, base, digest),
                        kind=CandidateKind.PAGE_NUM_CONTROL,
                        section=sec_label,
                        path=base,
                        layer="body",
                        text_preview="쪽번호 위치",
                        confidence=0.95,
                        evidence={"pos": child.get("pos") or child.get("page") or ""},
                        digest=digest,
                    )
                )
            elif name == "pageNum":
                manifest.candidates.append(
                    ControlCandidate(
                        id=_cand_id(CandidateKind.PAGE_NUM_CONTROL.value, sec_label, base, digest),
                        kind=CandidateKind.PAGE_NUM_CONTROL,
                        section=sec_label,
                        path=base,
                        layer="body",
                        text_preview="쪽번호(구형식)",
                        confidence=0.95,
                        digest=digest,
                    )
                )

        # body-top title candidate: first non-empty *direct* body paragraph.
        # Only direct children of the section root count — paragraphs inside
        # header/footer/master subLists are nested and handled above.
        if not body_top_done:
            body_paras = [c for c in list(root) if c.tag == f"{{{HP}}}p"]
            for pi, p in enumerate(body_paras):
                # skip the section-properties paragraph and anything hosting
                # controls — their aggregated text is control content, not
                # body text
                if p.find(f".//{{{HP}}}secPr") is not None or list(p.iter(f"{{{HP}}}ctrl")):
                    continue
                # text OUTSIDE any ctrl (control text must not leak into a
                # body-top preview)
                text = ""
                for t in p.iter(f"{{{HP}}}t"):
                    text += t.text or ""
                text = text.strip()
                if not text:
                    continue
                run_idx = 0
                run_el = None
                for ri, run in enumerate(p.findall(f"{{{HP}}}run")):
                    if _text_of(run).strip():
                        run_idx = ri
                        run_el = run
                        break
                _bt_path = f"{sec_label}/body/p[{pi}]/run[{run_idx}]"
                _bt_dg = _el_digest(run_el if run_el is not None else p)
                manifest.candidates.append(
                    ControlCandidate(
                        id=_cand_id(CandidateKind.TITLE_BODY_TOP.value, sec_label, _bt_path, _bt_dg),
                        kind=CandidateKind.TITLE_BODY_TOP,
                        section=sec_label,
                        path=_bt_path,
                        layer="body",
                        text_preview=text[:80],
                        confidence=0.5,
                        requires_user_confirm=True,
                        evidence={"note": "본문 상단 단락 — 제목인지 본문인지 확인 필요"},
                        digest=_bt_dg,
                    )
                )
                body_top_done = True
                break

        # drawing-object (글상자) text/pictures in body paragraphs — floating
        # title boxes and logos; every candidate needs explicit confirmation
        for pi, p in enumerate(c for c in list(root) if c.tag == f"{{{HP}}}p"):
            for ri, run in enumerate(p.findall(f"{{{HP}}}run")):
                for ci, cont in enumerate(run.findall(f"{{{HP}}}container")):
                    host = f"{sec_label}/body/p[{pi}]/run[{ri}]"
                    for dt_path, dt_run, dt_text in _walk_drawtext(
                        cont, f"container[{ci}]"
                    ):
                        t = dt_text.strip()
                        if not t:
                            continue
                        _d_path = f"{host}/{dt_path}"
                        _d_dg = _el_digest(dt_run)
                        manifest.candidates.append(
                            ControlCandidate(
                                id=_cand_id(
                                    CandidateKind.TITLE_BODY_TOP.value,
                                    sec_label, _d_path, _d_dg,
                                ),
                                kind=CandidateKind.TITLE_BODY_TOP,
                                section=sec_label,
                                path=_d_path,
                                layer="body",
                                text_preview=t[:80],
                                confidence=0.5,
                                requires_user_confirm=True,
                                evidence={
                                    "note": "본문 글상자 텍스트 — 제목인지 확인 필요",
                                    "object": "drawText",
                                },
                                digest=_d_dg,
                            )
                        )
                    for m, pic in enumerate(cont.iter(f"{{{HP}}}pic")):
                        _p_path = f"{host}/container[{ci}]/pic[{m}]"
                        _p_dg = _el_digest(pic)
                        manifest.candidates.append(
                            ControlCandidate(
                                id=_cand_id(
                                    CandidateKind.TITLE_IMAGE.value,
                                    sec_label, _p_path, _p_dg,
                                ),
                                kind=CandidateKind.TITLE_IMAGE,
                                section=sec_label,
                                path=_p_path,
                                layer="body",
                                text_preview="본문 글상자 이미지",
                                confidence=0.3,
                                requires_user_confirm=True,
                                evidence={"object": "container"},
                                digest=_p_dg,
                            )
                        )
                # body tables: a cell can carry branding as a borderFill
                # background image (same mechanism as header logo cells).
                # Skip runs hosting controls/secPr — their tables belong to
                # header/footer/master inventory, not the body.
                if list(run.iter(f"{{{HP}}}ctrl")) or run.find(
                    f".//{{{HP}}}secPr"
                ) is not None:
                    continue
                b_host = f"{sec_label}/body/p[{pi}]/run[{ri}]"
                for ti, tbl in enumerate(run.iter(f"{{{HP}}}tbl")):
                    for ci, tc in enumerate(tbl.iter(f"{{{HP}}}tc")):
                        bid = tc.get("borderFillIDRef")
                        if not bid or bid not in fill_images:
                            continue
                        ref, _img_dg = fill_images[bid]
                        _b_path = f"{b_host}/tbl[{ti}]/tc[{ci}]"
                        _b_dg = _el_digest(tc)
                        manifest.candidates.append(
                            ControlCandidate(
                                id=_cand_id(
                                    CandidateKind.TITLE_IMAGE.value,
                                    sec_label, _b_path, _b_dg,
                                ),
                                kind=CandidateKind.TITLE_IMAGE,
                                section=sec_label,
                                path=_b_path,
                                layer="body",
                                text_preview="본문 표 셀 배경 이미지(로고 가능성)",
                                confidence=0.4,
                                requires_user_confirm=True,
                                evidence={
                                    "object": "cell_border_fill",
                                    "fill_id": bid,
                                    "img": ref,
                                },
                                digest=_b_dg,
                            )
                        )

    # print-only header/footer tokens (settings.xml)
    if "settings.xml" in names:
        settings = zf.read("settings.xml").decode("utf-8", errors="ignore")
        for m in re.finditer(
            r'<(?:\w+:)?(?:printHeader|printFooter|headerFooter)[^>]*>(.*?)</(?:\w+:)?(?:printHeader|printFooter|headerFooter)>',
            settings,
            re.DOTALL,
        ):
            content = m.group(1)
            if _PRINT_TOKEN_RE.search(content):
                _pt_path = f"settings.xml/printToken[{m.start()}]"
                _pt_dg = hashlib.sha256(m.group(0).encode("utf-8")).hexdigest()
                manifest.candidates.append(
                    ControlCandidate(
                        id=_cand_id(CandidateKind.PRINT_PAGE_TOKEN.value, "settings.xml", _pt_path, _pt_dg),
                        kind=CandidateKind.PRINT_PAGE_TOKEN,
                        section="settings.xml",
                        path=_pt_path,
                        layer="settings",
                        text_preview=content.strip()[:80],
                        confidence=0.9,
                        # the block can carry academy text next to the token
                        # ("교육원 ^p 쪽") — explicit per-block confirmation
                        requires_user_confirm=True,
                        evidence={"tokens": sorted(set(_PRINT_TOKEN_RE.findall(content)))},
                        digest=_pt_dg,
                    )
                )
        if 'password="1"' in settings or "protectDocument" in settings:
            flags.encrypted_or_password = True

    manifest.section_count = len(section_names)
    manifest.header_variants = sorted(header_variants)
    manifest.footer_variants = sorted(footer_variants)
    return manifest


def _inventory_cell_backgrounds(
    manifest: BrandStructureManifest,
    el: ET.Element,
    base: str,
    sec_label: str,
    layer: str,
    apply_type: str,
    fill_images: dict[str, tuple[str, str]],
) -> None:
    """Table cells whose borderFillIDRef resolves to an image fill carry
    branding (seum-style logo cells). The fill itself lives in header.xml
    — the mutator clones it and repoints only the confirmed cell."""
    for ti, tbl in _nested_tables(el):
        for ci, tc in enumerate(tbl.iter(f"{{{HP}}}tc")):
            bid = tc.get("borderFillIDRef")
            if not bid or bid not in fill_images:
                continue
            ref, _img_dg = fill_images[bid]
            _tc_path = f"{base}/tbl[{ti}]/tc[{ci}]"
            _tc_dg = _el_digest(tc)
            manifest.candidates.append(
                ControlCandidate(
                    id=_cand_id(
                        CandidateKind.TITLE_IMAGE.value, sec_label, _tc_path, _tc_dg
                    ),
                    kind=CandidateKind.TITLE_IMAGE,
                    section=sec_label,
                    path=_tc_path,
                    apply_page_type=apply_type,
                    layer=layer,
                    text_preview="셀 배경 이미지(로고 가능성)",
                    confidence=0.4,
                    requires_user_confirm=True,
                    evidence={
                        "object": "cell_border_fill",
                        "fill_id": bid,
                        "img": ref,
                    },
                    digest=_tc_dg,
                )
            )


def _inventory_header_footer(
    manifest: BrandStructureManifest,
    el: ET.Element,
    base: str,
    sec_label: str,
    layer: str,
    apply_type: str,
    digest: str,
    fill_images: dict[str, tuple[str, str]],
) -> None:
    _inventory_cell_backgrounds(
        manifest, el, base, sec_label, layer, apply_type, fill_images
    )
    # title text candidates (header only — footer text is never a title;
    # literal-number footer runs are inventoried separately below)
    if layer == "header":
        for path, run, text in _sublist_para_runs(el):
            if not text.strip():
                continue
            inside_table = any(
                run in list(tbl.iter(f"{{{HP}}}run")) for _, tbl in _nested_tables(el)
            )
            if inside_table:
                continue  # cell runs get their own precise paths below
            _c_path = f"{base}/{path}"
            _c_dg = _el_digest(run)
            manifest.candidates.append(
                ControlCandidate(
                    id=_cand_id(CandidateKind.TITLE_HEADER_TEXT.value, sec_label, _c_path, _c_dg),
                    kind=CandidateKind.TITLE_HEADER_TEXT,
                    section=sec_label,
                    path=_c_path,
                    apply_page_type=apply_type,
                    layer=layer,
                    text_preview=text.strip()[:80],
                    confidence=0.9,
                    digest=_c_dg,
                )
            )
        # table-cell runs — the mutator replaces ONLY the selected cell run,
        # never the table or sibling picture
        for ti, tbl in _nested_tables(el):
            tcs = list(tbl.iter(f"{{{HP}}}tc"))
            for ci, tc in enumerate(tcs):
                sub = tc.find(f"{{{HP}}}subList")
                if sub is None:
                    continue
                for pi, p in enumerate(sub.findall(f"{{{HP}}}p")):
                    for ri, run in enumerate(p.findall(f"{{{HP}}}run")):
                        text = _direct_text(run).strip()
                        if not text:
                            continue
                        _tc_path = (
                            f"{base}/tbl[{ti}]/tc[{ci}]"
                            f"/sublist/p[{pi}]/run[{ri}]"
                        )
                        _tc_dg = _el_digest(run)
                        manifest.candidates.append(
                            ControlCandidate(
                                id=_cand_id(
                                    CandidateKind.TITLE_HEADER_TABLE_CELL.value,
                                    sec_label, _tc_path, _tc_dg,
                                ),
                                kind=CandidateKind.TITLE_HEADER_TABLE_CELL,
                                section=sec_label,
                                path=_tc_path,
                                apply_page_type=apply_type,
                                layer=layer,
                                text_preview=text[:80],
                                confidence=0.9,
                                digest=_tc_dg,
                            )
                        )
        # 글상자(drawText) text — drawing-object titles; always ambiguous
        for _d_path, _d_run, _d_text in _container_drawtext_runs(el, base):
            if not _d_text.strip():
                continue
            _d_dg = _el_digest(_d_run)
            manifest.candidates.append(
                ControlCandidate(
                    id=_cand_id(
                        CandidateKind.TITLE_HEADER_TEXT.value,
                        sec_label, _d_path, _d_dg,
                    ),
                    kind=CandidateKind.TITLE_HEADER_TEXT,
                    section=sec_label,
                    path=_d_path,
                    apply_page_type=apply_type,
                    layer=layer,
                    text_preview=_d_text.strip()[:80],
                    confidence=0.6,
                    requires_user_confirm=True,
                    evidence={"note": "머리말 글상자 텍스트 — 제목인지 확인 필요"},
                    digest=_d_dg,
                )
            )
    elif layer == "footer":
        # literal page numbers inside footer 글상자 — same rule as plain
        # footer text: never auto-removed, confirm per candidate
        for _f_path, _f_run, _f_text in _container_drawtext_runs(el, base):
            t = _f_text.strip()
            if not t or not _PAGE_NUM_TEXT_RE.match(t):
                continue
            _f_dg = _el_digest(_f_run)
            manifest.candidates.append(
                ControlCandidate(
                    id=_cand_id(
                        CandidateKind.LITERAL_PAGE_NUMBER.value,
                        sec_label, _f_path, _f_dg,
                    ),
                    kind=CandidateKind.LITERAL_PAGE_NUMBER,
                    section=sec_label,
                    path=_f_path,
                    apply_page_type=apply_type,
                    layer=layer,
                    text_preview=t,
                    confidence=0.3,
                    requires_user_confirm=True,
                    evidence={"literal": t, "object": "drawText"},
                    digest=_f_dg,
                )
            )

    # dynamic page-number fields inside this header/footer
    for path, field_el in _find_page_fields(el):
        _f_path = f"{base}/{path}"
        _f_dg = _el_digest(field_el)
        manifest.candidates.append(
            ControlCandidate(
                id=_cand_id(CandidateKind.PAGE_NUM_FIELD.value, sec_label, _f_path, _f_dg),
                kind=CandidateKind.PAGE_NUM_FIELD,
                section=sec_label,
                path=_f_path,
                apply_page_type=apply_type,
                layer=layer,
                text_preview="자동 쪽번호 필드",
                confidence=0.95,
                digest=_f_dg,
            )
        )

    # literal / image numbers — confirm required, never auto-removed
    for path, run, text in _find_literal_numbers(el):
        _l_path = f"{base}/{path}"
        _l_dg = _el_digest(run)
        manifest.candidates.append(
            ControlCandidate(
                id=_cand_id(CandidateKind.LITERAL_PAGE_NUMBER.value, sec_label, _l_path, _l_dg),
                kind=CandidateKind.LITERAL_PAGE_NUMBER,
                section=sec_label,
                path=_l_path,
                apply_page_type=apply_type,
                layer=layer,
                text_preview=text,
                confidence=0.3,
                requires_user_confirm=True,
                evidence={"literal": text},
                digest=_l_dg,
            )
        )
    for path, pic in _find_pictures(el):
        kind = CandidateKind.TITLE_IMAGE if layer == "header" else CandidateKind.LITERAL_PAGE_NUMBER
        _p_path = f"{base}/{path}"
        _p_dg = _el_digest(pic)
        manifest.candidates.append(
            ControlCandidate(
                id=_cand_id(kind.value, sec_label, _p_path, _p_dg),
                kind=kind,
                section=sec_label,
                path=_p_path,
                apply_page_type=apply_type,
                layer=layer,
                text_preview="이미지(머리말)" if layer == "header" else "이미지 번호 가능성",
                confidence=0.3,
                requires_user_confirm=True,
                digest=_p_dg,
            )
        )


def _inventory_master(
    manifest: BrandStructureManifest,
    el: ET.Element,
    base: str,
    sec_label: str,
    digest: str,
    fill_images: dict[str, tuple[str, str]],
) -> None:
    _inventory_cell_backgrounds(
        manifest, el, base, sec_label, "master_page", "BOTH", fill_images
    )
    for path, run, text in _sublist_para_runs(el):
        if not text.strip():
            continue
        _m_path = f"{base}/{path}"
        _m_dg = _el_digest(run)
        manifest.candidates.append(
            ControlCandidate(
                id=_cand_id(CandidateKind.TITLE_MASTER_TEXT.value, sec_label, _m_path, _m_dg),
                kind=CandidateKind.TITLE_MASTER_TEXT,
                section=sec_label,
                path=_m_path,
                layer="master_page",
                text_preview=text.strip()[:80],
                confidence=0.6,
                requires_user_confirm=True,
                digest=_m_dg,
            )
        )
    # 글상자(drawText) text on master pages — same confirm-only rule
    for _d_path, _d_run, _d_text in _container_drawtext_runs(el, base):
        if not _d_text.strip():
            continue
        _d_dg = _el_digest(_d_run)
        manifest.candidates.append(
            ControlCandidate(
                id=_cand_id(
                    CandidateKind.TITLE_MASTER_TEXT.value,
                    sec_label, _d_path, _d_dg,
                ),
                kind=CandidateKind.TITLE_MASTER_TEXT,
                section=sec_label,
                path=_d_path,
                layer="master_page",
                text_preview=_d_text.strip()[:80],
                confidence=0.6,
                requires_user_confirm=True,
                evidence={"note": "바탕쪽 글상자 텍스트 — 제목인지 확인 필요"},
                digest=_d_dg,
            )
        )
    for path, field_el in _find_page_fields(el):
        _mf_path = f"{base}/{path}"
        _mf_dg = _el_digest(field_el)
        manifest.candidates.append(
            ControlCandidate(
                id=_cand_id(
                    CandidateKind.PAGE_NUM_MASTER_FIELD.value,
                    sec_label, _mf_path, _mf_dg,
                ),
                kind=CandidateKind.PAGE_NUM_MASTER_FIELD,
                section=sec_label,
                path=_mf_path,
                layer="master_page",
                text_preview="바탕쪽 쪽번호 필드",
                confidence=0.95,
                digest=_mf_dg,
            )
        )
    for path, pic in _find_pictures(el):
        if _is_watermark_pic(pic):
            manifest.existing_watermark_count += 1
            kind = CandidateKind.EXISTING_WATERMARK
        else:
            kind = CandidateKind.TITLE_IMAGE
        _mp_path = f"{base}/{path}"
        _mp_dg = _el_digest(pic)
        manifest.candidates.append(
            ControlCandidate(
                id=_cand_id(kind.value, sec_label, _mp_path, _mp_dg),
                kind=kind,
                section=sec_label,
                path=_mp_path,
                layer="master_page",
                text_preview="기존 워터마크" if kind is CandidateKind.EXISTING_WATERMARK else "바탕쪽 이미지",
                confidence=0.8 if kind is CandidateKind.EXISTING_WATERMARK else 0.3,
                requires_user_confirm=True,
                digest=_mp_dg,
            )
        )
