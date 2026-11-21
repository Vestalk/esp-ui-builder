"""The project as data: what a ``.espui`` file contains.

Pydantic validates the *structure* here (types, ranges, formats of single
fields). Rules that relate fields to each other (bindings, conditions, pins
per chip, references to images, ...) live in :mod:`espui.core.checks`, so that
every problem gets an exact path and the GUI can check drafts while editing.

Unknown fields are kept (``extra="allow"``) and written back on save.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    model_validator,
)
from pydantic_core import PydanticCustomError

from espui.core.colors import is_hex, normalize_hex
from espui.core.hardware import DEFAULT_DRIVER, Chip, Driver
from espui.core.identifiers import identifier_problem, page_name_problem
from espui.displays import DEFAULT_MODEL, DisplayProfile, get_profile

SCHEMA_VERSION = 1


class Model(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
    )


# ------------------------------------------------------------------ field types
def _hex_color(value: str) -> str:
    if not is_hex(value):
        raise PydanticCustomError("color", "колір має бути у форматі #rrggbb")
    return normalize_hex(value)


def _identifier(value: str) -> str:
    problem = identifier_problem(value)
    if problem:
        raise PydanticCustomError("identifier", problem)
    return value


def _page_name(value: str) -> str:
    problem = page_name_problem(value)
    if problem:
        raise PydanticCustomError("page_name", problem)
    return value


def _empty_to_none(value: Any) -> Any:
    return None if value == "" else value


HexColor = Annotated[str, AfterValidator(_hex_color)]
Identifier = Annotated[str, AfterValidator(_identifier)]
PageName = Annotated[str, AfterValidator(_page_name)]
OptionalRef = Annotated[str | None, BeforeValidator(_empty_to_none)]


# Unions are discriminated by Python type with Capitalised tags: tags appear in
# error paths, and user names (identifiers) are lowercase, so they never clash.
def _value_kind(value: Any) -> str:
    if isinstance(value, bool):
        return "Bool"
    if isinstance(value, int):
        return "Int"
    if isinstance(value, float):
        return "Float"
    if isinstance(value, list):
        return "Series"
    return "Str"


Scalar = Annotated[
    Annotated[bool, Tag("Bool")]
    | Annotated[int, Tag("Int")]
    | Annotated[float, Tag("Float")]
    | Annotated[str, Tag("Str")],
    Discriminator(_value_kind),
]


# ------------------------------------------------------------------ parameters
def _x_kind(value: Any) -> str:
    return "Str" if isinstance(value, str) else "Float"


class SeriesPoint(Model):
    x: Annotated[
        Annotated[float, Tag("Float")] | Annotated[str, Tag("Str")], Discriminator(_x_kind)
    ]
    y: float


class _ParameterBase(Model):
    name: Identifier


class FloatParameter(_ParameterBase):
    type: Literal["float"] = "float"
    min: float
    max: float
    default: float


class IntParameter(_ParameterBase):
    type: Literal["int"] = "int"
    min: int
    max: int
    default: int


class BoolParameter(_ParameterBase):
    type: Literal["bool"] = "bool"
    default: bool = False


class StrParameter(_ParameterBase):
    type: Literal["str"] = "str"
    max_len: int = Field(32, ge=2, le=128)
    """Value length must be shorter than ``max_len`` (buffer incl. terminator)."""
    default: str = ""
    charset: Literal["latin_uk", "latin", "digits"] = "latin_uk"
    """Characters the board can draw for this parameter (fonts carry only the glyphs needed)."""
    extra_chars: str = Field("", max_length=256)
    """Added to ``charset`` (e.g. symbols the device may send)."""


class EnumParameter(_ParameterBase):
    type: Literal["enum"] = "enum"
    values: list[str] = Field(min_length=2)
    default: str = ""

    @model_validator(mode="before")
    @classmethod
    def _default_is_first_value(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data.get("default") and data.get("values"):
            return {**data, "default": data["values"][0]}
        return data


class SeriesParameter(_ParameterBase):
    type: Literal["series"] = "series"
    max_points: int = Field(24, ge=2, le=256)
    x_kind: Literal["number", "label"] = "number"
    min: float
    """Y range."""
    max: float
    default: list[SeriesPoint] = Field(default_factory=list)


Parameter = Annotated[
    FloatParameter | IntParameter | BoolParameter | StrParameter | EnumParameter | SeriesParameter,
    Field(discriminator="type"),
]
NumericParameter = FloatParameter | IntParameter
ParamValue = Annotated[
    Annotated[bool, Tag("Bool")]
    | Annotated[int, Tag("Int")]
    | Annotated[float, Tag("Float")]
    | Annotated[str, Tag("Str")]
    | Annotated[list[SeriesPoint], Tag("Series")],
    Discriminator(_value_kind),
]

PARAMETER_TYPES = ("float", "int", "bool", "str", "enum", "series")


# ------------------------------------------------------------------ rules
Operator = Literal["==", "!=", ">", "<", ">=", "<="]
_OPERATOR_ALIASES = {"=": "==", "≠": "!=", "≥": ">=", "≤": "<="}


def _operator(value: Any) -> Any:
    return _OPERATOR_ALIASES.get(value, value) if isinstance(value, str) else value


ConditionProp = Literal["color", "text", "visible", "opacity", "angle", "x", "y"]
MappingProp = Literal["opacity", "angle", "x", "y"]


class Condition(Model):
    """``{if: [param, op, value], set: prop, to: value}`` — a discrete change."""

    kind: Literal["condition"] = "condition"
    when: tuple[str, Annotated[Operator, BeforeValidator(_operator)], Scalar] = Field(alias="if")
    prop: ConditionProp = Field(alias="set")
    to: Scalar

    @property
    def param(self) -> str:
        return self.when[0]

    @property
    def op(self) -> Operator:
        return self.when[1]

    @property
    def value(self) -> Scalar:
        return self.when[2]


class MappingRule(Model):
    """``{param, prop, at_min, at_max}`` — linear dependency on a numeric parameter."""

    kind: Literal["mapping"] = "mapping"
    param: str
    prop: MappingProp
    at_min: float
    at_max: float


def _rule_kind(value: Any) -> str:
    if isinstance(value, dict):
        kind = value.get("kind") or (
            "mapping" if "at_min" in value or "at_max" in value else "condition"
        )
    else:
        kind = getattr(value, "kind", "condition")
    return str(kind).capitalize()


Rule = Annotated[
    Annotated[Condition, Tag("Condition")] | Annotated[MappingRule, Tag("Mapping")],
    Discriminator(_rule_kind),
]


# ------------------------------------------------------------------ widgets
WidgetType = Literal["rect", "circle", "line", "text", "value", "bar", "arc", "image", "chart"]
WIDGET_TYPES: tuple[WidgetType, ...] = (
    "rect",
    "circle",
    "line",
    "text",
    "value",
    "bar",
    "arc",
    "image",
    "chart",
)
Font = Literal["serif", "mono", "pixel"]
DEFAULT_FONT: Font = "serif"
FONT_TYPES = frozenset({"text", "value", "bar", "arc", "chart"})
FONT_SIZE_TYPES = frozenset({"text", "value", "bar", "arc"})
DEFAULT_FONT_SIZE = {"text": 16, "value": 24, "bar": 12, "arc": 14}

PivotPreset = Literal[
    "center",
    "top_left",
    "top",
    "top_right",
    "left",
    "right",
    "bottom_left",
    "bottom",
    "bottom_right",
]
PIVOT_FRACTIONS: dict[str, tuple[float, float]] = {
    "center": (0.5, 0.5),
    "top_left": (0.0, 0.0),
    "top": (0.5, 0.0),
    "top_right": (1.0, 0.0),
    "left": (0.0, 0.5),
    "right": (1.0, 0.5),
    "bottom_left": (0.0, 1.0),
    "bottom": (0.5, 1.0),
    "bottom_right": (1.0, 1.0),
}


class PivotPoint(Model):
    """Pivot relative to the widget's top-left corner, px."""

    x: float
    y: float


