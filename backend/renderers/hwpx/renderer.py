from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

from document.models import Document

_NS = (
    'xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" '
    'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
    'xmlns:hp10="http://www.hancom.co.kr/hwpml/2016/paragraph" '
    'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
    'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" '
    'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" '
    'xmlns:hhs="http://www.hancom.co.kr/hwpml/2011/history" '
    'xmlns:hm="http://www.hancom.co.kr/hwpml/2011/master-page" '
    'xmlns:hpf="http://www.hancom.co.kr/hwpml/2011/schema" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:opf="http://www.idpf.org/2007/opf/" '
    'xmlns:ooxmlchart="http://www.hancom.co.kr/hwpml/2016/ooxmlchart" '
    'xmlns:hwpunitchar="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar" '
    'xmlns:hgo="http://www.hancom.co.kr/hwpml/2016/hgo" '
    'xmlns:epub="http://www.idpf.org/2007/ops" '
    'xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0"'
)

_XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'


def render_hwpx(document: Document, title: str = "시험지") -> bytes:
    """Render the Verified Document JSON into a minimal HWPX package."""
    paragraphs = _question_paragraphs(document, title)
    files = {
        "mimetype": b"application/hwp+zip",
        "version.xml": _VERSION_XML.encode("utf-8"),
        "settings.xml": _SETTINGS_XML.encode("utf-8"),
        "META-INF/container.xml": _CONTAINER_XML.encode("utf-8"),
        "META-INF/manifest.xml": _manifest_xml().encode("utf-8"),
        "Contents/content.hpf": _content_hpf(title).encode("utf-8"),
        "Contents/header.xml": _header_xml().encode("utf-8"),
        "Contents/section0.xml": _section_xml(paragraphs).encode("utf-8"),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        zf.writestr(info, files.pop("mimetype"))
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _question_paragraphs(document: Document, title: str) -> list[str]:
    paras = [_para(title)]
    if not document.questions:
        paras.append(_para(""))
        return paras
    for q in sorted(document.questions, key=lambda x: x.number):
        head = f"{q.number}." + (f" ({q.points}점)" if q.points else "")
        paras.append(_para(head))
        for span in q.body:
            paras.append(_para(span.text))
        for eq in q.equations:
            paras.append(_para(f"[수식] {eq.latex or eq.hwp_formula or ''}"))
        for c in q.choices:
            text = " ".join(s.text for s in c.body)
            paras.append(_para(f"{c.label} {text}"))
        paras.append(_para(""))
    return paras


def _para(text: str) -> str:
    return (
        '<hp:p paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" '
        'merged="0"><hp:run charPrIDRef="0">'
        f"<hp:t>{escape(text)}</hp:t></hp:run></hp:p>"
    )


def _section_xml(paragraphs: list[str]) -> str:
    body = "".join(paragraphs)
    return f"""{_XML_DECL}
<hs:sec {_NS}>
  <hp:p paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
    <hp:run charPrIDRef="0">
      <hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" tabStop="8000" tabStopVal="4000" tabStopUnit="HWPUNIT" outlineShapeIDRef="1" memoShapeIDRef="0" textVerticalWidthHead="0" masterPageCnt="0">
        <hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0"/>
        <hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/>
        <hp:visibility hideFirstHeader="0" hideFirstFooter="0" hideFirstMasterPage="0" border="SHOW_ALL" fill="SHOW_ALL" hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/>
        <hp:lineNumberShape restartType="0" countBy="0" distance="0" startNumber="0"/>
        <hp:pagePr landscape="WIDELY" width="59528" height="84186" gutterType="LEFT_ONLY">
          <hp:margin header="4252" footer="4252" gutter="0" left="8504" right="8504" top="5668" bottom="4252"/>
        </hp:pagePr>
        <hp:footNotePr>
          <hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/>
          <hp:noteLine length="-1" type="SOLID" width="0.12 mm" color="#000000"/>
          <hp:noteSpacing betweenNotes="283" belowLineOffset="567" aboveLineOffset="850"/>
          <hp:noteNumbering type="CONTINUOUS" newNum="1"/>
          <hp:notePlacement place="EACH_COLUMN" beneathText="0"/>
        </hp:footNotePr>
        <hp:endNotePr>
          <hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/>
          <hp:noteLine length="14692344" type="SOLID" width="0.12 mm" color="#000000"/>
          <hp:noteSpacing betweenNotes="0" belowLineOffset="567" aboveLineOffset="850"/>
          <hp:noteNumbering type="CONTINUOUS" newNum="1"/>
          <hp:notePlacement place="LAST_DOCUMENT" beneathText="0"/>
        </hp:endNotePr>
        <hp:pageBorderFill type="BOTH" borderFillIDRef="1" textBorder="PAPER" headerInside="0" footerInside="0" fillArea="PAPER">
          <hp:offset left="1418" right="1418" top="1418" bottom="1418"/>
        </hp:pageBorderFill>
        <hp:pageBorderFill type="EVEN" borderFillIDRef="1" textBorder="PAPER" headerInside="0" footerInside="0" fillArea="PAPER">
          <hp:offset left="1418" right="1418" top="1418" bottom="1418"/>
        </hp:pageBorderFill>
        <hp:pageBorderFill type="ODD" borderFillIDRef="1" textBorder="PAPER" headerInside="0" footerInside="0" fillArea="PAPER">
          <hp:offset left="1418" right="1418" top="1418" bottom="1418"/>
        </hp:pageBorderFill>
      </hp:secPr>
      <hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1" sameSz="1" sameGap="0" colsGap="1134"/></hp:ctrl>
    </hp:run>
    <hp:t></hp:t>
  </hp:p>
  {body}
</hs:sec>"""


def _header_xml() -> str:
    fontface = "".join(
        f'<hh:fontface lang="{lang}" fontCnt="1">'
        '<hh:font id="0" face="함초롬바탕" type="TTF" isEmbedded="0">'
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
<hh:head {_NS} version="1.4" secCnt="1">
  <hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/>
  <hh:refList>
    <hh:fontfaces itemCnt="7">{fontface}</hh:fontfaces>
    <hh:borderFills itemCnt="1">
      <hh:borderFill id="1" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">
        <hh:slash type="NONE" Crooked="0" isCounter="0"/>
        <hh:backSlash type="NONE" Crooked="0" isCounter="0"/>
        <hh:leftBorder type="NONE" width="0.1 mm" color="#000000"/>
        <hh:rightBorder type="NONE" width="0.1 mm" color="#000000"/>
        <hh:topBorder type="NONE" width="0.1 mm" color="#000000"/>
        <hh:bottomBorder type="NONE" width="0.1 mm" color="#000000"/>
        <hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>
      </hh:borderFill>
    </hh:borderFills>
    <hh:charProperties itemCnt="1">
      <hh:charPr id="0" height="1000" textColor="#000000" shadeColor="4294967295" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="1">
        <hh:fontRef {lang_attrs.format(v='0')}/>
        <hh:ratio {lang_attrs.format(v='100')}/>
        <hh:spacing {lang_attrs.format(v='0')}/>
        <hh:relSz {lang_attrs.format(v='100')}/>
        <hh:offset {lang_attrs.format(v='0')}/>
        <hh:underline type="NONE" shape="SOLID" color="#000000"/>
        <hh:strikeout type="NONE"/>
        <hh:outline type="NONE"/>
        <hh:shadow type="NONE"/>
      </hh:charPr>
    </hh:charProperties>
    <hh:tabProperties itemCnt="1">
      <hh:tabPr id="0" autoTabLeft="0" autoTabRight="0"/>
    </hh:tabProperties>
    <hh:numberings itemCnt="1">
      <hh:numbering id="1" start="0">{numbering_levels}</hh:numbering>
    </hh:numberings>
    <hh:paraProperties itemCnt="1">
      <hh:paraPr id="0" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="1" suppressLineNumbers="0" checked="0">
        <hh:align horizontal="LEFT" vertical="BASELINE"/>
        <hh:heading type="NONE" idRef="0" level="0"/>
        <hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD" widowOrphan="0" keepWithNext="0" keepLines="0" pageBreakBefore="0" fontLineHeight="0"/>
        <hh:autoSpacing eAsianEng="0" eAsianNum="0"/>
        <hh:margin>
          <hc:intent value="0" unit="HWPUNIT"/>
          <hc:left value="0" unit="HWPUNIT"/>
          <hc:right value="0" unit="HWPUNIT"/>
          <hc:prev value="0" unit="HWPUNIT"/>
          <hc:next value="0" unit="HWPUNIT"/>
        </hh:margin>
        <hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/>
        <hh:border borderFillIDRef="1" offsetLeft="0" offsetRight="0" offsetTop="0" offsetBottom="0" connect="0" ignoreMargin="0"/>
      </hh:paraPr>
    </hh:paraProperties>
    <hh:styles itemCnt="1">
      <hh:style id="0" type="PARA" name="바탕글" engName="Normal" paraPrIDRef="0" charPrIDRef="0" nextStyleIDRef="0" langID="1042" lockForm="0"/>
    </hh:styles>
    <hh:memoProperties itemCnt="0"/>
  </hh:refList>
</hh:head>"""


def _content_hpf(title: str) -> str:
    return f"""{_XML_DECL}
<opf:package xmlns:opf="http://www.idpf.org/2007/opf" version="1.2" unique-identifier="bookid" id="bookid">
  <opf:metadata>
    <opf:title>{escape(title)}</opf:title>
    <opf:language>ko</opf:language>
  </opf:metadata>
  <opf:manifest>
    <opf:item id="header" href="Contents/header.xml" media-type="application/hwpml+xml"/>
    <opf:item id="section0" href="Contents/section0.xml" media-type="application/hwpml+xml"/>
    <opf:item id="settings" href="settings.xml" media-type="application/hwpml+xml"/>
  </opf:manifest>
  <opf:spine>
    <opf:itemref idref="header" linear="no"/>
    <opf:itemref idref="section0"/>
  </opf:spine>
</opf:package>"""


def _manifest_xml() -> str:
    entries = [
        ("/", "application/hwp+zip"),
        ("Contents/content.hpf", "application/hwpml-package+xml"),
        ("Contents/header.xml", "application/hwpml+xml"),
        ("Contents/section0.xml", "application/hwpml+xml"),
        ("settings.xml", "application/hwpml+xml"),
    ]
    body = "".join(
        f'<manifest:file-entry manifest:full-path="{p}" manifest:media-type="{m}"/>'
        for p, m in entries
    )
    return (
        f"{_XML_DECL}\n"
        '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">'
        f"{body}</manifest:manifest>"
    )


_CONTAINER_XML = f"""{_XML_DECL}
<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container" xmlns:hpf="http://www.idpf.org/2007/opf" version="1.0">
  <ocf:rootfiles>
    <ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/>
  </ocf:rootfiles>
</ocf:container>"""

_SETTINGS_XML = f"""{_XML_DECL}
<haw:config xmlns:haw="http://www.hancom.co.kr/hwpml/2011/config">
  <haw:caretPosition listIDRef="0" paraIDRef="0" pos="0"/>
</haw:config>"""

_VERSION_XML = f"""{_XML_DECL}
<hv:version xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" tag="1.4">5.1.0.1</hv:version>"""
