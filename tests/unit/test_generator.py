"""MicroPython generator: generated files, warnings, CLI."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from syrupy.assertion import SnapshotAssertion

from espui.cli import main
from espui.core import serializer
from espui.core.colors import to_wire
from espui.core.evaluate import format_value, number_label
from espui.core.models import Project
from espui.generators.micropython import generator
from espui.generators.micropython.drivers import DRIVERS, RUNTIME_DIR
from espui.generators.micropython.generator import MANIFEST, GenerationError, generate

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "weather.espui"


@pytest.fixture(scope="module")
def weather() -> Project:
    return serializer.load(EXAMPLE)


def project(widgets: list[dict[str, Any]], **display: Any) -> Project:
    return serializer.from_dict(
        {
            "display": display,
            "pages": [
                {
                    "name": "main",
                    "parameters": [
                        {"name": "t", "type": "float", "min": 0, "max": 50, "default": 20},
                        {"name": "n", "type": "int", "min": 0, "max": 10, "default": 3},
                        {"name": "s", "type": "series", "min": 0, "max": 1},
                    ],
                    "widgets": widgets,
                },
                {"name": "other"},
            ],
        }
    )


# ------------------------------------------------------------------ files
def test_files(weather: Project) -> None:
    result = generate(weather, source="weather.espui")
    assert list(result.files) == [
        "ui_display.py",
        "ui_st7789.py",
        "ui_draw.py",
        "ui_main.py",
        "ui_fonts.py",
        "main.py",
    ]
    assert result.warnings == ()
    assert result.page == "main"


@pytest.mark.parametrize("name", ["ui_main.py", "main.py", "ui_display.py"])
def test_snapshot(weather: Project, name: str, snapshot: SnapshotAssertion) -> None:
    files = generate(weather, source="weather.espui").files
    assert files[name].decode("utf-8") == snapshot


@pytest.mark.parametrize("name", ["weather", "transforms", "chart", "images", "pages", "sensors"])
def test_committed_example_is_up_to_date(name: str) -> None:
    """examples/<name>_mpy is what `espui generate examples/<name>.espui` produces."""
    source = ROOT / "examples" / f"{name}.espui"
    files = generate(serializer.load(source), source=source.name).files
    out = ROOT / "examples" / f"{name}_mpy"
    on_disk = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    assert on_disk - {MANIFEST} == set(files)
    for file, data in files.items():
        assert (out / file).read_bytes() == data, f"regenerate examples/{name}_mpy: {file}"


def test_runtime_files_are_copied_unchanged() -> None:
    result = generate(project([], driver="st7789py"))
    assert list(result.files) == [
        "ui_display.py",
        "st7789py.py",
        "st7789py.LICENSE",
        "ui_draw.py",
        "ui_main.py",
        "ui_other.py",
        "main.py",
    ]
    vendored = result.files["st7789py.py"]
    assert hashlib.sha256(vendored).hexdigest() == DRIVERS["st7789py"].sha256
    assert result.files["ui_draw.py"] == (RUNTIME_DIR / "ui_draw.py").read_bytes()


@pytest.mark.parametrize(
    ("display", "expected"),
    [
        (
            {},
            ['DRIVER = "builtin"', "SPI_ID = 2  # ESP32-S3", "ROTATION = 0", "SPI_HZ = 40_000_000"],
        ),
        (
            {
                "mcu": "esp32c3",
                "driver": "st7789py",
                "rotation": 3,
                "spi_hz": 26_000_000,
                "pins": {"sck": 4, "mosi": 6, "dc": 7, "cs": 10, "rst": 3, "bl": None},
            },
            [
                'DRIVER = "st7789py"',
                "SPI_ID = 1  # ESP32-C3",
                "ROTATION = 3",
                "SPI_HZ = 26_000_000",
                '"blk": None',
            ],
        ),
    ],
)
def test_display_settings(display: dict[str, Any], expected: list[str]) -> None:
    text = generate(project([], **display)).files["ui_display.py"].decode()
    for snippet in expected:
        assert snippet in text
    assert "INVERT = True" in text
    assert "def create(" in text  # the adapter itself is kept


def test_generated_code_is_valid_python(tmp_path: Path, weather: Project) -> None:
    for name, data in generate(weather).files.items():
        if name.endswith(".py"):
            compile(data, name, "exec")


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff not installed")
def test_generated_code_passes_ruff(tmp_path: Path, weather: Project) -> None:
    result = generate(weather)
    result.write(tmp_path)
    for name in ("ui_main.py", "main.py"):
        assert (tmp_path / name).exists()
    run = subprocess.run(
        ["ruff", "check", "--isolated", "--select", "E,F,W,B", "--line-length", "100",
         "ui_main.py", "main.py", "ui_display.py", "ui_draw.py"],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert run.returncode == 0, run.stdout


# ------------------------------------------------------------------ widgets
def test_widget_code() -> None:
    files = generate(
        project(
            [
                {"id": "r", "type": "rect", "x": 1, "y": 2, "w": 30, "h": 20, "color": "#ff0000"},
                {"id": "l", "type": "line", "x": 5, "y": 5, "w": 40, "h": 0},
                {"id": "v", "type": "value", "x": 0, "y": 30, "w": 100, "h": 20, "bind": "t", "format": "%d °C"},
                {"id": "b", "type": "bar", "x": 0, "y": 60, "w": 100, "h": 36},
                {"id": "a", "type": "arc", "x": 0, "y": 100, "w": 100, "h": 50, "bind": "n"},
            ]
        )
    ).files["ui_main.py"].decode()  # fmt: skip
    assert f"_d.rrect(fb, 1 - ox, 2 - oy, 30, 20, 4, 0x{to_wire('#ff0000'):04X})" in files
    assert '("l", 5, 5, 42, 2, ())' in files  # a 2 px line touches w + 2
    assert '_d.fmt("%d °C", p["t"])' in files
    assert '_d.frac(p["n"], 0, 10)' in files
    assert '_d.num(p["n"], False)' in files
    assert "0.5," in files  # unbound bar: placeholder fill
    assert 'DEFAULTS = {\n    "t": 20.0,  # float, 0…50' in files
    assert '"s": [],  # series' in files
    assert "def set_t(self, value):" in files


def test_text_fonts_and_alignment() -> None:
    result = generate(
        project(
            [
                {"id": "a", "type": "text", "w": 100, "h": 40, "font_size": 40, "format": "Київ"},
                {"id": "b", "type": "text", "w": 100, "h": 30, "font": "mono", "font_size": 12,
                 "align": "center", "format": "Привіт"},
                {"id": "c", "type": "value", "w": 100, "h": 30, "font": "pixel", "font_size": 16,
                 "bind": "t", "format": "%.1f°", "align": "right"},
                {"id": "d", "type": "bar", "y": 40, "w": 100, "h": 36, "font_size": 12, "bind": "n"},
            ]
        )
    )  # fmt: skip
    text = result.files["ui_main.py"].decode()
    assert "import ui_fonts as _f" in text
    assert '_d.label(fb, "Київ", 0 - ox, 0 - oy, 100, 40, 0xFFFF, _f.SERIF_40, _d.LEFT)' in text
    assert '_d.label(fb, "Привіт", 0 - ox, 0 - oy, 100, 30, 0xFFFF, _f.MONO_12, _d.CENTER)' in text
    assert "_f.PIXEL_16, _d.RIGHT)" in re.sub(r"\s+", " ", text).replace(", )", ")")
    assert "_f.SERIF_12," in text
    kb = f"{len(result.files['ui_fonts.py']) / 1024:.1f}".replace(".", ",")
    assert result.notes == (
        f"Шрифти: Literata 12/40 px · JetBrains Mono 12 px · Press Start 2P 16 px — ui_fonts.py {kb} КБ",
    )


def test_text_box_covers_glyphs() -> None:
    """Tall letters (Ї) and descenders stick out of a small box: the redrawn box grows."""
    text = (
        generate(
            project(
                [
                    {
                        "id": "a",
                        "type": "text",
                        "x": 10,
                        "y": 50,
                        "w": 60,
                        "h": 12,
                        "font_size": 24,
                        "format": "Їжу",
                    }
                ]
            )
        )
        .files["ui_main.py"]
        .decode()
    )
    box = re.search(r'\("a", (-?\d+), (-?\d+), (\d+), (\d+), \(\)\)', text)
    assert box is not None
    x, y, w, h = map(int, box.groups())
    assert y < 50
    assert y + h > 62
    assert x <= 10
    assert x + w >= 70


def test_warnings_for_later_stages() -> None:
    result = generate(project([{"id": "r", "type": "rect"}]))
    assert result.warnings == ()
    assert result.pages == ("main", "other")


def test_page_selection() -> None:
    assert generate(project([]), "other").page == "other"
    assert "ui_other.py" in generate(project([]), "other").files
    with pytest.raises(GenerationError, match="Немає сторінки «nope»; є: main, other"):
        generate(project([]), "nope")


# ------------------------------------------------------------------ runtime parity (CPython)
@pytest.fixture(scope="module")
def ui_draw() -> Any:
    sys.path.insert(0, str(RUNTIME_DIR))
    try:
        import ui_draw  # type: ignore[import-not-found]

        yield ui_draw
    finally:
        sys.path.remove(str(RUNTIME_DIR))
        sys.modules.pop("ui_draw", None)


FORMATS = [
    "%.1f°C",
    "%d %%",
    "%s",
    "%f",
    "%.0f",
    "%d/%d",
    "50%",
    "%x",
    "%.f",
    "%.2%",
    "%",
    "a%.3fb",
]
VALUES = [21.55, 2.5, -2.5, 0, 7, True, "OK", 1013.25]


@pytest.mark.parametrize("fmt", FORMATS)
def test_runtime_fmt_matches_core(ui_draw: Any, fmt: str) -> None:
    for value in VALUES:
        assert ui_draw.fmt(fmt, value) == format_value(fmt, value), (fmt, value)


def test_runtime_num_matches_core(ui_draw: Any) -> None:
    page = serializer.from_dict(
        {"pages": [{"name": "m", "parameters": [
            {"name": "f", "type": "float", "min": 0, "max": 1, "default": 0},
            {"name": "i", "type": "int", "min": 0, "max": 1, "default": 0},
        ]}]}
    ).pages[0]  # fmt: skip
    f, i = page.parameters
    for value in (21.25, 3, 0.05):
        assert ui_draw.num(value, True) == number_label(f, value)
    assert ui_draw.num(7, False) == number_label(i, 7)


def test_runtime_helpers(ui_draw: Any) -> None:
    assert ui_draw.frac(5, 0, 10) == 0.5
    assert ui_draw.frac(-1, 0, 10) == 0.0
    assert ui_draw.frac(20, 0, 10) == 1.0
    assert ui_draw.frac("x", 0, 10) == 0.0
    assert ui_draw.label_origin(10, 20, 100, 50, 40, ui_draw.LEFT) == (10, 60)
    assert ui_draw.label_origin(10, 20, 100, 50, 40, ui_draw.CENTER) == (40, 60)
    assert ui_draw.label_origin(10, 20, 100, 50, 40, ui_draw.RIGHT) == (70, 60)
    assert ui_draw.merge([(0, 0, 10, 10), (5, 5, 10, 10), (50, 50, 1, 1)]) == [
        (0, 0, 15, 15),
        (50, 50, 1, 1),
    ]
    assert ui_draw.clip((-5, -5, 10, 10), 320, 240) == (0, 0, 5, 5)
    assert ui_draw.clip((400, 0, 10, 10), 320, 240) is None
    for name, hex_color in (
        ("LABEL_COLOR", "#8fa3ad"),
        ("VALUE_COLOR", "#ffffff"),
        ("TRACK_COLOR", "#23343f"),
    ):
        assert getattr(ui_draw, name) == to_wire(hex_color)


def test_runtime_font_matches_assets(tmp_path: Path) -> None:
    """ui_fonts.Font (board) and BitmapFont (preview) measure and cut text the same way."""
    from espui.assets.fonts import rasterize
    from espui.generators.micropython.fonts import render_module

    chars = "Погода · Київ 0123456789.,-°C"
    bitmap = rasterize("serif", 16, chars)
    (tmp_path / "ui_fonts.py").write_text(render_module({("serif", 16): bitmap}), "utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        import ui_fonts  # type: ignore[import-not-found]

        font = ui_fonts.SERIF_16
        assert (font.ascent, font.descent, font.size) == (bitmap.ascent, bitmap.descent, 16)
        for text in ("Погода · Київ", "21.5°C", "Ж!"):  # Ж and ! are not in the set: '?'
            assert font.width(text) == bitmap.width(text)
            for width in (0, 5, 30, 60, 200):
                assert font.fit(text, width) == bitmap.fit(text, width)
        g = bitmap.glyphs["К"]
        off, w, h, left, top, adv = font.glyph("К")
        assert (w, h, left, top, adv) == (g.width, g.height, g.left, g.top, g.advance)
        assert bytes(font._data[off : off + len(g.rows)]) == g.rows
        assert font.glyph("Ж") == font.glyph("?")
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("ui_fonts", None)


# ------------------------------------------------------------------ CLI
def test_cli_generate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["generate", str(EXAMPLE), "-o", str(tmp_path / "out")]) == 0
    out = capsys.readouterr().out
    assert "Сторінка «main»" in out
    assert (tmp_path / "out" / "ui_main.py").is_file()


def test_cli_generate_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["generate", str(EXAMPLE), "-o", str(tmp_path), "--page", "x"]) == 1
    assert "Помилка: Немає сторінки «x»" in capsys.readouterr().err
    assert main(["generate", str(tmp_path / "none.espui"), "-o", str(tmp_path)]) == 1
    assert "не знайдено" in capsys.readouterr().err


def test_cli_generate_warnings(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "p.espui"
    serializer.save(project([{"id": "i", "type": "image", "rotation_deg": 10}]), src)
    assert main(["generate", str(src), "-o", str(tmp_path / "out")]) == 0
    assert "Увага: Елемент «i»: поворот картинок не підтримується" in capsys.readouterr().err


# ------------------------------------------------------------------ conditions (stage 04)
def conditions_project(rules: list[dict[str, Any]], kind: str = "text") -> Project:
    return serializer.from_dict(
        {
            "pages": [
                {
                    "name": "main",
                    "parameters": [
                        {"name": "t", "type": "float", "min": 0, "max": 50, "default": 20},
                        {"name": "on", "type": "bool"},
                        {"name": "mode", "type": "enum", "values": ["a", "b"]},
                        {"name": "s", "type": "str", "max_len": 8},
                    ],
                    "widgets": [
                        {"id": "w", "type": kind, "x": 10, "y": 20, "w": 50, "h": 30,
                         "bind": "t" if kind == "value" else None, "format": "%.1f", "rules": rules},
                    ],
                }
            ]
        }
    )  # fmt: skip


def page_code(project: Project) -> str:
    result = generate(project)
    assert result.warnings == ()
    return result.files["ui_main.py"].decode()


def test_condition_code_per_type() -> None:
    text = page_code(
        conditions_project(
            [
                {"if": ["on", "==", True], "set": "color", "to": "#ff0000"},
                {"if": ["on", "==", False], "set": "visible", "to": False},
                {"if": ["mode", "!=", "a"], "set": "text", "to": "B=%.0f"},
                {"if": ["s", "==", "x y"], "set": "color", "to": "#00ff00"},
                {"if": ["t", "≥", 40], "set": "color", "to": "#0000ff"},
            ],
            kind="value",
        )
    )
    body = text[text.index("def _draw_w(") :]
    assert body.splitlines()[1:] == [
        "        # redrawn when changed: t, on, mode, s",
        "        p = self.p",
        "        color = 0xFFFF",
        '        f = "%.1f"',
        "        visible = True",
        "        # conditions, top to bottom: the lowest one that matches wins",
        '        if p["on"]:',
        f"            color = 0x{to_wire('#ff0000'):04X}",
        '        if not p["on"]:',
        "            visible = False",
        '        if p["mode"] != "a":',
        '            f = "B=%.0f"',
        '        if p["s"] == "x y":',
        f"            color = 0x{to_wire('#00ff00'):04X}",
        '        if p["t"] >= 40:',
        f"            color = 0x{to_wire('#0000ff'):04X}",
        "        if not visible:",
        "            return",
        '        _d.label(fb, _d.fmt(f, p["t"]), 10 - ox, 20 - oy, 50, 30, color, _f.SERIF_24, _d.LEFT)',
    ]
    assert re.search(r'\("w", 10, \d+, \d+, \d+, \("t", "on", "mode", "s"\)\)', text)
    assert "_box_w" not in text


def test_condition_moves_widget() -> None:
    text = page_code(
        conditions_project(
            [
                {"if": ["t", ">", 30], "set": "x", "to": 100.5},
                {"if": ["on", "==", True], "set": "y", "to": 0},
            ],
            kind="line",
        )
    )
    draw = text[text.index("def _draw_w(") : text.index("def _box_w(")]
    assert "x = 10" in draw
    assert "x = 101" in draw  # rounded half up, as core.evaluate does
    assert "_d.line(fb, x - ox, y - oy, 50, 30, 0xFFFF)" in draw
    box = text[text.index("def _box_w(") :].splitlines()
    assert box[1:] == [
        "        p = self.p",
        "        x = 10",
        "        y = 20",
        "        # conditions, top to bottom: the lowest one that matches wins",
        '        if p["t"] > 30:',
        "            x = 101",
        '        if p["on"]:',
        "            y = 0",
        "        return (x, y, 52, 32)",
    ]


def test_only_y_moves() -> None:
    text = page_code(conditions_project([{"if": ["on", "==", True], "set": "y", "to": 5}], "rect"))
    assert "return (10, y, 50, 30)" in text


def test_remove_parameter_cleans_rules(weather: Project) -> None:
    project = weather.model_copy(deep=True)
    page = project.pages[0]
    assert page.remove_parameter("alarm") == 2
    assert page.parameter("alarm") is None
    assert all(r.param != "alarm" for w in page.widgets for r in w.rules)
    assert page.remove_parameter("city") == 0
    assert page.widget("city_txt").bind is None  # type: ignore[union-attr]
    generate(project)  # still generates


# ------------------------------------------------------------------ transforms (stage 05)
def transform_code(widget: dict[str, Any], params: list[dict[str, Any]] | None = None) -> str:
    data = {
        "pages": [
            {
                "name": "main",
                "parameters": params
                or [
                    {"name": "h", "type": "int", "min": 0, "max": 100, "default": 50},
                    {"name": "on", "type": "bool"},
                ],
                "widgets": [{"id": "w", "x": 10, "y": 20, "w": 40, "h": 30, **widget}],
            }
        ]
    }
    return page_code(serializer.from_dict(data))


def draw_body(text: str) -> list[str]:
    start = text.index("def _draw_w(")
    end = text.find("\n\n", start)
    return [line.strip() for line in text[start : end if end > 0 else None].splitlines()[1:]]


def test_mapping_code() -> None:
    text = transform_code(
        {"type": "rect", "rules": [
            {"param": "h", "prop": "x", "at_min": 0, "at_max": 100},
            {"param": "h", "prop": "angle", "at_min": -90, "at_max": 90},
            {"if": ["on", "==", True], "set": "x", "to": 5},
        ]}
    )  # fmt: skip
    assert draw_body(text) == [
        "# redrawn when changed: h, on",
        "p = self.p",
        "angle = 0.0",
        "x = 10",
        'x = _d.lin(p["h"], 0, 100, 0.0, 100.0)',
        'angle = _d.lin(p["h"], 0, 100, -90.0, 90.0)',
        "# conditions, top to bottom: the lowest one that matches wins",
        'if p["on"]:',
        "x = 5",
        "x = _d.rnd(x)",
        "r = _d.rot(angle, x - ox + 20, 35 - oy)",
        "_d.rrect(fb, x - ox, 20 - oy, 40, 30, 4, 0xFFFF, r)",
    ]
    assert "return _d.rbox(x, 20, 40, 30, angle, x + 20, 35)" in text


def test_static_rotation_and_opacity() -> None:
    text = transform_code(
        {"type": "line", "rotation_deg": 45, "opacity": 40, "pivot": {"x": 0, "y": 0}}
    )
    assert draw_body(text) == [
        "r = _d.rot(45.0, 10 - ox, 20 - oy)",
        "fb = self.begin_alpha(fb)  # opacity 40 %",
        "_d.line(fb, 10 - ox, 20 - oy, 40, 30, 0xFFFF, r)",
        "self.end_alpha(13)",
    ]
    assert "USES_ALPHA = True" in text
    assert "return _d.rbox(10, 20, 42, 32, 45.0, 10, 20)" in text  # 2 px line: w + 2


def test_dynamic_opacity() -> None:
    text = transform_code(
        {
            "type": "text",
            "format": "A",
            "rules": [{"if": ["on", "==", False], "set": "opacity", "to": 30}],
        }
    )
    body = draw_body(text)
    assert body[-8:] == [
        "level = _d.alpha(opacity)",
        "if level == 0:",
        "return",
        "if level < 32:",
        "fb = self.begin_alpha(fb)",
        '_d.label(fb, "A", 10 - ox, 20 - oy, 40, 30, 0xFFFF, _f.SERIF_16, _d.LEFT)',
        "if level < 32:",
        "self.end_alpha(level)",
    ]


def test_zero_opacity_is_never_drawn() -> None:
    text = transform_code({"type": "rect", "opacity": 0})
    assert draw_body(text) == ["return  # opacity 0 %: never drawn"]
    assert "USES_ALPHA" not in text


def test_opaque_page_has_no_alpha_buffer(weather: Project) -> None:
    assert "USES_ALPHA" not in generate(weather).files["ui_main.py"].decode()


def test_dynamic_rotation_of_big_text_warns() -> None:
    def warnings(w: int, h: int, dynamic: bool) -> tuple[str, ...]:
        rule = [{"param": "h", "prop": "angle", "at_min": 0, "at_max": 90}] if dynamic else []
        widget = {"id": "w", "type": "text", "w": w, "h": h, "rotation_deg": 10, "rules": rule}
        data = {"pages": [{"name": "main", "parameters": [
            {"name": "h", "type": "int", "min": 0, "max": 100, "default": 50}], "widgets": [widget]}]}  # fmt: skip
        return generate(serializer.from_dict(data)).warnings

    assert warnings(200, 60, dynamic=False) == ()
    assert warnings(60, 60, dynamic=True) == ()
    (message,) = warnings(200, 60, dynamic=True)
    assert "текст 200×60 з кутом від параметра повертається попіксельно" in message


def test_runtime_transform_helpers(ui_draw: Any) -> None:
    from espui.core.colors import blend, parse_hex, rgb565, to_hex
    from espui.core.evaluate import lin, round_half_up
    from espui.core.models import IntParameter

    param = IntParameter(name="h", min=0, max=100, default=0)
    for v in (-10, 0, 25, 50, 100, 140):
        assert ui_draw.lin(v, 0, 100, -90, 90) == lin(param, v, -90, 90)
    assert ui_draw.lin(True, 0, 100, 5, 9) == 5
    for half in (0.5, 1.5, -0.5, 2.49):
        assert ui_draw.rnd(half) == round_half_up(half)
    for opacity in (-5, 0, 1, 50, 99, 100, 120):
        assert ui_draw.alpha(opacity) == generator._alpha_level(opacity)
    assert ui_draw.rot(0, 1, 1) is None
    assert ui_draw.rot(360, 1, 1) is None
    r = ui_draw.rot(90, 0, 0)
    assert ui_draw.tpi(r, 10, 0) == (0, 10)  # clockwise on screen (y down)
    assert ui_draw.rbox(0, 0, 10, 4, 0, 0, 0) == (0, 0, 10, 4)
    bx, by, bw, bh = ui_draw.rbox(0, 0, 10, 4, 90, 0, 0)  # turned box: x -4..0, y 0..10
    assert bx <= -4
    assert by <= 0
    assert bx + bw >= 0
    assert by + bh >= 10
    assert bw <= 9
    assert bh <= 14
    # RGB565 blend is close to the 8-bit blend of the preview.
    for fg, bg, a in (
        ("#ff3366", "#ffffff", 16),
        ("#123456", "#abcdef", 8),
        ("#000000", "#ffffff", 32),
    ):
        got = ui_draw.blend565(rgb565(parse_hex(fg)), rgb565(parse_hex(bg)), a)
        want = parse_hex(blend(fg, bg, a / 32))
        r5, g6, b5 = got >> 11, (got >> 5) & 63, got & 31
        assert abs(r5 * 255 / 31 - want.r) <= 9
        assert abs(g6 * 255 / 63 - want.g) <= 5
        assert abs(b5 * 255 / 31 - want.b) <= 9
    assert to_hex(parse_hex("#ffffff")) == "#ffffff"


def test_broken_rules_of_a_draft_are_skipped() -> None:
    """Drafts (check=False) may hold rules the checks would reject: they are not generated."""
    draft = serializer.from_dict(
        {"pages": [{"name": "main",
                    "parameters": [{"name": "on", "type": "bool"}],
                    "widgets": [{"id": "w", "type": "rect", "w": 9, "h": 9, "rules": [
                        {"if": ["ghost", "==", 1], "set": "x", "to": 1},
                        {"param": "on", "prop": "x", "at_min": 0, "at_max": 9}]},
                        {"id": "c", "type": "chart", "rules": [
                        {"if": ["on", "==", True], "set": "angle", "to": 9}]}]}]},
        check=False,
    )  # fmt: skip
    text = generate(draft).files["ui_main.py"].decode()
    assert "def _draw_w(self, fb, ox, oy):\n        _d.rrect(" in text


# ------------------------------------------------------------------ chart (stage 06)
def test_chart_code() -> None:
    text = generate(
        serializer.from_dict(
            {"pages": [{"name": "main",
                        "parameters": [{"name": "s", "type": "series", "x_kind": "label", "min": 0, "max": 5,
                                        "default": [{"x": "Mon", "y": 1}, {"x": "Tue", "y": 2.5}]}],
                        "widgets": [{"id": "c", "type": "chart", "x": 1, "y": 2, "w": 150, "h": 60, "bind": "s",
                                     "chart": {"axis_x": "day", "y_max": 4, "style": "bars", "grid": False}},
                                    {"id": "u", "type": "chart", "w": 100, "h": 50}]}]}
        )
    ).files["ui_main.py"].decode()  # fmt: skip
    assert '"s": [{"Mon": 1}, {"Tue": 2.5}],  # series, ≤ 24 points, y 0…5' in text
    flat = re.sub(r"\s+", " ", text).replace("( ", "(").replace(", )", ")")
    assert (
        '_d.chart(fb, 1 - ox, 2 - oy, 150, 60, p["s"], False, 0.0, 5.0, None, 4.0, "day", "", '
        '"bars", False, 0xFFFF, _f.SERIF_8)'
    ) in flat
    assert (
        '_d.chart(fb, 0 - ox, 0 - oy, 100, 50, (), True, 0.0, 10.0, None, None, "", "", "line", '
        "True, 0xFFFF, _f.SERIF_8)"
    ) in flat


def test_long_series_default_is_wrapped() -> None:
    points = [{"x": i, "y": i * 1.5} for i in range(20)]
    text = generate(
        serializer.from_dict(
            {"pages": [{"name": "main", "parameters": [
                {"name": "s", "type": "series", "min": 0, "max": 40, "default": points}]}]}
        )
    ).files["ui_main.py"].decode()  # fmt: skip
    assert '    "s": [  # series, ≤ 24 points, y 0…40\n        {0: 0},\n        {1: 1.5},' in text
    assert max(len(line) for line in text.splitlines()) <= 100


def test_runtime_chart_helpers(ui_draw: Any) -> None:
    from espui.core.evaluate import chart_label_indices, chart_y_range
    from espui.core.models import ChartSettings, SeriesParameter, SeriesPoint

    data = [{3: 1.0}, {1: 5, 2: 9}, {"bad": 1}, {4: "x"}, (0, 2), "junk", {True: 1}]
    assert ui_draw.points(data, True) == [(0, 2), (1, 5), (2, 9), (3, 1.0)]
    assert ui_draw.points([{"Mon": 1}, {"Tue": 2}, ("Wed", 3)], False) == [
        ("Mon", 1),
        ("Tue", 2),
        ("Wed", 3),
    ]
    assert ui_draw.points(None, True) == []
    assert [ui_draw.tick(v) for v in (10.0, 3, 2.25, -1.5)] == ["10", "3", "2.2", "-1.5"]
    assert [ui_draw.xlabel(v) for v in (3.0, 4.5, "Mon", 7)] == ["3", "4.5", "Mon", "7"]
    for n in range(5):
        for w in (100, 150):
            assert ui_draw.label_indices(n, w) == chart_label_indices(n, w)
    param = SeriesParameter(name="s", min=10, max=30)
    for pts, lo, hi in (
        ([], None, None),
        ([(0, 5.0), (1, 40.0)], None, None),
        ([(0, 5.0)], 0.0, 20.0),
        ([], 7.0, 7.0),
    ):
        settings = ChartSettings(y_min=lo, y_max=hi)
        expected = chart_y_range(settings, param, [SeriesPoint(x=x, y=y) for x, y in pts])
        assert ui_draw.chart_range(pts, 10.0, 30.0, lo, hi) == expected
    snap = ui_draw.snapshot({"s": [{1: 2}], "t": 1})
    assert snap == {"s": [{1: 2}], "t": 1}
    original = {"s": [{1: 2}]}
    copy = ui_draw.snapshot(original)
    original["s"].append({2: 3})
    original["s"][0][1] = 9
    assert copy == {"s": [{1: 2}]}
    for name, hex_color in (
        ("CHART_BG", "#10222c"),
        ("GRID_COLOR", "#1f3340"),
        ("AXIS_COLOR", "#56707c"),
    ):
        assert getattr(ui_draw, name) == to_wire(hex_color)


# ------------------------------------------------------------------ pages (stage 09)
PAGES = ROOT / "examples" / "pages.espui"


@pytest.mark.parametrize("name", ["ui_main.py", "ui_settings.py", "main.py"])
def test_two_pages_snapshot(name: str, snapshot: SnapshotAssertion) -> None:
    files = generate(serializer.load(PAGES), source="pages.espui").files
    assert files[name].decode("utf-8") == snapshot


def test_all_pages_share_one_set_of_files() -> None:
    result = generate(serializer.load(PAGES))
    assert result.pages == ("main", "settings")
    assert result.page == "main"
    assert [n for n in result.files if n.startswith("ui_")] == [
        "ui_display.py",
        "ui_st7789.py",
        "ui_draw.py",
        "ui_main.py",
        "ui_settings.py",
        "ui_fonts.py",
    ]
    main_py = result.files["main.py"].decode()
    assert '"settings": (ui_settings.UI(d), dict(ui_settings.DEFAULTS)),' in main_py
    assert "def show(name):" in main_py
    # Both pages have a "title" parameter: each module keeps its own DEFAULTS.
    assert '"title": "Головна",' in result.files["ui_main.py"].decode()
    assert '"title": "Налаштування",' in result.files["ui_settings.py"].decode()


def test_shared_fonts_hold_glyphs_of_every_page() -> None:
    result = generate(serializer.load(PAGES))
    fonts = result.files["ui_fonts.py"].decode()
    serif_16 = fonts[fonts.index("\nSERIF_16 = Font(") :]
    serif_16 = serif_16[: serif_16.index("\n)\n")]
    for char in "Головна" + "Налаштування":  # str defaults of both pages (latin + Ukrainian)
        assert f"{char!r}: (" in serif_16
    mono_16 = fonts[fonts.index("\nMONO_16 = Font(") :]
    for char in "Wi-Fi: увімкнено" + "вимкнено":  # settings page only, incl. a condition text
        if char != " ":
            assert f"{char!r}: (" in mono_16
    assert result.notes[0].startswith("Шрифти: Literata 12/16/40 px · JetBrains Mono 16 px")


def test_one_page_only() -> None:
    result = generate(serializer.load(PAGES), "settings")
    assert result.pages == ("settings",)
    assert "ui_main.py" not in result.files
    assert "ui_settings.py" in result.files
    assert "show(" not in result.files["main.py"].decode()  # single-page example
    fonts = result.files["ui_fonts.py"].decode()
    assert "SERIF_40" not in fonts  # the big temperature of "main" is not needed


def test_cli_generates_all_pages(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["generate", str(PAGES), "-o", str(tmp_path / "all")]) == 0
    assert "Сторінки «main», «settings»" in capsys.readouterr().out
    assert (tmp_path / "all" / "ui_settings.py").is_file()
    assert main(["generate", str(PAGES), "-o", str(tmp_path / "one"), "--page", "settings"]) == 0
    assert "Сторінка «settings»" in capsys.readouterr().out
    assert not (tmp_path / "one" / "ui_main.py").exists()


def test_pictures_on_pages_with_other_backgrounds(tmp_path: Path) -> None:
    from PIL import Image

    from espui.assets.images import import_image

    Image.new("RGBA", (8, 8), (255, 0, 0, 128)).save(tmp_path / "dot.png")
    key, asset = import_image(tmp_path / "dot.png")
    widget = {"id": "pic", "type": "image", "w": 8, "h": 8, "image": {"file": key}}
    project = serializer.from_dict(
        {
            "images": {key: asset.model_dump(mode="json")},
            "pages": [
                {"name": "a", "background": "#000000", "widgets": [widget]},
                {"name": "b", "background": "#ffffff", "widgets": [widget]},  # same id, other page
                {"name": "c", "background": "#000000", "widgets": [widget]},
            ],
        }
    )
    result = generate(project)
    pictures = sorted(n for n in result.files if n.startswith("img/"))
    assert pictures == ["img/dot.bin", "img/dot_ffffff.bin"]  # mixed with each background
    assert result.files["img/dot.bin"] != result.files["img/dot_ffffff.bin"]
    assert '"/img/dot.bin")' in result.files["ui_a.py"].decode()
    assert '"/img/dot_ffffff.bin")' in result.files["ui_b.py"].decode()
    assert '"/img/dot.bin")' in result.files["ui_c.py"].decode()


def test_edited_main_is_kept(tmp_path: Path) -> None:
    """main.py is the developer's once edited: the new example goes to main.example.py."""
    import json

    result = generate(project([{"id": "r", "type": "rect"}]))
    written = result.write(tmp_path)
    assert (tmp_path / "main.py") in written
    manifest = json.loads((tmp_path / MANIFEST).read_text())
    assert set(manifest) == set(result.files)
    result.write(tmp_path)  # unchanged main.py: simply rewritten
    assert not (tmp_path / "main.example.py").exists()
    (tmp_path / "main.py").write_text("# mine\n")
    written = result.write(tmp_path)
    assert (tmp_path / "main.example.py") in written
    assert (tmp_path / "main.py").read_text() == "# mine\n"
    assert json.loads((tmp_path / MANIFEST).read_text())["main.py"] == manifest["main.py"]
    (tmp_path / MANIFEST).write_text("{broken")
    result.write(tmp_path)  # no manifest: an existing main.py counts as the developer's
    assert (tmp_path / "main.py").read_text() == "# mine\n"


