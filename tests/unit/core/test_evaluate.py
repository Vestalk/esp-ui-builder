"""Formulas shared by the generator and the GUI preview."""

from __future__ import annotations

from typing import Any

import pytest

from espui.core.evaluate import (
    ParameterValues,
    SeriesParseError,
    chart_label_indices,
    chart_y_range,
    compare,
    effective,
    effective_page,
    format_problem,
    format_value,
    lin,
    number_label,
    parse_series,
    pivot_offset,
    round_half_up,
    series_to_text,
)
from espui.core.models import (
    ChartSettings,
    FloatParameter,
    IntParameter,
    SeriesParameter,
    SeriesPoint,
    Widget,
)
from tests.unit.core.conftest import FLAG, LEVEL, MODE, NAME, SERIES, TEMP, make_page

T = FloatParameter.model_validate(TEMP)


def widget(**fields: Any) -> Widget:
    return Widget.model_validate({"id": "w", "type": "text", "w": 100, "h": 20, **fields})


def values(**overrides: Any) -> ParameterValues:
    params = make_page([TEMP, LEVEL, FLAG, MODE, NAME, SERIES]).parameters
    return ParameterValues(params, overrides)


# ------------------------------------------------------------------ numbers
@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, 10), (100, 30), (50, 20), (-20, 10), (150, 30), (25, 15)],
)
def test_lin_clamps(value: float, expected: float) -> None:
    assert lin(T, value, 10, 30) == expected


def test_lin_reversed_and_int() -> None:
    assert lin(T, 25, 100, 0) == 75
    assert lin(IntParameter.model_validate(LEVEL), 5, 0, 1) == 0.5


@pytest.mark.parametrize(
    ("value", "expected"), [(0.5, 1), (1.5, 2), (-0.5, 0), (2.49, 2), (-1.5, -1)]
)
def test_round_half_up(value: float, expected: int) -> None:
    assert round_half_up(value) == expected


# ------------------------------------------------------------------ compare
@pytest.mark.parametrize(
    ("op", "left", "right", "expected"),
    [
        ("==", 1, 1.0, True),
        ("!=", 1, 2, True),
        (">", 2, 1, True),
        ("<", 2, 1, False),
        (">=", 1, 1, True),
        ("<=", 1, 0, False),
        ("==", True, 1, False),
        ("!=", True, 1, True),
        (">", "a", 1, False),
    ],
)
def test_compare(op: str, left: Any, right: Any, expected: bool) -> None:
    assert compare(op, left, right) is expected


def test_compare_unknown_operator() -> None:
    with pytest.raises(ValueError, match="unknown operator"):
        compare("~", 1, 1)


# ------------------------------------------------------------------ values
def test_parameter_values() -> None:
    vals = values(t=70.0, ghost=1)
    assert vals.value("t") == 70.0
    assert vals.value("n") == 5
    assert vals.value("ghost") is None
    assert vals.value(None) is None
    assert vals.param(None) is None
    assert vals.as_dict()["mode"] == "a"


def test_values_for_page_use_test_values() -> None:
    page = make_page([TEMP, FLAG], test_values={"t": 80.0})
    assert ParameterValues.for_page(page).value("t") == 80.0
    assert ParameterValues.for_page(page, {"t": 10.0}).value("t") == 10.0


# ------------------------------------------------------------------ format
@pytest.mark.parametrize(
    ("fmt", "value", "expected"),
    [
        ("%.1f°C", 21.55, "21.6°C"),
        ("%.0f", 2.5, "2"),  # Python's banker-free formatting of 2.5 -> '2'
        ("%d %%", 2.5, "3 %"),
        ("%d", -2.5, "-2"),
        ("%f", 1, "1.000000"),
        ("%s", 21.5, "21.5"),
        ("%s", True, "True"),
        ("%d", True, "True"),
        ("%s!", "OK", "OK!"),
        ("Без формату", 5, "Без формату"),
        ("%d/%d", 7, "7/7"),
    ],
)
def test_format_value(fmt: str, value: Any, expected: str) -> None:
    assert format_value(fmt, value) == expected


@pytest.mark.parametrize(
    ("fmt", "problem"),
    [
        ("%.1f", None),
        ("%s %d %% %f", None),
        ("%x", "«%x» не підтримується; можна %s, %d, %.Nf, %%"),
        ("50%", "«%» не підтримується; можна %s, %d, %.Nf, %%"),
        ("%5d", "«%5» не підтримується; можна %s, %d, %.Nf, %%"),
    ],
)
def test_format_problem(fmt: str, problem: str | None) -> None:
    assert format_problem(fmt) == problem


# ------------------------------------------------------------------ series
S = SeriesParameter.model_validate(SERIES)
LABELS = SeriesParameter.model_validate({**SERIES, "x_kind": "label"})


