# ui_draw — drawing helpers and the page engine of ESP UI Builder.
#
# Copied unchanged into every generated project. Generated pages
# (ui_<page>.py) subclass `Page` and only describe their widgets; this module
# does the rest: region rendering in a bounded framebuf, dirty tracking,
# overlap handling (every widget that intersects a dirty region is redrawn in
# layer order) and the primitives below.
#
# Colours are RGB565 in wire order (bytes pre-swapped, see ui_st7789.color).
# Layout helpers (label_origin, bar_layout, arc_geometry, rot, rbox, blend565, ...)
# are pure functions that also run on CPython: tests use them to build the
# reference image.
#
# Transforms (stage 05): every primitive takes an optional ``r`` = rot(...)
# (rotation around an absolute pivot); opacity is applied by the engine
# (Page.begin_alpha / end_alpha) by blending a layer over the strip.

try:
    import framebuf
except ImportError:  # CPython: only the pure layout helpers are usable
    framebuf = None

import json
import os
from array import array

try:
    from time import ticks_diff, ticks_ms
except ImportError:  # CPython (layout tests)
    from time import monotonic

    def ticks_ms():
        return int(monotonic() * 1000)

    def ticks_diff(a, b):
        return a - b


from math import ceil, cos, floor, pi, sin

BUF_BYTES = 16384
"""Default region buffer: <= 32 KB without PSRAM (docs/benchmarks.md)."""

# Text is drawn with the project's bitmap fonts (ui_fonts.Font objects passed in
# by the generated page): text(fb, s, x, base, color, font) puts the baseline at
# ``base``. Fonts carry only the glyphs the page needs; anything else is '?'.
LEFT = 0
CENTER = 1
RIGHT = 2

# Colours the mock-up uses for widget decorations (wire order).
LABEL_COLOR = 0x158D  # #8fa3ad
VALUE_COLOR = 0xFFFF  # #ffffff
TRACK_COLOR = 0xA721  # #23343f
ARC_WIDTH = 7
ALPHA_LEVELS = 32  # opacity is blended in 1/32 steps (RGB565 has 5-6 bits per channel)


# ------------------------------------------------------------------ values
def fmt(f, v):
    """printf subset, the same as espui.core.evaluate.format_value."""
    out = []
    i = 0
    n = len(f)
    while i < n:
        c = f[i]
        if c != "%":
            out.append(c)
            i += 1
            continue
        j = i + 1
        digits = None
        if j < n and f[j] == ".":
            k = j + 1
            while k < n and "0" <= f[k] <= "9":
                k += 1
            if k > j + 1 and k < n and f[k] in "fds%":
                digits = int(f[j + 1 : k])
                j = k
        if j >= n or f[j] not in "fds%":
            out.append("%")
            i += 1
            continue
        kind = f[j]
        if kind == "%":
            out.append("%")
        elif kind == "s" or isinstance(v, bool) or not isinstance(v, (int, float)):
            out.append(str(v))
        elif kind == "d":
            out.append(str(int(floor(v + 0.5))))
        else:
            out.append(("%." + str(6 if digits is None else digits) + "f") % v)
        i = j + 1
    return "".join(out)


def num(v, is_float):
    """Number shown by bars and arcs: one decimal for float, as is otherwise."""
    if is_float and isinstance(v, (int, float)) and not isinstance(v, bool):
        return "%.1f" % v
    return str(v)


