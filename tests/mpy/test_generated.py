"""Generated page on the MicroPython unix port, with a fake display (real framebuf)."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from espui.core import serializer
from espui.core.models import Page, ParamValue, Project, SeriesPoint
from espui.generators.micropython.drivers import RUNTIME_DIR
from espui.generators.micropython.generator import bounds, generate
from tests.mpy.conftest import RunMpy
from tests.mpy.reference import Canvas, render_page

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "weather.espui"

# Point-in-shape vs framebuf rasterisation differ on curve edges only (measured <= 1.4 %).
# A wrong glyph of a large digit is ~4-5 % of its widget, so it can't hide in the tolerance.
MAX_WIDGET_MISMATCH = 0.03
MAX_FRAME_MISMATCH = 0.005
MAX_ROTATED_MISMATCH = 0.06

FAKE_DISPLAY = """
import binascii, json, os, sys
import ui_draw
ui_draw.ROOT = os.getcwd()  # board paths "/img/..." -> this folder
import {module}

class FakeDisplay:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.frame = bytearray(width * height * 2)
        self.blits = []

    def blit(self, buf, x, y, w, h):
        assert len(buf) >= w * h * 2
        self.blits.append([x, y, w, h])
        row = 2 * w
        for r in range(h):
            o = ((y + r) * self.width + x) * 2
            self.frame[o:o + row] = buf[r * row:(r + 1) * row]

def out(tag, value):
    print(tag + " " + json.dumps(value))

def frame(d):
    print("frame " + binascii.hexlify(d.frame).decode())