def test_parse_series_numbers_sorted() -> None:
    points = parse_series(" 3:13,5; 0:14 ;", S)
    assert [(p.x, p.y) for p in points] == [(0.0, 14.0), (3.0, 13.5)]
    assert series_to_text(points) == "0:14; 3:13.5"


def test_parse_series_labels_keep_order() -> None:
    points = parse_series("вт:2; пн:1.04", LABELS)
    assert [(p.x, p.y) for p in points] == [("вт", 2.0), ("пн", 1.04)]
    assert series_to_text(points) == "вт:2; пн:1"


def test_parse_series_label_with_colon() -> None:
    assert parse_series("12:30:5", LABELS)[0].x == "12:30"


@pytest.mark.parametrize(
    ("text", "param", "message"),
    [
        ("", S, "Введіть точки у форматі x:y; x:y"),
        ("5", S, "«5» — потрібен формат x:y"),
        (":5", S, "«:5» — потрібен формат x:y"),
        ("1:a", S, "«1:a» — y має бути числом"),
        ("1:inf", S, "«1:inf» — y має бути числом"),
        ("a:1", S, "«a:1» — ключ x має бути числом"),
        ("1:1; 1:2", S, "Ключі x мають бути різними"),
        ("1:1; 2:1; 3:1; 4:1; 5:1", S, "Максимум 4 точок"),
        ("понеділок:1", LABELS, "Мітка «понеділок» довша за 7 символів"),
        ("пн:1; пн:2", LABELS, "Ключі x мають бути різними"),
    ],
)
def test_parse_series_errors(text: str, param: SeriesParameter, message: str) -> None:
    with pytest.raises(SeriesParseError) as info:
        parse_series(text, param)
    assert str(info.value) == message


# ------------------------------------------------------------------ chart
def test_chart_y_range() -> None:
    pts = [SeriesPoint(x=0, y=5), SeriesPoint(x=1, y=12)]
    assert chart_y_range(ChartSettings(), S, pts) == (0, 12)
    assert chart_y_range(ChartSettings(y_min=2, y_max=8), S, pts) == (2, 8)
    assert chart_y_range(ChartSettings(), None, []) == (0, 10)
    assert chart_y_range(ChartSettings(y_min=5, y_max=5), S, pts) == (5, 6)


@pytest.mark.parametrize(
    ("count", "width", "expected"),
    [(0, 200, ()), (1, 200, (0,)), (2, 200, (0, 1)), (5, 200, (0, 2, 4)), (5, 100, (0, 4))],
)
def test_chart_label_indices(count: int, width: int, expected: tuple[int, ...]) -> None:
    assert chart_label_indices(count, width) == expected


# ------------------------------------------------------------------ effective
def test_base_values() -> None:
    e = effective(widget(x=10, y=20, opacity=80, rotation_deg=15, format="Hi"), values())
    assert (e.x, e.y, e.w, e.h, e.bounds) == (10, 20, 100, 20, (10, 20, 100, 20))
    assert (e.visible, e.color, e.opacity, e.alpha, e.angle) == (True, "#ffffff", 80, 0.8, 15)
    assert e.pivot == (60.0, 30.0)
    assert e.text == "Hi"
    assert e.value is None
    assert e.fraction is None
    assert e.image_source is None


MAP_X = {"param": "t", "prop": "x", "at_min": 0, "at_max": 200}


@pytest.mark.parametrize(("t", "x"), [(0.0, 0), (100.0, 200), (50.0, 100), (25.3, 51), (-5.0, 0)])
def test_mapping_min_max_middle(t: float, x: int) -> None:
    assert effective(widget(rules=[MAP_X]), values(t=t)).x == x


def test_every_mapping_prop() -> None:
    rules = [
        {"param": "t", "prop": "opacity", "at_min": 0, "at_max": 100},
        {"param": "t", "prop": "angle", "at_min": -90, "at_max": 90},
        {"param": "n", "prop": "y", "at_min": 0, "at_max": 100},
    ]
    e = effective(widget(rules=rules), values(t=25.0, n=2))
    assert (e.opacity, e.angle, e.y) == (25, -45, 20)


def test_conditions_lowest_wins() -> None:
    rules = [
        {"if": ["t", ">", 30], "set": "color", "to": "#FFA500"},
        {"if": ["t", ">", 60], "set": "color", "to": "#ff0000"},
    ]
    assert effective(widget(rules=rules), values(t=20.0)).color == "#ffffff"
    assert effective(widget(rules=rules), values(t=40.0)).color == "#ffa500"
    assert effective(widget(rules=rules), values(t=70.0)).color == "#ff0000"
    # Reversed order: the lower (weaker) rule now overrides.
    assert effective(widget(rules=rules[::-1]), values(t=70.0)).color == "#ffa500"