def _pivot_kind(value: Any) -> str:
    return "Preset" if isinstance(value, str) else "Point"


Pivot = Annotated[
    Annotated[PivotPreset, Tag("Preset")] | Annotated[PivotPoint, Tag("Point")],
    Discriminator(_pivot_kind),
]


class ImageSettings(Model):
    file: OptionalRef = None
    """Key in ``Project.images`` for a static picture; ignored when ``bind`` is set."""
    fit: Literal["contain", "cover", "fill"] = "contain"
    play: Literal["loop", "once"] = "loop"


class ChartSettings(Model):
    axis_x: str = Field("", max_length=16)
    axis_y: str = Field("", max_length=16)
    y_min: float | None = None
    """None = auto (parameter range, widened to the data)."""
    y_max: float | None = None
    style: Literal["line", "dots", "bars"] = "line"
    grid: bool = True


class Widget(Model):
    id: Identifier
    type: WidgetType
    x: int = 0
    y: int = 0
    w: int = Field(0, ge=0)
    h: int = Field(0, ge=0)
    color: HexColor = "#ffffff"
    font: Font | None = None
    font_size: int | None = Field(None, ge=8, le=72)
    bind: OptionalRef = None
    format: str = ""
    align: Literal["left", "center", "right"] = "left"
    """Horizontal alignment of text and value widgets in their box."""
    opacity: int = Field(100, ge=0, le=100)
    rotation_deg: float = Field(0.0, ge=-360, le=360)
    pivot: Pivot = "center"
    rules: list[Rule] = Field(default_factory=list)
    image: ImageSettings | None = None
    chart: ChartSettings | None = None

    @model_validator(mode="before")
    @classmethod
    def _type_defaults(cls, data: Any) -> Any:
        """Fill the per-type defaults so a minimal widget dict is complete."""
        if not isinstance(data, dict):
            return data
        kind = data.get("type")
        filled = dict(data)
        if kind in FONT_TYPES and filled.get("font") is None:
            filled["font"] = DEFAULT_FONT
        if kind in FONT_SIZE_TYPES and filled.get("font_size") is None:
            filled["font_size"] = DEFAULT_FONT_SIZE[kind]
        if kind == "image" and filled.get("image") is None:
            filled["image"] = {}
        if kind == "chart" and filled.get("chart") is None:
            filled["chart"] = {}
        return filled

    def conditions(self) -> Iterator[Condition]:
        return (r for r in self.rules if isinstance(r, Condition))

    def mappings(self) -> Iterator[MappingRule]:
        return (r for r in self.rules if isinstance(r, MappingRule))

    def dependencies(self) -> set[str]:
        """Parameters this widget depends on: ``bind`` + every rule."""
        names = {r.param for r in self.rules}
        if self.bind:
            names.add(self.bind)
        return names


