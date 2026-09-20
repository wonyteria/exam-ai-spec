"""Synthetic HWPX fixtures for rebranding tests (spec §12).

These build *valid-structure* HWPX packages exercising the risky shapes:
header table+image+text titles, master-page titles, odd/even/first header
variants, all five page-number mechanisms, and an existing watermark.
They contain no real student data and are safe to commit.
"""
from __future__ import annotations

import io
import zipfile

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"

_NS = (
    f'xmlns:hp="{HP}" xmlns:hs="{HS}" '
    'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" '
    'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" '
    'xmlns:opf="http://www.idpf.org/2007/opf/"'
)
_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'


def _p(text: str) -> str:
    return (
        '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" '
        'columnBreak="0" merged="0"><hp:run charPrIDRef="0">'
        f"<hp:t>{text}</hp:t></hp:run></hp:p>"
    )


def _run(text: str) -> str:
    return f'<hp:run charPrIDRef="0"><hp:t>{text}</hp:t></hp:run>'


def _sublist(inner: str) -> str:
    return (
        '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" '
        'vertAlign="TOP" linkListIDRef="0" linkListNextIDRef="0" textWidth="0" '
        f'textHeight="0" hasTextRef="0" hasNumRef="0">{inner}</hp:subList>'
    )


def _ctrl(inner: str) -> str:
    return f"<hp:ctrl>{inner}</hp:ctrl>"


def header_xml(title: str, apply: str = "BOTH", with_table: bool = False) -> str:
    """머리말 control — optionally a table+picture+text composite title."""
    if with_table:
        body = (
            '<hp:tbl id="2" zOrder="0" numberingType="TABLE" '
            'textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" '
            'rowCnt="1" colCnt="2" borderFillIDRef="2">'
            '<hp:sz width="9000" widthRelTo="PARA" height="900" '
            'heightRelTo="ABSOLUTE" protect="0"/>'
            '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" '
            'vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" '
            'horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
            "<hp:tr>"
            '<hp:tc name="" header="0" borderFillIDRef="1">'
            + _sublist(
                '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" '
                'columnBreak="0" merged="0"><hp:run charPrIDRef="0">'
                '<hp:pic id="7" zOrder="0" numberingType="PICTURE" '
                'textWrap="SQUARE" textFlow="BOTH_SIDES" lock="0">'
                '<hp:sz width="400" widthRelTo="ABSOLUTE" height="300" '
                'heightRelTo="ABSOLUTE" protect="0"/>'
                '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" '
                'vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" '
                'horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
                '<hp:img src="BinData/old_logo.png" dimOrgan="0"/>'
                "</hp:pic><hp:t/></hp:run></hp:p>"
            )
            + '<hp:cellAddr colAddr="0" rowAddr="0"/>'
            '<hp:cellSpan colSpan="1" rowSpan="1"/>'
            '<hp:cellSz width="1500" height="900"/></hp:tc>'
            '<hp:tc name="" header="0" borderFillIDRef="1">'
            + _sublist(_p(title))
            + '<hp:cellAddr colAddr="1" rowAddr="0"/>'
            '<hp:cellSpan colSpan="1" rowSpan="1"/>'
            '<hp:cellSz width="7500" height="900"/></hp:tc>'
            "</hp:tr></hp:tbl><hp:t/>"
        )
        return f'<hp:header applyPageType="{apply}">{_sublist(f"<hp:p id=\"0\" paraPrIDRef=\"0\" styleIDRef=\"0\" pageBreak=\"0\" columnBreak=\"0\" merged=\"0\"><hp:run charPrIDRef=\"0\">{body}</hp:run></hp:p>")}</hp:header>'
    return (
        f'<hp:header applyPageType="{apply}">'
        + _sublist(_p(title))
        + "</hp:header>"
    )


