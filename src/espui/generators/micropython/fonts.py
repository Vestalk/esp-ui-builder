"""Fonts for the board: which glyphs a page needs and the generated ``ui_fonts.py``.

Every (font, size) pair a page uses becomes one ``Font`` object in
``ui_fonts.py`` holding only the characters that can appear on screen:
static texts, formats, texts set by conditions, ``enum`` variants, axis
labels, the characters numbers are printed with and, for ``str`` parameters,
their configured charset. A character the font doesn't have is drawn as '?'
and reported as a warning.
"""

from __future__ import annotations

import base64
import re
import textwrap
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from espui.assets.fonts import ELLIPSIS, FONTS, REPLACEMENT, BitmapFont, rasterize
from espui.core.models import (
    DEFAULT_FONT,
    BoolParameter,
    Condition,
    EnumParameter,
    FloatParameter,
    IntParameter,
    Page,
    Parameter,
    SeriesParameter,
    StrParameter,
    Widget,
)

FONTS_FILE = "ui_fonts.py"
CHART_FONT_SIZE = 8
"""Chart ticks and axis labels, as in the mock-up."""

DIGITS = "0123456789"
NUMBER_CHARS = DIGITS + ".,-+%°: " + "einfa"
"""How numbers are printed (``%.1f``, ``%d``, ``%s``), incl. ``1e+20``, ``inf``, ``nan``."""
BOOL_CHARS = "TrueFals"
LATIN = "".join(chr(c) for c in range(32, 127))
UKRAINIAN = "АБВГҐДЕЄЖЗИІЇЙКЛМНОПРСТУФХЦЧШЩЬЮЯабвгґдеєжзиіїйклмнопрстуфхцчшщьюяʼ’«»—–…№°"
CHARSETS: Mapping[str, str] = {
    "latin_uk": LATIN + UKRAINIAN,
    "latin": LATIN,
    "digits": DIGITS + " .,-+:",
}
ALWAYS = " " + REPLACEMENT + ELLIPSIS
NO_DATA = "немає даних"

_SPEC_RE = re.compile(r"%(?:\.\d+)?[fds]")

FontKey = tuple[str, int]


def font_name(key: FontKey) -> str:
    """Name of the Font object in ui_fonts.py, e.g. ``SERIF_16``."""
    return f"{key[0].upper()}_{key[1]}"


def static_chars(fmt: str) -> str:
    """Characters of a format that are always printed (specifiers removed, '%%' -> '%')."""
    return _SPEC_RE.sub("", fmt).replace("%%", "%")


def value_chars(param: Parameter | None) -> tuple[str, str]:
    """(static, dynamic) characters a bound value can print.

    Static ones are known exactly (enum variants); dynamic ones are whole ranges
    (numbers, str charsets) whose missing glyphs are not worth a warning.
    """
    if param is None:
        return "", ""
    if isinstance(param, FloatParameter | IntParameter):
        return "", NUMBER_CHARS
    if isinstance(param, BoolParameter):
        return BOOL_CHARS, ""
    if isinstance(param, EnumParameter):
        return "".join(param.values), ""
    if isinstance(param, StrParameter):
        return param.extra_chars, CHARSETS[param.charset]
    assert isinstance(param, SeriesParameter)
    if param.x_kind == "label":
        return "".join(str(p.x) for p in param.default), LATIN + UKRAINIAN
    return "", NUMBER_CHARS


def widget_font(widget: Widget) -> FontKey | None:
    """(font, size) a widget draws text with, or None for shapes."""
    font = widget.font or DEFAULT_FONT
    if widget.type == "chart":
        return font, CHART_FONT_SIZE
    if widget.type in ("text", "value", "bar", "arc"):
        return font, widget.font_size or 16
    return None


def widget_chars(widget: Widget, page: Page) -> tuple[str, str]:
    """(static, dynamic) characters a widget can show."""
    param = page.parameter(widget.bind)
    kind = widget.type
    numeric = isinstance(param, FloatParameter | IntParameter)
    if kind in ("text", "value"):
        formats = [widget.format] + [
            str(r.to) for r in widget.rules if isinstance(r, Condition) and r.prop == "text"
        ]
        static, dynamic = value_chars(param)
        if param is None:  # an unbound text is shown as is
            return "".join(formats), ""
        return "".join(static_chars(f) for f in formats) + static, dynamic
    if kind == "bar":
        return widget.format, NUMBER_CHARS if numeric else ""
    if kind == "arc":
        return "", NUMBER_CHARS if numeric else ""
    if kind == "chart":
        chart = widget.chart
        static, dynamic = value_chars(param)
        axes = (chart.axis_x + chart.axis_y) if chart else ""
        return axes + NO_DATA + static, NUMBER_CHARS + dynamic
    return "", ""


@dataclass(frozen=True, slots=True)
class CharNeeds:
    static: set[str]
    dynamic: set[str]

    @property
    def all(self) -> set[str]:
        return self.static | self.dynamic | set(ALWAYS)


def collect(widgets: Iterable[Widget], page: Page) -> dict[FontKey, CharNeeds]:
    """Characters needed per (font, size), in the order fonts first appear."""
    needed: dict[FontKey, CharNeeds] = {}
    for widget in widgets:
        key = widget_font(widget)
        if key is None:
            continue
        static, dynamic = widget_chars(widget, page)
        needs = needed.setdefault(key, CharNeeds(set(), set()))
        needs.static.update(static)
        needs.dynamic.update(dynamic)
    return needed


