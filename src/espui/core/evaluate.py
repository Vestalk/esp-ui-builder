"""All formulas that turn a widget + parameter values into what is drawn.

Pure functions, no Qt and no MicroPython. The GUI preview uses them directly;
the generator emits code that computes exactly the same (tests compare both).

Order: base values -> every ``mapping`` -> every ``condition`` top to bottom
(the lowest one that matches wins).
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from espui.core.compat import MAX_LABEL_LEN, is_numeric
from espui.core.models import (
    PIVOT_FRACTIONS,
    BoolParameter,
    ChartSettings,
    Condition,
    IntParameter,
    NumericParameter,
    Page,
    Parameter,
    ParamValue,
    PivotPoint,
    SeriesParameter,
    SeriesPoint,
    Widget,
)


# ------------------------------------------------------------------ numbers
def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def round_half_up(value: float) -> int:
    """Rounding used everywhere for pixels and ``%d`` (JS ``Math.round``)."""
    return math.floor(value + 0.5)


def fraction(param: NumericParameter, value: float) -> float:
    """Position of ``value`` within the parameter range, clamped to 0..1."""
    return clamp01((value - param.min) / (param.max - param.min))


def lin(param: NumericParameter, value: float, a: float, b: float) -> float:
    """Linear mapping ``param.min -> a``, ``param.max -> b``, clamped to the range."""
    return a + (b - a) * fraction(param, value)


# ------------------------------------------------------------------ values
class ParameterValues:
    """Parameter definitions of a page together with their current values."""

    def __init__(
        self, parameters: Iterable[Parameter], values: Mapping[str, ParamValue] | None = None
    ) -> None:
        self._params = {p.name: p for p in parameters}
        self._values: dict[str, ParamValue] = {p.name: p.default for p in self._params.values()}
        self._values.update({k: v for k, v in (values or {}).items() if k in self._params})

    @classmethod
    def for_page(
        cls, page: Page, overrides: Mapping[str, ParamValue] | None = None
    ) -> ParameterValues:
        return cls(page.parameters, {**page.test_values, **(overrides or {})})

    def param(self, name: str | None) -> Parameter | None:
        return self._params.get(name) if name else None

    def value(self, name: str | None) -> ParamValue | None:
        return self._values.get(name) if name else None

    def as_dict(self) -> dict[str, ParamValue]:
        return dict(self._values)


def compare(op: str, left: Any, right: Any) -> bool:
    """Condition test with strict types: ``True`` never equals ``1``.

    ``in`` / ``not in``: ``right`` is ``(from, to)``, both ends included.
    """
    if op in ("in", "not in"):
        lo, hi = right
        if isinstance(left, bool) or not isinstance(left, int | float):
            return op == "not in"
        inside = bool(lo <= left <= hi)
        return inside if op == "in" else not inside
    if isinstance(left, bool) != isinstance(right, bool):
        return op == "!="
    if op == "==":
        return bool(left == right)
    if op == "!=":
        return bool(left != right)
    try:
        if op == ">":
            return bool(left > right)
        if op == "<":
            return bool(left < right)
        if op == ">=":
            return bool(left >= right)
        if op == "<=":
            return bool(left <= right)
    except TypeError:
        return False
    raise ValueError(f"unknown operator {op!r}")


def condition_matches(condition: Condition, values: ParameterValues) -> bool:
    param = values.param(condition.param)
    if param is None or isinstance(param, SeriesParameter):
        return False
    return compare(condition.op, values.value(param.name), condition.value)


# ------------------------------------------------------------------ format
_FORMAT_RE = re.compile(r"%(?:\.(\d+))?([fds%])")
_ANY_PERCENT_RE = re.compile(r"%(?:\.\d+)?.?", re.DOTALL)


def format_problem(fmt: str) -> str | None:
    """Ukrainian description of an unsupported ``%`` sequence, or None."""
    for match in _ANY_PERCENT_RE.finditer(fmt):
        if not _FORMAT_RE.fullmatch(match.group()):
            return f"«{match.group()}» не підтримується; можна %s, %d, %.Nf, %%"
    return None


def format_value(fmt: str, value: Any) -> str:
    """printf subset: ``%s``, ``%d`` (half-up rounding), ``%.Nf``, ``%f`` (6), ``%%``."""

    def repl(match: re.Match[str]) -> str:
        digits, kind = match.groups()
        if kind == "%":
            return "%"
        if kind == "s" or isinstance(value, bool) or not isinstance(value, int | float):
            return str(value)  # as MicroPython's '%s' % value: True, 21.5
        if kind == "d":
            return str(round_half_up(value))
        return f"{value:.{int(digits) if digits else 6}f}"

    return _FORMAT_RE.sub(repl, fmt)


# ------------------------------------------------------------------ series
class SeriesParseError(ValueError):
    """Ukrainian message about the ``x:y; x:y`` test value text."""


def parse_series(text: str, param: SeriesParameter) -> list[SeriesPoint]:
    """``"0:14; 3:13.5"`` -> points; numeric X are sorted ascending."""
    parts = [part.strip() for part in text.split(";") if part.strip()]
    if not parts:
        raise SeriesParseError("Введіть точки у форматі x:y; x:y")
    points: list[SeriesPoint] = []
    for part in parts:
        sep = part.rfind(":")
        if sep < 1:
            raise SeriesParseError(f"«{part}» — потрібен формат x:y")
        x_text, y_text = part[:sep].strip(), part[sep + 1 :].strip()
        y = _parse_number(y_text)
        if y is None:
            raise SeriesParseError(f"«{part}» — y має бути числом")
        x: float | str
        if param.x_kind == "number":
            number = _parse_number(x_text)
            if number is None:
                raise SeriesParseError(f"«{part}» — ключ x має бути числом")
            x = number
        else:
            if len(x_text) > MAX_LABEL_LEN:
                raise SeriesParseError(f"Мітка «{x_text}» довша за {MAX_LABEL_LEN} символів")
            x = x_text
        points.append(SeriesPoint(x=x, y=y))
    if len(points) > param.max_points:
        raise SeriesParseError(f"Максимум {param.max_points} точок")
    if len({str(p.x) for p in points}) != len(points):
        raise SeriesParseError("Ключі x мають бути різними")
    if param.x_kind == "number":
        points.sort(key=lambda p: float(p.x))
    return points


def _parse_number(text: str) -> float | None:
    try:
        number = float(text.replace(",", "."))
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _number_text(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def series_to_text(points: Sequence[SeriesPoint]) -> str:
    """Inverse of :func:`parse_series` (Y rounded to 0.1, as in the editor)."""
    return "; ".join(
        f"{p.x if isinstance(p.x, str) else _number_text(p.x)}:{_number_text(round(p.y, 1))}"
        for p in points
    )


# ------------------------------------------------------------------ chart
def chart_y_range(
    chart: ChartSettings, param: SeriesParameter | None, points: Sequence[SeriesPoint]
) -> tuple[float, float]:
    """Y axis range: manual bounds, else parameter range widened to the data."""
    lo = chart.y_min if chart.y_min is not None else (param.min if param else 0.0)
    hi = chart.y_max if chart.y_max is not None else (param.max if param else 10.0)
    ys = [p.y for p in points]
    if chart.y_min is None and ys:
        lo = min(lo, *ys)
    if chart.y_max is None and ys:
        hi = max(hi, *ys)
    if hi <= lo:
        hi = lo + 1
    return lo, hi


def chart_label_indices(count: int, width: int) -> tuple[int, ...]:
    """Which X labels are drawn: first, middle (if wider than 110 px), last."""
    if count > 2 and width > 110:
        return (0, (count - 1) // 2, count - 1)
    if count > 1:
        return (0, count - 1)
    return (0,) if count else ()


# ------------------------------------------------------------------ widget
def pivot_offset(widget: Widget) -> tuple[float, float]:
    """Pivot relative to the widget's top-left corner."""
    if isinstance(widget.pivot, PivotPoint):
        return widget.pivot.x, widget.pivot.y
    fx, fy = PIVOT_FRACTIONS[widget.pivot]
    return widget.w * fx, widget.h * fy


