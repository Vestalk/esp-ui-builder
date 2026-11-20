"""Colours: ``#rrggbb`` strings in the project, RGB565 on the device.

On the device every colour is RGB565 in *wire order* (bytes swapped in
advance, see ``runtime/ui_st7789.py`` and ``docs/benchmarks.md``):
:func:`to_wire` here and ``ui_st7789.color()`` there must agree.
"""

from __future__ import annotations

import re
from typing import NamedTuple

HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class RGB(NamedTuple):
    r: int
    g: int
    b: int


def is_hex(value: str) -> bool:
    return bool(HEX_RE.fullmatch(value))


def normalize_hex(value: str) -> str:
    """``#ABC`` / ``#AaBbCc`` -> ``#aabbcc``; ValueError if not a hex colour."""
    if not is_hex(value):
        raise ValueError(f"колір має бути у форматі #rrggbb, отримано {value!r}")
    digits = value[1:].lower()
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return "#" + digits


def parse_hex(value: str) -> RGB:
    digits = normalize_hex(value)[1:]
    return RGB(int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16))


def to_hex(rgb: RGB | tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(_channel(c) for c in rgb))


def _channel(value: int) -> int:
    return max(0, min(255, int(value)))


def rgb565(rgb: RGB | tuple[int, int, int]) -> int:
    r, g, b = (_channel(c) for c in rgb)
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def swap16(value: int) -> int:
    return ((value & 0xFF) << 8) | ((value >> 8) & 0xFF)


def to_wire(color: str) -> int:
    """``#rrggbb`` -> RGB565 with swapped bytes, as used by the device runtime."""
    return swap16(rgb565(parse_hex(color)))


def from_rgb565(value: int) -> RGB:
    """RGB565 -> 8-bit channels (low bits replicated, so white stays white)."""
    r5, g6, b5 = (value >> 11) & 0x1F, (value >> 5) & 0x3F, value & 0x1F
    return RGB((r5 << 3) | (r5 >> 2), (g6 << 2) | (g6 >> 4), (b5 << 3) | (b5 >> 2))


def quantize(color: str) -> str:
    """What the panel actually shows for ``color`` (RGB565 precision)."""
    return to_hex(from_rgb565(rgb565(parse_hex(color))))


def blend(fg: str, bg: str, alpha: float) -> str:
    """Alpha-blend ``fg`` over ``bg``; ``alpha`` 0..1 (clamped)."""
    a = max(0.0, min(1.0, alpha))
    f, b = parse_hex(fg), parse_hex(bg)
    return to_hex(RGB(*(round(fc * a + bc * (1 - a)) for fc, bc in zip(f, b, strict=True))))