def footer_xml(
    text: str,
    apply: str = "BOTH",
    with_page_field: bool = True,
    literal_number: str | None = None,
) -> str:
    """꼬리말 — text + optional autoNum PAGE field or a literal number."""
    runs = _run(text)
    if with_page_field:
        runs += (
            '<hp:run charPrIDRef="0"><hp:ctrl>'
            '<hp:autoNum num="1" numType="PAGE" new="0">'
            '<hp:autoNumFormat type="DIGIT" userChar="" prefixChar="-" '
            'suffixChar="-" supscript="0"/></hp:autoNum></hp:ctrl><hp:t/></hp:run>'
        )
    if literal_number:
        runs += _run(literal_number)
    return (
        f'<hp:footer applyPageType="{apply}">'
        + _sublist(
            '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" '
            f'columnBreak="0" merged="0">{runs}</hp:p>'
        )
        + "</hp:footer>"
    )


def _masterpage_paras(
    title: str = "", with_watermark: bool = False, page_field: bool = False
) -> str:
    paras = ""
    if with_watermark:
        paras += (
            '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" '
            'columnBreak="0" merged="0"><hp:run charPrIDRef="0">'
            '<hp:pic id="42" zOrder="-1" numberingType="PICTURE" '
            'textWrap="SQUARE" textFlow="BOTH_SIDES" lock="0">'
            '<hp:sz width="20000" widthRelTo="ABSOLUTE" height="8000" '
            'heightRelTo="ABSOLUTE" protect="0"/>'
            '<hp:pos treatAsChar="0" affectLSpacing="0" flowWithText="0" '
            'allowOverlap="1" vertRelTo="PAPER" horzRelTo="PAPER" '
            'vertAlign="CENTER" horzAlign="CENTER" vertOffset="0" horzOffset="0"/>'
            "<hp:shapeComment>watermark</hp:shapeComment>"
            '<hp:img src="BinData/wm.png" dimOrgan="0" alpha="30"/>'
            "</hp:pic><hp:t/></hp:run></hp:p>"
        )
    if page_field:
        paras += (
            '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" '
            'columnBreak="0" merged="0"><hp:run charPrIDRef="0"><hp:ctrl>'
            '<hp:autoNum num="1" numType="PAGE" new="0">'
            '<hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" '
            'suffixChar="" supscript="0"/></hp:autoNum></hp:ctrl><hp:t/></hp:run></hp:p>'
        )
    if title:
        paras += _p(title)
    return paras


def masterpage_xml(title: str = "", with_watermark: bool = False, page_field: bool = False) -> str:
    """Inline ctrl payload — synthetic census shape (real Hancom files use
    separate package parts instead; see masterpage_part_xml)."""
    return f"<hp:masterPage>{_sublist(_masterpage_paras(title, with_watermark, page_field))}</hp:masterPage>"


def masterpage_part_xml(
    title: str = "", with_watermark: bool = False, page_field: bool = False
) -> str:
    """A real standalone 바탕쪽 package part — un-namespaced <masterPage>
    root wrapping hp:subList, exactly as Hancom serializes it into
    Contents/masterpageN.xml."""
    return (
        f'{_DECL}<masterPage {_NS} id="masterpage0" type="BOTH" '
        'pageNumber="0" pageDuplicate="0" pageFront="0">'
        + _sublist(_masterpage_paras(title, with_watermark, page_field))
        + "</masterPage>"
    )


def pagenum_ctrl() -> str:
    """Dedicated 쪽번호 위치 control."""
    return (
        '<hp:pageNumCtrl id="0" pageStartsOn="BOTH">'
        '<hp:pageNum pos="BOTTOM_CENTER" format="DIGIT" sideChar=""/>'
        "</hp:pageNumCtrl>"
    )


