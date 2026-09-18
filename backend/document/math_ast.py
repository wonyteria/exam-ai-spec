"""Math AST, style tokens, and HWP equation-script conversion (WP05).

Requirements (REQ-08/09, A08):
- Mathematical numbers and variables render italic; units render roman.
- Equations render at 11pt — HWP baseUnit 1100 (validated in WP00 tech
  check: `<hp:equation>` with `baseUnit="1100"` round-trips through
  actual HWP 2020).
- Unsupported constructs fail loudly (`UnsupportedMathError`) — they
  become blocking issues, never silent garbage output.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# 11pt in HWP units (validated live against HWP 2020 in WP00).
HWP_BASE_UNIT_11PT = 1100


class UnsupportedMathError(ValueError):
    """Raised when a LaTeX construct has no safe HWP equivalent."""


class MathParseError(ValueError):
    """Raised when LaTeX input cannot be parsed at all."""


# -- AST -----------------------------------------------------------------------


@dataclass
class MNode:
    kind: str  # num|var|unit|op|sym|text|frac|sqrt|root|sup|sub|supsub|paren|seq
    value: str = ""
    children: list["MNode"] = field(default_factory=list)
    style: str = "it"  # it | rm — numbers/vars italic, units/text roman

    @staticmethod
    def seq(items: list["MNode"]) -> "MNode":
        if len(items) == 1:
            return items[0]
        return MNode("seq", children=items)


# Units recognized without an explicit \mathrm{} — Korean school-exam set.
_UNITS = {
    "cm", "mm", "km", "kg", "mg", "mL", "cm^2", "m^2", "cm^3",
    "m", "g", "t", "L", "s", "h", "min", "Hz", "N", "Pa", "J", "W",
    "mol", "kJ", "kcal", "rpm", "V", "A", "kWh",
    "원", "개", "명", "마리", "장", "번", "대", "권", "살", "점", "배",
}

# LaTeX symbol -> (hwp token, node kind)
_SYMBOLS = {
    "\\times": ("TIMES", "op"),
    "\\div": ("DIVIDE", "op"),
    "\\cdot": ("cdot", "op"),
    "\\pm": ("+-", "op"),
    "\\mp": ("-+", "op"),
    "\\le": ("<=", "op"),
    "\\leq": ("<=", "op"),
    "\\ge": (">=", "op"),
    "\\geq": (">=", "op"),
    "\\ne": ("!=", "op"),
    "\\neq": ("!=", "op"),
    "\\approx": ("approx", "op"),
    "\\equiv": ("==", "op"),
    "\\propto": ("propto", "op"),
    "\\infty": ("inf", "sym"),
    "\\pi": ("pi", "sym"),
    "\\alpha": ("alpha", "sym"),
    "\\beta": ("beta", "sym"),
    "\\gamma": ("gamma", "sym"),
    "\\theta": ("theta", "sym"),
    "\\phi": ("phi", "sym"),
    "\\omega": ("omega", "sym"),
    "\\lambda": ("lambda", "sym"),
    "\\mu": ("mu", "sym"),
    "\\Delta": ("DELTA", "sym"),
    "\\angle": ("angl", "sym"),
    "\\triangle": ("tri", "sym"),
    "\\parallel": ("paral", "op"),
    "\\perp": ("perp", "op"),
    "\\circ": ("deg", "sym"),
    "\\degree": ("deg", "sym"),
    "\\%": ("%", "sym"),
    "\\ldots": ("...", "sym"),
    "\\cdots": ("...", "sym"),
    "\\rightarrow": ("->", "op"),
    "\\leftarrow": ("<-", "op"),
    "\\Rightarrow": ("=>", "op"),
    "\\sim": ("~", "op"),
}

_ROMAN_CMDS = {"\\mathrm", "\\text", "\\rm", "\\operatorname"}
_UNSUPPORTED_PAT = re.compile(
    r"\\(begin|end|sum_|prod|int_|oint|bigg|lefteqn|boxed"
    r"|binom|vec|hat|dot|ddot|bar|overbrace|underbrace|xrightarrow|xleftarrow)"
)


# -- LaTeX-subset parser ---------------------------------------------------------


def parse_latex(src: str) -> MNode:
    """Parse the supported LaTeX subset into an MNode AST."""
    if not isinstance(src, str) or not src.strip():
        raise MathParseError("empty math source")
    if _UNSUPPORTED_PAT.search(src):
        raise UnsupportedMathError(
            f"unsupported LaTeX construct in {src[:40]!r}"
        )
    nodes, pos = _parse_seq(src, 0, len(src), stop=None)
    if pos < len(src):
        raise MathParseError(f"unbalanced braces at {pos}")
    return MNode.seq(nodes)


def _parse_seq(src: str, i: int, end: int, stop: Optional[str]):
    out: list[MNode] = []
    while i < end:
        ch = src[i]
        if stop and src.startswith(stop, i):
            return out, i + len(stop)
        if ch == "}" or ch == "]":
            return out, i
        if ch == "{":
            inner, i = _parse_seq(src, i + 1, end, "}")
            out.append(MNode.seq(inner))
            continue
        if ch == "^" or ch == "_":
            node, i = _parse_script(src, i, end, out)
            out.append(node)
            continue
        if ch == "\\":
            node, i = _parse_command(src, i, end)
            out.append(node)
            continue
        if ch.isdigit() or ch == ".":
            j = i + 1
            while j < end and (src[j].isdigit() or src[j] == "."):
                j += 1
            out.append(MNode("num", src[i:j], style="it"))
            i = j
            continue
        if ch.isalpha():
            j = i + 1
            while j < end and src[j].isalpha():
                j += 1
            word = src[i:j]
            if not word.isascii():
                # Hangul literal inside math — roman text (units like
                # 원/개/명 land here via _UNITS, other words too)
                out.append(MNode("unit" if word in _UNITS else "text",
                                 word, style="rm"))
            # unit heuristic: known unit word, and either multi-char
            # ("cm", "kg" — a lone "m"/"g" after an operator is a
            # variable, not a unit) or directly following a number.
            elif word in _UNITS and (
                len(word) > 1
                or (out and out[-1].kind in {"num", "paren"} and out[-1].value != "(")
            ):
                out.append(MNode("unit", word, style="rm"))
            else:
                for c in word:
                    out.append(MNode("var", c, style="it"))
            i = j
            continue
        if ch in "+-=<>/,;:!|":
            out.append(MNode("op", ch))
            i += 1
            continue
        if ch in "()[]{}":
            out.append(MNode("paren", ch))
            i += 1
            continue
        if ch in " ~\\,":
            i += 1  # spacing — layout concern, not content
            continue
        if ch == "'":
            out.append(MNode("sym", "prime"))
            i += 1
            continue
        if ch == "%":
            out.append(MNode("sym", "%"))
            i += 1
            continue
        # Hangul / other non-ASCII literals — roman text inside math
        j = i + 1
        while j < end and not src[j].isascii():
            j += 1
        out.append(MNode("text", src[i:j], style="rm"))
        i = j
    return out, i


def _parse_group(src: str, i: int, end: int):
    """Parse a `{...}` group or a single atom starting at i."""
    if i < end and src[i] == "{":
        inner, j = _parse_seq(src, i + 1, end, "}")
        return MNode.seq(inner), j
    if i < end and src[i] == "\\":
        return _parse_command(src, i, end)
    nodes, j = _parse_seq(src, i, min(i + 1, end), None)
    return MNode.seq(nodes), j


def _parse_script(src: str, i: int, end: int, out: list[MNode]):
    """Attach ^/_ to the previous node; combines ^ and _ on one base."""
    marker = src[i]
    arg, j = _parse_group(src, i + 1, end)
    base = out.pop() if out else MNode("seq")
    # merge consecutive sup+sub on the same base
    if base.kind == "supsub":
        if marker == "^":
            base.children[1] = MNode.seq([base.children[1], arg])
        else:
            base.children[2] = MNode.seq([base.children[2], arg])
        return base, j
    if j < end and src[j] in "^_" and src[j] != marker:
        arg2, j2 = _parse_group(src, j + 1, end)
        sup, sub = (arg, arg2) if marker == "^" else (arg2, arg)
        return MNode("supsub", children=[base, sup, sub]), j2
    return MNode("sup" if marker == "^" else "sub", children=[base, arg]), j


def _parse_command(src: str, i: int, end: int):
    j = i + 1
    while j < end and src[j].isalpha():
        j += 1
    cmd = src[i:j] if j > i + 1 else src[i : i + 2]
    if cmd in _ROMAN_CMDS:
        inner, j = _parse_group(src, j, end)
        return MNode("text", _plain_text(inner), style="rm"), j
    if cmd in {"\\frac", "\\dfrac", "\\tfrac"}:
        num, j = _parse_group(src, j, end)
        den, j = _parse_group(src, j, end)
        return MNode("frac", children=[num, den]), j
    if cmd == "\\sqrt":
        if j < end and src[j] == "[":
            k = src.find("]", j, end)
            if k < 0:
                raise MathParseError("unclosed \\sqrt[n]")
            n, _ = _parse_seq(src, j + 1, k, None)
            arg, j2 = _parse_group(src, k + 1, end)
            return MNode("root", children=[arg, MNode.seq(n)]), j2
        arg, j = _parse_group(src, j, end)
        return MNode("sqrt", children=[arg]), j
    if cmd == "\\overline":
        inner, j = _parse_group(src, j, end)
        return MNode("overline", children=[inner]), j
    if cmd in {"\\left", "\\right"}:
        # swallow the following delimiter char
        if j < end:
            j += 1
        return MNode("paren", src[j - 1] if j <= end else "("), j
    if cmd in _SYMBOLS:
        token, kind = _SYMBOLS[cmd]
        return MNode(kind, token), j
    raise UnsupportedMathError(f"unsupported command {cmd}")


def _plain_text(node: MNode) -> str:
    if node.kind in {"num", "var", "unit", "text", "sym", "op", "paren"}:
        return node.value
    return "".join(_plain_text(c) for c in node.children)


# -- HWP equation script ---------------------------------------------------------


def to_hwp_script(node: MNode) -> str:
    """Serialize the AST to HWP equation script (stored in <hp:script>).

    Numbers/variables emit bare (italic is HWP math default); units and
    literal text wrap in `rm{...}` — the REQ-08 style contract."""
    kind = node.kind
    if kind == "seq":
        return " ".join(to_hwp_script(c) for c in node.children)
    if kind in {"num", "var"}:
        return node.value
    if kind == "unit":
        return f"rm{{{node.value}}}"
    if kind == "text":
        return f"rm{{{node.value}}}"
    if kind == "sym":
        return node.value
    if kind == "op":
        return node.value
    if kind == "paren":
        return node.value
    if kind == "frac":
        return f"{{{to_hwp_script(node.children[0])}}} over {{{to_hwp_script(node.children[1])}}}"
    if kind == "sqrt":
        return f"sqrt{{{to_hwp_script(node.children[0])}}}"
    if kind == "root":
        return f"root {to_hwp_script(node.children[1])} of {{{to_hwp_script(node.children[0])}}}"
    if kind == "sup":
        return f"{_base(node.children[0])}^{{{to_hwp_script(node.children[1])}}}"
    if kind == "sub":
        return f"{_base(node.children[0])}_{{{to_hwp_script(node.children[1])}}}"
    if kind == "supsub":
        return (
            f"{_base(node.children[0])}^{{{to_hwp_script(node.children[1])}}}"
            f"_{{{to_hwp_script(node.children[2])}}}"
        )
    if kind == "overline":
        return f"overbar {{{to_hwp_script(node.children[0])}}}"
    raise UnsupportedMathError(f"cannot serialize node kind {kind}")


def _base(node: MNode) -> str:
    s = to_hwp_script(node)
    return s if " " not in s else f"{{{s}}}"


def latex_to_hwp(latex: str) -> dict:
    """LaTeX -> {"script": hwp equation script, "baseUnit": 1100}.

    The baseUnit is always emitted — 11pt is a hard requirement, not a
    renderer default."""
    node = parse_latex(latex)
    return {"script": to_hwp_script(node), "baseUnit": HWP_BASE_UNIT_11PT}
