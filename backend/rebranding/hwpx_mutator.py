"""Allowlisted HWPX mutation (HWP_REBRANDING_SPEC §5 step 6, §9 invariants).

Resolves *exact control paths* from the scanned manifest, verifies each
target's expected digest before touching it, applies only plan operations,
then re-inventories the result and proves that nothing outside the plan
changed. Anything unexpected aborts before producing output.
"""
from __future__ import annotations

import copy
import hashlib
import io
import re
import zipfile
from xml.etree import ElementTree as ET

from .models import (
    BrandRewritePlan,
    InvariantReport,
    PlanError,
    RebrandOpKind,
    RebrandOperation,
)
from .scanner import (
    HP,
    _direct_text,
    _el_digest,
    _iter_controls,
    _local,
    _text_of,
)

HC = "http://www.hancom.co.kr/hwpml/2011/core"

for _pfx, _uri in {
    "hp": HP,
    "hs": "http://www.hancom.co.kr/hwpml/2011/section",
    "hc": HC,
    "ha": "http://www.hancom.co.kr/hwpml/2011/app",
    "hp10": "http://www.hancom.co.kr/hwpml/2016/paragraph",
    "hh": "http://www.hancom.co.kr/hwpml/2011/head",
    "hhs": "http://www.hancom.co.kr/hwpml/2011/history",
    "hm": "http://www.hancom.co.kr/hwpml/2011/master-page",
    "hpf": "http://www.hancom.co.kr/schema/2011/hpf",
}.items():
    ET.register_namespace(_pfx, _uri)

_P = f"{{{HP}}}p"
_RUN = f"{{{HP}}}run"
_CTRL = f"{{{HP}}}ctrl"
_T = f"{{{HP}}}t"
_SUBLIST = f"{{{HP}}}subList"
_PIC = f"{{{HP}}}pic"
_TBL = f"{{{HP}}}tbl"
_IMG = f"{{{HC}}}img"

_SEG = re.compile(r"^([A-Za-z_]+)(?:\[(\d+)\])?$")
_PRINT_TOKEN_RE = re.compile(r"\^[pPnN]")
_PRINT_BLOCK_RE = re.compile(
    r"(<(?:\w+:)?(?:printHeader|printFooter|headerFooter)[^>]*>)(.*?)(</(?:\w+:)?(?:printHeader|printFooter|headerFooter)>)",
    re.DOTALL,
)


class _Doc:
    """One parsed section XML plus a parent map for surgical edits."""

    def __init__(self, name: str, raw: bytes):
        self.name = name
        self.raw = raw
        self.decl = raw.split(b"?>", 1)[0] + b"?>" if raw.startswith(b"<?xml") else b""
        self.root = ET.fromstring(raw)
        self.parent = {c: p for p in self.root.iter() for c in list(p)}

    # -- path resolution --------------------------------------------------------

    def _ctrl_children(self) -> list[tuple[ET.Element, ET.Element]]:
        """[(ctrl_el, control_child)] in document order — same indexing the
        scanner used for `ctrl[i]` path segments."""
        out = []
        for ctrl in self.root.iter(_CTRL):
            for child in list(ctrl):
                out.append((ctrl, child))
        return out

    def resolve(self, path: str) -> ET.Element:
        """Resolve a scanner-produced path to an element or raise."""
        segs = path.split("/")
        if segs[0] != self.name:
            raise PlanError("PATH_SECTION", f"path {path} is not in {self.name}")
        el: ET.Element = self.root
        i = 1
        while i < len(segs):
            m = _SEG.match(segs[i])
            if not m:
                raise PlanError("PATH_SYNTAX", f"bad path segment {segs[i]!r}")
            tag, idx_s = m.group(1), m.group(2)
            idx = int(idx_s or 0)
            el = self._step(el, tag, idx, path)
            i += 1
        return el

    def _step(self, el: ET.Element, tag: str, idx: int, path: str) -> ET.Element:
        if tag == "ctrl":
            if el is self.root:
                # nth *section-level* ctrl — same restricted enumeration the
                # scanner uses (direct body-paragraph run children only)
                ctrls = []
                for p in list(el):
                    if p.tag != _P:
                        continue
                    for run in p.findall(_RUN):
                        ctrls.extend(run.findall(_CTRL))
            else:
                ctrls = el.findall(_CTRL)
            if idx >= len(ctrls):
                raise PlanError("PATH_MISS", f"{path}: ctrl[{idx}] missing")
            return ctrls[idx]
        if tag == "sublist":
            sub = el.find(_SUBLIST)
            if sub is None:
                raise PlanError("PATH_MISS", f"{path}: subList missing")
            return sub
        if tag == "p":
            if el is self.root:
                paras = [c for c in list(el) if c.tag == _P]
            else:
                paras = el.findall(_P)
            if idx >= len(paras):
                raise PlanError("PATH_MISS", f"{path}: p[{idx}] missing")
            return paras[idx]
        if tag == "run":
            runs = el.findall(_RUN)
            if idx >= len(runs):
                raise PlanError("PATH_MISS", f"{path}: run[{idx}] missing")
            return runs[idx]
        if tag == "pic":
            scope = el.find(_SUBLIST)
            pics = list((scope if scope is not None else el).iter(_PIC))
            if idx >= len(pics):
                raise PlanError("PATH_MISS", f"{path}: pic[{idx}] missing")
            return pics[idx]
        if tag == "tbl":
            tbls = list(el.iter(_TBL))
            if idx >= len(tbls):
                raise PlanError("PATH_MISS", f"{path}: tbl[{idx}] missing")
            return tbls[idx]
        if tag == "tc":
            tcs = list(el.iter(f"{{{HP}}}tc"))
            if idx >= len(tcs):
                raise PlanError("PATH_MISS", f"{path}: tc[{idx}] missing")
            return tcs[idx]
        if tag == "body":
            return el  # virtual segment — next segment must be p[i]
        # named child: nth direct child whose local name matches — covers
        # ctrl payloads (header/footer/masterPage) and drawing-object
        # segments (container/rect/drawText) inside 글상자 paths
        nth = 0
        for child in list(el):
            if _local(child.tag) == tag:
                if nth == idx:
                    return child
                nth += 1
        raise PlanError("PATH_MISS", f"{path}: no <{tag}> under {_local(el.tag)}")


