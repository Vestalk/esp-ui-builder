"""``.espui`` project -> MicroPython files for the board.

For one page the output folder contains:

=================  ==========================================================
``ui_display.py``  display settings from the project + the ``Display`` adapter
driver file        ``ui_st7789.py`` or ``st7789py.py`` (+ its licence)
``ui_draw.py``     drawing helpers and the ``Page`` engine (draw / update)
``ui_<page>.py``   ``DEFAULTS`` and the ``UI`` class of the page
``main.py``        example: ``ui.draw(p)`` and a loop with ``ui.update(p)``
=================  ==========================================================

Every value that ends up in the code is computed here once (colours in wire
order, fonts, bounds), so the board only does the dynamic part.
Features of later stages (rules, transforms, images, charts) are reported as
warnings and skipped instead of being generated half-way.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, StrictUndefined

from espui.assets.fonts import BitmapFont
from espui.core.colors import to_wire
from espui.core.evaluate import pivot_offset, round_half_up
from espui.core.hardware import Chip
from espui.core.models import (
    DEFAULT_TRACK_COLOR,
    BoolParameter,
    ChartSettings,
    Condition,
    Display,
    EnumParameter,
    FloatParameter,
    IntParameter,
    MappingRule,
    Page,
    Parameter,
    Pins,
    Project,
    SeriesParameter,
    StrParameter,
    Widget,
)
from espui.generators.micropython.drivers import get_driver, runtime_file
from espui.generators.micropython.fonts import (
    FONTS_FILE,
    CharNeeds,
    FontKey,
    font_name,
    widget_font,
)
from espui.generators.micropython.fonts import build as build_fonts
from espui.generators.micropython.fonts import collect as collect_chars
from espui.generators.micropython.images import ImagePlan
from espui.generators.micropython.images import plan as plan_images

DRAW_FILE = "ui_draw.py"
VSCODE_SETTINGS = ".vscode/settings.json"
IMG_DIR = "img"
MICROPICO_DEFAULT_TYPES = ("py", "txt", "log", "json", "xml", "html", "js", "css", "mpy")
"""Default of ``micropico.syncFileTypes`` (MicroPico 4.6.1 package.json): no "bin"."""
SYNC_FILE_TYPES = ("py", "json", "bin")
"""What a generated project needs uploaded; "bin" = pictures."""
MAIN_FILE = "main.py"
PACKAGE_FILE = "__init__.py"
"""Makes the page folder importable from anywhere on the board (``from ui.main import …``)."""
MAIN_EXAMPLE_FILE = "main.example.py"
"""Written by older versions next to an edited main.py; removed on generation."""
"""Where the new example goes when the developer changed main.py."""
MANIFEST = ".espui-generated.json"
"""Hashes of the files the last generation wrote (to recognise an edited main.py)."""
SUPPORTED_TYPES = frozenset(
    {"rect", "circle", "line", "text", "value", "bar", "arc", "chart", "image"}
)
LATER_STAGE: dict[str, str] = {}
MAX_LINE = 99
INDENT = " " * 8

# Unbound bars/arcs show a placeholder fill, as in the mock-up.
UNBOUND_FRACTION = {"bar": 0.5, "arc": 0.6}

_SETTINGS_RE = re.compile(r"(# --- settings -+\n)(.*?)(\n# -{10,})", re.DOTALL)


class GenerationError(ValueError):
    """The project can't be turned into code (e.g. no such page)."""