d = FakeDisplay({width}, {height})
ui = {module}.UI(d, buf_bytes={buf})
p = dict({module}.DEFAULTS)
"""


@pytest.fixture(scope="module")
def ui_draw() -> Iterator[ModuleType]:
    sys.path.insert(0, str(RUNTIME_DIR))
    try:
        import ui_draw  # type: ignore[import-not-found]

        yield ui_draw
    finally:
        sys.path.remove(str(RUNTIME_DIR))
        sys.modules.pop("ui_draw", None)


@pytest.fixture(scope="module")
def weather() -> Project:
    return serializer.load(EXAMPLE)


class Run:
    def __init__(self, stdout: str, width: int, height: int) -> None:
        self.records: list[tuple[str, Any]] = []
        for line in stdout.splitlines():
            tag, _, rest = line.partition(" ")
            if tag == "frame":
                data = bytes.fromhex(rest)
                self.records.append((tag, Canvas.from_wire_bytes(width, height, data)))
            elif tag:
                self.records.append((tag, json.loads(rest)))

    def all(self, tag: str) -> list[Any]:
        return [value for t, value in self.records if t == tag]


def run_page(run_mpy: RunMpy, tmp_path: Path, project: Project, body: str, buf: int = 16384) -> Run:
    result = generate(project)
    result.write(tmp_path)
    width, height = project.display.size
    module = f"ui_{result.page}"
    source = FAKE_DISPLAY.format(module=module, width=width, height=height, buf=buf) + body
    proc = run_mpy(source)
    assert proc.returncode == 0, proc.stderr
    return Run(proc.stdout, width, height)


def compare(
    page: Page,
    frame: Canvas,
    expected: Canvas,
    tmp_path: Path,
    name: str,
    rotated: bool = False,
) -> None:
    """Rotated shapes are rasterised by framebuf.poly vs point-in-polygon: wider tolerance."""
    limit = MAX_ROTATED_MISMATCH if rotated else MAX_WIDGET_MISMATCH
    frame_limit = 2 * MAX_FRAME_MISMATCH if rotated else MAX_FRAME_MISMATCH
    worst = []
    for widget in page.widgets:
        ratio = frame.mismatch(expected, bounds(widget))
        if ratio > limit:
            worst.append(f"{widget.id}: {ratio:.1%}")
    total = frame.mismatch(expected)
    if worst or total > frame_limit:
        got = frame.save_png(tmp_path / f"{name}-device.png")
        ref = expected.save_png(tmp_path / f"{name}-reference.png")
        pytest.fail(f"frame differs ({total:.2%}; {', '.join(worst)}); see {got} and {ref}")


# ------------------------------------------------------------------ frame vs reference
@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"temperature": -12.3, "humidity": 100, "pressure": 950.0, "status": "Помилка"},
        {"temperature": 85.0, "humidity": 0, "pressure": 1050.0, "city": "Lviv"},
    ],
)
def test_frame_matches_reference(
    run_mpy: RunMpy,
    tmp_path: Path,
    weather: Project,
    ui_draw: ModuleType,
    overrides: dict[str, Any],
) -> None:
    body = f"p.update({json.dumps(overrides)})\nui.draw(p)\nframe(d)\n"
    run = run_page(run_mpy, tmp_path, weather, body)
    (frame,) = run.all("frame")
    page = weather.pages[0]
    expected = render_page(page, weather.display.size, overrides)
    compare(page, frame, expected, tmp_path, "weather")


def test_all_widget_types_portrait(run_mpy: RunMpy, tmp_path: Path, ui_draw: ModuleType) -> None:
    project = serializer.from_dict(
        {
            "display": {"rotation": 0},
            "pages": [
                {
                    "name": "demo",
                    "background": "#202020",
                    "parameters": [
                        {"name": "v", "type": "int", "min": 0, "max": 10, "default": 7},
                        {"name": "on", "type": "bool", "default": True},
                    ],
                    "widgets": [
                        {"id": "r", "type": "rect", "x": 5, "y": 5, "w": 100, "h": 60, "color": "#3366ff"},
                        {"id": "c", "type": "circle", "x": 40, "y": 20, "w": 81, "h": 41, "color": "#ff3300"},
                        {"id": "d", "type": "line", "x": 10, "y": 80, "w": 200, "h": 30, "color": "#ffff00"},
                        {"id": "s", "type": "line", "x": 220, "y": 10, "w": 5, "h": 120},
                        {"id": "t", "type": "text", "x": 5, "y": 120, "w": 230, "h": 30, "font_size": 24, "bind": "on", "format": "on=%s"},
                        {"id": "b", "type": "bar", "x": 5, "y": 160, "w": 230, "h": 30, "bind": "v", "format": "Level"},
                        {"id": "u", "type": "bar", "x": 5, "y": 200, "w": 230, "h": 12},
                        {"id": "a", "type": "arc", "x": 5, "y": 220, "w": 230, "h": 95, "bind": "v", "font_size": 24},
                    ],
                }
            ],
        }
    )  # fmt: skip
    run = run_page(run_mpy, tmp_path, project, "ui.draw(p)\nframe(d)\n")
    (frame,) = run.all("frame")
    expected = render_page(project.pages[0], project.display.size)
    compare(project.pages[0], frame, expected, tmp_path, "portrait")


# ------------------------------------------------------------------ update()
def test_update_writes_only_the_changed_widget(
    run_mpy: RunMpy, tmp_path: Path, weather: Project
) -> None:
    body = """
out("boxes", {w[0]: list(w[1:5]) for w in ui.WIDGETS})
ui.draw(p)
d.blits = []
p["humidity"] = 77
out("regions", ui.update(p))
out("blits", d.blits)
d.blits = []
out("regions", ui.update(p))
out("blits", d.blits)
d.blits = []
out("regions", ui.set_temperature(-3.5))
out("blits", d.blits)
d.blits = []
p["humidity"] = 10
p["pressure"] = 1000.0
out("regions", ui.update(p))
out("blits", d.blits)
"""
    run = run_page(run_mpy, tmp_path, weather, body)
    page = weather.pages[0]
    (box,) = run.all("boxes")  # as generated: text boxes cover glyphs sticking out
    assert box["h_bar"] == list(bounds(page.widget("h_bar")))  # type: ignore[arg-type]
    regions, blits = run.all("regions"), run.all("blits")

    assert regions == [1, 0, 1, 2]
    assert blits[1] == []  # nothing changed -> nothing written
    for changed, ids in ((0, ["h_bar"]), (2, ["t_val"]), (3, ["h_bar", "p_arc"])):
        allowed = [box[i] for i in ids]
        area = sum(b[2] * b[3] for b in blits[changed])
        assert area == sum(w * h for _, _, w, h in allowed), blits[changed]
        for x, y, w, h in blits[changed]:
            assert any(
                bx <= x and by <= y and x + w <= bx + bw and y + h <= by + bh
                for bx, by, bw, bh in allowed
            ), (x, y, w, h)


@pytest.mark.parametrize("buf", [16384, 1024])
def test_update_equals_full_redraw(
    run_mpy: RunMpy, tmp_path: Path, weather: Project, buf: int
) -> None:
    """Overlapping widgets are redrawn in layer order; small buffers draw in strips."""
    body = """