def test_condition_over_mapping() -> None:
    rules = [MAP_X, {"if": ["on", "==", True], "set": "x", "to": 5}]
    assert effective(widget(rules=rules), values(t=50.0)).x == 100
    assert effective(widget(rules=rules), values(t=50.0, on=True)).x == 5
    # Order in the list doesn't matter: mappings always go first.
    assert effective(widget(rules=rules[::-1]), values(t=50.0, on=True)).x == 5


def test_every_condition_prop() -> None:
    rules = [
        {"if": ["mode", "==", "b"], "set": "text", "to": "B: %s"},
        {"if": ["mode", "==", "b"], "set": "visible", "to": False},
        {"if": ["mode", "==", "b"], "set": "opacity", "to": 40},
        {"if": ["mode", "==", "b"], "set": "angle", "to": 90},
        {"if": ["mode", "==", "b"], "set": "y", "to": 7},
    ]
    e = effective(widget(bind="mode", format="%s", rules=rules), values(mode="b"))
    assert (e.text, e.visible, e.opacity, e.angle, e.y) == ("B: b", False, 40, 90, 7)
    e = effective(widget(bind="mode", format="%s", rules=rules), values(mode="a"))
    assert (e.text, e.visible, e.opacity, e.angle, e.y) == ("a", True, 100, 0, 0)


def test_broken_rules_are_ignored() -> None:
    rules = [
        {"param": "ghost", "prop": "x", "at_min": 0, "at_max": 9},
        {"param": "on", "prop": "x", "at_min": 0, "at_max": 9},
        {"if": ["ghost", "==", 1], "set": "x", "to": 9},
        {"if": ["s", "==", 1], "set": "x", "to": 9},
        {"if": ["t", ">", 0], "set": "x", "to": "nine"},
        {"if": ["t", ">", 0], "set": "color", "to": 5},
    ]
    e = effective(widget(x=3, rules=rules), values())
    assert (e.x, e.color) == (3, "#ffffff")


def test_opacity_is_clamped() -> None:
    rules = [{"param": "t", "prop": "opacity", "at_min": -50, "at_max": 300}]
    assert effective(widget(rules=rules), values(t=0.0)).opacity == 0
    assert effective(widget(rules=rules), values(t=100.0)).opacity == 100


def test_chart_never_rotates() -> None:
    w = widget(type="chart", bind="s", rules=[{"if": ["t", ">", 0], "set": "angle", "to": 30}])
    assert effective(w, values()).angle == 0


@pytest.mark.parametrize(
    ("pivot", "offset"),
    [
        ("center", (50, 10)),
        ("top_left", (0, 0)),
        ("bottom_right", (100, 20)),
        ("top", (50, 0)),
        ({"x": 3, "y": 4}, (3, 4)),
    ],
)
def test_pivot(pivot: Any, offset: tuple[float, float]) -> None:
    w = widget(pivot=pivot, x=10, y=10)
    assert pivot_offset(w) == offset
    assert effective(w, values()).pivot == (10 + offset[0], 10 + offset[1])


def test_pivot_moves_with_widget() -> None:
    w = widget(pivot="top_left", rules=[MAP_X])
    assert effective(w, values(t=50.0)).pivot == (100, 0)


def test_bound_widgets() -> None:
    vals = values(t=25.0, n=3, label="/img/a.bin")
    assert effective(widget(type="value", bind="t", format="%.1f"), vals).text == "25.0"
    bar = effective(widget(type="bar", bind="n", format="Рівень"), vals)
    assert (bar.text, bar.fraction, bar.value) == ("Рівень", 0.3, 3)
    arc = effective(widget(type="arc", bind="t"), vals)
    assert (arc.text, arc.fraction) == ("25.0", 0.25)
    assert effective(widget(type="arc"), vals).text is None
    assert effective(widget(type="rect"), vals).text is None
    assert effective(widget(type="text", bind="on", format="%s"), vals).fraction is None


def test_image_source() -> None:
    vals = values(label="/img/a.bin")
    assert effective(widget(type="image", image={"file": "logo"}), vals).image_source == "logo"
    assert effective(widget(type="image", bind="label"), vals).image_source == "/img/a.bin"
    assert effective(widget(type="image", bind="label"), values(label="")).image_source is None


@pytest.mark.parametrize(
    ("param", "value", "expected"),
    [(TEMP, 21.25, "21.2"), (LEVEL, 7, "7"), (FLAG, True, "True"), (TEMP, "x", "x")],
)
def test_number_label(param: dict[str, Any], value: Any, expected: str) -> None:
    p = make_page([param]).parameters[0]
    assert number_label(p, value) == expected


def test_effective_page() -> None:
    page = make_page(
        [TEMP],
        [{"id": "a", "type": "value", "bind": "t", "format": "%d"}, {"id": "b", "type": "rect"}],
        test_values={"t": 70.4},
    )
    assert [e.text for e in effective_page(page)] == ["70", None]
    assert [e.text for e in effective_page(page, values(t=1.0))] == ["1", None]