def frac(v, lo, hi):
    """Position of ``v`` in lo..hi, clamped to 0..1."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return 0.0
    f = (v - lo) / (hi - lo)
    return 0.0 if f < 0 else 1.0 if f > 1 else f


def label_origin(x, y, w, h, tw, align):
    """(x, baseline) of a text line of width ``tw`` in a box: baseline at 80 % height."""
    if align == CENTER:
        x += (w - tw) // 2
    elif align == RIGHT:
        x += w - tw
    return x, y + (h * 4) // 5


def bar_layout(x, y, w, h, f, size):
    """(track_y, track_h, fill_w, label_baseline) of a progress bar (font ``size`` px)."""
    th = 14 if h >= 16 else h
    ty = y + h - 16 if h >= 16 else y
    fw = int(w * f + 0.5)
    return ty, th, fw, y + size


def arc_geometry(x, y, w, h):
    """(cx, cy, r) of an arc widget: a half ring standing on the box bottom."""
    r = min(w // 2, h) - 5
    return x + w // 2, y + h - 2, r if r > 6 else 6


def arc_point(cx, cy, r, a):
    """Point at angle ``a`` (0 = left, pi/2 = top, pi = right)."""
    return cx - r * cos(a), cy - r * sin(a)


def intersects(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def clip(r, width, height):
    x0 = r[0] if r[0] > 0 else 0
    y0 = r[1] if r[1] > 0 else 0
    x1 = r[0] + r[2]
    y1 = r[1] + r[3]
    x1 = x1 if x1 < width else width
    y1 = y1 if y1 < height else height
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1 - x0, y1 - y0)


def merge(rects):
    """Union overlapping rectangles so that no pixel is sent twice."""
    out = []
    for r in rects:
        i = 0
        while i < len(out):
            o = out[i]
            if intersects(o, r):
                x0 = o[0] if o[0] < r[0] else r[0]
                y0 = o[1] if o[1] < r[1] else r[1]
                x1 = max(o[0] + o[2], r[0] + r[2])
                y1 = max(o[1] + o[3], r[1] + r[3])
                r = (x0, y0, x1 - x0, y1 - y0)
                out.pop(i)
                i = 0
            else:
                i += 1
        out.append(r)
    return out


# ------------------------------------------------------------------ transforms (pure)
def lin(v, lo, hi, a, b):
    """Linear mapping lo -> a, hi -> b, clamped (core.evaluate.lin)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return a
    f = (v - lo) / (hi - lo)
    f = 0.0 if f < 0 else 1.0 if f > 1 else f
    return a + (b - a) * f


def rnd(v):
    """Half-up rounding used for pixels (core.evaluate.round_half_up)."""
    return int(floor(v + 0.5))


def alpha(opacity):
    """Opacity 0..100 % -> blend level 0..ALPHA_LEVELS."""
    if opacity <= 0:
        return 0
    if opacity >= 100:
        return ALPHA_LEVELS
    return int(opacity * ALPHA_LEVELS / 100 + 0.5)


def rot(angle, px, py):
    """Rotation by ``angle`` degrees (clockwise on screen) around (px, py); None for 0."""
    a = angle % 360
    if a == 0:
        return None
    rad = a * pi / 180
    return (cos(rad), sin(rad), px, py)


def tp(r, x, y):
    """Rotate point (x, y) with ``r``; returns floats."""
    c, s, px, py = r
    dx = x - px
    dy = y - py
    return px + dx * c - dy * s, py + dx * s + dy * c


def tpi(r, x, y):
    tx, ty = tp(r, x, y)
    return int(floor(tx + 0.5)), int(floor(ty + 0.5))


def rbox(x, y, w, h, angle, px, py):
    """Bounding box of the box (x, y, w, h) rotated around (px, py), 1 px margin."""
    r = rot(angle, px, py)
    if r is None:
        return (x, y, w, h)
    return _rbox_r(r, x, y, w, h)


def blend565(fg, bg, a):
    """Blend two RGB565 values (true order); ``a`` in 0..ALPHA_LEVELS."""
    b = ALPHA_LEVELS - a
    h = ALPHA_LEVELS // 2
    r5 = ((fg >> 11) * a + (bg >> 11) * b + h) >> 5
    g6 = (((fg >> 5) & 63) * a + ((bg >> 5) & 63) * b + h) >> 5
    b5 = ((fg & 31) * a + (bg & 31) * b + h) >> 5
    return (r5 << 11) | (g6 << 5) | b5


def _blend_rect_py(dst, src, sw, x0, y0, x1, y1, a):
    """Blend the pixels that differ in ``src`` (layer) over ``dst`` (strip), wire order."""
    for yy in range(y0, y1):
        o = 2 * (yy * sw + x0)
        for _ in range(x0, x1):
            l0 = src[o]
            l1 = src[o + 1]
            d0 = dst[o]
            d1 = dst[o + 1]
            if l0 != d0 or l1 != d1:
                # framebuf keeps wire-order values little-endian: byte 0 = high byte.
                v = blend565((l0 << 8) | l1, (d0 << 8) | d1, a)
                dst[o] = v >> 8
                dst[o + 1] = v & 0xFF
            o += 2