ui.draw(p)
p["temperature"] = 33.3
p["city"] = "Odesa"
p["status"] = "Увага"
ui.update(p)
frame(d)
fresh = FakeDisplay(d.width, d.height)
{module}.UI(fresh, buf_bytes={buf}).draw(p)
frame(fresh)
out("strips", len(fresh.blits))
""".format(module="ui_main", buf=buf)
    run = run_page(run_mpy, tmp_path, weather, body, buf=buf)
    updated, fresh = run.all("frame")
    assert updated.pixels == fresh.pixels
    (strips,) = run.all("strips")
    assert strips >= (1 if buf >= 320 * 240 * 2 else (320 * 240 * 2) // buf)


def test_generated_main_compiles(run_mpy: RunMpy, tmp_path: Path, weather: Project) -> None:
    generate(weather).write(tmp_path)
    (tmp_path / "example_main.py").write_bytes((tmp_path / "main.py").read_bytes())
    proc = run_mpy(
        "for name in ('example_main.py', 'ui_display.py', 'ui_main.py', 'ui_draw.py'):\n"
        "    compile(open(name).read(), name, 'exec')\n"
        "print('ok')\n"
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"


# ------------------------------------------------------------------ conditions (stage 04)
@pytest.mark.parametrize("alarm", [False, True])
@pytest.mark.parametrize("status", ["Норма", "Увага", "Помилка"])
def test_conditions_frame_matches_reference(
    run_mpy: RunMpy,
    tmp_path: Path,
    weather: Project,
    ui_draw: ModuleType,
    alarm: bool,
    status: str,
) -> None:
    """Every alarm/status combination: a fresh draw and an update() give the reference frame."""
    overrides: dict[str, ParamValue] = {"alarm": alarm, "status": status}
    body = f"""
ui.draw(p)
p.update({json.dumps(overrides).replace("true", "True").replace("false", "False")})
ui.update(p)
frame(d)
"""
    run = run_page(run_mpy, tmp_path, weather, body)
    (frame,) = run.all("frame")
    page = weather.pages[0]
    expected = render_page(page, weather.display.size, overrides)
    compare(page, frame, expected, tmp_path, f"alarm-{alarm}-{status}")


def overlap_project() -> Project:
    return serializer.from_dict(
        {
            "display": {"rotation": 1},
            "pages": [
                {
                    "name": "main",
                    "parameters": [
                        {"name": "on", "type": "bool"},
                        {"name": "t", "type": "int", "min": 0, "max": 100, "default": 10},
                    ],
                    "widgets": [
                        {"id": "under", "type": "rect", "x": 20, "y": 20, "w": 120, "h": 80, "color": "#3366ff"},
                        {"id": "badge", "type": "circle", "x": 60, "y": 40, "w": 41, "h": 41, "color": "#ff3300",
                         "rules": [{"if": ["on", "==", False], "set": "visible", "to": False}]},
                        {"id": "mover", "type": "rect", "x": 200, "y": 150, "w": 30, "h": 20, "color": "#ffff00",
                         "rules": [{"if": ["t", ">=", 50], "set": "x", "to": 40},
                                   {"if": ["t", ">=", 80], "set": "y", "to": 30}]},
                    ],
                }
            ],
        }
    )  # fmt: skip


def test_hide_show_and_move(run_mpy: RunMpy, tmp_path: Path, ui_draw: ModuleType) -> None:
    project = overlap_project()
    body = """
