"""Taps on widgets ("При натиску"): the generated page calls functions of the board code."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from espui.core import serializer
from espui.core.models import Display, Project
from espui.generators.micropython.generator import generate
from tests.mpy.conftest import RunMpy


def tap_project() -> Project:
    return serializer.from_dict(
        {
            "display": {"rotation": 1},
            "pages": [
                {
                    "name": "main",
                    "parameters": [
                        {"name": "on", "type": "bool", "default": True},
                        {"name": "count", "type": "int", "min": 0, "max": 100, "default": 0},
                    ],
                    "widgets": [
                        {"id": "bg", "type": "rect", "w": 320, "h": 240, "color": "#102030"},
                        {"id": "btn_start", "type": "rect", "x": 10, "y": 10, "w": 100, "h": 40,
                         "on_tap": "start_pump"},
                        # drawn over the start button's right half, also tappable
                        {"id": "btn_top", "type": "rect", "x": 60, "y": 10, "w": 100, "h": 40,
                         "on_tap": "top_pressed"},
                        {"id": "btn_stop", "type": "rect", "x": 10, "y": 60, "w": 100, "h": 40,
                         "on_tap": "stop_pump",
                         "rules": [{"if": ["on", "==", False], "set": "visible", "to": False}]},
                        {"id": "counter", "type": "value", "x": 200, "y": 200, "w": 80, "h": 24,
                         "bind": "count", "format": "%d"},
                    ],
                }
            ],
        }
    )  # fmt: skip


SCRIPT = r"""
import json, ui_draw, ui_main

class FakeDisplay:
    width = 320
    height = 240
    def __init__(self):
        self.blits = 0
    def blit(self, buf, x, y, w, h):
        self.blits += 1

class FakeTouch:
    def __init__(self, points):
        self.points = list(points)
    def read(self):
        return self.points.pop(0) if self.points else None

calls = []
def start_pump():
    calls.append("start")
    p["count"] += 1
def stop_pump():
    calls.append("stop")
def top_pressed():
    calls.append("top")

def out(tag, value):
    print(tag + " " + json.dumps(value))

d = FakeDisplay()
ui = ui_main.UI(d)
p = dict(ui_main.DEFAULTS)
ui.draw(p, actions={"start_pump": start_pump, "stop_pump": stop_pump, "top_pressed": top_pressed})
out("taps", ui.TAPS)
out("hits", [ui.hit(20, 20), ui.hit(80, 20), ui.hit(20, 70), ui.hit(300, 100), ui.hit(150, 45)])
p["on"] = False
ui.update(p)
out("hidden", ui.hit(20, 70))  # btn_stop hidden by its condition: no tap
p["on"] = True
ui.update(p)

# a press held for 3 readings, lifted, pressed again: two calls, not four
touch = FakeTouch([(20, 20), (21, 21), (22, 22), None, None, (20, 20), None, None])
blits = d.blits
results = [ui.poll_touch(touch) for _ in range(8)]
out("polls", results)
out("calls", calls)
out("count", p["count"])
out("redrawn", d.blits > blits)

# a tap on nothing tappable (the background rectangle has no function)
out("miss", ui.tap(300, 100))

# the timer callback skips while the bus is busy
ui._touch = FakeTouch([(80, 20)])
ui._pressed = False
with ui_draw.Busy():
    ui._touch_tick(None)
out("busy_skipped", calls[-1])
ui._touch_tick(None)
out("after_busy", calls[-1])

# missing procedures: reported by draw(), before any tap
ui2 = ui_main.UI(d)
try:
    ui2.draw(dict(ui_main.DEFAULTS), actions={"start_pump": start_pump})
except ValueError as e:
    out("draw_error", str(e))
out("missing", ui2.missing_actions())

# globals() works as the map too
ui3 = ui_main.UI(d)
ui3.draw(dict(ui_main.DEFAULTS), actions=globals())
out("globals_ok", ui3.missing_actions())
"""


def test_taps_call_functions_once_per_press(run_mpy: RunMpy, tmp_path: Path) -> None:
    generate(tap_project()).write(tmp_path)
    proc = run_mpy(SCRIPT)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    r: dict[str, Any] = {
        line.split(" ", 1)[0]: json.loads(line.split(" ", 1)[1])
        for line in proc.stdout.splitlines()
    }
    assert r["taps"] == {
        "btn_start": "start_pump",
        "btn_top": "top_pressed",
        "btn_stop": "stop_pump",
    }
    # the start button; the top one where they overlap; stop; background; nothing
    assert r["hits"] == ["btn_start", "btn_top", "btn_stop", None, "btn_top"]
    assert r["hidden"] is None
    assert r["polls"] == ["btn_start", None, None, None, None, "btn_start", None, None]
    assert r["calls"] == ["start", "start"]
    assert r["count"] == 2
    assert r["redrawn"] is True  # the tap changed p: the counter was redrawn
    assert r["miss"] is None
    assert r["busy_skipped"] == "start"  # nothing happened while the bus was busy
    assert r["after_busy"] == "top"
    assert r["missing"] == ["top_pressed", "stop_pump"]
    assert r["draw_error"] == "no procedure for: top_pressed, stop_pump (add it to actions)"
    assert r["globals_ok"] == []


def test_listen_touch_runs_from_a_timer(run_mpy: RunMpy, tmp_path: Path) -> None:
    """listen_touch(): a periodic machine.Timer polls the panel, the code has no loop."""
    generate(tap_project()).write(tmp_path)
    (tmp_path / "machine.py").write_text(
        "class Timer:\n"
        "    PERIODIC = 1\n"
        "    made = []\n"
        "    def __init__(self, timer_id):\n"
        "        self.id = timer_id\n"
        "        Timer.made.append(self)\n"
        "    def init(self, mode, period, callback):\n"
        "        self.period, self.callback = period, callback\n"
        "    def deinit(self):\n"
        "        self.callback = None\n",
        "utf-8",
    )
    script = (
        SCRIPT.split("# a press held")[0]
        + r"""