@dataclass(frozen=True, slots=True)
class EffectiveWidget:
    """A widget as it must look for given parameter values (absolute coordinates)."""

    id: str
    type: str
    x: int
    y: int
    w: int
    h: int
    visible: bool
    color: str
    opacity: float
    """Percent 0..100 after rules (may be fractional from a mapping)."""
    angle: float
    """Degrees; always 0 for a chart."""
    pivot: tuple[float, float]
    """Absolute pivot point (moves with the widget)."""
    format: str
    text: str | None
    """Text to draw (text/value/bar/arc label), None for shapes."""
    value: ParamValue | None
    """Bound parameter value."""
    fraction: float | None
    """Bar/arc fill 0..1 (numeric binding only)."""
    image_source: str | None
    """Image key (static file) or board path (from a ``str`` parameter)."""

    @property
    def alpha(self) -> float:
        return clamp01(self.opacity / 100)

    @property
    def bounds(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.w, self.h


def effective(widget: Widget, values: ParameterValues) -> EffectiveWidget:
    x: float = widget.x
    y: float = widget.y
    opacity: float = widget.opacity
    angle: float = widget.rotation_deg
    color, fmt, visible = widget.color, widget.format, True

    for mapping in widget.mappings():
        param = values.param(mapping.param)
        current = values.value(mapping.param)
        if not is_numeric(param) or not isinstance(current, int | float):
            continue
        result = lin(param, current, mapping.at_min, mapping.at_max)  # type: ignore[arg-type]
        if mapping.prop == "opacity":
            opacity = result
        elif mapping.prop == "angle":
            angle = result
        elif mapping.prop == "x":
            x = result
        else:
            y = result

    for condition in widget.conditions():
        if not condition_matches(condition, values):
            continue
        to = condition.to
        if condition.prop == "color" and isinstance(to, str):
            color = to.lower()
        elif condition.prop == "text":
            fmt = str(to)
        elif condition.prop == "visible":
            visible = bool(to)
        elif isinstance(to, int | float) and not isinstance(to, bool):
            if condition.prop == "opacity":
                opacity = to
            elif condition.prop == "angle":
                angle = to
            elif condition.prop == "x":
                x = to
            elif condition.prop == "y":
                y = to

    if widget.type == "chart":
        angle = 0.0
    ix, iy = round_half_up(x), round_half_up(y)
    px, py = pivot_offset(widget)
    param = values.param(widget.bind)
    value = values.value(widget.bind) if param is not None else None

    return EffectiveWidget(
        id=widget.id,
        type=widget.type,
        x=ix,
        y=iy,
        w=widget.w,
        h=widget.h,
        visible=visible,
        color=color,
        opacity=max(0.0, min(100.0, opacity)),
        angle=angle,
        pivot=(ix + px, iy + py),
        format=fmt,
        text=_widget_text(widget, fmt, param, value),
        value=value,
        fraction=_fraction(param, value),
        image_source=_image_source(widget, value),
    )


def _widget_text(widget: Widget, fmt: str, param: Parameter | None, value: Any) -> str | None:
    if widget.type in ("text", "value"):
        return fmt if param is None else format_value(fmt, value)
    if widget.type == "bar":
        return fmt  # label; the number is drawn by the bar itself
    if widget.type == "arc":
        return None if param is None else number_label(param, value)
    return None


def number_label(param: Parameter, value: Any) -> str:
    """Number shown by bars and arcs: one decimal for float, as is for int."""
    if isinstance(param, IntParameter | BoolParameter):
        return str(value)
    return f"{value:.1f}" if isinstance(value, int | float) else str(value)


def _fraction(param: Parameter | None, value: Any) -> float | None:
    if is_numeric(param) and isinstance(value, int | float) and not isinstance(value, bool):
        return fraction(param, value)  # type: ignore[arg-type]
    return None


def _image_source(widget: Widget, value: Any) -> str | None:
    if widget.type != "image":
        return None
    if widget.bind:
        return value if isinstance(value, str) and value else None
    return widget.image.file if widget.image else None


def effective_page(page: Page, values: ParameterValues | None = None) -> list[EffectiveWidget]:
    vals = values or ParameterValues.for_page(page)
    return [effective(w, vals) for w in page.widgets]
