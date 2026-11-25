"""Software renderer of a page: what the display shows, pixel for pixel.

The GUI preview and the tests use it. Values and texts come from
``core.evaluate``, glyphs from ``assets.fonts`` (the bitmaps ui_fonts.py is
built from), pictures from ``assets.images`` (the conversion the generator
uses), the layout follows the mock-up (``docs/plan.html``). Tests on the
MicroPython unix port compare the board's frames with this renderer, so the
preview is checked against the generated code.
"""

from __future__ import annotations

import math
import struct
import zlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from espui.assets.fonts import BitmapFont, rasterize
from espui.assets.images import decode, render, to_rgb565
from espui.core.colors import from_rgb565, to_wire
from espui.core.evaluate import (
    EffectiveWidget,
    ParameterValues,
    chart_label_indices,
    chart_y_range,
    effective,
    number_label,
)
from espui.core.models import (
    ChartSettings,
    ImageAsset,
    Page,
    ParamValue,
    SeriesParameter,
    SeriesPoint,
    Widget,
)
from espui.i18n import tr


@dataclass
class Canvas:
    width: int
    height: int
    pixels: list[int]

    @classmethod
    def filled(cls, width: int, height: int, color: int) -> Canvas:
        return cls(width, height, [color] * (width * height))

    @classmethod
    def from_wire_bytes(cls, width: int, height: int, data: bytes) -> Canvas:
        return cls(width, height, list(struct.unpack(f"<{width * height}H", data)))

    def set(self, x: int, y: int, color: int) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            self.pixels[y * self.width + x] = color

    def get(self, x: int, y: int) -> int:
        return self.pixels[y * self.width + x]

    def fill_where(self, box: tuple[int, int, int, int], color: int, inside: Any) -> None:
        x0, y0, w, h = box
        for y in range(y0, y0 + h):
            for x in range(x0, x0 + w):
                if inside(x, y):
                    self.set(x, y, color)

    def mismatch(self, other: Canvas, box: tuple[int, int, int, int] | None = None) -> float:
        x0, y0, w, h = box or (0, 0, self.width, self.height)
        x1, y1 = min(x0 + w, self.width), min(y0 + h, self.height)
        x0, y0 = max(x0, 0), max(y0, 0)
        total = max(1, (x1 - x0) * (y1 - y0))
        bad = sum(
            1 for y in range(y0, y1) for x in range(x0, x1) if self.get(x, y) != other.get(x, y)
        )
        return bad / total

    def save_png(self, path: Path, scale: int = 2) -> Path:
        rows = []
        for y in range(self.height):
            row = bytearray()
            for x in range(self.width):
                v = self.get(x, y)
                rgb = from_rgb565(((v & 0xFF) << 8) | (v >> 8))  # wire order -> RGB565
                row += bytes(rgb) * scale
            rows += [b"\x00" + bytes(row)] * scale

        def chunk(kind: bytes, data: bytes) -> bytes:
            crc = zlib.crc32(kind + data) & 0xFFFFFFFF
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

        header = struct.pack(">IIBBBBB", self.width * scale, self.height * scale, 8, 2, 0, 0, 0)
        path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(b"".join(rows)))
            + chunk(b"IEND", b"")
        )
        return path


# ------------------------------------------------------------------ rotation
Rot = tuple[float, float, float, float] | None
"""(cos, sin, pivot_x, pivot_y), clockwise on screen; None = not rotated."""


def make_rot(angle: float, pivot: tuple[float, float]) -> Rot:
    a = angle % 360
    if a == 0:
        return None
    rad = math.radians(a)
    return (math.cos(rad), math.sin(rad), pivot[0], pivot[1])


def fwd(r: Rot, x: float, y: float) -> tuple[float, float]:
    if r is None:
        return x, y
    c, s, px, py = r
    return px + (x - px) * c - (y - py) * s, py + (x - px) * s + (y - py) * c


def inv(r: Rot, x: float, y: float) -> tuple[float, float]:
    if r is None:
        return x, y
    c, s, px, py = r
    return px + (x - px) * c + (y - py) * s, py - (x - px) * s + (y - py) * c


def fwd_int(r: Rot, x: float, y: float) -> tuple[int, int]:
    fx, fy = fwd(r, x, y)
    return math.floor(fx + 0.5), math.floor(fy + 0.5)