ui.draw(p)
for change in ({"on": True}, {"on": False}, {"t": 60}, {"t": 90}, {"t": 0, "on": True}):
    d.blits = []
    p.update(change)
    out("regions", ui.update(p))
    out("blits", d.blits)
    frame(d)
"""
    run = run_page(run_mpy, tmp_path, project, body)
    page = project.pages[0]
    states: list[dict[str, ParamValue]] = [
        {"on": True, "t": 10},
        {"on": False, "t": 10},
        {"on": False, "t": 60},
        {"on": False, "t": 90},
        {"on": True, "t": 0},
    ]
    frames = run.all("frame")
    for i, (state, frame) in enumerate(zip(states, frames, strict=True)):
        expected = render_page(page, project.display.size, state)
        compare(page, frame, expected, tmp_path, f"step{i}")

    regions, blits = run.all("regions"), run.all("blits")
    badge = (60, 40, 41, 41)
    # Showing/hiding the badge repaints only its own box (the rect under it included).
    for step in (0, 1):
        assert regions[step] == 1
        assert sum(w * h for _, _, w, h in blits[step]) == 41 * 41
        assert all(b[0] >= badge[0] and b[1] >= badge[1] for b in blits[step])
    # Moving repaints the old and the new place: two separate regions.
    assert regions[2] == 2
    assert {tuple(b) for b in blits[2]} >= {(200, 150, 30, 20), (40, 150, 30, 20)}
    # Moving back while the badge appears: old box, new box and the badge (merged with the old box).
    assert regions[4] >= 2


# ------------------------------------------------------------------ transforms (stage 05)
TRANSFORMS = ROOT / "examples" / "transforms.espui"


def single_widget_project(widget: dict[str, Any]) -> Project:
    return serializer.from_dict(
        {
            "display": {"rotation": 1},
            "pages": [
                {
                    "name": "main",
                    "background": "#102030",
                    "parameters": [{"name": "v", "type": "int", "min": 0, "max": 10, "default": 6}],
                    "widgets": [
                        {"id": "under", "type": "text", "x": 60, "y": 60, "w": 200, "h": 40,
                         "font_size": 32, "color": "#ffffff", "format": "UNDER"},
                        widget,
                    ],
                }
            ],
        }
    )  # fmt: skip


SHAPES = {
    "rect": {"type": "rect", "x": 110, "y": 80, "w": 100, "h": 50, "color": "#ff3366"},
    "circle": {"type": "circle", "x": 120, "y": 70, "w": 61, "h": 41, "color": "#33ff66", "pivot": "top_left"},
    "line": {"type": "line", "x": 100, "y": 120, "w": 120, "h": 0, "color": "#ffff00", "pivot": "left"},
    "text": {"type": "text", "x": 90, "y": 90, "w": 140, "h": 30, "font_size": 24, "color": "#66ccff", "format": "Hi 42"},
    "bar": {"type": "bar", "x": 80, "y": 90, "w": 160, "h": 36, "bind": "v", "format": "Lvl", "color": "#5dcaa5"},
    "arc": {"type": "arc", "x": 100, "y": 70, "w": 120, "h": 66, "bind": "v", "color": "#efa627"},
}  # fmt: skip


@pytest.mark.parametrize("angle", [0, 45, 90])
@pytest.mark.parametrize("kind", sorted(SHAPES))
def test_rotation_matches_reference(
    run_mpy: RunMpy, tmp_path: Path, ui_draw: ModuleType, kind: str, angle: int
) -> None:
    project = single_widget_project({"id": "w", **SHAPES[kind], "rotation_deg": angle})
    run = run_page(run_mpy, tmp_path, project, "ui.draw(p)\nframe(d)\n")
    (frame,) = run.all("frame")
    expected = render_page(project.pages[0], project.display.size)
    compare(project.pages[0], frame, expected, tmp_path, f"{kind}-{angle}", rotated=True)


@pytest.mark.parametrize("opacity", [0, 50, 100])
@pytest.mark.parametrize("kind", ["rect", "text", "bar"])
def test_opacity_matches_reference(
    run_mpy: RunMpy, tmp_path: Path, ui_draw: ModuleType, kind: str, opacity: int
) -> None:
    project = single_widget_project({"id": "w", **SHAPES[kind], "opacity": opacity})
    run = run_page(run_mpy, tmp_path, project, "ui.draw(p)\nframe(d)\n")
    (frame,) = run.all("frame")
    expected = render_page(project.pages[0], project.display.size)
    compare(project.pages[0], frame, expected, tmp_path, f"{kind}-{opacity}")
    if opacity == 0:
        blank = render_page(
            single_widget_project({"id": "w", "type": "rect", "w": 0, "h": 0}).pages[0],
            project.display.size,
        )  # fmt: skip
        assert frame.pixels == blank.pixels  # 0 %: not drawn at all


def test_translucent_rect_blends_with_text(run_mpy: RunMpy, tmp_path: Path) -> None:
    project = single_widget_project({"id": "w", **SHAPES["rect"], "opacity": 50})
    run = run_page(run_mpy, tmp_path, project, "ui.draw(p)\nframe(d)\n")
    (frame,) = run.all("frame")
    colors = {
        frame.get(x, y) for x in range(115, 205) for y in range(85, 125)
    }  # inside the corners
    from espui.core.colors import to_wire

    white, red, bg = to_wire("#ffffff"), to_wire("#ff3366"), to_wire("#102030")
    assert white not in colors
    assert red not in colors
    assert bg not in colors
    assert len(colors) == 2  # red over text, red over background


@pytest.fixture(scope="module")
def transforms() -> Project:
    return serializer.load(TRANSFORMS)


@pytest.mark.parametrize(
    "state",
    [
        {"humidity": 0, "temperature": -20.0, "alarm": False},
        {"humidity": 50, "temperature": 10.0, "alarm": True},
        {"humidity": 100, "temperature": 40.0, "alarm": False},
        {"humidity": 73, "temperature": 33.3, "alarm": True},
    ],
)
def test_transforms_example_matches_reference(
    run_mpy: RunMpy,
    tmp_path: Path,
    transforms: Project,
    ui_draw: ModuleType,
    state: dict[str, ParamValue],
) -> None:
    body = f"ui.draw(p)\np.update({_mpy(state)})\nui.update(p)\nframe(d)\n"
    run = run_page(run_mpy, tmp_path, transforms, body)
    (frame,) = run.all("frame")
    page = transforms.pages[0]
    expected = render_page(page, transforms.display.size, state)
    compare(page, frame, expected, tmp_path, "transforms", rotated=True)


def test_needle_and_marker_leave_no_traces(
    run_mpy: RunMpy, tmp_path: Path, transforms: Project
) -> None:
    """Sweep the needle (−180°…0°) and the marker (x 4…304): every update == a fresh draw."""
    body = """