import machine
ui.listen_touch(FakeTouch([(20, 20), None, None, (20, 70)]))
timer = machine.Timer.made[-1]
out("timer", [timer.id, timer.period])
for _ in range(4):
    timer.callback(timer)   # what the board's timer does every 30 ms
out("timer_calls", calls)
ui.stop_touch()
out("stopped", timer.callback is None)
"""
    )
    proc = run_mpy(script)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    r = {
        line.split(" ", 1)[0]: json.loads(line.split(" ", 1)[1])
        for line in proc.stdout.splitlines()
    }
    assert r["timer"] == [0, 30]
    assert r["timer_calls"] == ["start", "stop"]
    assert r["stopped"] is True


@pytest.mark.parametrize("touch", [True, False])
def test_generated_example_wires_the_taps(touch: bool) -> None:
    project = tap_project()
    if touch:
        data = project.display.model_dump()
        data["pins"]["miso"] = 13
        data["touch"] = {"kind": "xpt2046", "cs": 14, "irq": 15}
        project = project.model_copy(update={"display": Display.model_validate(data)})
    result = generate(project)
    main = result.files["main.py"].decode()
    for name in ("start_pump", "stop_pump", "top_pressed"):
        assert f"def {name}():" in main
    assert "UI(display)" in main
    assert '"start_pump": start_pump,' in main
    assert "ui.draw(p, actions=ACTIONS)" in main
    assert "ui.listen_touch()" in main
    warned = any("сенсорний екран не ввімкнено" in w for w in result.warnings)
    assert warned is not touch


def editor_vs_board_project() -> Project:
    """Taps on moved, turned and hidden widgets: the editor must answer as the board."""
    return serializer.from_dict(
        {
            "display": {"rotation": 1},
            "pages": [
                {
                    "name": "main",
                    "parameters": [
                        {"name": "on", "type": "bool", "default": True},
                        {"name": "level", "type": "int", "min": 0, "max": 100, "default": 70},
                    ],
                    "test_values": {"on": False, "level": 30},
                    "widgets": [
                        {"id": "plain", "type": "rect", "x": 10, "y": 10, "w": 60, "h": 40,
                         "on_tap": "a"},
                        {"id": "turned", "type": "rect", "x": 100, "y": 20, "w": 80, "h": 30,
                         "rotation_deg": 30, "on_tap": "b"},
                        {"id": "moving", "type": "rect", "x": 0, "y": 150, "w": 50, "h": 40,
                         "on_tap": "c",
                         "rules": [{"param": "level", "prop": "x", "at_min": 0, "at_max": 200}]},
                        {"id": "hiding", "type": "circle", "x": 200, "y": 100, "w": 60, "h": 60,
                         "on_tap": "d",
                         "rules": [{"if": ["on", "==", False], "set": "visible", "to": False}]},
                        {"id": "label", "type": "text", "x": 20, "y": 20, "w": 40, "h": 16,
                         "text": "OK"},
                    ],
                }
            ],
        }
    )  # fmt: skip


GRID_SCRIPT = r"""
import json, ui_main

class FakeDisplay:
    width = 320
    height = 240
    def blit(self, buf, x, y, w, h):
        pass

ui = ui_main.UI(FakeDisplay())
p = dict(ui_main.DEFAULTS)
p.update(json.loads(VALUES))
ui.draw(p, actions={"a": print, "b": print, "c": print, "d": print})
print(json.dumps([[ui.hit(x, y) for x in range(0, 320, 5)] for y in range(0, 240, 5)]))
"""


@pytest.mark.parametrize("values", [{}, "test"])
def test_editor_preview_taps_match_the_board(
    run_mpy: RunMpy, tmp_path: Path, values: dict[str, object] | str
) -> None:
    """ "Перегляд" (core.touch.tap_at) and ui_draw.Page.hit agree at every point of a grid."""
    from espui.core.evaluate import ParameterValues
    from espui.core.touch import tap_at

    project = editor_vs_board_project()
    page = project.pages[0]
    board_values = page.test_values if values == "test" else {}
    generate(project).write(tmp_path)
    proc = run_mpy(GRID_SCRIPT.replace("VALUES", repr(json.dumps(board_values))))
    assert proc.returncode == 0, proc.stderr + proc.stdout
    board = json.loads(proc.stdout.strip().splitlines()[-1])
    editor_values = ParameterValues(page.parameters, dict(board_values))
    differ = []
    for row, y in enumerate(range(0, 240, 5)):
        for col, x in enumerate(range(0, 320, 5)):
            widget = tap_at(page, x, y, editor_values)
            if (widget.id if widget else None) != board[row][col]:
                differ.append((x, y, widget.id if widget else None, board[row][col]))
    assert differ == []
    hit = {cell for line in board for cell in line}
    expected = {None, "plain", "turned", "moving"} | ({"hiding"} if values == {} else set())
    assert hit == expected  # all kinds took part; the text over "plain" doesn't block it