def section_xml(
    controls: list[str],
    body_paras: list[str],
    raw_body: list[str] | None = None,
    master_refs: list[str] | None = None,
) -> str:
    first_run = "".join(_ctrl(c) for c in controls)
    refs = master_refs or []
    # real linkage: <hp:masterPage idRef="..."/> children inside secPr —
    # masterPageCnt is their count
    mp_children = "".join(f'<hp:masterPage idRef="{r}"/>' for r in refs)
    secpr = (
        '<hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" '
        f'tabStop="8000" masterPageCnt="{len(refs)}"><hp:grid lineGrid="0" charGrid="0"/>'
        '<hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/>'
        '<hp:visibility hideFirstHeader="0" hideFirstFooter="0" '
        'hideFirstMasterPage="0" border="SHOW_ALL" fill="SHOW_ALL"/>'
        '<hp:pagePr landscape="WIDELY" width="59528" height="84186" '
        'gutterType="LEFT_ONLY"><hp:margin header="4252" footer="4252" '
        'gutter="0" left="8504" right="8504" top="5668" bottom="4252"/>'
        f"</hp:pagePr>{mp_children}</hp:secPr>"
    )
    first = (
        '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" '
        'columnBreak="0" merged="0"><hp:run charPrIDRef="0">'
        f"{secpr}{first_run}<hp:t/></hp:run></hp:p>"
    )
    body = "".join(_p(t) for t in body_paras) + "".join(raw_body or [])
    return f"{_DECL}<hs:sec {_NS}>{first}{body}</hs:sec>"


_CONTENT_HPF = f"""{_DECL}
<opf:package {_NS} version="1.0" unique-identifier="id">
<opf:manifest>
<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>
<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>
</opf:manifest></opf:package>"""

_SETTINGS = f"""{_DECL}
<ha:HWPSetting {_NS} version="1.0">
<ha:printHeader>교육원 ^p 쪽</ha:printHeader>
<ha:printFooter>- ^P -</ha:printFooter>
</ha:HWPSetting>"""

_SETTINGS_CLEAN = f"""{_DECL}
<ha:HWPSetting {_NS} version="1.0"></ha:HWPSetting>"""

_CONTAINER = f"""{_DECL}
<opf:container {_NS} version="1.0"><opf:rootfiles>
<opf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/>
</opf:rootfiles></opf:container>"""

_MANIFEST = f"""{_DECL}
<opf:manifest {_NS}><opf:item id="content" href="Contents/content.hpf"/></opf:manifest>"""

_HEADER = f"""{_DECL}
<hh:head {_NS} version="1.2" secCnt="1"><hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/><hh:refList/></hh:head>"""

_VERSION = f"""{_DECL}
<hv:HwpDocs version="1.0" {_NS}/>"""


def build_hwpx(
    sections: list[str],
    settings: str = _SETTINGS,
    extra_files: dict[str, bytes] | None = None,
    masterpages: list[str] | None = None,
) -> bytes:
    hpf = _CONTENT_HPF
    for i in range(len(masterpages or [])):
        hpf = hpf.replace(
            "</opf:manifest>",
            f'<opf:item id="masterpage{i}" href="Contents/masterpage{i}.xml" '
            'media-type="application/xml"/></opf:manifest>',
        )
    files = {
        "mimetype": b"application/hwp+zip",
        "version.xml": _VERSION.encode(),
        "settings.xml": settings.encode(),
        "META-INF/container.xml": _CONTAINER.encode(),
        "META-INF/manifest.xml": _MANIFEST.encode(),
        "Contents/content.hpf": hpf.encode(),
        "Contents/header.xml": _HEADER.encode(),
    }
    for i, sec in enumerate(sections):
        files[f"Contents/section{i}.xml"] = sec.encode()
    for i, mp in enumerate(masterpages or []):
        files[f"Contents/masterpage{i}.xml"] = mp.encode()
    for name, data in (extra_files or {}).items():
        files[name] = data
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        zf.writestr(info, files.pop("mimetype"))
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


# --- canonical fixture shapes -----------------------------------------------------


