"""Bundled fonts and their 1-bit bitmap glyphs.

The same glyphs are used by the MicroPython generator (``ui_fonts.py``), by
the GUI preview (stage 10+) and by the tests, so the screen and the preview
match pixel for pixel. Glyphs are rendered by FreeType in monochrome mode
(hinted, no anti-aliasing); Press Start 2P is a pixel font and lands exactly on
its 8 px grid at sizes that are multiples of 8.

All fonts are SIL OFL 1.1; their licences lie next to the TTF files.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from types import MappingProxyType

import freetype

FONTS_DIR = "fonts"
"""Folder with the TTF files and licences, next to this module."""
ELLIPSIS = "…"
REPLACEMENT = "?"


@dataclass(frozen=True, slots=True)
class FontInfo:
    key: str
    """Value of ``widget.font``."""
    title: str
    file: str
    license_file: str
    kind: str
    """Ukrainian description for the GUI."""
    optical_size: bool = False
    """Variable font with an ``opsz`` axis: it follows the pixel size (as browsers do)."""


FONTS: Mapping[str, FontInfo] = MappingProxyType(
    {
        "serif": FontInfo(
            "serif", "Literata", "Literata[opsz,wght].ttf", "Literata-OFL.txt", "з засічками", True
        ),
        "mono": FontInfo(
            "mono",
            "JetBrains Mono",
            "JetBrainsMono[wght].ttf",
            "JetBrainsMono-OFL.txt",
            "моноширинний",
        ),
        "pixel": FontInfo(
            "pixel",
            "Press Start 2P",
            "PressStart2P-Regular.ttf",
            "PressStart2P-OFL.txt",
            "піксельний",
        ),
    }
)


class UnknownFontError(KeyError):
    def __str__(self) -> str:
        return f"невідомий шрифт «{self.args[0]}»; є: {', '.join(FONTS)}"


@dataclass(frozen=True, slots=True)
class Glyph:
    char: str
    width: int
    height: int
    left: int
    """Bitmap offset from the pen position, px."""
    top: int
    """Distance from the baseline up to the bitmap's first row, px."""
    advance: int
    rows: bytes
    """MONO_HLSB: ``(width + 7) // 8`` bytes per row, most significant bit = leftmost pixel."""

    @property
    def stride(self) -> int:
        return (self.width + 7) // 8

    def pixel(self, x: int, y: int) -> bool:
        return bool(self.rows[y * self.stride + x // 8] & (0x80 >> (x % 8)))


@dataclass(frozen=True, slots=True)
class BitmapFont:
    """Glyphs of one font at one pixel size."""

    key: str
    size: int
    ascent: int
    descent: int
    glyphs: Mapping[str, Glyph] = field(repr=False)

    @property
    def title(self) -> str:
        return f"{FONTS[self.key].title} {self.size} px"

    @property
    def height(self) -> int:
        return self.ascent + self.descent

    def glyph(self, char: str) -> Glyph | None:
        """The glyph, or the replacement '?' if this set doesn't have the character."""
        return self.glyphs.get(char) or self.glyphs.get(REPLACEMENT)

    def width(self, text: str) -> int:
        return sum(g.advance for g in map(self.glyph, text) if g is not None)

    def fit(self, text: str, width: int) -> str:
        """``text`` cut with '…' to fit ``width`` px (same rule as on the board)."""
        if self.width(text) <= width:
            return text
        n = len(text)
        while n > 0 and self.width(text[:n] + ELLIPSIS) > width:
            n -= 1
        if n == 0 and self.width(ELLIPSIS) > width:
            return ""
        return text[:n] + ELLIPSIS

    def subset(self, chars: Iterable[str]) -> BitmapFont:
        wanted = set(chars)
        return BitmapFont(
            self.key,
            self.size,
            self.ascent,
            self.descent,
            MappingProxyType({c: g for c, g in self.glyphs.items() if c in wanted}),
        )


def font_info(key: str) -> FontInfo:
    try:
        return FONTS[key]
    except KeyError:
        raise UnknownFontError(key) from None


def font_path(key: str) -> str:
    return str(resources.files("espui.assets").joinpath(FONTS_DIR, font_info(key).file))


@cache
def _face(key: str, size: int) -> freetype.Face:
    info = font_info(key)
    face = freetype.Face(font_path(key))
    if info.optical_size and face.has_multiple_masters:
        axes = face.get_variation_info().axes
        coords = [
            float(min(max(size, a.minimum), a.maximum)) if a.tag == "opsz" else float(a.default)
            for a in axes
        ]
        face.set_var_design_coords(coords)
    face.set_pixel_sizes(0, size)
    return face


def _round26(value: int) -> int:
    """26.6 fixed point -> integer pixels."""
    return (value + 32) >> 6


@cache
def _glyph(key: str, size: int, char: str) -> Glyph | None:
    face = _face(key, size)
    if face.get_char_index(char) == 0:
        return None
    face.load_char(char, freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_MONO)
    slot = face.glyph
    bitmap = slot.bitmap
    width, height, pitch = bitmap.width, bitmap.rows, abs(bitmap.pitch)
    stride = (width + 7) // 8
    data = bytes(bitmap.buffer)
    rows = b"".join(data[r * pitch : r * pitch + stride] for r in range(height))
    return Glyph(
        char=char,
        width=width,
        height=height,
        left=slot.bitmap_left,
        top=slot.bitmap_top,
        advance=_round26(slot.advance.x),
        rows=rows,
    )


def has_glyph(key: str, char: str) -> bool:
    return bool(_face(key, 16).get_char_index(char) != 0)


@cache
def _metrics(key: str, size: int) -> tuple[int, int]:
    metrics = _face(key, size).size
    return _round26(metrics.ascender), _round26(-metrics.descender)


def rasterize(key: str, size: int, chars: Iterable[str]) -> BitmapFont:
    """Glyphs for ``chars`` (those the font has; '?' is always included)."""
    ascent, descent = _metrics(key, size)
    glyphs = {}
    for char in sorted(set(chars) | {REPLACEMENT}):
        glyph = _glyph(key, size, char)
        if glyph is not None:
            glyphs[char] = glyph
    return BitmapFont(key, size, ascent, descent, MappingProxyType(glyphs))
