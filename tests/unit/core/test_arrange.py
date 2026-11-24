"""Align and distribute: how far each widget moves."""

from __future__ import annotations

from typing import Any

import pytest

from espui.core.arrange import align, distribute
from espui.core.models import Widget


def w(wid: str, x: int, y: int, width: int, height: int) -> Widget:
    return Widget.model_validate(
        {"id": wid, "type": "rect", "x": x, "y": y, "w": width, "h": height}
    )


THREE = [w("a", 10, 10, 40, 20), w("b", 70, 30, 20, 40), w("c", 200, 5, 60, 10)]


@pytest.mark.parametrize(
    ("how", "expected"),
    [
        ("left", {"b": (-60, 0), "c": (-190, 0)}),  # to x = 10
        ("right", {"a": (210, 0), "b": (170, 0)}),  # to right edge 260
        ("hcenter", {"a": (105, 0), "b": (55, 0), "c": (-95, 0)}),  # centre 135
        ("top", {"a": (0, -5), "b": (0, -25)}),  # to y = 5
        ("bottom", {"a": (0, 40), "b": (0, 0)} | {"c": (0, 55)}),  # to bottom 70
        ("vcenter", {"a": (0, 17), "b": (0, -13), "c": (0, 27)}),  # middle 37
    ],
)
def test_align_to_the_selection(how: Any, expected: dict[str, tuple[int, int]]) -> None:
    moves = align(THREE, how, (320, 240))
    assert moves == {k: v for k, v in expected.items() if v != (0, 0)}


def test_one_widget_aligns_to_the_screen() -> None:
    one = [w("a", 10, 10, 40, 20)]
    assert align(one, "hcenter", (320, 240)) == {"a": (130, 0)}  # (320 - 40) / 2 = 140
    assert align(one, "right", (320, 240)) == {"a": (270, 0)}
    assert align(one, "vcenter", (320, 240)) == {"a": (0, 100)}
    assert align(one, "left", (320, 240)) == {"a": (-10, 0)}


def test_distribute_keeps_the_ends_and_evens_the_gaps() -> None:
    row = [w("a", 0, 0, 20, 10), w("b", 25, 0, 20, 10), w("c", 100, 0, 20, 10)]
    moves = distribute(row, "horizontal")
    assert moves == {"b": (25, 0)}  # gaps 30 and 30 between 0..120
    col = [w("a", 0, 0, 10, 10), w("b", 0, 12, 10, 30), w("c", 0, 14, 10, 10),
           w("d", 0, 100, 10, 10)]  # fmt: skip
    moved = {k: (0, 0) for k in "abcd"} | distribute(col, "vertical")
    ys = sorted((c.y + moved[c.id][1], c.y + moved[c.id][1] + c.h) for c in col)
    gaps = [ys[i + 1][0] - ys[i][1] for i in range(3)]
    assert max(gaps) - min(gaps) <= 1  # equal (the remainder spread by 1 px)
    assert ys[0][0] == 0
    assert ys[-1][1] == 110  # the ends stay
    assert distribute(row[:2], "horizontal") == {}  # needs three