def fixture_header_table_image_title() -> bytes:
    """Header with table+logo picture+title text, footer with autoNum PAGE
    + other text, dedicated pageNumCtrl, print ^p token — mechanisms 1,2,4."""
    sec = section_xml(
        controls=[
            header_xml("다른학원 수학", apply="BOTH", with_table=True),
            footer_xml("문의 02-000-0000", apply="BOTH", with_page_field=True),
            pagenum_ctrl(),
        ],
        body_paras=["제1회 모의고사", "1. 다음 식을 계산하시오.", "2. 그림을 보고 답하시오."],
    )
    return build_hwpx([sec])


def fixture_five_mechanisms() -> bytes:
    """All five page-number mechanisms: dedicated control, header/footer
    autoNum field, master-page field, print token, literal footer number."""
    sec = section_xml(
        controls=[
            header_xml("다른학원 수학", apply="BOTH"),
            footer_xml("연락처", apply="BOTH", with_page_field=True, literal_number="3"),
            pagenum_ctrl(),
        ],
        body_paras=["시험 본문"],
        master_refs=["masterpage0"],
    )
    return build_hwpx(
        [sec], masterpages=[masterpage_part_xml(page_field=True)]
    )


def fixture_master_title_variants() -> bytes:
    """Master-page title + odd/even/first header variants + existing
    watermark picture on the master page (a real 바탕쪽 package part)."""
    sec = section_xml(
        controls=[
            header_xml("세움학원", apply="FIRST"),
            header_xml("세움학원 홀수", apply="ODD"),
            header_xml("세움학원 짝수", apply="EVEN"),
        ],
        body_paras=["본문 1", "본문 2"],
        master_refs=["masterpage0"],
    )
    return build_hwpx(
        [sec],
        settings=_SETTINGS_CLEAN,
        masterpages=[masterpage_part_xml("세움학원 바탕쪽", with_watermark=True)],
    )


def fixture_multi_section() -> bytes:
    """Three sections — section 2 owns a real master-page part; the
    watermark must cover all three."""
    secs = [
        section_xml(
            controls=[header_xml("A학원 1부"), footer_xml("A", with_page_field=True)],
            body_paras=["섹션1 본문"],
        ),
        section_xml(
            controls=[header_xml("A학원 2부")],
            body_paras=["섹션2 본문"],
            master_refs=["masterpage0"],
        ),
        section_xml(
            controls=[header_xml("A학원 3부")],
            body_paras=["섹션3 본문"],
        ),
    ]
    return build_hwpx(
        secs,
        settings=_SETTINGS_CLEAN,
        masterpages=[masterpage_part_xml()],
    )


def fixture_body_top_title() -> bytes:
    """No header — title lives only at body top (ambiguous, confirm-only)."""
    sec = section_xml(
        controls=[footer_xml("안내", with_page_field=True)],
        body_paras=["진수학 중간고사", "1. 문제"],
    )
    return build_hwpx([sec], settings=_SETTINGS_CLEAN)


def drawtext_run(text: str) -> str:
    """A run hosting hp:container > hp:rect > hp:drawText (글상자) — the
    drawing-object shape real Hancom files use for floating title boxes."""
    return (
        '<hp:run charPrIDRef="0">'
        '<hp:container id="9" zOrder="0" numberingType="NONE" '
        'textWrap="SQUARE" textFlow="BOTH_SIDES" lock="0" '
        'dropcapstyle="None" href="" groupLevel="0" instid="1">'
        '<hp:sz width="89040" widthRelTo="ABSOLUTE" height="17040" '
        'heightRelTo="ABSOLUTE" protect="0"/>'
        '<hp:pos treatAsChar="0" affectLSpacing="0" flowWithText="0" '
        'allowOverlap="1" vertRelTo="PAPER" horzRelTo="PAPER" '
        'vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
        '<hp:rect id="10" zOrder="0" numberingType="NONE" '
        'textWrap="SQUARE" textFlow="BOTH_SIDES" lock="0" '
        'dropcapstyle="None" href="" groupLevel="1" instid="2" ratio="0">'
        '<hp:offset x="0" y="0"/>'
        '<hp:orgSz width="20000" height="2000"/>'
        '<hp:curSz width="0" height="0"/>'
        '<hp:drawText textWidth="0" style="">'
        + _sublist(_p(text))
        + "</hp:drawText></hp:rect></hp:container><hp:t/></hp:run>"
    )