# --- element-level edits --------------------------------------------------------


def _set_run_text(run: ET.Element, text: str) -> None:
    ts = run.findall(_T)
    if not ts:
        t = ET.SubElement(run, _T)
        t.text = text
        return
    ts[0].text = text
    for extra in ts[1:]:
        extra.text = ""


def _remove_element(doc: _Doc, el: ET.Element) -> None:
    parent = doc.parent.get(el)
    if parent is None:
        raise PlanError("PATH_MISS", "cannot remove element without parent")
    parent.remove(el)
    # cleanup: if the enclosing ctrl no longer holds any control child or
    # text, remove it too so no empty shell remains
    if parent.tag == _CTRL and not list(parent):
        gp = doc.parent.get(parent)
        if gp is not None:
            gp.remove(parent)


_WATERMARK_PIC = (
    f'<hp:p xmlns:hp="{HP}" xmlns:hc="{HC}" id="0" paraPrIDRef="0" styleIDRef="0" '
    'pageBreak="0" columnBreak="0" merged="0">'
    '<hp:run charPrIDRef="0">'
    '<hp:pic id="9001" zOrder="-1" numberingType="PICTURE" textWrap="BEHIND_TEXT" '
    'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href="" groupLevel="0" '
    'instid="0" reverse="0">'
    '<hp:offset x="0" y="0"/>'
    '<hp:orgSz width="{w}" height="{h}"/>'
    '<hp:curSz width="{w}" height="{h}"/>'
    '<hp:flip horizontal="0" vertical="0"/>'
    '<hp:rotationInfo angle="0" centerX="{cx}" centerY="{cy}" rotateimage="1"/>'
    '<hp:renderingInfo>'
    '<hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
    '<hc:scaMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
    '<hc:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
    '</hp:renderingInfo>'
    '<hp:imgRect>'
    '<hc:pt0 x="0" y="0"/><hc:pt1 x="{w}" y="0"/>'
    '<hc:pt2 x="{w}" y="{h}"/><hc:pt3 x="0" y="{h}"/>'
    '</hp:imgRect>'
    '<hp:imgClip left="0" right="{w}" top="0" bottom="{h}"/>'
    '<hp:inMargin left="0" right="0" top="0" bottom="0"/>'
    '<hc:img binaryItemIDRef="{item}" bright="0" contrast="0" '
    'effect="REAL_PIC" alpha="{alpha}"/>'
    '<hp:effects/>'
    '<hp:sz width="{w}" widthRelTo="ABSOLUTE" height="{h}" heightRelTo="ABSOLUTE" protect="0"/>'
    '<hp:pos treatAsChar="0" affectLSpacing="0" flowWithText="0" allowOverlap="1" '
    'holdAnchorAndSO="0" vertRelTo="PAPER" horzRelTo="PAPER" vertAlign="TOP" '
    'horzAlign="LEFT" vertOffset="{vo}" horzOffset="{ho}"/>'
    '<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
    '<hp:shapeComment>watermark</hp:shapeComment>'
    "</hp:pic><hp:t/></hp:run></hp:p>"
)




def _page_size(doc: "_Doc") -> tuple[int, int]:
    """(width, height) in HWP units from the section's pagePr — A4 default."""
    for pp in doc.root.iter(f"{{{HP}}}pagePr"):
        try:
            return int(pp.get("width", "59528")), int(pp.get("height", "84186"))
        except ValueError:
            break
    return 59528, 84186