# The same loop compiled to machine code (~30x faster on ESP32). Compiled from a
# string so that a port without the native emitter just keeps the Python loop.
_BLEND_VIPER = """
@micropython.viper
def blend_rect(dst, src, sw: int, x0: int, y0: int, x1: int, y1: int, a: int):
    d = ptr8(dst)
    s = ptr8(src)
    b = 32 - a
    yy = y0
    while yy < y1:
        o = 2 * (yy * sw + x0)
        e = o + 2 * (x1 - x0)
        while o < e:
            l0 = s[o]
            l1 = s[o + 1]
            d0 = d[o]
            d1 = d[o + 1]
            if l0 != d0 or l1 != d1:
                fg = (l0 << 8) | l1
                bg = (d0 << 8) | d1
                r5 = ((fg >> 11) * a + (bg >> 11) * b + 16) >> 5
                g6 = (((fg >> 5) & 63) * a + ((bg >> 5) & 63) * b + 16) >> 5
                b5 = ((fg & 31) * a + (bg & 31) * b + 16) >> 5
                v = (r5 << 11) | (g6 << 5) | b5
                d[o] = v >> 8
                d[o + 1] = v & 0xFF
            o += 2
        yy += 1
"""
try:
    import micropython

    _ns = {"micropython": micropython}
    exec(_BLEND_VIPER, _ns)
    blend_rect = _ns["blend_rect"]
except Exception:  # no native emitter (or not MicroPython): the Python loop
    blend_rect = _blend_rect_py


# ------------------------------------------------------------------ primitives
_clip = [0, 0]  # size of the strip being drawn (set by Page._render)
_quad = array("h", [0] * 8)


def text(fb, s, x, base, c, font, r=None):
    """Draw text with its baseline at ``base`` (rotated around r's pivot if given)."""
    if not s:
        return
    if r is None:
        font.draw(fb, s, x, base, c)
    else:
        _text_rotated(fb, s, x, base - font.ascent, c, font, r)


def _text_rotated(fb, s, x, y, c, font, r):
    """Per-pixel inverse mapping (slow: the generator warns about big dynamic texts)."""
    g, tw, th = font.mono(s)
    bx, by, bw, bh = _rbox_r(r, x, y, tw, th)
    x0 = bx if bx > 0 else 0
    y0 = by if by > 0 else 0
    x1 = bx + bw if bx + bw < _clip[0] else _clip[0]
    y1 = by + bh if by + bh < _clip[1] else _clip[1]
    co, si, px, py = r
    pixel = g.pixel
    for sy in range(y0, y1):
        dy = sy + 0.5 - py
        for sx in range(x0, x1):
            dx = sx + 0.5 - px
            u = int(floor(px + dx * co + dy * si - x))
            v = int(floor(py - dx * si + dy * co - y))
            if 0 <= u < tw and 0 <= v < th and pixel(u, v):
                fb.pixel(sx, sy, c)


def _rbox_r(r, x, y, w, h):
    xs = []
    ys = []
    for cx, cy in ((x, y), (x + w, y), (x + w, y + h), (x, y + h)):
        tx, ty = tp(r, cx, cy)
        xs.append(tx)
        ys.append(ty)
    x0 = int(floor(min(xs))) - 1
    y0 = int(floor(min(ys))) - 1
    return (x0, y0, int(ceil(max(xs))) + 2 - x0, int(ceil(max(ys))) + 2 - y0)


def label(fb, s, x, y, w, h, c, font, align=LEFT, r=None):
    """Text widget / value: cut with '…' to the box width, baseline at 80 % height."""
    s = font.fit(s, w)
    tx, base = label_origin(x, y, w, h, font.width(s), align)
    text(fb, s, tx, base, c, font, r)


def _poly(fb, r, pts, c):
    q = _quad
    for i in range(4):
        q[2 * i], q[2 * i + 1] = tpi(r, pts[2 * i], pts[2 * i + 1])
    fb.poly(0, 0, q, c, True)