def header_xml_drawtext(title: str, apply: str = "BOTH") -> str:
    """머리말 whose title text lives inside a 글상자 (container>rect>drawText)."""
    return (
        f'<hp:header applyPageType="{apply}">'
        + _sublist(
            '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" '
            'columnBreak="0" merged="0">' + drawtext_run(title) + "</hp:p>"
        )
        + "</hp:header>"
    )


def fixture_drawtext_title() -> bytes:
    """jinsu-style 글상자 title: header container>rect>drawText text plus a
    body floating box containing a logo picture — all confirm-only."""
    body_box = (
        '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" '
        'columnBreak="0" merged="0">'
        + drawtext_run("다른학원 모의고사")
        + '<hp:run charPrIDRef="0"><hp:container id="11" zOrder="0" '
          'numberingType="NONE" textWrap="SQUARE" textFlow="BOTH_SIDES" '
          'lock="0" dropcapstyle="None" href="" groupLevel="0" instid="3">'
          '<hp:pic id="12" zOrder="0" numberingType="PICTURE" '
          'textWrap="SQUARE" textFlow="BOTH_SIDES" lock="0">'
          '<hp:sz width="400" widthRelTo="ABSOLUTE" height="300" '
          'heightRelTo="ABSOLUTE" protect="0"/>'
          '<hp:pos treatAsChar="0" affectLSpacing="0" flowWithText="0" '
          'vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" '
          'horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
          '<hp:img src="BinData/image1.png" dimOrgan="0"/></hp:pic>'
          "</hp:container><hp:t/></hp:run></hp:p>"
    )
    sec = section_xml(
        controls=[
            header_xml_drawtext("다른학원 중간고사"),
            footer_xml("연락처", apply="BOTH", with_page_field=True),
        ],
        body_paras=["1. 다음을 구하시오."],
        raw_body=[body_box],
    )
    return build_hwpx(
        [sec],
        settings=_SETTINGS_CLEAN,
        extra_files={"BinData/image1.png": b"\x89PNG\x00"},
    )


def fixture_cell_borderfill_logo() -> bytes:
    """seum-style: the academy logo is a table-cell *background* image —
    an hh:borderFill in header.xml, not an hp:pic. The census must
    disclose it; confirming it must fail closed."""
    hdr = (
        '<hp:header applyPageType="BOTH">'
        + _sublist(
            '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" '
            'columnBreak="0" merged="0"><hp:run charPrIDRef="0">'
            '<hp:tbl id="2" zOrder="0" numberingType="TABLE" '
            'textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" '
            'rowCnt="1" colCnt="2" borderFillIDRef="1">'
            '<hp:sz width="9000" widthRelTo="PARA" height="900" '
            'heightRelTo="ABSOLUTE" protect="0"/>'
            '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" '
            'vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" '
            'horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
            "<hp:tr>"
            '<hp:tc name="" header="0" borderFillIDRef="6">'
            + _sublist(_p(""))
            + '<hp:cellAddr colAddr="0" rowAddr="0"/>'
            '<hp:cellSpan colSpan="1" rowSpan="1"/>'
            '<hp:cellSz width="1500" height="900"/></hp:tc>'
            '<hp:tc name="" header="0" borderFillIDRef="1">'
            + _sublist(_p("2026 다른학교1"))
            + '<hp:cellAddr colAddr="1" rowAddr="0"/>'
            '<hp:cellSpan colSpan="1" rowSpan="1"/>'
            '<hp:cellSz width="7500" height="900"/></hp:tc>'
            "</hp:tr></hp:tbl><hp:t/></hp:run></hp:p>"
        )
        + "</hp:header>"
    )
    head_with_fill = f"""{_DECL}
<hh:head {_NS} version="1.2" secCnt="1"><hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/><hh:refList><hh:borderFills itemCnt="1">
<hh:borderFill id="6" type="SOLID"><hh:fillBrush><hc:brush><hc:img binaryItemIDRef="image1" mode="TILE"/></hc:brush></hh:fillBrush></hh:borderFill>
</hh:borderFills></hh:refList></hh:head>"""
    sec = section_xml(
        controls=[hdr, footer_xml("연락처", with_page_field=True)],
        body_paras=["본문 유지"],
    )
    return build_hwpx(
        [sec],
        settings=_SETTINGS_CLEAN,
        extra_files={
            "Contents/header.xml": head_with_fill.encode(),
            "BinData/image1.png": b"\x89PNG\x00",
        },
    )


