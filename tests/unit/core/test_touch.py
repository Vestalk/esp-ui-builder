"""Tap advice and the calibration line from the board."""

from __future__ import annotations

from typing import Any

from espui.core import serializer
from espui.core.models import Project
from espui.core.touch import MIN_TAP_PX, parse_calibration, tap_advice, tap_zones
from espui.generators.micropython.generator import generate


def project(widgets: list[dict[str, Any]], touch: bool = True) -> Project:
    pins = {"sck": 12, "mosi": 11, "dc": 9, "cs": 10, "rst": 8, "bl": 7, "miso": 13}
    display: dict[str, Any] = {"model": "ILI9341-3.2", "pins": pins}
    if touch:
        display["touch"] = {"kind": "xpt2046", "cs": 14, "irq": 15}
    return serializer.from_dict(
        {"display": display, "pages": [{"name": "main", "widgets": widgets}]}
    )


def advice(p: Project) -> list[str]:
    return [f"{i.path}: {i.message}" for i in tap_advice(p)]


def test_small_buttons_and_covered_ones() -> None:
    p = project(
        [
            {"id": "ok", "type": "rect", "x": 0, "y": 0, "w": 60, "h": 40, "on_tap": "go"},
            {"id": "tiny", "type": "rect", "x": 100, "y": 0, "w": 20, "h": 50, "on_tap": "go"},
            {"id": "under", "type": "rect", "x": 0, "y": 100, "w": 40, "h": 40, "on_tap": "a"},
            {"id": "over", "type": "rect", "x": 0, "y": 90, "w": 80, "h": 80, "on_tap": "b"},
            {"id": "plain", "type": "rect", "x": 200, "y": 0, "w": 10, "h": 10},  # no tap
        ]
    )
    assert advice(p) == [
        f"pages[0].widgets[1].on_tap: «tiny»: зона натиску 20×50 px — пальцем важко влучити, "
        f"краще від {MIN_TAP_PX} px",
        "pages[0].widgets[2].on_tap: «under» повністю під «over»: усі натиски дістануться «over»",
    ]
    assert [z.widget.id for z in tap_zones(p.pages[0])] == ["ok", "tiny", "under", "over"]


def test_taps_without_a_touch_panel_and_generation_warnings() -> None:
    p = project([{"id": "b", "type": "rect", "w": 60, "h": 40, "on_tap": "go"}], touch=False)
    assert advice(p) == [
        "pages[0].widgets[0].on_tap: «b»: дисплей без сенсора — натиски не працюватимуть "
        "(Дисплей → Сенсорний екран)"
    ]
    warnings = generate(p).warnings
    assert any(w.startswith("сторінка «main»: «b»: дисплей без сенсора") for w in warnings)
    fine = project([{"id": "b", "type": "rect", "w": 60, "h": 40, "on_tap": "go"}])
    assert advice(fine) == []


def test_calibration_line() -> None:
    line = "ESPUI-CAL x_min=3812 x_max=291 y_min=240 y_max=3705 swap_xy=1"
    assert parse_calibration(line) == {
        "x_min": 3812,
        "x_max": 291,
        "y_min": 240,
        "y_max": 3705,
        "swap_xy": True,
    }
    assert parse_calibration(">>> " + line.replace("swap_xy=1", "swap_xy=0") + "\r\n") == {
        "x_min": 3812,
        "x_max": 291,
        "y_min": 240,
        "y_max": 3705,
        "swap_xy": False,
    }
    assert parse_calibration("x_min=5000 x_max=-3 y_min=1 y_max=2")["x_min"] == 4095  # type: ignore[index]
    assert parse_calibration("hello") is None
    assert parse_calibration("x_min=1 x_max=1 y_min=1 y_max=2") is None  # no range