def rrect(fb, x, y, w, h, rad, c, r=None):
    """Filled rectangle with rounded corners (a plain rotated quad when ``r`` is set)."""
    if w <= 0 or h <= 0:
        return
    if r is not None:
        _poly(fb, r, (x, y, x + w, y, x + w, y + h, x, y + h), c)
        return
    rad = min(rad, w // 2, h // 2)
    if rad <= 0:
        fb.fill_rect(x, y, w, h, c)
        return
    fb.fill_rect(x + rad, y, w - 2 * rad, h, c)
    fb.fill_rect(x, y + rad, rad, h - 2 * rad, c)
    fb.fill_rect(x + w - rad, y + rad, rad, h - 2 * rad, c)
    fb.ellipse(x + rad, y + rad, rad, rad, c, True, 2)
    fb.ellipse(x + w - 1 - rad, y + rad, rad, rad, c, True, 1)
    fb.ellipse(x + rad, y + h - 1 - rad, rad, rad, c, True, 4)
    fb.ellipse(x + w - 1 - rad, y + h - 1 - rad, rad, rad, c, True, 8)


def ellipse(fb, x, y, w, h, c, r=None):
    """Filled ellipse; rotation only moves its centre (the axes stay upright)."""
    rx = (w - 1) // 2
    ry = (h - 1) // 2
    cx = x + rx
    cy = y + ry
    if r is not None:
        cx, cy = tpi(r, cx, cy)
    fb.ellipse(cx, cy, rx, ry, c, True)


def line(fb, x, y, w, h, c, r=None):
    """2 px line from (x, y) to (x + w, y + h)."""
    x0, y0, x1, y1 = x, y, x + w, y + h
    if r is not None:
        x0, y0 = tpi(r, x0, y0)
        x1, y1 = tpi(r, x1, y1)
    fb.line(x0, y0, x1, y1, c)
    if abs(x1 - x0) >= abs(y1 - y0):
        fb.line(x0, y0 + 1, x1, y1 + 1, c)
    else:
        fb.line(x0 + 1, y0, x1 + 1, y1, c)


def bar(fb, x, y, w, h, f, c, label_text, value_text, font, r=None):
    ty, th, fw, base = bar_layout(x, y, w, h, f, font.size)
    if label_text:
        text(fb, font.fit(label_text, w), x, base, LABEL_COLOR, font, r)
    if value_text:
        s = font.fit(value_text, w)
        text(fb, s, x + w - font.width(s), base, VALUE_COLOR, font, r)
    rrect(fb, x, ty, w, th, 3, TRACK_COLOR, r)
    if fw > 0:
        rrect(fb, x, ty, fw, th, 3, c, r)


def _ring(fb, cx, cy, rad, a0, a1, c, r=None):
    ri = rad - ARC_WIDTH // 2
    ro = rad + ARC_WIDTH // 2
    steps = int((a1 - a0) / pi * max(8, rad // 2)) + 1
    q = _quad
    prev = None
    for i in range(steps + 1):
        a = a0 + (a1 - a0) * i / steps
        ox, oy = arc_point(cx, cy, ro, a)
        ix, iy = arc_point(cx, cy, ri, a)
        if r is not None:
            ox, oy = tp(r, ox, oy)
            ix, iy = tp(r, ix, iy)
        cur = (int(ox + 0.5), int(oy + 0.5), int(ix + 0.5), int(iy + 0.5))
        if prev is not None:
            q[0], q[1], q[2], q[3] = prev[0], prev[1], cur[0], cur[1]
            q[4], q[5], q[6], q[7] = cur[2], cur[3], prev[2], prev[3]
            fb.poly(0, 0, q, c, True)
        prev = cur


def arc(fb, x, y, w, h, f, c, value_text, font, r=None):
    cx, cy, rad = arc_geometry(x, y, w, h)
    _ring(fb, cx, cy, rad, 0.0, pi, TRACK_COLOR, r)
    if f > 0:
        _ring(fb, cx, cy, rad, 0.0, pi * f, c, r)
    if value_text:
        s = font.fit(value_text, w)
        text(fb, s, cx - font.width(s) // 2, cy - 4, VALUE_COLOR, font, r)


# ------------------------------------------------------------------ chart
CHART_BG = 0x0511  # #10222c
GRID_COLOR = 0x8819  # #1f3340
AXIS_COLOR = 0x8F53  # #56707c
NO_DATA = "немає даних"


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def points(data, numeric):
    """``[{x: y}, ...]`` -> [(x, y), ...]; a map may hold several pairs.

    Numeric X are sorted ascending; labels keep the list order.
    """
    out = []
    if isinstance(data, (list, tuple)):
        for item in data:
            if isinstance(item, dict):
                for k in item:
                    out.append((k, item[k]))
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                out.append((item[0], item[1]))
    out = [q for q in out if _is_num(q[1]) and (_is_num(q[0]) if numeric else True)]
    if numeric:
        out.sort(key=lambda q: q[0])
    return out


def tick(v):
    """Y axis label: integer as is, otherwise one decimal."""
    return str(int(v)) if v == int(v) else "%.1f" % v


def xlabel(v):
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


def label_indices(n, w):
    """X labels: first, middle (if wider than 110 px), last (core.evaluate)."""
    if n > 2 and w > 110:
        return (0, (n - 1) // 2, n - 1)
    if n > 1:
        return (0, n - 1)
    return (0,) if n else ()


def chart_range(pts, lo, hi, y_min, y_max):
    """Y range: manual bounds, else the parameter range widened to the data."""
    if y_min is not None:
        lo = y_min
    if y_max is not None:
        hi = y_max
    if pts:
        if y_min is None:
            lo = min(lo, min(q[1] for q in pts))
        if y_max is None:
            hi = max(hi, max(q[1] for q in pts))
    if hi <= lo:
        hi = lo + 1
    return lo, hi


def chart_frame(x, y, w, h, lw, axis_x, axis_y):
    """(L, R, T, B) of the plot area; ``lw`` = width of the Y labels + 4 px."""
    return x + lw, x + w - 3, y + (11 if axis_y else 4), y + h - 10 - (9 if axis_x else 0)


def chart(
    fb, x, y, w, h, data, numeric, lo, hi, y_min, y_max, axis_x, axis_y, style, grid, c, font
):
    pts = points(data, numeric)
    lo, hi = chart_range(pts, lo, hi, y_min, y_max)
    rrect(fb, x, y, w, h, 3, CHART_BG)
    lw = max(font.width(tick(lo)), font.width(tick(hi))) + 4
    left, right, top, bottom = chart_frame(x, y, w, h, lw, axis_x, axis_y)
    if bottom - top < 6 or right - left < 10:
        return
    span = bottom - top

    def my(v):
        f = (v - lo) / (hi - lo)
        f = 0.0 if f < 0 else 1.0 if f > 1 else f
        return int(floor(bottom - span * f + 0.5))

    if grid:
        for f in (0.0, 0.5, 1.0):
            fb.hline(left, int(floor(bottom - span * f + 0.5)), right - left + 1, GRID_COLOR)
    fb.vline(left, top, span + 1, AXIS_COLOR)
    fb.hline(left, bottom, right - left + 1, AXIS_COLOR)
    for s, base in ((tick(hi), top + 3), (tick(lo), bottom)):
        text(fb, s, left - 2 - font.width(s), base, LABEL_COLOR, font)
    if axis_y:
        text(fb, font.fit(axis_y, w), left + 3, y + 8, LABEL_COLOR, font)
    if axis_x:
        s = font.fit(axis_x, w)
        text(fb, s, right - font.width(s), y + h - 2, LABEL_COLOR, font)
    n = len(pts)
    if not n:
        tx = (left + right) // 2 - font.width(NO_DATA) // 2
        text(fb, NO_DATA, tx, (top + bottom) // 2, LABEL_COLOR, font)
        return
    bars = style == "bars"
    bw = (right - left) / n
    x0 = pts[0][0] if numeric else 0
    x1 = pts[-1][0] if numeric else n - 1
    xs = []
    for k in range(n):
        if bars:
            xs.append(left + bw * (k + 0.5))
        elif x1 == x0:
            xs.append((left + right) / 2)
        else:
            xv = pts[k][0] if numeric else k
            xs.append(left + 4 + (right - left - 8) * (xv - x0) / (x1 - x0))
    ks = label_indices(n, w)
    for i in range(len(ks)):
        k = ks[i]
        s = xlabel(pts[k][0])
        tw = font.width(s)
        if len(ks) > 1 and i == 0 and not bars:
            tx = xs[k]
        elif len(ks) > 1 and i == len(ks) - 1 and not bars:
            tx = xs[k] - tw
        else:
            tx = xs[k] - tw / 2
        text(fb, s, int(floor(tx + 0.5)), bottom + 8, LABEL_COLOR, font)
    if bars:
        bar_w = max(1, int(floor(bw * 0.7 + 0.5)))
        for k in range(n):
            yy = my(pts[k][1])
            if bottom - yy > 0:
                fb.fill_rect(int(floor(xs[k] - bw * 0.35 + 0.5)), yy, bar_w, bottom - yy, c)
        return
    px = None
    py = None
    for k in range(n):
        cx = int(floor(xs[k] + 0.5))
        cy = my(pts[k][1])
        if px is not None:
            fb.line(px, py, cx, cy, c)
        if style == "dots":
            fb.ellipse(cx, cy, 2, 2, c, True)
        px = cx
        py = cy


# ------------------------------------------------------------------ images
ROOT = ""  # prefix of board paths ("/img/..."); tests on a PC point it at a folder
MISSING_COLOR = 0x2511  # #13252f: a missing / unreadable picture
MISSING_BORDER = 0x8F53  # #56707c
_row = [None, 0]  # reusable row buffer: [bytearray, width]
IMAGE_CACHE = 0
"""RAM (bytes) for keeping pictures after the first read; 0 = read them from flash each time.

Boards with PSRAM: e.g. ``ui_draw.IMAGE_CACHE = 2_000_000`` makes redrawing over a
picture several times faster. Pictures that don't fit are still read row by row.
"""
_cache = {}  # path -> FrameBuffer of the whole picture
_cache_used = [0]
_anims = {}  # folder -> (frames, delay_ms) read from anim.json


def _row_fb(w):
    if _row[1] != w:
        _row[0] = bytearray(2 * w)
        _row[1] = w
    return _row[0]


def _file_size(path):
    try:
        return os.stat(path)[6]
    except OSError:
        return -1


def missing(fb, x, y, w, h):
    """Grey placeholder instead of a picture that isn't on the board."""
    fb.fill_rect(x, y, w, h, MISSING_COLOR)
    fb.rect(x, y, w, h, MISSING_BORDER)


def image(fb, x, y, w, h, path):
    """Draw a raw RGB565 file (w x h, wire order) row by row: only one row in RAM.

    Only the rows inside the strip being drawn are read. A missing file or one
    of another size gives the grey placeholder instead of an exception.
    """
    if path:
        path = ROOT + path
    if not path or _file_size(path) != 2 * w * h:
        missing(fb, x, y, w, h)
        return
    r0 = -y if y < 0 else 0
    r1 = _clip[1] - y if _clip[1] - y < h else h
    if r1 <= r0:
        return
    pic = _cached(path, w, h)
    if pic is not None:
        fb.blit(pic, x, y)
        return
    buf = _row_fb(w)
    row = framebuf.FrameBuffer(buf, w, 1, framebuf.RGB565)
    try:
        with open(path, "rb") as f:
            f.seek(2 * w * r0)
            for r in range(r0, r1):
                f.readinto(buf)
                fb.blit(row, x, y + r)
    except OSError:
        missing(fb, x, y, w, h)


def _cached(path, w, h):
    """The whole picture in RAM if :data:`IMAGE_CACHE` allows it, else None."""
    pic = _cache.get(path)
    if pic is not None or _cache_used[0] + 2 * w * h > IMAGE_CACHE:
        return pic
    try:
        data = bytearray(2 * w * h)
        with open(path, "rb") as f:
            f.readinto(data)
    except (OSError, MemoryError):
        return None
    pic = framebuf.FrameBuffer(data, w, h, framebuf.RGB565)
    _cache[path] = pic
    _cache_used[0] += len(data)
    return pic


def anim_info(path):
    """(folder, frames, delay_ms) of an animation folder ``/img/<name>/``, or None."""
    if not path or not path.endswith("/"):
        return None
    info = _anims.get(path)
    if info is None:
        try:
            with open(ROOT + path + "anim.json") as f:
                data = json.load(f)
            info = (path, int(data["frames"]), int(data["delay_ms"]))
        except (OSError, ValueError, KeyError):
            info = (path, 0, 0)
        _anims[path] = info
    return info if info[1] > 0 else None


def frame_path(folder, index):
    return "%s%03d.bin" % (folder, index)


# ------------------------------------------------------------------ page engine
_buffers = {}


def shared_buffer(name, size):
    """A buffer of at least ``size`` bytes shared by every page (pages never draw at once)."""
    buf = _buffers.get(name)
    if buf is None or len(buf) < size:
        buf = memoryview(bytearray(size))
        _buffers[name] = buf
    return buf[:size]


def snapshot(p):
    """Copy of the values for change detection: series lists are copied by content."""
    out = {}
    for k in p:
        v = p[k]
        if isinstance(v, list):
            v = [dict(m) if isinstance(m, dict) else m for m in v]
        out[k] = v
    return out


class Page:
    """Base class of generated pages.

    Subclasses set BACKGROUND and WIDGETS = ((id, x, y, w, h, deps), ...)
    in layer order (first = lowest) and define ``_draw_<id>(fb, ox, oy)``.
    A widget whose box can change (position, angle) also defines
    ``_box_<id>()`` returning its current (x, y, w, h); a hidden widget
    simply draws nothing, and the engine repaints what is under it.
    A translucent widget draws into ``fb = self.begin_alpha(fb)`` and calls
    ``self.end_alpha(level)`` (USES_ALPHA = True allocates the layer buffer).
    """

    BACKGROUND = 0
    WIDGETS = ()
    DEFAULTS = {}
    USES_ALPHA = False
    ANIMS = ()  # (("id", loop), ...): widgets that can show an animation folder

    def __init__(self, display, p=None, buf_bytes=None):
        global IMAGE_CACHE
        self.display = display
        self.p = dict(self.DEFAULTS) if p is None else p
        self.width = display.width
        self.height = display.height
        # Memory settings come with the display (ui_display: BUF_BYTES, IMAGE_CACHE).
        if buf_bytes is None:
            buf_bytes = getattr(display, "buf_bytes", BUF_BYTES)
        cache = getattr(display, "image_cache", None)
        if cache is not None:
            IMAGE_CACHE = cache
        if buf_bytes > 2 * self.width * self.height:
            buf_bytes = 2 * self.width * self.height
        if buf_bytes < 2 * self.width:
            buf_bytes = 2 * self.width
        # One region buffer (and one alpha layer) for all pages: only one page draws at a time.
        self._mv = shared_buffer("region", buf_bytes)
        self._buf = self._mv
        self._layer = shared_buffer("layer", buf_bytes) if self.USES_ALPHA else None
        self._prev = None
        self._draws = tuple(getattr(self, "_draw_" + wd[0]) for wd in self.WIDGETS)
        self._box_fns = tuple(getattr(self, "_box_" + wd[0], None) for wd in self.WIDGETS)
        self._boxes = [(wd[1], wd[2], wd[3], wd[4]) for wd in self.WIDGETS]
        self._strip = None  # (x, y, w, h, n, framebuffer) being drawn
        self._box = None  # box of the widget being drawn
        # Animations: widget index -> [frame, last tick ms, playing, folder, loop]
        self._anim = {}
        self._anim_fns = {}
        self._index = {}
        for i in range(len(self.WIDGETS)):
            self._index[self.WIDGETS[i][0]] = i
        for wid, loop in self.ANIMS:
            i = self._index[wid]
            self._anim_fns[i] = getattr(self, "_anim_" + wid)
            self._anim[i] = [0, ticks_ms(), True, None, loop]

    def _refresh_boxes(self):
        fns = self._box_fns
        for i in range(len(fns)):
            if fns[i] is not None:
                self._boxes[i] = fns[i]()

    def draw(self, p=None):
        """Redraw the whole screen."""
        if p is not None:
            self.p = p
        self._refresh_boxes()
        self._render((0, 0, self.width, self.height))
        self._prev = snapshot(self.p)

    def update(self, p=None):
        """Redraw only widgets whose parameters changed; returns the number of regions."""
        if p is not None:
            self.p = p
        prev = self._prev
        if prev is None:
            self.draw()
            return 1
        cur = self.p
        changed = set()
        for k in cur:
            if k not in prev or prev[k] != cur[k]:
                changed.add(k)
        if not changed:
            return 0
        rects = []
        widgets = self.WIDGETS
        boxes = self._boxes
        fns = self._box_fns
        for i in range(len(widgets)):
            for k in widgets[i][5]:
                if k in changed:
                    old = boxes[i]
                    rects.append(old)
                    if fns[i] is not None:
                        new = fns[i]()
                        if new != old:
                            boxes[i] = new
                            rects.append(new)
                    break
        n = self._render_rects(rects)
        self._prev = snapshot(cur)
        return n

    def _render_rects(self, rects):
        regions = []
        for r in merge(rects):
            r = clip(r, self.width, self.height)
            if r is not None:
                regions.append(r)
        for r in regions:
            self._render(r)
        return len(regions)

    # -------------------------------------------------------------- animations
    def frame(self, wid):
        """Current frame of animated widget ``wid``; restarts when its folder changes."""
        i = self._index[wid]
        st = self._anim[i]
        info = self._anim_fns[i]()
        folder = info[0] if info is not None else None
        if folder != st[3]:
            st[0] = 0
            st[1] = ticks_ms()
            st[2] = True
            st[3] = folder
        return st[0]

    def tick(self, now=None):
        """Advance the animations whose next frame is due (non-blocking).

        Call it often (e.g. every 10 ms); only the widgets that change are
        redrawn. Returns the number of regions written to the display.
        """
        if self._prev is None or not self._anim:
            return 0
        now = ticks_ms() if now is None else now
        rects = []
        for i in self._anim:
            st = self._anim[i]
            info = self._anim_fns[i]()
            if info is None or not st[2] or info[0] != st[3]:
                continue
            if ticks_diff(now, st[1]) < info[2]:
                continue
            nxt = st[0] + 1
            if nxt >= info[1]:
                if not st[4]:
                    st[2] = False  # "once": stays on the last frame
                    continue
                nxt = 0
            st[0] = nxt
            st[1] = now
            rects.append(self._boxes[i])
        return self._render_rects(rects) if rects else 0

    def play(self, wid):
        """Restart animated widget ``wid`` from its first frame."""
        i = self._index[wid]
        st = self._anim[i]
        st[0] = 0
        st[1] = ticks_ms()
        st[2] = True
        return self._render_rects([self._boxes[i]]) if self._prev is not None else 0

    # -------------------------------------------------------------- opacity
    def begin_alpha(self, fb):
        """Start a translucent widget: returns a layer that copies the strip so far."""
        _, _, w, h, n, _ = self._strip
        self._layer[:n] = self._mv[:n]
        return framebuf.FrameBuffer(self._layer[:n], w, h, framebuf.RGB565)

    def end_alpha(self, level):
        """Blend the pixels the widget changed in the layer over the strip."""
        sx, sy, sw, sh, _, _ = self._strip
        bx, by, bw, bh = self._box
        x0 = bx - sx if bx > sx else 0
        y0 = by - sy if by > sy else 0
        x1 = bx + bw - sx if bx + bw - sx < sw else sw
        y1 = by + bh - sy if by + bh - sy < sh else sh
        if x1 > x0 and y1 > y0:
            blend_rect(self._mv, self._layer, sw, x0, y0, x1, y1, level)

    # -------------------------------------------------------------- rendering
    def _render(self, region):
        x, y, w, h = region
        rows = len(self._buf) // (2 * w)
        if rows > h:
            rows = h
        boxes = self._boxes
        draws = self._draws
        blit = self.display.blit
        bg = self.BACKGROUND
        y0 = y
        while y0 < y + h:
            hh = rows if y0 + rows <= y + h else y + h - y0
            n = 2 * w * hh
            buf = self._mv[:n]
            fb = framebuf.FrameBuffer(buf, w, hh, framebuf.RGB565)
            fb.fill(bg)
            strip = (x, y0, w, hh)
            self._strip = (x, y0, w, hh, n, fb)
            _clip[0] = w
            _clip[1] = hh
            for i in range(len(boxes)):
                if intersects(strip, boxes[i]):
                    self._box = boxes[i]
                    draws[i](fb, x, y0)
            blit(buf, x, y0, w, hh)
            y0 += hh
