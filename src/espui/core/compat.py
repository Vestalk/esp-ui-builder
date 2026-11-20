"""What goes with what: bindings, operators, rule properties, valid values.

Pure functions shared by the checks, ``evaluate`` and (later) the GUI, which
uses them to offer only compatible choices.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from espui.core.colors import is_hex
from espui.core.models import (
    BoolParameter,
    ConditionProp,
    EnumParameter,
    FloatParameter,
    IntParameter,
    MappingProp,
    Operator,
    Parameter,
    SeriesParameter,
    SeriesPoint,
    StrParameter,
    WidgetType,
)

MAX_LABEL_LEN = 7

BIND_TYPES: dict[WidgetType, frozenset[str]] = {
    "rect": frozenset(),
    "circle": frozenset(),
    "line": frozenset(),
    "text": frozenset({"float", "int", "bool", "str", "enum"}),
    "value": frozenset({"float", "int"}),
    "bar": frozenset({"float", "int"}),
    "arc": frozenset({"float", "int"}),
    "image": frozenset({"str"}),
    "chart": frozenset({"series"}),
}

_ALL_OPERATORS: tuple[Operator, ...] = (">", "<", ">=", "<=", "==", "!=")


def is_numeric(param: Parameter | None) -> bool:
    return isinstance(param, FloatParameter | IntParameter)


def can_bind(widget_type: WidgetType, param: Parameter) -> bool:
    return param.type in BIND_TYPES[widget_type]


def operators_for(param: Parameter) -> tuple[Operator, ...]:
    if isinstance(param, BoolParameter):
        return ("==",)
    if isinstance(param, EnumParameter | StrParameter):
        return ("==", "!=")
    if isinstance(param, SeriesParameter):
        return ()
    return _ALL_OPERATORS


def condition_props(widget_type: WidgetType) -> tuple[ConditionProp, ...]:
    props: list[ConditionProp] = ["color"]
    if widget_type in ("text", "value"):
        props.append("text")
    props += ["visible", "opacity"]
    if widget_type != "chart":
        props.append("angle")
    props += ["x", "y"]
    return tuple(props)


def mapping_props(widget_type: WidgetType) -> tuple[MappingProp, ...]:
    if widget_type == "chart":
        return ("opacity", "x", "y")
    return ("opacity", "angle", "x", "y")


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def value_problem(param: Parameter, value: Any) -> str | None:
    """Ukrainian reason why ``value`` is not valid for ``param``, or None."""
    if isinstance(param, BoolParameter):
        return None if isinstance(value, bool) else "очікується true або false"
    if isinstance(param, IntParameter):
        if not _is_number(value) or value != int(value):
            return "очікується ціле число"
        return _range_problem(value, param.min, param.max)
    if isinstance(param, FloatParameter):
        return (
            "очікується число"
            if not _is_number(value)
            else _range_problem(value, param.min, param.max)
        )
    if isinstance(param, StrParameter):
        if not isinstance(value, str):
            return "очікується рядок"
        if len(value) >= param.max_len:
            return f"довше за {param.max_len - 1} символів"
        return None
    if isinstance(param, EnumParameter):
        if value not in param.values:
            return f"має бути одним з варіантів: {', '.join(param.values)}"
        return None
    if not isinstance(value, list) or not all(isinstance(p, SeriesPoint) for p in value):
        return "очікується список точок {x, y}"
    return series_problem(param, value)


def _range_problem(value: float, lo: float, hi: float) -> str | None:
    return None if lo <= value <= hi else f"значення має бути в межах {lo:g}…{hi:g}"


def series_problem(param: SeriesParameter, points: Sequence[SeriesPoint]) -> str | None:
    if len(points) > param.max_points:
        return f"максимум {param.max_points} точок"
    for point in points:
        if param.x_kind == "number" and not _is_number(point.x):
            return f"ключ x «{point.x}» має бути числом"
        if param.x_kind == "label":
            if not isinstance(point.x, str):
                return f"ключ x «{point.x}» має бути міткою (рядком)"
            if len(point.x) > MAX_LABEL_LEN:
                return f"мітка «{point.x}» довша за {MAX_LABEL_LEN} символів"
        if not math.isfinite(point.y):
            return "y має бути числом"
    if len({str(p.x) for p in points}) != len(points):
        return "ключі x мають бути різними"
    return None


def prop_value_problem(prop: str, value: Any) -> str | None:
    """Ukrainian reason why ``value`` can't be assigned to rule property ``prop``."""
    if prop == "color":
        return None if isinstance(value, str) and is_hex(value) else "колір у форматі #rrggbb"
    if prop == "text":
        return None if isinstance(value, str) else "очікується рядок"
    if prop == "visible":
        return None if isinstance(value, bool) else "очікується true (показати) або false (сховати)"
    if not _is_number(value):
        return "очікується число"
    if prop == "opacity" and not 0 <= value <= 100:
        return "непрозорість від 0 до 100 %"
    return None