# ------------------------------------------------------------------ page
class Page(Model):
    name: PageName
    background: HexColor = "#000000"
    parameters: list[Parameter] = Field(default_factory=list)
    widgets: list[Widget] = Field(default_factory=list)
    """Layer order: the first one is the lowest."""
    test_values: dict[str, ParamValue] = Field(default_factory=dict)
    """Preview values; a missing entry means the parameter's default."""

    def parameter(self, name: str | None) -> Parameter | None:
        return next((p for p in self.parameters if p.name == name), None) if name else None

    def widget(self, widget_id: str) -> Widget | None:
        return next((w for w in self.widgets if w.id == widget_id), None)

    def remove_parameter(self, name: str) -> int:
        """Delete a parameter and everything that refers to it.

        Removes every ``rules[]`` record that uses it, unbinds widgets bound to
        it and drops its test value. Returns the number of removed rules.
        """
        self.parameters = [p for p in self.parameters if p.name != name]
        self.test_values.pop(name, None)
        removed = 0
        for widget in self.widgets:
            if widget.bind == name:
                widget.bind = None
            kept = [r for r in widget.rules if r.param != name]
            removed += len(widget.rules) - len(kept)
            widget.rules = kept
        return removed

    def value_of(self, name: str) -> ParamValue | None:
        """Test value if set, otherwise the default."""
        if name in self.test_values:
            return self.test_values[name]
        param = self.parameter(name)
        return None if param is None else param.default