def test_cli_reports_kept_main(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out"
    assert main(["generate", str(EXAMPLE), "-o", str(out)]) == 0
    (out / "main.py").write_text("# mine\n")
    capsys.readouterr()
    assert main(["generate", str(EXAMPLE), "-o", str(out)]) == 0
    assert "новий приклад записано в main.example.py" in capsys.readouterr().err


# ------------------------------------------------------------------ memory estimate (stage 15)
def test_memory_estimate() -> None:
    from espui.generators.micropython.memory import REGION_BUFFER, estimate

    images = serializer.load(ROOT / "examples" / "images.espui")
    memory = estimate(images)
    real = generate(images).files
    assert memory.images == sum(len(d) for n, d in real.items() if n.startswith("img/"))
    assert memory.fonts == len(real["ui_fonts.py"])
    assert memory.code == sum(
        len(d) for n, d in real.items() if n.endswith(".py") and n != "ui_fonts.py"
    )
    assert memory.flash == memory.code + memory.fonts + memory.images
    assert memory.ram > REGION_BUFFER * 2  # a translucent picture: two region buffers
    assert memory.summary().startswith("Флеш ≈ ")
    plain = estimate(serializer.load(ROOT / "examples" / "weather.espui"))
    assert plain.images == 0
    assert REGION_BUFFER < plain.ram < 2 * REGION_BUFFER + plain.fonts
    assert "картинки 0)" in plain.summary()


def test_sizing_without_conversion_matches() -> None:
    project = serializer.load(ROOT / "examples" / "images.espui")
    sized = generate(project, convert_images=False).files
    real = generate(project).files
    assert {n: len(d) for n, d in sized.items()} == {n: len(d) for n, d in real.items()}