def _watermark_para(
    item_id: str, scale: float, opacity: float, page_w: int, page_h: int
) -> ET.Element:
    width = int(page_w * min(max(scale, 0.2), 0.5))
    height = int(width * 0.35)
    # real Hancom files anchor floating shapes with PAPER+TOP/LEFT and an
    # explicit offset — the observed CENTER alignment rendered at the top
    # band, so center it ourselves: offset = (page - shape) / 2
    frag = _WATERMARK_PIC.format(
        w=width,
        h=height,
        cx=width // 2,
        cy=height // 2,
        item=item_id,
        alpha=int(min(max(opacity, 0.02), 0.5) * 255),
        vo=max(0, (page_h - height) // 2),
        ho=max(0, (page_w - width) // 2),
    )
    return ET.fromstring(frag)


_SECPR = f"{{{HP}}}secPr"
_MP_REF = f"{{{HP}}}masterPage"
_MASTERPAGE_PART = re.compile(r"^Contents/masterpage(\d+)\.xml$")

# A real 바탕쪽 is a separate package part (Contents/masterpageN.xml) whose
# root <masterPage> is un-namespaced and whose story lives in one
# hp:subList. Sections own master pages *positionally*: walking sections in
# order, each consumes masterPageCnt parts. Verified against a real
# Hancom-authored HWPX (sample-masterpage-cover.hwpx) — and against Hancom
# itself: fabricated hp:ctrl/hp:masterPage children are rejected on Open.
_MASTERPAGE_NS = (
    'xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" '
    f'xmlns:hp="{HP}" '
    'xmlns:hp10="http://www.hancom.co.kr/hwpml/2016/paragraph" '
    'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
    f'xmlns:hc="{HC}" '
    'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" '
    'xmlns:hhs="http://www.hancom.co.kr/hwpml/2011/history" '
    'xmlns:hm="http://www.hancom.co.kr/hwpml/2011/master-page" '
    'xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:opf="http://www.idpf.org/2007/opf/" '
    'xmlns:ooxmlchart="http://www.hancom.co.kr/hwpml/2016/ooxmlchart" '
    'xmlns:hwpunitchar="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar" '
    'xmlns:epub="http://www.idpf.org/2007/ops" '
    'xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0"'
)


def _masterpage_names(entries: dict[str, bytes]) -> list[str]:
    return sorted(
        (n for n in entries if _MASTERPAGE_PART.match(n)),
        key=lambda n: int(_MASTERPAGE_PART.match(n).group(1)),  # type: ignore[union-attr]
    )


def _secprs(docs: dict[str, "_Doc"]) -> dict[str, ET.Element]:
    """sec_label -> the section's hp:secPr element (first one wins)."""
    out: dict[str, ET.Element] = {}
    for label, doc in docs.items():
        for el in doc.root.iter(_SECPR):
            out[label] = el
            break
    return out


def _section_order(docs: dict[str, "_Doc"]) -> list[str]:
    def _idx(label: str) -> int:
        m = re.search(r"section(\d+)\.xml$", label)
        return int(m.group(1)) if m else 0

    return sorted(docs, key=_idx)


def _masterpage_xml(part_id: str, inner: str, text_w: int, text_h: int) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
        f'<masterPage {_MASTERPAGE_NS} id="{part_id}" type="BOTH" '
        'pageNumber="0" pageDuplicate="0" pageFront="0">'
        '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" '
        'vertAlign="TOP" linkListIDRef="0" linkListNextIDRef="0" '
        f'textWidth="{text_w}" textHeight="{text_h}" '
        'hasTextRef="0" hasNumRef="0">'
        + inner
        + "</hp:subList></masterPage>"
    ).encode("utf-8")


def _inject_hpf_item_xml(hpf: bytes, item_id: str, href: str) -> bytes:
    """Register a non-image package part (media-type application/xml)."""
    if not hpf:
        raise PlanError("MANIFEST_MISSING", f"{_HPF_NAME} absent")
    text = hpf.decode("utf-8")
    idx = text.find("</opf:manifest>")
    if idx < 0:
        raise PlanError(
            "MANIFEST_MISSING", f"{_HPF_NAME} has no opf:manifest — fail closed"
        )
    item = (
        f'<opf:item id="{item_id}" href="{href}" '
        'media-type="application/xml"/>'
    )
    return (text[:idx] + item + text[idx:]).encode("utf-8")


def _text_area(doc: "_Doc") -> tuple[int, int, int, int]:
    """(page_w, page_h, text_w, text_h) from pagePr + margin."""
    page_w, page_h = _page_size(doc)
    for pp in doc.root.iter(f"{{{HP}}}pagePr"):
        m = pp.find(f"{{{HP}}}margin")
        if m is not None:
            try:
                l = int(m.get("left", "2834"))
                r = int(m.get("right", "2834"))
                t = int(m.get("top", "1417"))
                b = int(m.get("bottom", "1417"))
                return page_w, page_h, max(1, page_w - l - r), max(1, page_h - t - b)
            except ValueError:
                break
    return page_w, page_h, page_w, page_h


_HPF_NAME = "Contents/content.hpf"
_MEDIA_TYPES = {
    "png": "image/png",
    "jpg": "image/jpg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "bmp": "image/bmp",
}


def _logo_item_id(hpf: bytes, logo_name: str) -> str:
    """Unique opf:item id for the logo binary — never collides with ids the
    source document already declares."""
    base = re.sub(r"[^A-Za-z0-9_-]", "_", logo_name.rsplit(".", 1)[0]) or "rebrand_logo"
    declared = set(re.findall(r'id="([^"]+)"', hpf.decode("utf-8", errors="ignore")))
    item = base
    n = 1
    while item in declared:
        n += 1
        item = f"{base}{n}"
    return item


def _inject_hpf_item(hpf: bytes, item_id: str, href: str) -> bytes:
    """Register the logo binary in the OPF manifest. A package entry Hancom
    cannot resolve to a manifest item makes the whole file unopenable, so a
    missing manifest is fail-closed, never skipped."""
    if not hpf:
        raise PlanError(
            "MANIFEST_MISSING", f"{_HPF_NAME} absent — cannot register logo asset"
        )
    text = hpf.decode("utf-8")
    mt = _MEDIA_TYPES.get(href.rsplit(".", 1)[-1].lower(), "image/png")
    item = (
        f'<opf:item id="{item_id}" href="{href}" '
        f'media-type="{mt}" isEmbeded="1"/>'
    )
    idx = text.find("</opf:manifest>")
    if idx < 0:
        raise PlanError(
            "MANIFEST_MISSING", f"{_HPF_NAME} has no opf:manifest — fail closed"
        )
    return (text[:idx] + item + text[idx:]).encode("utf-8")


# --- main entry -------------------------------------------------------------------


def apply_plan(
    hwpx_bytes: bytes,
    plan: BrandRewritePlan,
    logo_png: bytes | None = None,
    logo_name: str = "rebrand_logo.png",
) -> tuple[bytes, InvariantReport]:
    """Apply `plan` to a *copy* of the HWPX package. Raises PlanError on any
    digest/path/invariant violation — callers must treat that as fail-closed
    (no artifact, source untouched)."""
    zf = zipfile.ZipFile(io.BytesIO(hwpx_bytes))
    entries = {n: zf.read(n) for n in zf.namelist()}

    docs: dict[str, _Doc] = {}
    for name in list(entries):
        if re.match(r"^Contents/section\d+\.xml$", name):
            sec_label = name.split("/")[-1]
            docs[sec_label] = _Doc(sec_label, entries[name])

    # before-inventory: path -> digest for every control child, plus
    # run-level and body-level snapshots for the masked-diff contract
    before: dict[str, str] = {}
    before_body: dict[str, tuple[str, str]] = {}
    for sec_label, doc in docs.items():
        for path, el in _inventory(doc):
            before[f"{sec_label}/{path}"] = _el_digest(el)
        before_body.update(_body_inventory(doc))

    touched: set[str] = set()
    removed: list[str] = []
    replaced: list[str] = []
    added: list[str] = []
    needs_logo = any(
        op.op in {
            RebrandOpKind.ADD_WATERMARK_SHAPE,
            RebrandOpKind.REPLACE_SELECTED_SHAPE,
            RebrandOpKind.REPLACE_CELL_BACKGROUND,
        }
        for op in plan.operations
    )
    if needs_logo and not logo_png:
        raise PlanError("LOGO_REQUIRED", "watermark/image title ops need a verified logo asset")
    logo_item_id = ""
    if needs_logo:
        # HWPX is OCF: every package entry must resolve to an opf:manifest
        # item or Hancom refuses the whole document on Open.
        logo_item_id = _logo_item_id(entries.get(_HPF_NAME, b""), logo_name)
        entries[_HPF_NAME] = _inject_hpf_item(
            entries.get(_HPF_NAME, b""), logo_item_id, f"BinData/{logo_name}"
        )

    # Phase 1 — resolve every path and pin digests BEFORE mutating, so index
    # shifts from removals can never redirect a later op onto the wrong
    # control.
    resolved: list[tuple[RebrandOperation, "_Doc", list[tuple[str, ET.Element]]]] = []
    touched_anc: dict[int, tuple[ET.Element, str]] = {}   # el id -> (control child, pre-digest)
    touched_para: dict[int, tuple[ET.Element, str]] = {}  # para id -> (element, stripped digest)
    para_runs_before: dict[int, dict[int, tuple[str, str]]] = {}
    para_runs_allowed: dict[int, set[int]] = {}       # para id -> run idx legitimately mutated
    anc_runs_before: dict[int, dict[str, tuple[str, str]]] = {}
    replace_run_suffixes: dict[int, set[str]] = {}   # anc id -> replaced run suffixes
    field_run_suffixes: dict[int, set[str]] = {}     # anc id -> runs losing a field
    watermark_anc: set[int] = set()                  # anc ids gaining a watermark run
    touched_body_paths: set[str] = set()             # body para paths legitimately mutated
    removed_child_digest: set[str] = set()

    # Contents/header.xml is loaded lazily — only cell-background ops touch
    # the shared style part, and they do so by *cloning* a borderFill so
    # every other cell keeps its original fill
    head_doc: _Doc | None = None
    head_fills_before: dict[str, str] = {}
    head_other_before = ""
    added_fill_ids: list[str] = []

    def _head_doc() -> _Doc:
        nonlocal head_doc, head_fills_before, head_other_before
        if head_doc is None:
            raw = entries.get("Contents/header.xml")
            if raw is None:
                raise PlanError(
                    "PATH_MISS",
                    "Contents/header.xml missing — cell background fills live there",
                )
            head_doc = _Doc("header.xml", raw)
            head_fills_before, head_other_before = _fill_inventory(head_doc)
        return head_doc

    # Contents/masterpageN.xml parts are likewise loaded lazily — ops that
    # target 바탕쪽 content (master-page titles, page fields) resolve into
    # the part doc, which joins the same before/after inventory. Parts may
    # be *renamed* by the watermark pass below, so each doc tracks the
    # entry name its bytes must be written back under.
    part_docs: dict[str, _Doc] = {}          # original label -> doc
    part_current: dict[str, str] = {}        # original label -> current label
    part_rev: dict[str, str] = {}            # current label -> original label
    allowed_new_body_paths: set[str] = set()  # appended watermark paras

    def _part_doc(label: str) -> _Doc:
        orig = part_rev.get(label, label)
        if orig not in part_docs:
            raw = entries.get(f"Contents/{label}")
            if raw is None:
                raw = entries.get(f"Contents/{orig}")
            if raw is None:
                raise PlanError("PATH_SECTION", f"no part {label}")
            part_docs[orig] = _Doc(orig, raw)
            part_current[orig] = label
            doc = part_docs[orig]
            for path, el in _inventory(doc):
                before[f"{orig}/{path}"] = _el_digest(el)
            before_body.update(_body_inventory(doc))
        return part_docs[orig]

    for op in plan.operations:
        if op.section == "settings.xml":
            if op.op is not RebrandOpKind.CLEAR_PRINT_PAGE_TOKEN:
                raise PlanError("OP_NOT_ALLOWED", f"{op.op} on settings.xml")
            continue  # applied in phase 2

        doc = docs.get(op.section)
        if doc is None:
            doc = _part_doc(op.section)  # masterpageN.xml — raises if absent
        if op.op is RebrandOpKind.ADD_WATERMARK_SHAPE:
            continue  # resolved inside the section's master page at apply time

        targets: list[tuple[str, ET.Element]] = []
        for path in op.paths:
            el = doc.resolve(path)
            expected = op.expected_digests.get(path)
            if expected and _el_digest(el) != expected:
                raise PlanError(
                    "DIGEST_MISMATCH",
                    f"{path}: element changed since scan — refusing to mutate",
                )
            segs = path.split("/")[1:]  # drop the section name
            if segs[0].startswith("ctrl["):
                anc = doc.resolve("/".join(path.split("/")[:3]))
                touched_anc[id(anc)] = (anc, _el_digest(anc))
                anc_runs_before.setdefault(id(anc), _runs_in(anc))
                host = _host_run_suffix(anc, el, doc.parent)
                if host:
                    if op.op in {
                        RebrandOpKind.REPLACE_TEXT_RUNS,
                        RebrandOpKind.REPLACE_SELECTED_SHAPE,
                        RebrandOpKind.REPLACE_CELL_BACKGROUND,
                    }:
                        replace_run_suffixes.setdefault(id(anc), set()).add(host)
                    else:
                        field_run_suffixes.setdefault(id(anc), set()).add(host)
                if len(segs) == 2 and op.op in {
                    RebrandOpKind.REMOVE_PAGE_NUM_CONTROL,
                    RebrandOpKind.REMOVE_PAGE_NUM_FIELD,
                }:
                    removed_child_digest.add(_el_digest(el))
            elif segs[0] in {"body", "sublist"} and segs[1].startswith("p["):
                para = doc.resolve("/".join(path.split("/")[:3]))
                touched_para[id(para)] = (para, _stripped_digest(para))
                touched_body_paths.add("/".join(path.split("/")[:3]))
                para_runs_before[id(para)] = {
                    ri: (_el_digest(r), _direct_text(r))
                    for ri, r in enumerate(para.findall(_RUN))
                }
                # target nested in run[j] (글상자/drawText, or a field inside
                # a masterpage part) — the host run's digest legitimately
                # changes, so exempt exactly that index
                rm = re.match(r"run\[(\d+)\]", segs[2]) if len(segs) > 2 else None
                if rm:
                    para_runs_allowed.setdefault(id(para), set()).add(int(rm.group(1)))
            targets.append((path, el))
        resolved.append((op, doc, targets))

    # Phase 2 — apply
    added_controls: list[ET.Element] = []
    for op, doc, targets in resolved:
        if op.op is RebrandOpKind.ADD_WATERMARK_SHAPE:
            pass  # handled below (needs logo)
        for path, el in targets:
            if op.op is RebrandOpKind.REPLACE_TEXT_RUNS:
                _set_run_text(el, op.payload.get("text", ""))
                replaced.append(path)
                touched.add(path)
            elif op.op is RebrandOpKind.REPLACE_SELECTED_SHAPE:
                _replace_shape(doc, el, logo_item_id)
                replaced.append(path)
                touched.add(path)
            elif op.op is RebrandOpKind.REPLACE_CELL_BACKGROUND:
                new_fill = _replace_cell_fill(
                    _head_doc(), el, op.payload.get("fill_id", ""), logo_item_id
                )
                added_fill_ids.append(new_fill)
                replaced.append(path)
                touched.add(path)
            elif op.op in {
                RebrandOpKind.REMOVE_PAGE_NUM_CONTROL,
                RebrandOpKind.REMOVE_PAGE_NUM_FIELD,
            }:
                _remove_element(doc, el)
                removed.append(path)
                touched.add(path)
            else:
                raise PlanError("OP_NOT_ALLOWED", f"{op.op} cannot target {path}")

    # print tokens: gather ALL confirmed offsets before a single scrub —
    # sequential scrubs shift later offsets and corrupt the path contract
    token_paths = [
        p for op in plan.operations
        if op.section == "settings.xml"
        and op.op is RebrandOpKind.CLEAR_PRINT_PAGE_TOKEN
        for p in op.paths
    ]
    if token_paths:
        entries["settings.xml"] = _clear_print_tokens(
            entries.get("settings.xml", b""), token_paths
        )
        touched.add("settings.xml")

    # --- 바탕쪽: real masterPage *package parts* ------------------------------
    # A section's master pages are separate Contents/masterpageN.xml parts
    # owned positionally — walking sections in order, each consumes
    # `masterPageCnt` parts. Hancom renders their floating objects natively
    # centered behind text on every page (verified: inline hp:ctrl
    # fabrications are rejected on Open; separate parts open + render).
    wm_ops = [
        op for op in plan.operations
        if op.op is RebrandOpKind.ADD_WATERMARK_SHAPE
        and op.section != "settings.xml"
    ]
    mp_before_digest: dict[str, str] = {}    # full part name -> sha256 before
    mp_new_parts: set[str] = set()
    if wm_ops:
        secprs = _secprs(docs)
        for name in _masterpage_names(entries):
            mp_before_digest[name] = hashlib.sha256(entries[name]).hexdigest()
        for sec_label in _section_order(docs):
            op = next((o for o in wm_ops if o.section == sec_label), None)
            if op is None:
                continue
            secpr = secprs.get(sec_label)
            if secpr is None:
                raise PlanError(
                    "NO_ANCHOR",
                    f"{sec_label}: no secPr — cannot link a master page",
                )
            doc = docs[sec_label]
            page_w, page_h, text_w, text_h = _text_area(doc)

            def _wm_para() -> ET.Element:
                return _watermark_para(
                    logo_item_id,
                    op.payload.get("scale", 0.35),
                    op.payload.get("opacity", 0.10),
                    page_w,
                    page_h,
                )

            # the real linkage: <hp:masterPage idRef="masterpageN"/> children
            # inside hp:secPr — masterPageCnt is just their count. A section
            # can own several master pages (ODD/EVEN/OPTIONAL_PAGE) — merge
            # into EVERY referenced part so all pages are covered.
            refs = [
                ch.get("idRef")
                for ch in secpr.findall(_MP_REF)
                if ch.get("idRef")
            ]
            if refs:
                for ref in refs:
                    label = f"{ref}.xml"
                    if f"Contents/{label}" not in entries:
                        raise PlanError(
                            "PART_MISSING",
                            f"{sec_label}: {ref} referenced but part absent",
                        )
                    mp_doc = _part_doc(label)
                    sub = mp_doc.root.find(_SUBLIST)
                    if sub is None:
                        sub = ET.SubElement(mp_doc.root, _SUBLIST)
                    allowed_new_body_paths.add(
                        f"{mp_doc.name}/sublist/p[{len(sub.findall(_P))}]"
                    )
                    sub.append(_wm_para())
                    added.append(f"{mp_doc.name}/watermark")
            else:
                # no master page yet — create a real part AND the secPr
                # idRef child that links it (verified against a real
                # Hancom-authored masterpage: idRef is what activates it)
                used = {
                    int(_MASTERPAGE_PART.match(n).group(1))  # type: ignore[union-attr]
                    for n in entries
                    if _MASTERPAGE_PART.match(n)
                }
                idx = 0
                while idx in used:
                    idx += 1
                part_id = f"masterpage{idx}"
                part_name = f"Contents/{part_id}.xml"
                entries[part_name] = _masterpage_xml(
                    part_id,
                    ET.tostring(_wm_para(), encoding="unicode"),
                    text_w,
                    text_h,
                )
                mp_new_parts.add(part_name)
                ref_el = ET.SubElement(secpr, _MP_REF)
                ref_el.set("idRef", part_id)
                secpr.set("masterPageCnt", str(len(refs) + 1))
                added.append(f"{part_name}/watermark")
                # the secPr lives inside a body para's run — whitelist that
                # run so its digest change is a planned mutation
                for pi, p in enumerate(
                    c for c in list(doc.root) if c.tag == _P
                ):
                    if p.find(f".//{_SECPR}") is None:
                        continue
                    touched_para[id(p)] = (p, _stripped_digest(p))
                    touched_body_paths.add(f"{sec_label}/body/p[{pi}]")
                    para_runs_before[id(p)] = {
                        ri: (_el_digest(r), _direct_text(r))
                        for ri, r in enumerate(p.findall(_RUN))
                    }
                    for ri, r in enumerate(p.findall(_RUN)):
                        if r.find(f".//{_SECPR}") is not None:
                            para_runs_allowed.setdefault(id(p), set()).add(ri)
                    break
        for part in sorted(mp_new_parts):
            pid = part.rsplit("/", 1)[-1][:-4]
            entries[_HPF_NAME] = _inject_hpf_item_xml(
                entries[_HPF_NAME], pid, part
            )
    # write mutated masterpage parts back under their current names
    for orig, doc in part_docs.items():
        entries[f"Contents/{part_current[orig]}"] = doc.decl + ET.tostring(
            doc.root, encoding="utf-8"
        )

    # --- invariants: 허용 mask 밖 diff 0 (digest-multiset comparison) -------------
    report = InvariantReport(
        controls_before=len(before),
        removed_paths=removed,
        replaced_paths=replaced,
        added_paths=added,
    )
    _verify_invariants(
        docs={**docs, **part_docs},
        before=before,
        before_body=before_body,
        touched_anc=touched_anc,
        anc_runs_before=anc_runs_before,
        replace_run_suffixes=replace_run_suffixes,
        field_run_suffixes=field_run_suffixes,
        watermark_anc=watermark_anc,
        touched_para=touched_para,
        para_runs_before=para_runs_before,
        para_runs_allowed=para_runs_allowed,
        touched_body_paths=touched_body_paths,
        removed_child_digest=removed_child_digest,
        added_controls=added_controls,
        allowed_new_body_paths=allowed_new_body_paths,
        touched=touched,
        report=report,
    )
    if head_doc is not None:
        # header.xml contract: only *new* borderFill elements may appear —
        # every pre-existing fill and everything outside borderFills must
        # be byte-identical
        fills_after, other_after = _fill_inventory(head_doc)
        if other_after != head_other_before:
            report.violations.append("header.xml changed outside borderFills")
        for fid, dg in head_fills_before.items():
            if fills_after.get(fid) != dg:
                report.violations.append(
                    f"borderFill {fid} changed outside plan"
                )
        if set(fills_after) - set(head_fills_before) != set(added_fill_ids):
            report.violations.append(
                "unexpected borderFill add/remove in header.xml"
            )
    if wm_ops:
        # masterpage parts contract: every pre-existing part that was never
        # loaded for mutation is byte-identical; mutated parts are verified
        # element-wise by _verify_invariants; the only new parts are the
        # ones this run created.
        after_names = set(_masterpage_names(entries))
        expected = set(mp_before_digest) | mp_new_parts
        if after_names != expected:
            report.violations.append(
                "masterpage part set changed outside plan"
            )
        for name, dg in mp_before_digest.items():
            if name.rsplit("/", 1)[-1] in part_docs:
                continue  # mutated — verified element-wise above
            data = entries.get(name)
            if data is None or hashlib.sha256(data).hexdigest() != dg:
                report.violations.append(f"{name} changed outside plan")
    report.controls_after = sum(
        len(list(_inventory(d))) for d in docs.values()
    )
    report.passed = not report.violations
    if not report.passed:
        raise PlanError(
            "INVARIANT_VIOLATION",
            "post-mutation structure check failed",
            {"violations": report.violations},
        )

    if head_doc is not None:
        entries["Contents/header.xml"] = head_doc.decl + ET.tostring(
            head_doc.root, encoding="utf-8"
        )

    # --- repack ----------------------------------------------------------------------
    # Keep every entry's original ZipInfo (compress type / metadata) — Hancom
    # validates package layout beyond the mimetype-first rule.
    infos = {i.filename: i for i in zf.infolist()}
    section_entry_names = {f"Contents/{s}" for s in docs}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zo:
        for name, data in entries.items():
            if name in section_entry_names or name == "settings.xml":
                continue  # rewritten below with mutations applied
            info = infos.get(name)
            if name == "mimetype":
                info = zipfile.ZipInfo("mimetype")
                info.compress_type = zipfile.ZIP_STORED
            if info is not None:
                zo.writestr(info, data)
            else:
                zo.writestr(name, data)
        if "settings.xml" in entries:
            info = infos.get("settings.xml")
            if info is not None:
                zo.writestr(info, entries["settings.xml"])
            else:
                zo.writestr("settings.xml", entries["settings.xml"])
        for sec_label, doc in docs.items():
            body = ET.tostring(doc.root, encoding="utf-8")
            zo.writestr(f"Contents/{sec_label}", doc.decl + body)
        if needs_logo and logo_png:
            zo.writestr(f"BinData/{logo_name}", logo_png)
    return out.getvalue(), report


def _runs_in(control: ET.Element) -> dict[str, tuple[str, str]]:
    """suffix -> (digest, direct_text) for runs inside ONE control's
    subList — per-control granularity for the masked-diff contract."""
    inv: dict[str, tuple[str, str]] = {}
    sub = control.find(_SUBLIST)
    if sub is None:
        return inv
    for pi, p in enumerate(sub.findall(_P)):
        for ri, run in enumerate(p.findall(_RUN)):
            inv[f"sublist/p[{pi}]/run[{ri}]"] = (_el_digest(run), _direct_text(run))
    return inv


def _stripped_digest(p: ET.Element) -> str:
    """Digest of a body paragraph with all hp:ctrl subtrees removed —
    controls embedded in runs (headers, page numbers, fields) are verified
    separately at control/run granularity, so paragraph-level comparison
    must not let them mask body changes."""
    import copy

    clone = copy.deepcopy(p)
    for run in clone.findall(_RUN):
        for ctrl in run.findall(_CTRL):
            run.remove(ctrl)
    return _el_digest(clone)


def _stripped_text(p: ET.Element) -> str:
    import copy

    clone = copy.deepcopy(p)
    for run in clone.findall(_RUN):
        for ctrl in run.findall(_CTRL):
            run.remove(ctrl)
    return _text_of(clone)


def _body_inventory(doc: _Doc) -> dict[str, tuple[str, str]]:
    """path -> (stripped_digest, stripped_text) for direct body paragraphs —
    plus root-level subList paragraphs for masterpage-part docs."""
    inv: dict[str, tuple[str, str]] = {}
    paras = [c for c in list(doc.root) if c.tag == _P]
    for pi, p in enumerate(paras):
        inv[f"{doc.name}/body/p[{pi}]"] = (_stripped_digest(p), _stripped_text(p))
    sub = doc.root.find(_SUBLIST)
    if sub is not None:
        for pi, p in enumerate(sub.findall(_P)):
            inv[f"{doc.name}/sublist/p[{pi}]"] = (
                _stripped_digest(p),
                _stripped_text(p),
            )
    return inv


def _ancestor_controls(path: str) -> list[str]:
    """'a/ctrl[2]/footer/sublist/p[0]/run[1]' -> ['a/ctrl[2]/footer']."""
    m = re.match(r"^(section\d+\.xml/ctrl\[\d+\]/[A-Za-z_]+)", path)
    return [m.group(1)] if m else []


def _verify_invariants(
    docs: dict[str, "_Doc"],
    before: dict[str, str],
    before_body: dict[str, tuple[str, str]],
    touched_anc: dict[int, tuple[ET.Element, str]],
    anc_runs_before: dict[int, dict[str, tuple[str, str]]],
    replace_run_suffixes: dict[int, set[str]],
    field_run_suffixes: dict[int, set[str]],
    watermark_anc: set[int],
    touched_para: dict[int, tuple[ET.Element, str]],
    para_runs_before: dict[int, dict[int, tuple[str, str]]],
    para_runs_allowed: dict[int, set[int]],
    touched_body_paths: set[str],
    removed_child_digest: set[str],
    added_controls: list[ET.Element],
    allowed_new_body_paths: set[str],
    touched: set[str],
    report: InvariantReport,
) -> None:
    """Prove nothing outside the plan changed — digest-multiset comparison,
    immune to control index shifts caused by removals."""
    from collections import Counter

    # 1) section-level control inventory as a digest multiset
    after_digests: list[str] = []
    for doc in docs.values():
        for _p, el in _inventory(doc):
            after_digests.append(_el_digest(el))
    before_ms = Counter(before.values())
    after_ms = Counter(after_digests)

    allowed_old = Counter(removed_child_digest)
    allowed_new = Counter()
    for _id, (el, pre_dg) in touched_anc.items():
        allowed_old[pre_dg] += 1
        allowed_new[_el_digest(el)] += 1
    for el in added_controls:
        allowed_new[_el_digest(el)] += 1

    for dg, n in (before_ms - allowed_old - after_ms).items():
        report.violations.append(f"control digest vanished outside plan x{n}: {dg[:12]}")
    for dg, n in (after_ms - allowed_new - before_ms).items():
        report.violations.append(f"control digest appeared outside plan x{n}: {dg[:12]}")

    # 2) run-level diff inside each touched control
    for anc_id, (el, _pre) in touched_anc.items():
        before_runs = anc_runs_before.get(anc_id, {})
        after_runs = _runs_in(el)
        replaced = replace_run_suffixes.get(anc_id, set())
        fielded = field_run_suffixes.get(anc_id, set())
        can_add = anc_id in watermark_anc
        for suffix, (dg, text) in after_runs.items():
            old = before_runs.get(suffix)
            if old is None:
                if not can_add:
                    report.violations.append(
                        f"unexpected new run inside control: {suffix}"
                    )
                continue
            if suffix in replaced:
                continue  # payload applied — digest differs by design
            if suffix in fielded:
                # a field inside this run was removed — its text must survive
                if text != old[1]:
                    report.violations.append(f"touched run lost text: {suffix}")
            elif dg != old[0]:
                report.violations.append(
                    f"run changed inside control outside plan: {suffix}"
                )
        for suffix in before_runs:
            if suffix not in after_runs and suffix not in fielded:
                report.violations.append(
                    f"run removed inside control outside plan: {suffix}"
                )

    # 3) body paragraphs — stripped (ctrl-free) digest identical except
    #    touched paras, whose runs are compared individually
    for sec_label, doc in docs.items():
        after_body = _body_inventory(doc)
        for path, (dg, _t) in after_body.items():
            old = before_body.get(path)
            if old is None:
                if path not in allowed_new_body_paths:
                    report.violations.append(
                        f"unexpected new body paragraph {path}"
                    )
                continue
            if dg != old[0] and path not in touched_body_paths:
                report.violations.append(f"body paragraph changed outside plan: {path}")
        prefix = f"{sec_label}/"
        for path in before_body:
            if path.startswith(prefix) and path not in after_body:
                report.violations.append(f"body paragraph removed: {path}")
    for pid, (para, _sd) in touched_para.items():
        before_runs = para_runs_before.get(pid, {})
        after_runs = {
            ri: (_el_digest(r), _direct_text(r))
            for ri, r in enumerate(para.findall(_RUN))
        }
        for ri, (dg, text) in after_runs.items():
            old = before_runs.get(ri)
            if old is None:
                report.violations.append(f"unexpected new run in body para: {ri}")
                continue
            if dg != old[0] and ri not in para_runs_allowed.get(pid, set()):
                report.violations.append(f"body para run changed outside plan: {ri}")
        for ri in before_runs:
            if ri not in after_runs:
                report.violations.append(f"body para run removed: {ri}")


def _host_run_suffix(
    anc_el: ET.Element, target: ET.Element, parent: dict
) -> str | None:
    """Suffix 'sublist/p[i]/run[j]' of the *direct* subList run under `anc_el`
    that contains `target` — targets nested in table cells map to the host
    run, not the cell's inner run. None when target lives elsewhere."""
    cur = target
    while True:
        p = parent.get(cur)
        if p is None:
            return None
        if _local(p.tag) == "p" and _local(cur.tag) == "run":
            gp = parent.get(p)
            if gp is not None and _local(gp.tag) == "subList":
                owner = parent.get(gp)  # header/footer/masterPage/etc.
                if owner is anc_el:
                    pi = [c for c in gp if _local(c.tag) == "p"].index(p)
                    ri = list(p.findall(_RUN)).index(cur)
                    return f"sublist/p[{pi}]/run[{ri}]"
        cur = p


def _inventory(doc: _Doc):
    """(path, element) for every control child — identical indexing to the
    scanner so before/after comparison is apples-to-apples."""
    yield from _iter_controls(doc.root)


_HH = "http://www.hancom.co.kr/hwpml/2011/head"


def _fill_inventory(doc: _Doc) -> tuple[dict[str, str], str]:
    """(borderFill id -> digest, digest of the doc minus borderFills) —
    proves a cell-background edit added exactly the recorded fills and
    changed nothing else in the shared style part."""
    root_copy = copy.deepcopy(doc.root)
    fills: dict[str, str] = {}
    for holder in list(root_copy.iter(f"{{{_HH}}}borderFills")):
        for bf in list(holder):
            if _local(bf.tag) == "borderFill":
                fills[bf.get("id") or "?"] = _el_digest(bf)
                holder.remove(bf)
        # itemCnt is recomputed when a fill is cloned — not a violation
        holder.attrib.pop("itemCnt", None)
    return fills, _el_digest(root_copy)


def _replace_cell_fill(
    head_doc: _Doc, tc: ET.Element, fill_id: str, logo_item_id: str
) -> str:
    """Clone the tc's borderFill with the logo image and repoint ONLY this
    cell — other cells sharing the original fill keep it byte-identical.
    Returns the new fill id."""
    bid = tc.get("borderFillIDRef")
    if not bid or bid != fill_id:
        raise PlanError(
            "DIGEST_MISMATCH",
            f"cell borderFillIDRef {bid!r} changed since scan (expected {fill_id!r})",
        )
    holder = None
    src_fill = None
    for h in head_doc.root.iter(f"{{{_HH}}}borderFills"):
        for bf in list(h):
            if _local(bf.tag) == "borderFill" and bf.get("id") == bid:
                holder = h
                src_fill = bf
        if src_fill is not None:
            break
    if holder is None or src_fill is None:
        raise PlanError("PATH_MISS", f"borderFill {fill_id} missing in header.xml")
    clone = copy.deepcopy(src_fill)
    existing = {
        bf.get("id")
        for bf in list(holder)
        if _local(bf.tag) == "borderFill"
    }
    nid = 1
    while str(nid) in existing:
        nid += 1
    imgs = [e for e in clone.iter() if _local(e.tag) == "img"]
    if not imgs:
        raise PlanError(
            "STRUCTURE_UNSUPPORTED", "borderFill has no img payload to replace"
        )
    for im in imgs:
        im.attrib.pop("src", None)
        im.set("binaryItemIDRef", logo_item_id)
    clone.set("id", str(nid))
    holder.append(clone)
    cnt = holder.get("itemCnt")
    if cnt is not None:
        try:
            holder.set("itemCnt", str(int(cnt) + 1))
        except ValueError:
            pass
    tc.set("borderFillIDRef", str(nid))
    return str(nid)


def _replace_shape(doc: _Doc, el: ET.Element, logo_item_id: str) -> None:
    """Replace an image title's picture payload with the brand logo —
    keeps the pic element's position/size, swaps only the binaryItemIDRef."""
    if el.tag != _PIC:
        raise PlanError("OP_NOT_ALLOWED", "REPLACE_SELECTED_SHAPE only targets hp:pic")
    img = el.find(_IMG)
    if img is None:
        img = el.find(f"{{{HP}}}img")
    if img is None:
        raise PlanError(
            "STRUCTURE_UNSUPPORTED",
            "pic has no hc:img payload — refusing to guess a replacement target",
        )
    img.attrib.pop("src", None)
    img.set("binaryItemIDRef", logo_item_id)


def _clear_print_tokens(settings: bytes, paths: list[str]) -> bytes:
    """Remove ^p/^P/^n/^N tokens inside the *confirmed* printHeader/printFooter
    blocks only — paths carry the scanner-recorded char offsets so an
    unconfirmed sibling block is preserved verbatim."""
    text = settings.decode("utf-8", errors="ignore")
    if not text:
        raise PlanError("PATH_MISS", "settings.xml missing for print-token op")
    offsets = set()
    for p in paths:
        m = re.search(r"printToken\[(\d+)\]", p)
        if m:
            offsets.add(int(m.group(1)))
    if not offsets:
        raise PlanError("PATH_MISS", "no printToken offsets in plan paths")

    seen = set()

    def scrub(m: re.Match) -> str:
        if m.start() not in offsets:
            return m.group(0)  # not confirmed — leave byte-identical
        seen.add(m.start())
        inner = _PRINT_TOKEN_RE.sub("", m.group(2))
        return m.group(1) + inner + m.group(3)

    out = _PRINT_BLOCK_RE.sub(scrub, text)
    missing = offsets - seen
    if missing:
        raise PlanError(
            "DIGEST_MISMATCH",
            "printToken offsets no longer match settings.xml — refusing to mutate",
            {"missing": sorted(missing)},
        )
    return out.encode("utf-8")