@dataclass(frozen=True, slots=True)
class Generation:
    files: Mapping[str, bytes]
    """File name -> content, in the order they should be listed."""
    warnings: tuple[str, ...] = ()
    pages: tuple[str, ...] = ()
    """Generated pages, in project order (``ui_<page>.py`` each)."""
    notes: tuple[str, ...] = ()
    """Information for the user, e.g. which fonts went into ui_fonts.py and their size."""

    @property
    def page(self) -> str:
        """The first generated page (the one main.py shows first)."""
        return self.pages[0] if self.pages else ""

    def write(self, out_dir: str | Path) -> list[Path]:
        """Write the files; whatever an earlier generation left there is replaced.

        Every file (``main.py`` too) is overwritten with the new version; files
        of the previous generation that this one no longer produces (a deleted
        page's ``ui_<page>.py``, old pictures, ``main.example.py`` of older
        versions) are removed, see :data:`MANIFEST`. Files the generator never
        wrote are left alone. An existing ``.vscode/settings.json`` is merged.
        """
        target = Path(out_dir)
        target.mkdir(parents=True, exist_ok=True)
        keep = {target / name for name in self.files}
        _remove_stale_images(target, keep)
        for name in [*_read_manifest(target), MAIN_EXAMPLE_FILE]:
            old = target / name
            if old not in keep and old.is_file() and old.resolve().is_relative_to(target.resolve()):
                old.unlink()
        written = []
        hashes = {}
        for name, data in self.files.items():
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if name == VSCODE_SETTINGS and path.is_file():
                data = vscode_settings(path.read_text("utf-8")).encode("utf-8")
            path.write_bytes(data)
            written.append(path)
            hashes[name] = _sha256(data)
        (target / MANIFEST).write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n", "utf-8")
        return written


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_manifest(target: Path) -> dict[str, str]:
    try:
        data = json.loads((target / MANIFEST).read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _remove_stale_images(target: Path, keep: set[Path]) -> None:
    folder = target / IMG_DIR
    if not folder.is_dir():
        return
    for path in sorted(folder.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_file() and path.suffix in (".bin", ".json") and path not in keep:
            path.unlink()
        elif path.is_dir() and not any(path.iterdir()):
            path.rmdir()


@dataclass(slots=True)
class _WidgetCode:
    id: str
    bounds: tuple[int, int, int, int]
    deps: tuple[str, ...]
    body: list[str] = field(default_factory=list)
    box: list[str] = field(default_factory=list)
    """Body of ``_box_<id>()`` for widgets that can move or are rotated."""
    translucent: bool = False
    anim: list[str] = field(default_factory=list)
    """Body of ``_anim_<id>()``: (folder, frames, delay) or None, for image widgets."""
    loop: bool = True
    tap: str | None = None
    """Function called when the widget is tapped ("При натиску")."""
    shown: list[str] = field(default_factory=list)
    """Body of ``_shown_<id>()``: whether a hidden-by-condition widget catches taps."""


# ------------------------------------------------------------------ entry point
def generate(
    project: Project,
    page_name: str | None = None,
    source: str = "",
    convert_images: bool = True,
) -> Generation:
    """All pages (or only ``page_name``) with the files they share.

    ``convert_images=False`` gives picture files of the right size but without
    content (for :mod:`espui.generators.micropython.memory`).
    """
    pages = [_pick_page(project, page_name)] if page_name is not None else list(project.pages)
    warnings: list[str] = []

    driver = get_driver(project.display.driver)
    driver_files = driver.files_for(project.display.profile.controller)
    files: dict[str, bytes] = {}
    files[driver_files[0]] = render_display_settings(project).encode("utf-8")
    for name in driver_files[1:]:
        files[name] = runtime_file(name).read_bytes()
    if driver.license_file:
        files[driver.license_file] = runtime_file(driver.license_file).read_bytes()
    files[DRAW_FILE] = runtime_file(DRAW_FILE).read_bytes()
    if project.display.touch is not None:
        files[TOUCH_FILE] = runtime_file(TOUCH_FILE).read_bytes()

    drawn = {page.name: [w for w in page.widgets if w.type in SUPPORTED_TYPES] for page in pages}
    needs: dict[FontKey, CharNeeds] = {}
    for page in pages:  # one ui_fonts.py: the glyphs of every page
        for key, chars in collect_chars(drawn[page.name], page).items():
            merged = needs.setdefault(key, CharNeeds(set(), set()))
            merged.static.update(chars.static)
            merged.dynamic.update(chars.dynamic)
    fonts_module = build_fonts(needs)
    warnings += fonts_module.warnings
    image_plan = plan_images(
        project, [(page, drawn[page.name]) for page in pages], convert=convert_images
    )
    warnings += image_plan.warnings

    width, height = project.display.size
    contexts = []
    for page in pages:
        codes = [
            _widget_code(w, page, warnings, fonts_module.fonts, image_plan) for w in page.widgets
        ]
        widgets = [w for w in codes if w is not None]
        context: dict[str, Any] = {
            "source": source,
            "page": page,
            "module": f"ui_{page.name}",
            "width": width,
            "height": height,
            "background": _color(page.background),
            "background_hex": page.background,
            "defaults": [_default_entry(p) for p in page.parameters],
            "parameters": page.parameters,
            "widgets": widgets,
            "uses_alpha": any(w.translucent for w in widgets),
            "anims": [w for w in widgets if w.anim],
            "taps": [w for w in widgets if w.tap],
            "uses_fonts": bool(fonts_module.fonts),
            "first_numeric": next((p for p in page.parameters if _is_number_param(p)), None),
            "first_series": next(
                (
                    p
                    for p in page.parameters
                    if isinstance(p, SeriesParameter) and p.x_kind == "number"
                ),
                None,
            ),
        }
        files[f"ui_{page.name}.py"] = _render("ui_page.py.j2", context).encode("utf-8")
        contexts.append(context)

    notes: tuple[str, ...] = ()
    if fonts_module.fonts:
        files[FONTS_FILE] = fonts_module.source.encode("utf-8")
        notes = (fonts_module.summary(),)
    if image_plan.files:
        files.update(image_plan.files)
        files[VSCODE_SETTINGS] = vscode_settings().encode("utf-8")
        notes += tuple(image_plan.summary())
    display = project.display
    actions = sorted({w.tap for c in contexts for w in c["taps"]})
    if actions and display.touch is None:
        warnings.append(
            "Є елементи з «При натиску», але сенсорний екран не ввімкнено "
            "(Дисплей → Сенсорний екран): на платі дотики не читатимуться."
        )
    main_context = {
        **contexts[0],
        "pages": contexts,
        "actions": actions,
        "poll_touch": display.touch is not None and not actions,
        "touch": display.touch is not None,
    }
    files[MAIN_FILE] = _render("main.py.j2", main_context).encode("utf-8")
    files[PACKAGE_FILE] = _render(
        "package_init.py.j2", {"modules": [f"ui_{page.name}" for page in pages]}
    ).encode("utf-8")
    return Generation(
        files=files, warnings=tuple(warnings), pages=tuple(p.name for p in pages), notes=notes
    )


def _pick_page(project: Project, name: str | None) -> Page:
    if name is None:
        return project.pages[0]
    page = project.page(name)
    if page is None:
        known = ", ".join(p.name for p in project.pages)
        raise GenerationError(f"Немає сторінки «{name}»; є: {known}")
    return page


# ------------------------------------------------------------------ ui_display.py
def vscode_settings(existing: str | None = None) -> str:
    """``.vscode/settings.json`` for MicroPico: upload .bin pictures with the code.

    Other settings of an existing file are kept.
    """
    data: dict[str, object] = {}
    if existing:
        try:
            loaded = json.loads(existing)
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict):
            data = loaded
    current = data.get("micropico.syncFileTypes")
    # Setting the key replaces MicroPico's default list, so start from that default.
    types = (
        [str(t) for t in current] if isinstance(current, list) else list(MICROPICO_DEFAULT_TYPES)
    )
    data["micropico.syncFileTypes"] = types + [t for t in SYNC_FILE_TYPES if t not in types]
    return json.dumps(data, ensure_ascii=False, indent=4) + "\n"


HSPI_PINS = (14, 13)
"""Classic ESP32: SCK / MOSI of SPI2 (HSPI) on its IOMUX pins (the CYD wires them)."""


def spi_id(chip: Chip, pins: Pins | None = None) -> int:
    """MicroPython hardware SPI id for the display.

    ``SPI(1)`` is SPI2_HOST and ``SPI(2)`` is SPI3_HOST. On the classic ESP32
    the default pins (18/23) are SPI3's (VSPI) IOMUX pins and 14/13 are SPI2's
    (HSPI, the CYD): the matching host keeps the full speed. On ESP32-S3 the
    default pins (12/11/10) are SPI2's (FSPI) IOMUX pins, and ``SPI(2)`` there
    resets the board by watchdog with octal PSRAM (MicroPython 1.29). ESP32-C3
    has only SPI2.
    """
    if chip is Chip.ESP32:
        on_hspi = pins is not None and (pins.sck, pins.mosi) == HSPI_PINS
        return 1 if on_hspi else 2
    return 1


def _touch_settings(display: Display) -> str:
    touch = display.touch
    if touch is None:
        return "None"
    if touch.kind == "xpt2046":
        own = (
            f', "sck": {touch.sck}, "mosi": {touch.mosi}, "miso": {touch.miso}'
            if touch.own_bus
            else ""
        )
        return (
            f'{{"kind": "xpt2046", "cs": {touch.cs}, "irq": {touch.irq}, '
            f'"x_min": {touch.x_min}, "x_max": {touch.x_max}, '
            f'"y_min": {touch.y_min}, "y_max": {touch.y_max}, "swap_xy": {touch.swap_xy}{own}}}'
        )
    return (
        f'{{"kind": "cst816s", "sda": {touch.sda}, "scl": {touch.scl}, '
        f'"irq": {touch.irq}, "rst": {touch.rst}}}'
    )


TOUCH_FILE = "ui_touch.py"


def render_display_settings(project: Project) -> str:
    display = project.display
    pins = display.pins
    profile = display.profile
    settings = "\n".join(
        [
            f'DRIVER = "{display.driver.value}"  # "builtin" | "st7789py"',
            "PINS = {"
            f'"sck": {pins.sck}, "mosi": {pins.mosi}, "cs": {pins.cs}, '
            f'"dc": {pins.dc}, "rst": {pins.rst}, "blk": {pins.bl}, "miso": {pins.miso}'
            "}  # None: the module has no such pin",
            f"SPI_ID = {spi_id(display.mcu, pins)}  # {display.mcu.label}",
            f"SPI_HZ = {display.spi_hz:_}",
            f"WIDTH = {profile.width}  # physical panel size, portrait",
            f"HEIGHT = {profile.height}",
            f"ROTATION = {display.rotation}  # 0-3",
            f"INVERT = {display.inverted}",
            f'CONTROLLER = "{profile.controller}"  # {profile.title}',
            "ROTATIONS = (  # (MADCTL, width, height, x offset, y offset) per rotation",
            *(
                f"    ({row[0]:#04x}, {row[1]}, {row[2]}, {row[3]}, {row[4]}),"
                for row in profile.rotation_table()
            ),
            ")",
            f"BUF_BYTES = {display.buf_bytes:_}  # region buffer: one strip of what is redrawn",
            f"IMAGE_CACHE = {display.image_cache:_}"
            "  # RAM for keeping pictures (0 = read from flash each time)",
            f"TOUCH = {_touch_settings(display)}  # touch panel (ui_touch.py), None = none",
        ]
    )
    template = runtime_file(get_driver(display.driver).files[0]).read_text("utf-8")
    result, count = _SETTINGS_RE.subn(lambda m: m[1] + settings + m[3], template, count=1)
    if count != 1:  # pragma: no cover - guards the runtime file layout
        raise RuntimeError("ui_display.py: settings block not found")
    return result


# ------------------------------------------------------------------ parameters
def _is_number_param(param: Parameter) -> bool:
    return isinstance(param, FloatParameter | IntParameter)


def _py(value: object) -> str:
    """Python/MicroPython literal; strings in double quotes (ruff format style)."""
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return repr(value)


def _py_tuple(items: Iterable[object]) -> str:
    parts = [_py(i) for i in items]
    if len(parts) == 1:
        return f"({parts[0]},)"
    return f"({', '.join(parts)})"


def defaults_source(page: Page) -> str:
    """The ``DEFAULTS = {...}`` block of ``ui_<page>.py`` (also shown in the GUI)."""
    lines = "".join(f"    {_default_entry(p)}\n" for p in page.parameters)
    return f"DEFAULTS = {{\n{lines}}}\n"


def _default_entry(param: Parameter) -> str:
    """One ``DEFAULTS`` entry (may span several lines)."""
    name, value, comment = _default_line(param)
    return f"{name}: {value},  # {comment}" if comment else f"{name}: {value},"


def _default_line(param: Parameter) -> tuple[str, str, str]:
    """(name literal, value literal, comment) for the DEFAULTS dict."""
    if isinstance(param, FloatParameter | IntParameter):
        comment = f"{param.type}, {param.min:g}…{param.max:g}"
        value = _py(param.default)
    elif isinstance(param, BoolParameter):
        comment, value = "bool", _py(param.default)
    elif isinstance(param, StrParameter):
        comment, value = f"str, < {param.max_len} chars", _py(param.default)
    elif isinstance(param, EnumParameter):
        comment, value = "enum: " + ", ".join(param.values), _py(param.default)
    else:
        assert isinstance(param, SeriesParameter)
        comment = f"series, ≤ {param.max_points} points, y {param.min:g}…{param.max:g}"
        points = [
            f"{{{_num(p.x) if isinstance(p.x, float) else _py(p.x)}: {_num(p.y)}}}"
            for p in param.default
        ]
        one_line = f"[{', '.join(points)}]"
        if len(one_line) + len(param.name) + len(comment) + 12 <= MAX_LINE:
            value = one_line
        else:  # one point per line; the comment goes after the opening bracket
            items = "".join(f"\n        {point}," for point in points)
            return _py(param.name), f"[  # {comment}{items}\n    ]", ""
    return _py(param.name), value, comment


# ------------------------------------------------------------------ widgets
def _color(hex_color: str) -> str:
    return f"0x{to_wire(hex_color):04X}"


_ALIGN = {"left": "_d.LEFT", "center": "_d.CENTER", "right": "_d.RIGHT"}


def _text_margins(widget: Widget, font: BitmapFont | None) -> tuple[int, int, int, int]:
    """(left, top, right, bottom) px the glyphs may stick out of the widget box.

    The text baseline is fixed (80 % of the height for text, ``size`` for a bar
    label), so tall letters (Ї, Й) and descenders can leave the box: the
    redrawn area must cover them, or an update would leave traces.
    """
    if font is None or not font.glyphs or widget.type not in ("text", "value", "bar"):
        return 0, 0, 0, 0
    base = (widget.h * 4) // 5 if widget.type != "bar" else font.size
    glyphs = font.glyphs.values()
    top = max(0, max(g.top for g in glyphs) - base)
    bottom = max(0, base + max(g.height - g.top for g in glyphs) - widget.h)
    left = max(0, -min(g.left for g in glyphs))
    right = max(0, max(g.left + g.width - g.advance for g in glyphs))
    return left, top, right, bottom


def bounds(widget: Widget) -> tuple[int, int, int, int]:
    """Area a widget may touch (a line is 2 px thick)."""
    if widget.type == "line":
        return widget.x, widget.y, widget.w + 2, widget.h + 2
    return widget.x, widget.y, widget.w, widget.h


def _call(func: str, args: Iterable[str]) -> list[str]:
    items = list(args)
    one = f"{func}({', '.join(items)})"
    if len(INDENT) + len(one) <= MAX_LINE:
        return [one]
    return [f"{func}(", *(f"    {a}," for a in items), ")"]


# Widget property -> variable in the generated code.
_VARS = {
    "color": "color",
    "text": "f",
    "visible": "visible",
    "opacity": "opacity",
    "angle": "angle",
    "x": "x",
    "y": "y",
}
_GEOMETRY = ("angle", "x", "y")
ALPHA_LEVELS = 32  # ui_draw.ALPHA_LEVELS
MAX_ROTATED_TEXT_PX = 64 * 64
"""Dynamically rotated text is drawn pixel by pixel: warn above this box area."""


def _condition_test(condition: Condition, param: Parameter) -> str:
    """Python test of a condition, with the semantics of ``core.evaluate.compare``."""
    value = f"p[{_py(condition.param)}]"
    if isinstance(param, BoolParameter):  # only "==" is allowed for bool
        return value if condition.value is True else f"not {value}"
    if isinstance(condition.value, tuple):  # in / not in: both ends included
        lo, hi = condition.value
        inside = f"{_py(lo)} <= {value} <= {_py(hi)}"
        return inside if condition.op == "in" else f"not ({inside})"
    return f"{value} {condition.op} {_py(condition.value)}"


def _condition_literal(prop: str, to: object) -> str:
    if prop == "color":
        assert isinstance(to, str)
        return _color(to)
    if prop == "text":
        return _py(str(to))
    if prop == "visible":
        return repr(bool(to))
    assert isinstance(to, int | float)
    if prop in ("x", "y"):
        return str(round_half_up(to))
    return repr(to)


def _alpha_level(opacity: float) -> int:
    """Same as ui_draw.alpha()."""
    if opacity <= 0:
        return 0
    if opacity >= 100:
        return ALPHA_LEVELS
    return int(opacity * ALPHA_LEVELS / 100 + 0.5)


def _rules(widget: Widget, page: Page) -> list[Condition | MappingRule]:
    """Records that can be generated: their parameter exists and suits the record."""
    out: list[Condition | MappingRule] = []
    for rule in widget.rules:
        param = page.parameter(rule.param)
        if param is None:
            continue
        if isinstance(rule, MappingRule) and not _is_number_param(param):
            continue
        if widget.type == "chart" and rule.prop == "angle":
            continue
        out.append(rule)
    return out


def _rule_lines(
    rules: list[Condition | MappingRule], page: Page, widget: Widget, props: Iterable[str]
) -> list[str]:
    """Base values -> mappings -> conditions for ``props`` (as core.evaluate.effective)."""
    wanted = set(props)
    used = [r for r in rules if r.prop in wanted]
    if not used:
        return []
    base = {
        "color": _color(widget.color),
        "text": _py(widget.format),
        "visible": "True",
        "opacity": repr(widget.opacity),
        "angle": repr(widget.rotation_deg),
        "x": str(widget.x),
        "y": str(widget.y),
    }
    touched = {r.prop for r in used}
    lines = [f"{_VARS[prop]} = {base[prop]}" for prop in _VARS if prop in touched]
    mapped = set()
    for rule in used:
        if isinstance(rule, MappingRule):
            param = page.parameter(rule.param)
            assert isinstance(param, FloatParameter | IntParameter)
            lines.append(
                f"{_VARS[rule.prop]} = _d.lin(p[{_py(rule.param)}], {param.min!r}, "
                f"{param.max!r}, {rule.at_min!r}, {rule.at_max!r})"
            )
            mapped.add(rule.prop)
    conditions = [r for r in used if isinstance(r, Condition)]
    if conditions:
        lines.append("# conditions, top to bottom: the lowest one that matches wins")
    for rule in conditions:
        param = page.parameter(rule.param)
        assert param is not None
        lines.append(f"if {_condition_test(rule, param)}:")
        lines.append(f"    {_VARS[rule.prop]} = {_condition_literal(rule.prop, rule.to)}")
    for axis in ("x", "y"):
        if axis in mapped:
            lines.append(f"{axis} = _d.rnd({axis})")
    return lines


def _num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def _chart_args(widget: Widget, param: Parameter | None, value: str | None) -> list[str]:
    """Arguments of ``_d.chart`` after the box (see ui_draw.chart)."""
    chart = widget.chart or ChartSettings()
    series = param if isinstance(param, SeriesParameter) else None
    lo, hi = (series.min, series.max) if series else (0.0, 10.0)  # core.evaluate.chart_y_range
    return [
        value if series is not None and value else "()",
        repr(series is None or series.x_kind == "number"),
        repr(lo),
        repr(hi),
        repr(chart.y_min),
        repr(chart.y_max),
        _py(chart.axis_x),
        _py(chart.axis_y),
        _py(chart.style),
        repr(chart.grid),
    ]


def _image_code(
    widget: Widget,
    page: Page,
    pos: list[str],
    images: ImagePlan | None,
    extra: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """(draw call lines, ``_anim_`` body) of an image widget; ``extra``: ``["r"]`` if turned."""
    extra = extra or []
    wid = _py(widget.id)
    if widget.bind:
        value = f"p[{_py(widget.bind)}]"
        call = [
            f"path = {value}",
            f"info = self._anim_{widget.id}()",
            "if info is not None:",
            f"    path = _d.frame_path(info[0], self.frame({wid}))",
            *_call("_d.image", ["fb", *pos, "path", *extra]),
        ]
        return call, [f"return _d.anim_info(self.p[{_py(widget.bind)}])"]
    path = (images.paths.get((page.name, widget.id)) if images else None) or None
    if path is None:
        return _call("_d.image", ["fb", *pos, '""', *extra]) if extra else _call(
            "_d.missing", ["fb", *pos]
        ), []
    anim = images.animations.get(path) if images else None
    if anim is None:
        return _call("_d.image", ["fb", *pos, _py(path), *extra]), []
    folder, frames, delay = anim
    frame = f"_d.frame_path({_py(folder)}, self.frame({wid}))"
    return _call("_d.image", ["fb", *pos, frame, *extra]), [
        f"return ({_py(folder)}, {frames}, {delay})"
    ]


def _widget_code(
    widget: Widget,
    page: Page,
    warnings: list[str],
    fonts: Mapping[FontKey, BitmapFont] | None = None,
    images: ImagePlan | None = None,
) -> _WidgetCode | None:
    kind = widget.type
    if kind not in SUPPORTED_TYPES:
        warnings.append(
            f"Елемент «{widget.id}» ({kind}) пропущено: підтримка — етап {LATER_STAGE[kind]}."
        )
        return None

    rules = _rules(widget, page)
    dynamic = {r.prop for r in rules}
    param = page.parameter(widget.bind)
    deps = dict.fromkeys([*([param.name] if param is not None else []), *(r.param for r in rules)])
    value = f"p[{_py(param.name)}]" if param is not None else None
    font_key = widget_font(widget)
    font = (fonts or {}).get(font_key) if font_key else None
    font_ref = f"_f.{font_name(font_key)}" if font_key else ""
    ml, mt, mr, mb = _text_margins(widget, font)
    bx, by, bw, bh = bounds(widget)
    bx, by, bw, bh = bx - ml, by - mt, bw + ml + mr, bh + mt + mb
    code = _WidgetCode(widget.id, (bx, by, bw, bh), tuple(deps))

    static_level = _alpha_level(widget.opacity)
    if "opacity" not in dynamic and static_level == 0:
        code.body = ["return  # opacity 0 %: never drawn"]
        return code

    x = "x" if "x" in dynamic else str(widget.x)
    y = "y" if "y" in dynamic else str(widget.y)
    pos = [f"{x} - ox", f"{y} - oy", str(widget.w), str(widget.h)]
    color = "color" if "color" in dynamic else _color(widget.color)
    rotated = "angle" in dynamic or widget.rotation_deg % 360 != 0
    angle = "angle" if "angle" in dynamic else repr(widget.rotation_deg)
    px, py = pivot_offset(widget)
    extra = ["r"] if rotated else []

    if kind == "rect":
        call = _call("_d.rrect", ["fb", *pos, "4", color, *extra])
    elif kind == "circle":
        call = _call("_d.ellipse", ["fb", *pos, color, *extra])
    elif kind == "line":
        call = _call("_d.line", ["fb", *pos, color, *extra])
    elif kind in ("text", "value"):
        f = "f" if "text" in dynamic else _py(widget.format)
        text = f"_d.fmt({f}, {value})" if value else f
        args = ["fb", text, *pos, color, font_ref, _ALIGN[widget.align], *extra]
        call = _call("_d.label", args)
        if "angle" in dynamic and widget.w * widget.h > MAX_ROTATED_TEXT_PX:
            warnings.append(
                f"Елемент «{widget.id}»: текст {widget.w}×{widget.h} з кутом від параметра "
                f"повертається попіксельно й малюватиметься повільно (більше "
                f"{MAX_ROTATED_TEXT_PX} px); зменште його або зробіть кут сталим."
            )
    elif kind == "image":
        call, code.anim = _image_code(widget, page, [*pos], images, extra)
        code.loop = widget.image is None or widget.image.play == "loop"
    elif kind == "chart":
        args = ["fb", *pos, *_chart_args(widget, param, value), color, font_ref]
        call = _call("_d.chart", args)
    else:
        numeric = param is not None and _is_number_param(param)
        if numeric:
            assert isinstance(param, FloatParameter | IntParameter)
            fraction = f"_d.frac({value}, {param.min!r}, {param.max!r})"
            number = f"_d.num({value}, {isinstance(param, FloatParameter)})"
        else:
            fraction, number = repr(UNBOUND_FRACTION[kind]), '""'
        if not widget.show_value:
            number = '""'
        # The fixed track: the default colour needs no argument, "None" hides it.
        track = (
            ["track=None"]
            if not widget.show_track
            else []
            if widget.track_color == DEFAULT_TRACK_COLOR
            else [f"track={_color(widget.track_color)}"]
        )
        if kind == "bar":
            args = ["fb", *pos, fraction, color, _py(widget.format), number, font_ref, *extra]
            call = _call("_d.bar", [*args, *track])
        else:
            args = ["fb", *pos, fraction, color, number, font_ref, *extra, *track]
            call = _call("_d.arc", args)

    body = _rule_lines(rules, page, widget, _VARS)
    if "visible" in dynamic:
        body += ["if not visible:", "    return"]
    translucent = "opacity" in dynamic or static_level < ALPHA_LEVELS
    if "opacity" in dynamic:
        body += ["level = _d.alpha(opacity)", "if level == 0:", "    return"]
    if rotated:
        pivot_x = f"x - ox + {_num(px)}" if "x" in dynamic else f"{_num(widget.x + px)} - ox"
        pivot_y = f"y - oy + {_num(py)}" if "y" in dynamic else f"{_num(widget.y + py)} - oy"
        body.append(f"r = _d.rot({angle}, {pivot_x}, {pivot_y})")
    if "opacity" in dynamic:
        body += ["if level < 32:", "    fb = self.begin_alpha(fb)", *call]
        body += ["if level < 32:", "    self.end_alpha(level)"]
    elif translucent:
        body += [f"fb = self.begin_alpha(fb)  # opacity {_num(widget.opacity)} %", *call]
        body.append(f"self.end_alpha({static_level})")
    else:
        body += call
    if value is not None or rules:
        body.insert(0, "p = self.p")
    code.body = body
    code.translucent = translucent

    if widget.on_tap:
        code.tap = widget.on_tap
        visible = []
        if "visible" in dynamic:
            visible.append("visible")
        if "opacity" in dynamic:
            visible.append("_d.alpha(opacity) > 0")
        if visible:
            lines = _rule_lines(rules, page, widget, ("visible", "opacity"))
            code.shown = ["p = self.p", *lines, f"return {' and '.join(visible)}"]
        elif static_level == 0:
            code.shown = ["return False  # opacity 0 %: never drawn, never tapped"]
    if rotated or dynamic & {"x", "y"}:
        # The box moves or turns: the engine redraws both the old and the new area.
        box = _rule_lines(rules, page, widget, _GEOMETRY)
        ex = (f"x - {ml}" if ml else "x") if "x" in dynamic else str(bx)
        ey = (f"y - {mt}" if mt else "y") if "y" in dynamic else str(by)
        if rotated:
            cx = f"x + {_num(px)}" if "x" in dynamic else _num(widget.x + px)
            cy = f"y + {_num(py)}" if "y" in dynamic else _num(widget.y + py)
            ret = f"return _d.rbox({ex}, {ey}, {bw}, {bh}, {angle}, {cx}, {cy})"
        else:
            ret = f"return ({ex}, {ey}, {bw}, {bh})"
        code.box = (["p = self.p"] if box else []) + [*box, ret]
    return code


# ------------------------------------------------------------------ templates
@cache
def _environment() -> Environment:
    env = Environment(
        loader=PackageLoader("espui.generators.micropython", "templates"),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
    )
    env.filters["py"] = _py
    env.filters["pytuple"] = _py_tuple
    env.globals["INDENT"] = INDENT
    return env


def _render(template: str, context: dict[str, object]) -> str:
    return _environment().get_template(template).render(**context)
