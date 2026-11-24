"""Taps in the editor: where a widget catches them, which one a tap reaches, advice.

The same rules as the board (``ui_draw.Page.hit``): only widgets with "При натиску"
take part, the topmost one under the point wins, one hidden by a condition doesn't
catch taps, and the box is the widget's box as drawn (moved / turned by rules).
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator
from dataclasses import dataclass

from espui.core.evaluate import ParameterValues, effective
from espui.core.issues import Issue, format_path
from espui.core.models import Page, Project, Widget

MIN_TAP_PX = 36
"""Smaller than this (either side) is hard to hit with a finger (~6 mm on a 2.8" panel)."""

CAL_PREFIX = "ESPUI-CAL"
"""The line ``ui_display.calibrate_touch()`` prints on the board, pasted into "Дисплей"."""

Box = tuple[int, int, int, int]


def tap_box(widget: Widget, values: ParameterValues) -> Box:
    """(x, y, w, h) where the widget catches taps: its box as drawn (a turned one: around it)."""
    e = effective(widget, values)
    x, y, w, h = e.bounds
    angle = e.angle % 360
    if not angle:
        return x, y, w, h
    px, py = e.pivot
    turn = math.radians(angle)
    cos, sin = math.cos(turn), math.sin(turn)
    xs, ys = [], []
    for cx, cy in ((x, y), (x + w, y), (x, y + h), (x + w, y + h)):
        dx, dy = cx - px, cy - py
        xs.append(px + dx * cos - dy * sin)
        ys.append(py + dx * sin + dy * cos)
    left, top = math.floor(min(xs)), math.floor(min(ys))
    return left, top, math.ceil(max(xs)) - left, math.ceil(max(ys)) - top


@dataclass(frozen=True, slots=True)
class TapZone:
    widget: Widget
    box: Box
    shown: bool
    """False: hidden by a condition now (with these values), so it doesn't catch taps."""

    @property
    def small(self) -> bool:
        return min(self.box[2], self.box[3]) < MIN_TAP_PX


def tap_zones(page: Page, values: ParameterValues | None = None) -> list[TapZone]:
    """Widgets with "При натиску", bottom to top (the last one is drawn over the others)."""
    values = values or ParameterValues.for_page(page)
    return [
        TapZone(w, tap_box(w, values), effective(w, values).visible)
        for w in page.widgets
        if w.on_tap
    ]


def tap_at(page: Page, x: float, y: float, values: ParameterValues | None = None) -> Widget | None:
    """The widget a tap at (x, y) reaches on the board, or None."""
    for zone in reversed(tap_zones(page, values)):
        bx, by, bw, bh = zone.box
        if zone.shown and bx <= x < bx + bw and by <= y < by + bh:
            return zone.widget
    return None


def _covers(outer: Box, inner: Box) -> bool:
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return ox <= ix and oy <= iy and ix + iw <= ox + ow and iy + ih <= oy + oh


def tap_advice(project: Project, pages: list[Page] | None = None) -> Iterator[Issue]:
    """Not errors — the page generates — but taps that won't work as one may expect."""
    no_touch = project.display.touch is None
    for p_index, page in enumerate(project.pages):
        if pages is not None and page not in pages:
            continue
        zones = tap_zones(page)
        for i, zone in enumerate(zones):
            w_index = page.widgets.index(zone.widget)
            path = format_path(("pages", p_index, "widgets", w_index, "on_tap"))
            wid = zone.widget.id
            if no_touch:
                yield Issue(
                    path,
                    f"«{wid}»: дисплей без сенсора — натиски не працюватимуть "
                    "(Дисплей → Сенсорний екран)",
                )
            if zone.small:
                yield Issue(
                    path,
                    f"«{wid}»: зона натиску {zone.box[2]}×{zone.box[3]} px — пальцем важко "
                    f"влучити, краще від {MIN_TAP_PX} px",
                )
            above = next((z for z in zones[i + 1 :] if _covers(z.box, zone.box)), None)
            if above is not None:
                yield Issue(
                    path,
                    f"«{wid}» повністю під «{above.widget.id}»: усі натиски дістануться "
                    f"«{above.widget.id}»",
                )


def tap_hint(project: Project, page: Page, widget: Widget) -> str:
    """The advice about one widget, as one line for the properties panel ("" if none)."""
    p_index = project.pages.index(page)
    w_index = page.widgets.index(widget)
    path = format_path(("pages", p_index, "widgets", w_index, "on_tap"))
    return "; ".join(i.message for i in tap_advice(project) if i.path == path)


_CAL = re.compile(r"(x_min|x_max|y_min|y_max|swap_xy)\s*[=:]\s*(-?\d+|true|false)", re.I)


def parse_calibration(text: str) -> dict[str, int | bool] | None:
    """``ESPUI-CAL x_min=… x_max=… y_min=… y_max=… swap_xy=0|1`` -> values, or None."""
    found = {name.lower(): value.lower() for name, value in _CAL.findall(text)}
    if not {"x_min", "x_max", "y_min", "y_max"} <= found.keys():
        return None
    out: dict[str, int | bool] = {k: int(found[k]) for k in ("x_min", "x_max", "y_min", "y_max")}
    swap = found.get("swap_xy", "0")
    out["swap_xy"] = swap in ("1", "true")
    for key in ("x_min", "x_max", "y_min", "y_max"):
        out[key] = max(0, min(4095, int(out[key])))
    if out["x_min"] == out["x_max"] or out["y_min"] == out["y_max"]:
        return None
    return out
