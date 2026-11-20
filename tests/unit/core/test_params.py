"""Editing a parameter and its references (core.params)."""

from __future__ import annotations

from typing import Any

import pytest

from espui.core.checks import check_project
from espui.core.models import Condition, MappingRule, Parameter, Project
from espui.core.params import (
    default_compare_value,
    fit_value,
    parameter_summary,
    unused_parameters,
    update_parameter,
)
from tests.unit.core.conftest import FLAG, MODE, NAME, SERIES, TEMP, make_project


def project() -> Project:
    return make_project(
        parameters=[TEMP, FLAG, MODE, NAME, SERIES],
        widgets=[
            {"id": "v", "type": "value", "bind": "t", "rules": [
                {"if": ["t", ">", 40], "set": "color", "to": "#ff0000"},
                {"param": "t", "prop": "x", "at_min": 0, "at_max": 100},
            ]},
            {"id": "m", "type": "text", "bind": "mode", "format": "%s", "rules": [
                {"if": ["mode", "==", "c"], "set": "visible", "to": False},
            ]},
            {"id": "b", "type": "bar", "bind": "t"},
        ],
    )  # fmt: skip


def param(data: dict[str, Any]) -> Parameter:
    from pydantic import TypeAdapter

    return TypeAdapter(Parameter).validate_python(data)


def test_rename_updates_every_reference() -> None:
    p = project()
    p.pages[0].test_values = {"t": 30.0}
    page, notes = update_parameter(p.pages[0], "t", param({**TEMP, "name": "temp"}))
    v, _, b = page.widgets
    assert (v.bind, b.bind) == ("temp", "temp")
    assert {r.param for r in v.rules} == {"temp"}
    assert page.test_values == {"temp": 30.0}
    assert notes == []
    p.pages[0] = page
    assert check_project(p) == []


def test_new_bounds_clamp_the_test_value() -> None:
    p = project()
    p.pages[0].test_values = {"t": 90.0}
    page, notes = update_parameter(p.pages[0], "t", param({**TEMP, "max": 50, "default": 10}))
    assert page.test_values == {"t": 50.0}
    assert notes == ["Тестове значення «t» змінено на 50.0: воно поза новими межами."]


def test_removed_enum_variant_is_replaced_in_conditions() -> None:
    p = project()
    page, notes = update_parameter(p.pages[0], "mode", param({**MODE, "values": ["a", "b"]}))
    (rule,) = page.widgets[1].rules
    assert isinstance(rule, Condition)
    assert rule.value == "a"
    assert notes == ["Умов зі зміненим значенням: 1 (такого варіанта більше немає)."]


def test_type_change_cleans_up() -> None:
    p = project()
    p.pages[0].test_values = {"t": 30.0}
    page, notes = update_parameter(p.pages[0], "t", param({"name": "t", "type": "bool"}))
    v, _, b = page.widgets
    assert (v.bind, b.bind) == (None, None)  # a value or a bar can't show a bool
    assert not any(isinstance(r, MappingRule) for r in v.rules)
    (condition,) = v.rules
    assert isinstance(condition, Condition)
    assert (condition.op, condition.value) == ("==", True)
    assert page.test_values == {"t": False}
    assert notes == [
        "Прив'язок знято: 2 (елементи не можуть показати bool).",
        "Залежностей видалено: 1 (потрібен числовий параметр).",
        "Умов скинуто до значень за замовчуванням: 1.",
    ]
    p.pages[0] = page
    assert check_project(p) == []


def test_unknown_parameter() -> None:
    with pytest.raises(KeyError):
        update_parameter(project().pages[0], "ghost", param(FLAG))


def test_helpers() -> None:
    page = project().pages[0]
    assert unused_parameters(page) == ["on", "label", "s"]
    params = {p.name: p for p in page.parameters}
    assert parameter_summary(params["t"]) == "float · 0…100"
    assert parameter_summary(params["mode"]) == "enum · a, b, c"
    assert parameter_summary(params["label"]) == "str · < 8 символів"
    assert parameter_summary(params["s"]) == "series · ≤ 4 точок · y 0…10"
    assert parameter_summary(params["on"]) == "bool"
    assert fit_value(params["t"], 150) == 100.0
    assert fit_value(params["mode"], "zzz") == "a"
    assert fit_value(params["label"], "ok") == "ok"
    int_param = param({"name": "n", "type": "int", "min": 0, "max": 10, "default": 1})
    assert fit_value(int_param, 7.6) == 8
    assert [default_compare_value(params[n]) for n in ("on", "mode", "label", "t")] == [
        True,
        "a",
        "",
        50.0,
    ]
    assert default_compare_value(int_param) == 5
    assert default_compare_value(params["s"]) is None