@dataclass(frozen=True, slots=True)
class FontsModule:
    source: str
    fonts: Mapping[FontKey, BitmapFont]
    warnings: tuple[str, ...]

    @property
    def size(self) -> int:
        return len(self.source.encode("utf-8"))

    def summary(self) -> str:
        """``Literata 12/40 px · JetBrains Mono 14 px — ui_fonts.py 12,3 КБ``."""
        sizes: dict[str, list[int]] = defaultdict(list)
        for key, size in sorted(self.fonts):
            sizes[key].append(size)
        families = " · ".join(
            f"{FONTS[key].title} {'/'.join(map(str, sizes[key]))} px"
            for key in FONTS
            if key in sizes
        )
        kb = f"{self.size / 1024:.1f}".replace(".", ",")
        return f"Шрифти: {families} — {FONTS_FILE} {kb} КБ"


def build(needed: Mapping[FontKey, CharNeeds]) -> FontsModule:
    fonts: dict[FontKey, BitmapFont] = {}
    warnings: list[str] = []
    for key, chars in needed.items():
        font = rasterize(key[0], key[1], chars.all)
        missing = sorted(c for c in chars.static if c not in font.glyphs and not c.isspace())
        if missing:
            warnings.append(
                f"Шрифт {FONTS[key[0]].title} не має символів {''.join(missing)!r}: "
                f"на екрані буде «{REPLACEMENT}»."
            )
        fonts[key] = font
    return FontsModule(render_module(fonts), fonts, tuple(warnings))


# ------------------------------------------------------------------ ui_fonts.py
_RUNTIME = '''\
# ui_fonts — bitmap fonts of this project, generated by ESP UI Builder.
#
# Only the glyphs the page can show are here: one Font per (font, size).
# Glyphs are 1-bit (MONO_HLSB) and drawn with framebuf.blit and a 2-colour
# palette, so text looks the same with every display driver.
# Fonts: {licenses} — SIL Open Font License 1.1.

from binascii import a2b_base64

try:
    import framebuf
except ImportError:  # CPython (tests): metrics and fitting only
    framebuf = None

ELLIPSIS = "…"


class Font:
    """index: char -> (offset, width, height, left, top, advance)."""

    def __init__(self, size, ascent, descent, data, index):
        self.size = size
        self.ascent = ascent
        self.descent = descent
        self.height = ascent + descent
        self._data = memoryview(bytearray(a2b_base64(data)))
        self._index = index
        self._fbs = {{}}
        self._pal = None

    def glyph(self, ch):
        g = self._index.get(ch)
        return g if g is not None else self._index.get("?")

    def width(self, s):
        w = 0
        for ch in s:
            g = self.glyph(ch)
            if g is not None:
                w += g[5]
        return w

    def fit(self, s, w):
        """``s`` cut with '…' to fit ``w`` px."""
        if self.width(s) <= w:
            return s
        n = len(s)
        while n > 0 and self.width(s[:n] + ELLIPSIS) > w:
            n -= 1
        if n == 0 and self.width(ELLIPSIS) > w:
            return ""
        return s[:n] + ELLIPSIS

    def _fb(self, ch, g):
        fb = self._fbs.get(ch)
        if fb is None:
            off, w, h = g[0], g[1], g[2]
            fb = framebuf.FrameBuffer(self._data[off : off + ((w + 7) // 8) * h], w, h,
                                      framebuf.MONO_HLSB)  # fmt: skip
            self._fbs[ch] = fb
        return fb

    def draw(self, fb, s, x, base, color):
        """Draw ``s`` with its baseline at ``base``; returns the x after the text."""
        key = color ^ 1
        pal = self._pal
        if pal is None:
            pal = self._pal = framebuf.FrameBuffer(bytearray(4), 2, 1, framebuf.RGB565)
        pal.pixel(0, 0, key)
        pal.pixel(1, 0, color)
        for ch in s:
            g = self.glyph(ch)
            if g is None:
                continue
            if g[1] and g[2]:
                fb.blit(self._fb(ch, g), x + g[3], base - g[4], key, pal)
            x += g[5]
        return x

    def mono(self, s):
        """``s`` in a 1-bit buffer (width(s) x height, baseline at ``ascent``)."""
        w = self.width(s)
        buf = framebuf.FrameBuffer(bytearray(((w + 7) // 8) * self.height), w, self.height,
                                   framebuf.MONO_HLSB)  # fmt: skip
        x = 0
        for ch in s:
            g = self.glyph(ch)
            if g is None:
                continue
            if g[1] and g[2]:
                buf.blit(self._fb(ch, g), x + g[3], self.ascent - g[4], 0)
            x += g[5]
        return buf, w, self.height


def draw_text(fb, text, x, base, font, color):
    return font.draw(fb, text, x, base, color)
'''


def _font_source(name: str, font: BitmapFont) -> str:
    data = bytearray()
    index = []
    for char, glyph in sorted(font.glyphs.items()):
        index.append(
            f"        {char!r}: ({len(data)}, {glyph.width}, {glyph.height}, "
            f"{glyph.left}, {glyph.top}, {glyph.advance}),"
        )
        data += glyph.rows
    encoded = base64.b64encode(bytes(data)).decode("ascii")
    chunks = "\n".join(f'        "{c}"' for c in textwrap.wrap(encoded, 88)) or '        ""'
    return (
        f"# {font.title}: {len(font.glyphs)} glyphs, {len(data)} bytes\n"
        f"{name} = Font(\n"
        f"    {font.size},\n"
        f"    {font.ascent},\n"
        f"    {font.descent},\n"
        f"    (\n{chunks}\n    ),\n"
        "    {\n" + "\n".join(index) + "\n    },\n)\n"
    )


def render_module(fonts: Mapping[FontKey, BitmapFont]) -> str:
    licenses = ", ".join(sorted({FONTS[key].title for key, _ in fonts})) or "none"
    parts = [_RUNTIME.format(licenses=licenses)]
    for key, font in fonts.items():
        parts.append("\n" + _font_source(font_name(key), font))
    return "\n".join(parts)