# ------------------------------------------------------------------ display
class Pins(Model):
    sck: int = Field(ge=0)
    mosi: int = Field(ge=0)
    dc: int = Field(ge=0)
    cs: int = Field(ge=0)
    rst: int = Field(ge=0)
    bl: int | None = Field(None, ge=0)
    """Backlight; None if the module has no BLK pin."""

    def assigned(self) -> dict[str, int]:
        return {
            name: value
            for name in ("sck", "mosi", "dc", "cs", "rst", "bl")
            if (value := getattr(self, name)) is not None
        }


def _default_pins() -> Pins:
    return Pins.model_validate(get_profile(DEFAULT_MODEL).default_pins)


DEFAULT_BUF_BYTES = 16_384
"""Fits boards without PSRAM (<= 32 KB, docs/benchmarks.md)."""
MIN_BUF_BYTES = 1_024
MAX_BUF_BYTES = 4_000_000
MAX_IMAGE_CACHE = 32_000_000


class Display(Model):
    model: str = DEFAULT_MODEL
    rotation: int = Field(0, ge=0, le=3)
    """0/2 portrait, 1/3 landscape."""
    spi_hz: int = Field(40_000_000, ge=1_000_000, le=80_000_000)
    mcu: Chip = Chip.ESP32S3
    driver: Driver = DEFAULT_DRIVER
    pins: Pins = Field(default_factory=_default_pins)
    buf_bytes: int = Field(DEFAULT_BUF_BYTES, ge=MIN_BUF_BYTES, le=MAX_BUF_BYTES)
    """RAM for one strip of the region being redrawn (ui_draw.BUF_BYTES).

    Bigger means fewer strips per update (less visible redrawing); a whole
    screen (2 * w * h) needs PSRAM. Never more than a screen is allocated.
    """
    image_cache: int = Field(0, ge=0, le=MAX_IMAGE_CACHE)
    """RAM for keeping pictures after the first read (ui_draw.IMAGE_CACHE); 0 = off."""

    @property
    def screen_bytes(self) -> int:
        """A whole-screen buffer: the most the region buffer can use."""
        return 2 * self.profile.width * self.profile.height

    @property
    def profile(self) -> DisplayProfile:
        return get_profile(self.model)

    @property
    def size(self) -> tuple[int, int]:
        """Logical (width, height) for the current rotation."""
        return self.profile.size(self.rotation)


# ------------------------------------------------------------------ images
IMAGE_PATH_PATTERN = r"^/img/[a-z0-9_-]+(\.bin|/)$"
MAX_ANIMATION_FRAMES = 48


IMAGE_KEY_PATTERN = r"^[a-z0-9_-]{1,64}$"
ImageKey = Annotated[str, Field(pattern=IMAGE_KEY_PATTERN)]


class ImageAsset(Model):
    """Original picture embedded in the project; converted to RGB565 on generation."""

    name: str
    """Original file name (for the user)."""
    path: str = Field(pattern=IMAGE_PATH_PATTERN)
    """Path on the board: ``/img/<name>.bin``, or ``/img/<name>/`` for an animation."""
    mime: str = "image/png"
    data: str
    """Original file, base64."""
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    frames: list[str] | None = None
    """Animation frames (base64 PNG), GIF/video only."""
    delay_ms: int | None = Field(None, ge=20, le=5000)

    @property
    def is_animation(self) -> bool:
        return self.frames is not None


# ------------------------------------------------------------------ project
class EditorState(Model):
    zoom: float = Field(1.5, ge=0.5, le=4)
    page: int = Field(0, ge=0)


class Project(Model):
    schema_version: int = Field(SCHEMA_VERSION, alias="schema", ge=1)
    display: Display = Field(default_factory=Display)
    pages: list[Page] = Field(min_length=1)
    images: dict[ImageKey, ImageAsset] = Field(default_factory=dict)
    """Key: short lowercase name, referenced by ``widget.image.file``."""
    editor: EditorState = Field(default_factory=EditorState)

    def page(self, name: str) -> Page | None:
        return next((p for p in self.pages if p.name == name), None)
