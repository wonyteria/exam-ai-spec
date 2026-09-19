"""Plan-driven HWPX renderer (WP07 / REQ-15·16·17·19).

Consumes a `LayoutPlan` — never invents layout. Emits real objects whose
XML mirrors documents written by HWP itself (validated live in WP00):
`<hp:equation>` (baseUnit=1100, i.e. 11pt), `<hp:endNote>` markers
carrying answer+explanation for every scored unit, a bordered answer-space
table for descriptive questions, and a 2-column newspaper layout for the
objective grid. Raw LaTeX never reaches output — unserializable equations
are dropped (the canonical check flags them; export stays fail-closed).
"""
from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

from document.math_ast import latex_to_hwp
from document.models import Document, Question

from ..brand import BrandTemplate, get_brand
from ..plan import EndnoteEntry, LayoutPlan, Slot, build_plan

# Namespace set exactly as emitted by HWP 2020 itself.
_NS = (
    'xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" '
    'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
    'xmlns:hp10="http://www.hancom.co.kr/hwpml/2016/paragraph" '
    'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
    'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" '
    'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" '
    'xmlns:hhs="http://www.hancom.co.kr/hwpml/2011/history" '
    'xmlns:hm="http://www.hancom.co.kr/hwpml/2011/master-page" '
    'xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:opf="http://www.idpf.org/2007/opf/" '
    'xmlns:ooxmlchart="http://www.hancom.co.kr/hwpml/2016/ooxmlchart" '
    'xmlns:epub="http://www.idpf.org/2007/ops" '
    'xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0"'
)

_XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'

# ~160% of 11pt in HWP units — one ruled answer line
_ANSWER_LINE_H = 560

_SUBLIST_ATTRS = (
    'id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="TOP" '
    'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" '
    'hasTextRef="0" hasNumRef="0"'
)