def fixture_body_cell_borderfill() -> bytes:
    """Body-table branding: the logo cell sits inside a *body* paragraph's
    table, not the header — same borderFill mechanism resolved under
    body/p[i]/run[j]/tbl[k]/tc[m]."""
    body_tbl = (
        '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" '
        'columnBreak="0" merged="0"><hp:run charPrIDRef="0">'
        '<hp:tbl id="2" zOrder="0" numberingType="TABLE" '
        'textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" '
        'rowCnt="1" colCnt="2" borderFillIDRef="1">'
        '<hp:sz width="9000" widthRelTo="PARA" height="900" '
        'heightRelTo="ABSOLUTE" protect="0"/>'
        '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" '
        'vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" '
        'horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
        "<hp:tr>"
        '<hp:tc name="" header="0" borderFillIDRef="6">'
        + _sublist(_p(""))
        + '<hp:cellAddr colAddr="0" rowAddr="0"/>'
        '<hp:cellSpan colSpan="1" rowSpan="1"/>'
        '<hp:cellSz width="1500" height="900"/></hp:tc>'
        '<hp:tc name="" header="0" borderFillIDRef="1">'
        + _sublist(_p("타학원 로고 표"))
        + '<hp:cellAddr colAddr="1" rowAddr="0"/>'
        '<hp:cellSpan colSpan="1" rowSpan="1"/>'
        '<hp:cellSz width="7500" height="900"/></hp:tc>'
        "</hp:tr></hp:tbl><hp:t/></hp:run></hp:p>"
    )
    head_with_fill = f"""{_DECL}
<hh:head {_NS} version="1.2" secCnt="1"><hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/><hh:refList><hh:borderFills itemCnt="1">
<hh:borderFill id="6" type="SOLID"><hh:fillBrush><hc:brush><hc:img binaryItemIDRef="image1" mode="TILE"/></hc:brush></hh:fillBrush></hh:borderFill>
</hh:borderFills></hh:refList></hh:head>"""
    sec = section_xml(
        controls=[header_xml("다른학원 시험지")],
        body_paras=[],
        raw_body=[body_tbl, _p("본문 문제 유지")],
    )
    return build_hwpx(
        [sec],
        settings=_SETTINGS_CLEAN,
        extra_files={
            "Contents/header.xml": head_with_fill.encode(),
            "BinData/image1.png": b"\x89PNG\x00",
        },
    )


def fixture_encrypted() -> bytes:
    """settings.xml flagged protected -> fail closed."""
    sec = section_xml(controls=[], body_paras=["본문"])
    settings = f"""{_DECL}
<ha:HWPSetting {_NS} version="1.0" password="1" protectDocument="1"></ha:HWPSetting>"""
    return build_hwpx([sec], settings=settings)