ui.draw(p)
for h, t in ((0, -20.0), (10, -14.0), (35, 0.5), (50, 10.0), (90, 34.0), (100, 40.0), (5, -20.0)):
    p["humidity"] = h
    p["temperature"] = t
    d.blits = []
    ui.update(p)
    out("area", sum(b[2] * b[3] for b in d.blits))
    fresh = FakeDisplay(d.width, d.height)
    ui_main.UI(fresh).draw(p)
    out("same", bytes(fresh.frame) == bytes(d.frame))
"""
    run = run_page(run_mpy, tmp_path, transforms, body)
    assert run.all("same") == [True] * 7
    assert all(0 < area < 320 * 240 for area in run.all("area"))  # partial redraws only


def _mpy(state: dict[str, ParamValue]) -> str:
    return json.dumps(state).replace("true", "True").replace("false", "False")


# ------------------------------------------------------------------ chart (stage 06)
CHART = ROOT / "examples" / "chart.espui"


@pytest.fixture(scope="module")
def charts() -> Project:
    return serializer.load(CHART)


def test_chart_example_matches_reference(
    run_mpy: RunMpy, tmp_path: Path, charts: Project, ui_draw: ModuleType
) -> None:
    run = run_page(run_mpy, tmp_path, charts, "ui.draw(p)\nframe(d)\n")
    (frame,) = run.all("frame")
    page = charts.pages[0]
    compare(page, frame, render_page(page, charts.display.size), tmp_path, "charts")


def series_literal(points: list[tuple[Any, float]]) -> str:
    return "[" + ", ".join(f"{{{x!r}: {y!r}}}" for x, y in points) + "]"


@pytest.mark.parametrize("style", ["line", "dots", "bars"])
@pytest.mark.parametrize("x_kind", ["number", "label"])
@pytest.mark.parametrize("bounds", [(None, None), (5.0, 15.0)])
def test_chart_styles_match_reference(
    run_mpy: RunMpy,
    tmp_path: Path,
    ui_draw: ModuleType,
    style: str,
    x_kind: str,
    bounds: tuple[float | None, float | None],
) -> None:
    labels = ["00:00", "06:00", "12:00", "18:00", "24:00", "x"]
    xs: list[Any] = [0, 4.5, 9, 13.5, 18, 22.5] if x_kind == "number" else labels
    ys = [12.0, 3.5, 18.0, 25.0, 9.0, 14.0]
    project = serializer.from_dict(
        {
            "display": {"rotation": 1},
            "pages": [{
                "name": "main",
                "parameters": [{"name": "s", "type": "series", "x_kind": x_kind, "min": 0, "max": 20,
                                "max_points": 8, "default": [{"x": x, "y": y} for x, y in zip(xs, ys, strict=True)]}],
                "widgets": [{"id": "c", "type": "chart", "x": 20, "y": 30, "w": 280, "h": 170, "bind": "s",
                             "color": "#4da3ff", "chart": {"axis_x": "time", "axis_y": "val", "style": style,
                                                           "y_min": bounds[0], "y_max": bounds[1]}}],
            }],
        }
    )  # fmt: skip
    run = run_page(run_mpy, tmp_path, project, "ui.draw(p)\nframe(d)\n")
    (frame,) = run.all("frame")
    page = project.pages[0]
    expected = render_page(page, project.display.size)
    compare(page, frame, expected, tmp_path, f"chart-{style}-{x_kind}")


def test_chart_update_on_append_and_empty(
    run_mpy: RunMpy, tmp_path: Path, charts: Project, ui_draw: ModuleType
) -> None:
    body = f"""