def render_hwpx(
    document: Document,
    title: str = "시험지",
    output_mode: str = "STUDENT_WITH_ENDNOTES",
    brand_id: str | None = None,
) -> bytes:
    """Render the canonical document into an HWPX package."""
    plan = build_plan(document, output_mode=output_mode, title=title)
    brand = get_brand(brand_id or document.brand_id)
    body = _body_xml(document, plan, brand)
    files = {
        "mimetype": b"application/hwp+zip",
        "version.xml": _VERSION_XML.encode("utf-8"),
        "settings.xml": _SETTINGS_XML.encode("utf-8"),
        "META-INF/container.xml": _CONTAINER_XML.encode("utf-8"),
        "META-INF/manifest.xml": _MANIFEST_XML.encode("utf-8"),
        "Contents/content.hpf": _content_hpf(title).encode("utf-8"),
        "Contents/header.xml": _header_xml(brand).encode("utf-8"),
        "Contents/section0.xml": _section_xml(body, plan).encode("utf-8"),
        "Preview/PrvText.txt": (plan.title + "\n").encode("utf-8"),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        zf.writestr(info, files.pop("mimetype"))
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


# -- body -------------------------------------------------------------------------


def _body_xml(
    doc: Document, plan: LayoutPlan, brand: BrandTemplate
) -> list[str]:
    paras: list[str] = []
    paras.append(_para(brand.header_text or plan.title, char_pr=1))
    if not plan.slots:
        paras.append(_para(""))
        return paras

    q_by_id = {q.id: q for q in doc.questions}
    endnotes = {
        e.question_id: (i + 1, e) for i, e in enumerate(plan.endnotes)
    }
    for slot in plan.slots:
        q = q_by_id[slot.question_id]
        paras.extend(_question_paras(q, slot, endnotes.get(q.id)))

    if plan.output_mode in {"ANSWER_SOLUTION", "TEACHER"}:
        paras.extend(_solution_section(plan))
    if plan.output_mode == "TEACHER":
        paras.extend(_teacher_meta(doc))
    return paras


def _question_paras(
    q: Question, slot: Slot, endnote: tuple[int, EndnoteEntry] | None
) -> list[str]:
    out: list[str] = []
    head = f"{slot.label}." + (f" ({q.points}점)" if q.points else "")
    if endnote is not None:
        # scored unit -> inline endnote marker carrying answer+solution
        number, entry = endnote
        out.append(_para_with_endnote(head, number, entry))
    else:
        out.append(_para(head, char_pr=2))
    for span in q.body:
        out.append(_para(span.text))
    for eq in q.equations:
        eq_xml = _equation_xml(eq)
        if eq_xml is not None:
            out.append(_para_run(eq_xml))
    for fig_xml in _figure_objects_xml(q):
        out.append(_para_run(fig_xml))
    for c in q.choices:
        text = " ".join(s.text for s in c.body)
        out.append(_para(f"{c.label} {text}"))
    if slot.answer_lines > 0:
        out.append(_answer_space_xml(slot.answer_lines))
    return out


def _solution_section(plan: LayoutPlan) -> list[str]:
    out = [_para("정답 및 해설", char_pr=1)]
    for e in plan.endnotes:
        out.append(_para(f"{e.label}. 정답: {e.answer}"))
        out.append(_para(e.explanation))
    return out


def _teacher_meta(doc: Document) -> list[str]:
    out = [_para("— 검증 상태 —", char_pr=1)]
    for q in sorted(doc.questions, key=lambda x: x.number):
        flags = ", ".join(f.kind for f in q.verification.logic_flags) or "-"
        out.append(
            _para(
                f"{q.number}. {q.verification.status.value} (flags: {flags})"
            )
        )
    return out


# -- objects ------------------------------------------------------------------------


def _equation_xml(eq) -> str | None:
    """Real hp:equation object — script from hwp_formula, or derived from
    latex on the fly. Unserializable input -> None (never raw LaTeX).

    `hp:equation` is a shape object: a direct child of `hp:run` (like
    `hp:pic`/`hp:rect`), NOT wrapped in `hp:ctrl`.
    """
    script = eq.hwp_formula
    if not script and eq.latex:
        try:
            script = latex_to_hwp(eq.latex)["script"]
        except Exception:
            return None
    if not script:
        return None
    return (
        '<hp:equation id="1" zOrder="0" numberingType="EQUATION" '
        'textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" '
        'dropcapstyle="None" version="" baseLine="67" textColor="#000000" '
        'baseUnit="1100" lineMode="CHAR" font="HYhwpEQ">'
        '<hp:sz width="2000" widthRelTo="ABSOLUTE" height="800" '
        'heightRelTo="ABSOLUTE" protect="0"/>'
        '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" '
        'allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" '
        'horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" '
        'horzOffset="0"/>'
        '<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
        "<hp:shapeComment>수식입니다.</hp:shapeComment>"
        f"<hp:script>{escape(script)}</hp:script>"
        "</hp:equation>"
    )


def _endnote_xml(number: int, entry: EndnoteEntry) -> str:
    """An actual hp:endNote inside hp:ctrl — the number renders at the
    insertion point and the subList holds answer+explanation, exactly the
    structure HWP writes for InsertEndnote."""
    content = f" {entry.label}. 정답: {entry.answer} — {entry.explanation}"
    return (
        f'<hp:ctrl><hp:endNote number="{number}" suffixChar="41" '
        f'instId="{1000 + number}">'
        f'<hp:subList {_SUBLIST_ATTRS}>'
        '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" '
        'columnBreak="0" merged="0"><hp:run charPrIDRef="0">'
        f'<hp:ctrl><hp:autoNum num="{number}" numType="ENDNOTE">'
        '<hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" '
        'suffixChar=")" supscript="0"/></hp:autoNum></hp:ctrl>'
        f"<hp:t>{escape(content)}</hp:t></hp:run></hp:p></hp:subList>"
        "</hp:endNote></hp:ctrl>"
    )


def _answer_space_xml(lines: int) -> str:
    """Ruled answer area as a bordered single-cell table — a real object,
    not a stack of empty paragraphs (no pixel-counted blank lines).
    `hp:tbl` is a direct child of `hp:run` (shape object, not a ctrl)."""
    height = lines * _ANSWER_LINE_H
    return (
        '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" '
        'columnBreak="0" merged="0"><hp:run charPrIDRef="0">'
        '<hp:tbl id="2" zOrder="0" numberingType="TABLE" '
        'textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" '
        'dropcapstyle="None" pageBreak="CELL" repeatHeader="0" rowCnt="1" '
        'colCnt="1" cellSpacing="0" borderFillIDRef="2" noAdjust="0">'
        '<hp:sz width="10000" widthRelTo="PARA" '
        f'height="{height}" heightRelTo="ABSOLUTE" protect="0"/>'
        '<hp:pos treatAsChar="0" affectLSpacing="0" flowWithText="1" '
        'allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" '
        'horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" '
        'horzOffset="0"/>'
        '<hp:outMargin left="141" right="141" top="141" bottom="141"/>'
        '<hp:inMargin left="510" right="510" top="141" bottom="141"/>'
        '<hp:tr><hp:tc name="" header="0" hasMargin="0" protect="0" '
        'editable="0" dirty="0" borderFillIDRef="2">'
        f'<hp:subList {_SUBLIST_ATTRS}>'
        '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" '
        'columnBreak="0" merged="0"><hp:run charPrIDRef="0">'
        "<hp:t>서술형 답안 작성란</hp:t></hp:run></hp:p></hp:subList>"
        '<hp:cellAddr colAddr="0" rowAddr="0"/>'
        '<hp:cellSpan colSpan="1" rowSpan="1"/>'
        f'<hp:cellSz width="10000" height="{height}"/>'
        '<hp:cellMargin left="510" right="510" top="141" bottom="141"/>'
        "</hp:tc></hp:tr></hp:tbl><hp:t/></hp:run></hp:p>"
    )


def _figure_objects_xml(q: Question) -> list[str]:
    out: list[str] = []
    for fig in q.figures:
        scene = getattr(fig, "scene", None)
        if scene is None:
            continue
        points: dict[str, tuple[float, float]] = {}
        for p in scene.primitives:
            if p.kind == "point":
                x = p.props.get("x")
                y = p.props.get("y")
                if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                    points[p.id] = (float(x), float(y))
        if not points:
            continue
        xs = [xy[0] for xy in points.values()]
        ys = [xy[1] for xy in points.values()]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = max(1.0, max_x - min_x)
        span_y = max(1.0, max_y - min_y)

        def sx(x: float) -> int:
            return int(((x - min_x) / span_x) * 3600) + 200

        def sy(y: float) -> int:
            return int(((y - min_y) / span_y) * 2200) + 200

        for p in scene.primitives:
            if p.kind in {"segment", "line", "ray"} and len(p.refs) >= 2:
                a = points.get(p.refs[0])
                b = points.get(p.refs[1])
                if a is None or b is None:
                    continue
                out.append(
                    '<hp:line id="31" zOrder="0" numberingType="LINE" textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0">'
                    '<hp:sz width="0" widthRelTo="ABSOLUTE" height="0" heightRelTo="ABSOLUTE" protect="0"/>'
                    '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
                    '<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
                    f'<hp:startPt x="{sx(a[0])}" y="{sy(a[1])}"/>'
                    f'<hp:endPt x="{sx(b[0])}" y="{sy(b[1])}"/>'
                    '<hp:lineShape endCap="FLAT" headStyle="NONE" tailStyle="NONE" outlineStyle="SOLID" color="#000000" width="40"/>'
                    "</hp:line>"
                )
        if len(points) >= 2:
            out.append(
                '<hp:rect id="41" zOrder="0" numberingType="RECTANGLE" textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0">'
                '<hp:sz width="3800" widthRelTo="ABSOLUTE" height="2400" heightRelTo="ABSOLUTE" protect="0"/>'
                '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
                '<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
                '<hp:lineShape endCap="FLAT" headStyle="NONE" tailStyle="NONE" outlineStyle="SOLID" color="#444444" width="20"/>'
                "</hp:rect>"
            )
    return out


# -- paragraphs ---------------------------------------------------------------------


def _para(text: str, char_pr: int = 0) -> str:
    return (
        '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" '
        f'columnBreak="0" merged="0"><hp:run charPrIDRef="{char_pr}">'
        f"<hp:t>{escape(text)}</hp:t></hp:run></hp:p>"
    )


def _para_run(inner: str) -> str:
    """A paragraph whose run is raw control XML (equation/table object)."""
    return (
        '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" '
        'columnBreak="0" merged="0"><hp:run charPrIDRef="0">'
        f"{inner}<hp:t/></hp:run></hp:p>"
    )


def _para_with_endnote(text: str, number: int, entry: EndnoteEntry) -> str:
    return (
        '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" '
        'columnBreak="0" merged="0"><hp:run charPrIDRef="2">'
        f"<hp:t>{escape(text)}</hp:t></hp:run>"
        f'<hp:run charPrIDRef="0">{_endnote_xml(number, entry)}'
        "<hp:t/></hp:run></hp:p>"
    )


# -- section / header -----------------------------------------------------------------


def _section_xml(paragraphs: list[str], plan: LayoutPlan) -> str:
    body = "".join(paragraphs)
    col_count = (
        2 if any(s.kind == "objective" for s in plan.slots) else 1
    )
    return f"""{_XML_DECL}
<hs:sec {_NS}><hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="0"><hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" tabStop="8000" outlineShapeIDRef="1" memoShapeIDRef="0" textVerticalWidthHead="0" masterPageCnt="0"><hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0"/><hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/><hp:visibility hideFirstHeader="0" hideFirstFooter="0" hideFirstMasterPage="0" border="SHOW_ALL" fill="SHOW_ALL" hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/><hp:lineNumberShape restartType="0" countBy="0" distance="0" startNumber="0"/><hp:pagePr landscape="WIDELY" width="59528" height="84186" gutterType="LEFT_ONLY"><hp:margin header="4252" footer="4252" gutter="0" left="8504" right="8504" top="5668" bottom="4252"/></hp:pagePr><hp:footNotePr><hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/><hp:noteLine length="-1" type="SOLID" width="0.12 mm" color="#000000"/><hp:noteSpacing betweenNotes="283" belowLine="567" aboveLine="850"/><hp:numbering type="CONTINUOUS" newNum="1"/><hp:placement place="EACH_COLUMN" beneathText="0"/></hp:footNotePr><hp:endNotePr><hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/><hp:noteLine length="14692344" type="SOLID" width="0.12 mm" color="#000000"/><hp:noteSpacing betweenNotes="0" belowLine="567" aboveLine="850"/><hp:numbering type="CONTINUOUS" newNum="1"/><hp:placement place="LAST_DOCUMENT" beneathText="0"/></hp:endNotePr><hp:pageBorderFill type="BOTH" borderFillIDRef="1" textBorder="PAPER" headerInside="0" footerInside="0" fillArea="PAPER"><hp:offset left="1417" right="1417" top="1417" bottom="1417"/></hp:pageBorderFill><hp:pageBorderFill type="EVEN" borderFillIDRef="1" textBorder="PAPER" headerInside="0" footerInside="0" fillArea="PAPER"><hp:offset left="1417" right="1417" top="1417" bottom="1417"/></hp:pageBorderFill><hp:pageBorderFill type="ODD" borderFillIDRef="1" textBorder="PAPER" headerInside="0" footerInside="0" fillArea="PAPER"><hp:offset left="1417" right="1417" top="1417" bottom="1417"/></hp:pageBorderFill></hp:secPr><hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="{col_count}" sameSz="1" sameGap="0"/></hp:ctrl></hp:run><hp:run charPrIDRef="0"><hp:t/></hp:run></hp:p>{body}</hs:sec>"""


def _header_xml(brand: BrandTemplate) -> str:
    fontface = "".join(
        f'<hh:fontface lang="{lang}" fontCnt="1">'
        f'<hh:font id="0" face="{escape(brand.body_font)}" type="TTF" isEmbedded="0">'
        '<hh:typeInfo familyType="FCAT_GOTHIC" weight="6" proportion="4" contrast="0" '
        'strokeVariation="1" armStyle="1" letterform="1" midline="1" xHeight="1"/>'
        "</hh:font></hh:fontface>"
        for lang in ("HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER")
    )
    lang_attrs = 'hangul="{v}" latin="{v}" hanja="{v}" japanese="{v}" other="{v}" symbol="{v}" user="{v}"'
    numbering_levels = "".join(
        f'<hh:paraHead start="1" level="{lv}" align="LEFT" useInstWidth="1" '
        f'autoIndent="1" widthAdjust="0" textOffsetType="PERCENT" textOffset="50" '
        f'numFormat="DIGIT" charPrIDRef="4294967295" checkable="0">^{lv}.</hh:paraHead>'
        for lv in range(1, 11)
    )
    return f"""{_XML_DECL}
<hh:head {_NS} version="1.2" secCnt="1"><hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/><hh:refList><hh:fontfaces itemCnt="7">{fontface}</hh:fontfaces><hh:borderFills itemCnt="2"><hh:borderFill id="1" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0"><hh:slash type="NONE" Crooked="0" isCounter="0"/><hh:backSlash type="NONE" isCounter="0"/><hh:leftBorder type="NONE" width="0.1 mm" color="#000000"/><hh:rightBorder type="NONE" width="0.1 mm" color="#000000"/><hh:topBorder type="NONE" width="0.1 mm" color="#000000"/><hh:bottomBorder type="NONE" width="0.1 mm" color="#000000"/><hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/></hh:borderFill><hh:borderFill id="2" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0"><hh:slash type="NONE" Crooked="0" isCounter="0"/><hh:backSlash type="NONE" isCounter="0"/><hh:leftBorder type="SOLID" width="0.4 mm" color="#000000"/><hh:rightBorder type="SOLID" width="0.4 mm" color="#000000"/><hh:topBorder type="SOLID" width="0.4 mm" color="#000000"/><hh:bottomBorder type="SOLID" width="0.4 mm" color="#000000"/><hh:diagonal type="NONE" width="0.1 mm" color="#000000"/></hh:borderFill></hh:borderFills><hh:charProperties itemCnt="3"><hh:charPr id="0" height="1000" textColor="#000000" shadeColor="4294967295" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="1"><hh:fontRef {lang_attrs.format(v='0')}/><hh:ratio {lang_attrs.format(v='100')}/><hh:spacing {lang_attrs.format(v='0')}/><hh:relSz {lang_attrs.format(v='100')}/><hh:offset {lang_attrs.format(v='0')}/><hh:underline type="NONE" shape="SOLID" color="#000000"/><hh:strikeout type="NONE"/><hh:outline type="NONE"/><hh:shadow type="NONE"/></hh:charPr><hh:charPr id="1" height="1400" textColor="{brand.accent_color}" shadeColor="4294967295" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="1"><hh:fontRef {lang_attrs.format(v='0')}/><hh:ratio {lang_attrs.format(v='100')}/><hh:spacing {lang_attrs.format(v='0')}/><hh:relSz {lang_attrs.format(v='100')}/><hh:offset {lang_attrs.format(v='0')}/><hh:underline type="NONE" shape="SOLID" color="#000000"/><hh:strikeout type="NONE"/><hh:outline type="NONE"/><hh:shadow type="NONE"/></hh:charPr><hh:charPr id="2" height="1000" textColor="#000000" shadeColor="4294967295" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="1"><hh:fontRef {lang_attrs.format(v='0')}/><hh:ratio {lang_attrs.format(v='100')}/><hh:spacing {lang_attrs.format(v='0')}/><hh:relSz {lang_attrs.format(v='100')}/><hh:offset {lang_attrs.format(v='0')}/><hh:underline type="NONE" shape="SOLID" color="#000000"/><hh:strikeout type="NONE"/><hh:outline type="NONE"/><hh:shadow type="NONE"/></hh:charPr></hh:charProperties><hh:tabProperties itemCnt="1"><hh:tabPr id="0" autoTabLeft="0" autoTabRight="0"/></hh:tabProperties><hh:numberings itemCnt="1"><hh:numbering id="1" start="0">{numbering_levels}</hh:numbering></hh:numberings><hh:paraProperties itemCnt="1"><hh:paraPr id="0" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="1" suppressLineNumbers="0" checked="0"><hh:align horizontal="LEFT" vertical="BASELINE"/><hh:heading type="NONE" idRef="0" level="0"/><hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD" widowOrphan="0" keepWithNext="0" keepLines="0" pageBreakBefore="0" fontLineHeight="0"/><hh:autoSpacing eAsianEng="0" eAsianNum="0"/><hh:margin><hc:intent value="0" unit="HWPUNIT"/><hc:left value="0" unit="HWPUNIT"/><hc:right value="0" unit="HWPUNIT"/><hc:prev value="0" unit="HWPUNIT"/><hc:next value="0" unit="HWPUNIT"/></hh:margin><hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/><hh:border borderFillIDRef="1" offsetLeft="0" offsetRight="0" offsetTop="0" offsetBottom="0" connect="0" ignoreMargin="0"/></hh:paraPr></hh:paraProperties><hh:styles itemCnt="1"><hh:style id="0" type="PARA" name="바탕글" engName="Normal" paraPrIDRef="0" charPrIDRef="0" nextStyleIDRef="0" langID="1042" lockForm="0"/></hh:styles><hh:memoProperties itemCnt="0"/></hh:refList></hh:head>"""


def _content_hpf(title: str) -> str:
    return f"""{_XML_DECL}
<opf:package {_NS} version="" unique-identifier="" id=""><opf:metadata><opf:title>{escape(title)}</opf:title><opf:language>ko</opf:language><opf:meta name="creator" content="text">exam-ai-spec</opf:meta></opf:metadata><opf:manifest><opf:item id="header" href="Contents/header.xml" media-type="application/xml"/><opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/><opf:item id="settings" href="settings.xml" media-type="application/xml"/></opf:manifest><opf:spine><opf:itemref idref="header" linear="yes"/><opf:itemref idref="section0" linear="yes"/></opf:spine></opf:package>"""


_MANIFEST_XML = (
    f"{_XML_DECL}\n"
    '<odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>'
)

_CONTAINER_XML = f"""{_XML_DECL}
<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container" xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf"><ocf:rootfiles><ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/><ocf:rootfile full-path="Preview/PrvText.txt" media-type="text/plain"/></ocf:rootfiles></ocf:container>"""

_SETTINGS_XML = f"""{_XML_DECL}
<ha:HWPApplicationSetting xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0"><ha:CaretPosition listIDRef="0" paraIDRef="0" pos="0"/></ha:HWPApplicationSetting>"""

_VERSION_XML = f"""{_XML_DECL}
<hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" tagetApplication="WORDPROCESSOR" major="5" minor="1" micro="0" buildNumber="1" os="1" xmlVersion="1.2" application="Hancom Office Hangul" appVersion="11, 0, 0, 2129 WIN32LEWindows_8"/>"""