def scan_box(
    r: Rot, x: float, y: float, w: float, h: float, margin: int = 2
) -> tuple[int, int, int, int]:
    pts = [fwd(r, px, py) for px, py in ((x, y), (x + w, y), (x + w, y + h), (x, y + h))]
    x0 = math.floor(min(p[0] for p in pts)) - margin
    y0 = math.floor(min(p[1] for p in pts)) - margin
    x1 = math.ceil(max(p[0] for p in pts)) + margin
    y1 = math.ceil(max(p[1] for p in pts)) + margin
    return x0, y0, x1 - x0, y1 - y0


# ------------------------------------------------------------------ shapes
def _rrect(c: Canvas, x: int, y: int, w: int, h: int, r: int, color: int, rot: Rot = None) -> None:
    if w <= 0 or h <= 0:
        return
    if rot is not None:  # rotated: a plain quad (corners are not rounded)

        def inside_rotated(px: int, py: int) -> bool:
            u, v = inv(rot, px + 0.5, py + 0.5)
            return x <= u <= x + w and y <= v <= y + h

        c.fill_where(scan_box(rot, x, y, w, h), color, inside_rotated)
        return
    r = min(r, w // 2, h // 2)
    corners = (
        (x + r, y + r),
        (x + w - 1 - r, y + r),
        (x + r, y + h - 1 - r),
        (x + w - 1 - r, y + h - 1 - r),
    )

    def inside(px: int, py: int) -> bool:
        cx = corners[0][0] if px < x + r else corners[1][0] if px > x + w - 1 - r else px
        cy = corners[0][1] if py < y + r else corners[2][1] if py > y + h - 1 - r else py
        return (px - cx) ** 2 + (py - cy) ** 2 <= r * r + r

    c.fill_where((x, y, w, h), color, inside)


def _ellipse(c: Canvas, x: int, y: int, w: int, h: int, color: int, rot: Rot = None) -> None:
    rx, ry = max((w - 1) // 2, 0), max((h - 1) // 2, 0)
    cx, cy = fwd_int(rot, x + rx, y + ry)

    def inside(px: int, py: int) -> bool:
        if rx == 0 or ry == 0:
            return px == cx or py == cy
        return ((px - cx) / (rx + 0.5)) ** 2 + ((py - cy) / (ry + 0.5)) ** 2 <= 1

    c.fill_where((cx - rx - 1, cy - ry - 1, 2 * rx + 3, 2 * ry + 3), color, inside)


def _segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _line(c: Canvas, x: int, y: int, w: int, h: int, color: int, rot: Rot = None) -> None:
    x0, y0 = fwd_int(rot, x, y)
    x1, y1 = fwd_int(rot, x + w, y + h)
    ox, oy = (0, 1) if abs(x1 - x0) >= abs(y1 - y0) else (1, 0)

    def inside(px: int, py: int) -> bool:
        return (
            _segment_distance(px, py, x0, y0, x1, y1) <= 0.5
            or _segment_distance(px, py, x0 + ox, y0 + oy, x1 + ox, y1 + oy) <= 0.5
        )

    box = (min(x0, x1) - 1, min(y0, y1) - 1, abs(x1 - x0) + 3, abs(y1 - y0) + 3)
    c.fill_where(box, color, inside)


def bitmap_font(widget: Widget, text: str, size: int | None = None) -> BitmapFont:
    """Glyphs of the widget's font for ``text`` (plus '…' and '?')."""
    return rasterize(widget.font or "serif", size or widget.font_size or 16, text + "…?")


def _text_pixels(bf: BitmapFont, s: str) -> set[tuple[int, int]]:
    """Set pixels of ``s`` relative to (pen x, baseline)."""
    out = set()
    pen = 0
    for ch in s:
        g = bf.glyph(ch)
        if g is None:
            continue
        for gy in range(g.height):
            for gx in range(g.width):
                if g.pixel(gx, gy):
                    out.add((pen + g.left + gx, gy - g.top))
        pen += g.advance
    return out


def _text(
    c: Canvas, bf: BitmapFont, s: str, x: int, base: int, color: int, rot: Rot = None
) -> None:
    if not s:
        return
    pixels = _text_pixels(bf, s)
    if rot is None:
        for px, py in pixels:
            c.set(x + px, base + py, color)
        return
    top = base - bf.ascent
    tw, th = bf.width(s), bf.height

    def inside(px: int, py: int) -> bool:
        u, v = inv(rot, px + 0.5, py + 0.5)
        uu, vv = math.floor(u - x), math.floor(v - top)
        return 0 <= uu < tw and 0 <= vv < th and (uu, vv - bf.ascent) in pixels

    c.fill_where(scan_box(rot, x, top, tw, th), color, inside)


def _ring(
    c: Canvas, cx: int, cy: int, r: int, a1: float, color: int, width: int, rot: Rot = None
) -> None:
    ri, ro = r - width // 2, r + width // 2

    def inside(px: int, py: int) -> bool:
        u, v = inv(rot, px, py)
        if v > cy + 0.5:
            return False
        d = math.hypot(u - cx, v - cy)
        if not ri - 0.5 <= d <= ro + 0.5:
            return False
        return math.atan2(cy - v, cx - u) <= a1 + 0.02

    c.fill_where(scan_box(rot, cx - ro, cy - ro, 2 * ro, ro), color, inside)


# ------------------------------------------------------------------ opacity
def alpha_level(opacity: float) -> int:
    return 0 if opacity <= 0 else 32 if opacity >= 100 else int(opacity * 32 / 100 + 0.5)


def _to565(wire: int) -> int:
    return ((wire & 0xFF) << 8) | (wire >> 8)


def blend_wire(fg: int, bg: int, level: int) -> int:
    f, b = _to565(fg), _to565(bg)
    channels = []
    for shift, mask in ((11, 31), (5, 63), (0, 31)):
        cf, cb = (f >> shift) & mask, (b >> shift) & mask
        channels.append(((cf * level + cb * (32 - level) + 16) >> 5) << shift)
    v = channels[0] | channels[1] | channels[2]
    return ((v & 0xFF) << 8) | (v >> 8)


# ------------------------------------------------------------------ page
@dataclass
class Pictures:
    """What image widgets need: the project library, the page background, animation frames."""

    library: Mapping[str, ImageAsset]
    background: str
    frames: Mapping[str, int]


ARC_WIDTH = 7


def arc_geometry(x: int, y: int, w: int, h: int) -> tuple[int, int, int]:
    """(cx, cy, r) of an arc widget: a half ring standing on the box bottom (ui_draw)."""
    r = min(w // 2, h) - 5
    return x + w // 2, y + h - 2, r if r > 6 else 6


def render_page(
    page: Page,
    size: tuple[int, int],
    overrides: Mapping[str, ParamValue] | None = None,
    images: Mapping[str, ImageAsset] | None = None,
    frames: Mapping[str, int] | None = None,
) -> Canvas:
    """Render ``page`` with parameter ``overrides`` (else test values / defaults).

    ``frames``: current frame of each animated image widget (default 0).
    """
    width, height = size
    canvas = Canvas.filled(width, height, to_wire(page.background))
    values = ParameterValues.for_page(page, overrides)
    pictures = Pictures(images or {}, page.background, frames or {})
    for widget in page.widgets:
        _widget(canvas, widget, values, pictures)
    return canvas


def _widget(c: Canvas, widget: Widget, values: ParameterValues, pictures: Pictures) -> None:
    e = effective(widget, values)
    if not e.visible:
        return
    level = alpha_level(e.opacity)
    if level == 0:
        return
    target = Canvas(c.width, c.height, list(c.pixels)) if level < 32 else c
    if e.type == "image":
        _image(target, widget, e, pictures)
    else:
        _draw(target, widget, values, e)
    if level < 32:
        c.pixels = [
            old if new == old else blend_wire(new, old, level)
            for new, old in zip(target.pixels, c.pixels, strict=True)
        ]


def _draw(c: Canvas, widget: Widget, values: ParameterValues, e: Any) -> None:
    x, y, w, h = e.bounds
    color = to_wire(e.color)
    rot = make_rot(e.angle, e.pivot)
    param = values.param(widget.bind)
    if e.type == "rect":
        _rrect(c, x, y, w, h, 4, color, rot)
    elif e.type == "circle":
        _ellipse(c, x, y, w, h, color, rot)
    elif e.type == "line":
        _line(c, x, y, w, h, color, rot)
    elif e.type in ("text", "value"):
        bf = bitmap_font(widget, e.text or "")
        text = bf.fit(e.text or "", w)
        tw = bf.width(text)
        tx = x + {"left": 0, "center": (w - tw) // 2, "right": w - tw}[widget.align]
        _text(c, bf, text, tx, y + (h * 4) // 5, color, rot)
    elif e.type == "bar":
        number = number_label(param, e.value) if param is not None and widget.show_value else ""
        bf = bitmap_font(widget, (e.text or "") + number)
        f = e.fraction if e.fraction is not None else 0.5
        th = 14 if h >= 16 else h
        ty = y + h - 16 if h >= 16 else y
        fw = int(w * f + 0.5)
        base = y + bf.size
        _text(c, bf, bf.fit(e.text or "", w), x, base, to_wire("#8fa3ad"), rot)
        if number:
            number = bf.fit(number, w)
            _text(c, bf, number, x + w - bf.width(number), base, to_wire("#ffffff"), rot)
        if widget.show_track:
            _rrect(c, x, ty, w, th, 3, to_wire(widget.track_color), rot)
        _rrect(c, x, ty, fw, th, 3, color, rot)
    elif e.type == "chart":
        _chart(c, widget, values, e, color)
    elif e.type == "arc":
        f = e.fraction if e.fraction is not None else 0.6
        cx, cy, r = arc_geometry(x, y, w, h)
        if widget.show_track:
            _ring(c, cx, cy, r, math.pi, to_wire(widget.track_color), ARC_WIDTH, rot)
        if f > 0:
            _ring(c, cx, cy, r, math.pi * f, color, ARC_WIDTH, rot)
        if e.text and widget.show_value:
            bf = bitmap_font(widget, e.text)
            s = bf.fit(e.text, w)
            _text(c, bf, s, cx - bf.width(s) // 2, cy - 4, to_wire("#ffffff"), rot)


# ------------------------------------------------------------------ chart
def _tick(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:.1f}"


def _hline(c: Canvas, x: int, y: int, w: int, color: int) -> None:
    for xx in range(x, x + w):
        c.set(xx, y, color)


def _chart(
    c: Canvas, widget: Widget, values: ParameterValues, e: EffectiveWidget, color: int
) -> None:
    """The mock-up's chart (docs/plan.html); labels in the widget's font at 8 px."""
    x, y, w, h = e.bounds
    settings = widget.chart or ChartSettings()
    param = values.param(widget.bind)
    series = param if isinstance(param, SeriesParameter) else None
    numeric = series is None or series.x_kind == "number"
    pts: list[SeriesPoint] = (
        list(e.value) if series is not None and isinstance(e.value, list) else []
    )
    if numeric:
        pts.sort(key=lambda q: float(q.x))
    lo, hi = chart_y_range(settings, series, pts)
    label, axis = to_wire("#8fa3ad"), to_wire("#56707c")
    _rrect(c, x, y, w, h, 3, to_wire("#10222c"))
    labels = [
        str(int(q.x)) if isinstance(q.x, float) and q.x.is_integer() else str(q.x) for q in pts
    ]
    bf = bitmap_font(
        widget,
        "".join(labels)
        + _tick(lo)
        + _tick(hi)
        + settings.axis_x
        + settings.axis_y
        + tr("немає даних"),
        8,
    )
    lw = max(bf.width(_tick(lo)), bf.width(_tick(hi))) + 4
    left, right = x + lw, x + w - 3
    top = y + (11 if settings.axis_y else 4)
    bottom = y + h - 10 - (9 if settings.axis_x else 0)
    if bottom - top < 6 or right - left < 10:
        return

    def my(v: float) -> int:
        f = max(0.0, min(1.0, (v - lo) / (hi - lo)))
        return math.floor(bottom - (bottom - top) * f + 0.5)

    if settings.grid:
        for f in (0.0, 0.5, 1.0):
            _hline(
                c,
                left,
                math.floor(bottom - (bottom - top) * f + 0.5),
                right - left + 1,
                to_wire("#1f3340"),
            )
    for yy in range(top, bottom + 1):
        c.set(left, yy, axis)
    _hline(c, left, bottom, right - left + 1, axis)
    for text, base in ((_tick(hi), top + 3), (_tick(lo), bottom)):
        _text(c, bf, text, left - 2 - bf.width(text), base, label)
    if settings.axis_y:
        _text(c, bf, bf.fit(settings.axis_y, w), left + 3, y + 8, label)
    if settings.axis_x:
        ax = bf.fit(settings.axis_x, w)
        _text(c, bf, ax, right - bf.width(ax), y + h - 2, label)
    n = len(pts)
    if not n:
        nd = tr("немає даних")
        _text(c, bf, nd, (left + right) // 2 - bf.width(nd) // 2, (top + bottom) // 2, label)
        return
    bars = settings.style == "bars"
    bw = (right - left) / n
    xv = [float(q.x) if numeric else k for k, q in enumerate(pts)]
    x0, x1 = xv[0], xv[-1]
    xs = [
        left + bw * (k + 0.5) if bars
        else (left + right) / 2 if x1 == x0
        else left + 4 + (right - left - 8) * (xv[k] - x0) / (x1 - x0)
        for k in range(n)
    ]  # fmt: skip
    ks = chart_label_indices(n, w)
    for i, k in enumerate(ks):
        text = labels[k]
        tw = bf.width(text)
        if len(ks) > 1 and i == 0 and not bars:
            tx = xs[k]
        elif len(ks) > 1 and i == len(ks) - 1 and not bars:
            tx = xs[k] - tw
        else:
            tx = xs[k] - tw / 2
        _text(c, bf, text, math.floor(tx + 0.5), bottom + 8, label)
    if bars:
        bar_w = max(1, math.floor(bw * 0.7 + 0.5))
        for k in range(n):
            yy = my(pts[k].y)
            bx = math.floor(xs[k] - bw * 0.35 + 0.5)
            for py in range(yy, bottom):
                _hline(c, bx, py, bar_w, color)
        return
    prev = None
    for k in range(n):
        cur = (math.floor(xs[k] + 0.5), my(pts[k].y))
        if prev is not None:
            p0, p1 = prev, cur

            def on_line(px: int, py: int, a: tuple[int, int] = p0, b: tuple[int, int] = p1) -> bool:
                return _segment_distance(px, py, a[0], a[1], b[0], b[1]) <= 0.5

            box = (
                min(p0[0], p1[0]),
                min(p0[1], p1[1]),
                abs(p1[0] - p0[0]) + 1,
                abs(p1[1] - p0[1]) + 1,
            )
            c.fill_where(box, color, on_line)
        if settings.style == "dots":
            _ellipse(c, cur[0] - 2, cur[1] - 2, 5, 5, color)
        prev = cur


# ------------------------------------------------------------------ images
def _missing(c: Canvas, x: int, y: int, w: int, h: int) -> None:
    fill, border = to_wire("#13252f"), to_wire("#56707c")
    for yy in range(y, y + h):
        for xx in range(x, x + w):
            edge = xx in (x, x + w - 1) or yy in (y, y + h - 1)
            c.set(xx, yy, border if edge else fill)


ROT_ONE = 65536
"""Fixed point of a turned picture: the same 16.16 terms as ui_draw.rotation_terms."""


def rotation_terms(rot: tuple[float, float, float, float], x: int, y: int) -> tuple[int, ...]:
    """(ku, kv, c, s): screen pixel (X, Y) shows picture pixel
    (``(ku + X*c + Y*s) >> 16``, ``(kv - X*s + Y*c) >> 16``) — as on the board."""
    c, s, px, py = rot
    ku = px - x + (0.5 - px) * c + (0.5 - py) * s
    kv = py - y - (0.5 - px) * s + (0.5 - py) * c
    return tuple(math.floor(v * ROT_ONE + 0.5) for v in (ku, kv, c, s))


def _image_rotated(c: Canvas, x: int, y: int, w: int, h: int, data: bytes, rot: Rot) -> None:
    assert rot is not None
    ku, kv, cu, su = rotation_terms(rot, x, y)
    bx, by, bw, bh = scan_box(rot, x, y, w, h)
    for yy in range(max(by, 0), min(by + bh, c.height)):
        for xx in range(max(bx, 0), min(bx + bw, c.width)):
            u = (ku + xx * cu + yy * su) >> 16
            v = (kv - xx * su + yy * cu) >> 16
            if 0 <= u < w and 0 <= v < h:
                k = 2 * (v * w + u)
                c.set(xx, yy, int.from_bytes(data[k : k + 2], "little"))


def _image(c: Canvas, widget: Widget, e: EffectiveWidget, pictures: Pictures) -> None:
    """The library picture fitted into the box (the board shows the converted file).

    A turned picture is sampled like on the board: every screen pixel takes the
    picture pixel under its centre turned back around the pivot.
    """
    x, y, w, h = e.bounds
    rot = make_rot(e.angle, e.pivot)
    settings = widget.image
    asset = None
    if widget.bind:
        path = e.image_source
        asset = next((a for a in pictures.library.values() if a.path == path), None)
    elif settings is not None and settings.file:
        asset = pictures.library.get(settings.file)
    if asset is None:
        if rot is None:
            _missing(c, x, y, w, h)
        else:  # a turned grey box (no border), as ui_draw.image
            _rrect(c, x, y, w, h, 0, to_wire("#13252f"), rot)
        return
    frames = decode(asset)
    frame = frames[min(pictures.frames.get(widget.id, 0), len(frames) - 1)]
    fit = settings.fit if settings is not None else "contain"
    data = to_rgb565(render(frame, w, h, fit, pictures.background))
    if rot is not None:
        _image_rotated(c, x, y, w, h, data, rot)
        return
    for i in range(w * h):
        c.set(x + i % w, y + i // w, int.from_bytes(data[2 * i : 2 * i + 2], "little"))