ui.draw(p)
d.blits = []
p["temp_day"].append({{24: 17.5}})   # same list object: update() must still see the change
out("regions", ui.update(p))
out("blits", d.blits)
fresh = FakeDisplay(d.width, d.height)
ui_main.UI(fresh).draw(p)
out("same", bytes(fresh.frame) == bytes(d.frame))
d.blits = []
out("regions", ui.update(p))
p["temp_day"] = []
ui.update(p)
frame(d)
p["temp_day"] = {series_literal([(3, 1.0), (1, 5.0), (2, 9.0)])}   # unsorted numeric X
ui.update(p)
frame(d)
"""
    run = run_page(run_mpy, tmp_path, charts, body)
    regions = run.all("regions")
    assert regions == [1, 0]
    (blits,) = run.all("blits")
    assert sum(b[2] * b[3] for b in blits) == 150 * 110  # only the "day" chart
    assert all(b[0] >= 6 and b[0] + b[2] <= 156 and b[1] >= 6 and b[1] + b[3] <= 116 for b in blits)
    assert run.all("same") == [True]

    page = charts.pages[0]
    empty, unsorted = run.all("frame")
    for got, value in (
        (empty, []),
        (unsorted, [SeriesPoint(x=1, y=5), SeriesPoint(x=2, y=9), SeriesPoint(x=3, y=1)]),
    ):
        expected = render_page(page, charts.display.size, {"temp_day": value})
        compare(page, got, expected, tmp_path, "chart-update")


# ------------------------------------------------------------------ fonts (stage 07)
@pytest.mark.parametrize("key", ["serif", "mono", "pixel"])
def test_font_sizes_match_reference(
    run_mpy: RunMpy, tmp_path: Path, ui_draw: ModuleType, key: str
) -> None:
    """Text of 8, 12, 16, 24 and 40 px, three alignments and a cut with '…', glyph for glyph."""
    texts = [
        (8, "Погода · Київ", "left"),
        (12, "ПЕРЕГРІВ", "center"),
        (16, "Вологість 40 %", "right"),
        (24, "Ґанок, їжак: 21.5°", "left"),
        (40, "Єнот ʼ Щука ще довше", "left"),
    ]
    widgets = []
    y = 2
    for i, (size, text, align) in enumerate(texts):
        h = size * 3 // 2
        widgets.append({"id": f"t{i}", "type": "text", "x": 4, "y": y, "w": 312, "h": h,
                        "font": key, "font_size": size, "format": text, "align": align})  # fmt: skip
        y += h + 2
    project = serializer.from_dict(
        {"display": {"rotation": 1}, "pages": [{"name": "main", "widgets": widgets}]}
    )
    run = run_page(run_mpy, tmp_path, project, "ui.draw(p)\nframe(d)\n")
    (frame,) = run.all("frame")
    page = project.pages[0]
    expected = render_page(page, project.display.size)
    assert frame.mismatch(expected) == 0, frame.save_png(tmp_path / f"{key}-device.png")


# ------------------------------------------------------------------ images (stage 08)
IMAGES = ROOT / "examples" / "images.espui"


@pytest.fixture(scope="module")
def pictures() -> Project:
    return serializer.load(IMAGES)


def test_images_example_matches_reference(
    run_mpy: RunMpy, tmp_path: Path, pictures: Project, ui_draw: ModuleType
) -> None:
    run = run_page(run_mpy, tmp_path, pictures, "ui.draw(p)\nframe(d)\n")
    (frame,) = run.all("frame")
    page = pictures.pages[0]
    expected = render_page(page, pictures.display.size, images=pictures.images)
    compare(page, frame, expected, tmp_path, "images")


def test_icon_from_parameter_and_missing_file(
    run_mpy: RunMpy, tmp_path: Path, pictures: Project, ui_draw: ModuleType
) -> None:
    body = """
