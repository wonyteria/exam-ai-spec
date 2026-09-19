"""Allowlisted HWPX mutation (HWP_REBRANDING_SPEC §5 step 6, §9 invariants).

Resolves *exact control paths* from the scanned manifest, verifies each
target's expected digest before touching it, applies only plan operations,
then re-inventories the result and proves that nothing outside the plan
changed. Anything unexpected aborts before producing output.
"""
from __future__ import annotations

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
    'holdAnchorAndSO="0" vertRelTo="PAPER" horzRelTo="PAPER" vertAlign="CENTER" '
    'horzAlign="CENTER" vertOffset="0" horzOffset="0"/>'
    '<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
    '<hp:shapeComment>watermark</hp:shapeComment>'
    "</hp:pic><hp:t/></hp:run></hp:p>"
)

_HEADER = (
    f'<hp:header xmlns:hp="{HP}" id="0" applyPageType="BOTH">'
    '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" '
    'vertAlign="TOP" linkListIDRef="0" linkListNextIDRef="0" textWidth="0" '
    'textHeight="0" hasTextRef="0" hasNumRef="0">{inner}</hp:subList></hp:header>'
)


def _watermark_para(item_id: str, scale: float, opacity: float) -> ET.Element:
    width = int(59528 * min(max(scale, 0.2), 0.5))
    height = int(width * 0.35)
    frag = _WATERMARK_PIC.format(
        w=width,
        h=height,
        cx=width // 2,
        cy=height // 2,
        item=item_id,
        alpha=int(min(max(opacity, 0.02), 0.5) * 255),
    )
    return ET.fromstring(frag)


def _add_watermark(
    doc: _Doc, op: RebrandOperation, logo_item_id: str
) -> tuple[str, ET.Element | None, list[tuple[ET.Element, str, dict]]]:
    """Merge one behind-text paper-centered pic into the section's per-page
    host. Real HWP renders paper-anchored header content on every page, and
    a fabricated hp:masterPage ctrl is *invalid HWPML* — Hancom crashes on
    it (observed: COM RPC failure on Open). Order: merge into an existing
    masterPage when present, else every existing header (covers ODD/EVEN/
    FIRST variants), else create a real hp:header ctrl — never a
    masterPage shell.

    Returns (label, created_control_el, [(ancestor, pre_digest, pre_runs)]).
    The watermark para is APPENDED so existing run indices stay stable."""
    payload = op.payload

    def _make_para() -> ET.Element:
        return _watermark_para(
            logo_item_id, payload.get("scale", 0.35), payload.get("opacity", 0.10)
        )

    hosts = [
        child for _c, child in _iter_ctrl_pairs(doc)
        if _local(child.tag) == "masterPage"
    ]
    kind = "masterPage"
    if not hosts:
        kind = "header"
        hosts = [
            child for _c, child in _iter_ctrl_pairs(doc)
            if _local(child.tag) == "header"
        ]
    if hosts:
        touched: list[tuple[ET.Element, str, dict]] = []
        for host in hosts:
            pre_dg = _el_digest(host)
            pre_runs = _runs_in(host)
            sub = host.find(_SUBLIST)
            if sub is None:
                sub = ET.SubElement(host, _SUBLIST)
            sub.append(_make_para())
            touched.append((host, pre_dg, pre_runs))
        return f"{doc.name}/{kind}/watermark", None, touched

    # no per-page host at all — create a real header ctrl in the
    # section-properties run (same place header/footer controls live)
    target_run = None
    for p in doc.root.iter(_P):
        for run in p.findall(_RUN):
            if run.find(f"{{{HP}}}secPr") is not None or run.find(_CTRL) is not None:
                target_run = run
                break
        if target_run is not None:
            break
    if target_run is None:
        raise PlanError("NO_ANCHOR", f"{doc.name}: no run to host header")
    inner = ET.tostring(_make_para(), encoding="unicode")
    frag = ET.fromstring(_HEADER.format(inner=inner))
    ctrl = ET.SubElement(target_run, _CTRL)
    ctrl.append(frag)
    return f"{doc.name}/header/watermark", frag, []


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


def _iter_ctrl_pairs(doc: _Doc):
    for ctrl in doc.root.iter(_CTRL):
        for child in list(ctrl):
            yield ctrl, child


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
        op.op in {RebrandOpKind.ADD_WATERMARK_SHAPE, RebrandOpKind.REPLACE_SELECTED_SHAPE}
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

    for op in plan.operations:
        if op.section == "settings.xml":
            if op.op is not RebrandOpKind.CLEAR_PRINT_PAGE_TOKEN:
                raise PlanError("OP_NOT_ALLOWED", f"{op.op} on settings.xml")
            continue  # applied in phase 2

        doc = docs.get(op.section)
        if doc is None:
            raise PlanError("PATH_SECTION", f"no section {op.section}")
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
                    }:
                        replace_run_suffixes.setdefault(id(anc), set()).add(host)
                    else:
                        field_run_suffixes.setdefault(id(anc), set()).add(host)
                if len(segs) == 2 and op.op in {
                    RebrandOpKind.REMOVE_PAGE_NUM_CONTROL,
                    RebrandOpKind.REMOVE_PAGE_NUM_FIELD,
                }:
                    removed_child_digest.add(_el_digest(el))
            elif segs[0] == "body" and segs[1].startswith("p["):
                para = doc.resolve("/".join(path.split("/")[:3]))
                touched_para[id(para)] = (para, _stripped_digest(para))
                touched_body_paths.add("/".join(path.split("/")[:3]))
                para_runs_before[id(para)] = {
                    ri: (_el_digest(r), _direct_text(r))
                    for ri, r in enumerate(para.findall(_RUN))
                }
                # target nested in run[j] (글상자/drawText) — the host run's
                # digest legitimately changes, so exempt exactly that index
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

    for op in plan.operations:
        if op.section == "settings.xml":
            continue
        if op.op is RebrandOpKind.ADD_WATERMARK_SHAPE:
            doc = docs[op.section]
            label, created_el, anc_list = _add_watermark(doc, op, logo_item_id)
            added.append(label)
            if created_el is not None:
                added_controls.append(created_el)
            for anc_el, pre_dg, pre_runs in anc_list:
                # keep the EARLIEST captured pre-digest — an earlier field
                # removal may already have recorded the true "before" state
                if id(anc_el) not in touched_anc:
                    touched_anc[id(anc_el)] = (anc_el, pre_dg)
                anc_runs_before.setdefault(id(anc_el), pre_runs)
                watermark_anc.add(id(anc_el))

    # --- invariants: 허용 mask 밖 diff 0 (digest-multiset comparison) -------------
    report = InvariantReport(
        controls_before=len(before),
        removed_paths=removed,
        replaced_paths=replaced,
        added_paths=added,
    )
    _verify_invariants(
        docs=docs,
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
        touched=touched,
        report=report,
    )
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
    """path -> (stripped_digest, stripped_text) for direct body paragraphs."""
    inv: dict[str, tuple[str, str]] = {}
    paras = [c for c in list(doc.root) if c.tag == _P]
    for pi, p in enumerate(paras):
        inv[f"{doc.name}/body/p[{pi}]"] = (_stripped_digest(p), _stripped_text(p))
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
                report.violations.append(f"unexpected new body paragraph {path}")
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
