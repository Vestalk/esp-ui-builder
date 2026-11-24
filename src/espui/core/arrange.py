"""Align and distribute widgets ("Розташування"): how far each one moves.

Works on the widgets' own boxes (x, y, w, h as set in the editor). Several
widgets align to the box around all of them; a single one aligns to the screen.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from espui.core.models import Widget

Align = Literal["left", "hcenter", "right", "top", "vcenter", "bottom"]
Distribute = Literal["horizontal", "vertical"]

ALIGN_TITLES: dict[Align, str] = {
    "left": "Вирівняти за лівим краєм",
    "hcenter": "Вирівняти по центру (горизонтально)",
    "right": "Вирівняти за правим краєм",
    "top": "Вирівняти за верхом",
    "vcenter": "Вирівняти по середині (вертикально)",
    "bottom": "Вирівняти за низом",
}
DISTRIBUTE_TITLES: dict[Distribute, str] = {
    "horizontal": "Розподілити горизонтально",
    "vertical": "Розподілити вертикально",
}


def bounds(widgets: Sequence[Widget]) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1) around all the widgets."""
    return (
        min(w.x for w in widgets),
        min(w.y for w in widgets),
        max(w.x + w.w for w in widgets),
        max(w.y + w.h for w in widgets),
    )


def align(
    widgets: Sequence[Widget], how: Align, screen: tuple[int, int]
) -> dict[str, tuple[int, int]]:
    """{id: (dx, dy)} lining the widgets up; one widget lines up with the screen."""
    if not widgets:
        return {}
    x0, y0, x1, y1 = (0, 0, *screen) if len(widgets) == 1 else bounds(widgets)
    moves = {}
    for w in widgets:
        if how == "left":
            dx, dy = x0 - w.x, 0
        elif how == "right":
            dx, dy = x1 - (w.x + w.w), 0
        elif how == "hcenter":
            dx, dy = (x0 + x1 - w.w) // 2 - w.x, 0
        elif how == "top":
            dx, dy = 0, y0 - w.y
        elif how == "bottom":
            dx, dy = 0, y1 - (w.y + w.h)
        else:  # vcenter
            dx, dy = 0, (y0 + y1 - w.h) // 2 - w.y
        if dx or dy:
            moves[w.id] = (dx, dy)
    return moves


def distribute(widgets: Sequence[Widget], how: Distribute) -> dict[str, tuple[int, int]]:
    """{id: (dx, dy)}: equal gaps between neighbours; the outermost two stay put."""
    if len(widgets) < 3:
        return {}
    horizontal = how == "horizontal"

    def start(w: Widget) -> int:
        return w.x if horizontal else w.y

    def size(w: Widget) -> int:
        return w.w if horizontal else w.h

    order = sorted(widgets, key=lambda w: (start(w), w.id))
    first, last = order[0], order[-1]
    free = (start(last) + size(last)) - start(first) - sum(size(w) for w in order)
    gaps = len(order) - 1
    moves = {}
    position = start(first)
    for i, w in enumerate(order):
        if 0 < i < len(order) - 1:
            delta = position - start(w)
            if delta:
                moves[w.id] = (delta, 0) if horizontal else (0, delta)
        # the remainder of an uneven split goes to the first gaps
        position += size(w) + free // gaps + (1 if i < free % gaps else 0)
    return moves