ui.draw(p)
for path in ("/img/cloud.bin", "/img/rain.bin", "/img/none.bin", "", "/img/sun.bin"):
    d.blits = []
    out("regions", ui.set_weather_icon(path))
    out("blits", d.blits)
    frame(d)
out("row", len(ui_draw._row[0]))
"""
    run = run_page(run_mpy, tmp_path, pictures, body)
    assert run.all("regions") == [1] * 5
    for blits in run.all("blits"):  # only the 64x64 icon is rewritten
        assert sum(b[2] * b[3] for b in blits) == 64 * 64
        assert all(
            b[0] >= 20 and b[0] + b[2] <= 84 and b[1] >= 20 and b[1] + b[3] <= 84 for b in blits
        )
    # RAM for pictures: one row of the picture being drawn (the 64 px icon was the last one).
    assert run.all("row") == [2 * 64]
    page = pictures.pages[0]
    for path, got in zip(
        ("/img/cloud.bin", "/img/rain.bin", "/img/none.bin", "", "/img/sun.bin"),
        run.all("frame"),
        strict=True,
    ):
        expected = render_page(
            page, pictures.display.size, {"weather_icon": path}, images=pictures.images
        )
        compare(page, got, expected, tmp_path, f"icon{path.replace('/', '_')}")


def test_animations_tick_and_play_once(
    run_mpy: RunMpy, tmp_path: Path, pictures: Project, ui_draw: ModuleType
) -> None:
    """spinner: 12 frames, loop; loading: 8 frames, once (stops on the last frame)."""
    body = """
import time
ui.draw(p)
t0 = time.ticks_ms() + 1000
out("idle", ui.tick(t0 - 1000))      # nothing is due yet
for k in range(1, 15):
    d.blits = []
    n = ui.tick(t0 + 1000 * k)          # both animations are due every time
    out("tick", [n, sum(b[2] * b[3] for b in d.blits)])
frame(d)
out("restart", ui.play_loading())
frame(d)
"""
    run = run_page(run_mpy, tmp_path, pictures, body)
    assert run.all("idle") == [0]
    ticks = run.all("tick")
    spinner, loading = 64 * 64, 128 * 32
    # Frames 1..7 of "loading" are drawn together with the spinner, then only the spinner moves.
    assert ticks[:7] == [[2, spinner + loading]] * 7
    assert ticks[7:] == [[1, spinner]] * 7
    after_ticks, after_restart = run.all("frame")
    assert run.all("restart") == [1]
    page = pictures.pages[0]
    size = pictures.display.size
    for got, frames, name in (
        (after_ticks, {"spinner": 14 % 12, "loading": 7}, "anim-ticks"),
        (after_restart, {"spinner": 14 % 12, "loading": 0}, "anim-restart"),
    ):
        expected = render_page(page, size, images=pictures.images, frames=frames)
        compare(page, got, expected, tmp_path, name)


# ------------------------------------------------------------------ pages (stage 09)
def test_two_pages_switch(run_mpy: RunMpy, tmp_path: Path, ui_draw: ModuleType) -> None:
    """Both modules run side by side, share one region buffer and redraw fully on a switch."""
    project = serializer.load(ROOT / "examples" / "pages.espui")
    body = """
import ui_settings
pages = {
    "main": (ui, p),
    "settings": (ui_settings.UI(d), dict(ui_settings.DEFAULTS)),
}

def show(name):
    global ui, p
    ui, p = pages[name]
    d.blits = []
    ui.draw(p)
    out("full", sum(b[2] * b[3] for b in d.blits))
    frame(d)

show("main")
show("settings")
pages["settings"][1]["wifi"] = False
pages["settings"][1]["brightness"] = 25
ui.update(p)
frame(d)
show("main")
out("buffers", sorted(ui_draw._buffers))
pages["main"][0]._mv[0] = 123  # one buffer: a byte written via one page is seen by the other
out("shared", pages["settings"][0]._mv[0] == 123)
"""
    run = run_page(run_mpy, tmp_path, project, body)
    assert run.all("full") == [320 * 240] * 3  # a switch always redraws the whole screen
    assert run.all("buffers") == [["region"]]
    assert run.all("shared") == [True]
    main_page, settings = project.pages
    size = project.display.size
    first, second, changed, back = run.all("frame")
    compare(main_page, first, render_page(main_page, size), tmp_path, "page-main")
    compare(settings, second, render_page(settings, size), tmp_path, "page-settings")
    expected = render_page(settings, size, {"wifi": False, "brightness": 25})
    compare(settings, changed, expected, tmp_path, "page-settings-changed")
    assert back.pixels == first.pixels


# ------------------------------------------------------------------ release examples (stage 15)
@pytest.mark.parametrize(
    "state",
    [
        {},
        {"temperature": 31.0, "co2": 1600, "battery": 15},
        {"temperature": -20.0, "humidity": 100, "co2": 1200},
    ],
)
def test_sensors_dashboard_matches_reference(
    run_mpy: RunMpy, tmp_path: Path, state: dict[str, ParamValue]
) -> None:
    project = serializer.load(ROOT / "examples" / "sensors.espui")
    body = f"ui.draw(p)\np.update({_mpy(state)})\nui.update(p)\nframe(d)\n"
    run = run_page(run_mpy, tmp_path, project, body)
    (frame,) = run.all("frame")
    page = project.pages[0]
    compare(
        page,
        frame,
        render_page(page, project.display.size, state),
        tmp_path,
        "sensors",
        rotated=True,
    )
