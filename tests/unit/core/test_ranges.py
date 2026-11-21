"""Conditions on a range: ``[t, "in", [10, 20]]`` / ``[t, "not in", [10, 20]]``, ends included."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from espui.core import serializer
from espui.core.checks import check_project
from espui.core.evaluate import ParameterValues, compare, condition_matches, effective
from espui.core.models import Condition, Project
from espui.core.params import compare_value_for
from espui.generators.micropython.generator import generate


def project(op: str = "in", value: Any = (10, 20), kind: str = "int") -> Project:
    return serializer.from_dict(
        {
            "pages": [
                {
                    "name": "main",
                    "parameters": [
                        {"name": "t", "type": kind, "min": 0, "max": 100, "default": 15},
                        {"name": "mode", "type": "str"},
                    ],
                    "widgets": [
                        {
                            "id": "r",
                            "type": "rect",
                            "w": 40,
                            "h": 20,
                            "rules": [
                                {"if": ["t", op, list(value)], "set": "color", "to": "#ff0000"}
                            ],
                        }
                    ],
                }
            ]
        }
    )


@pytest.mark.parametrize(
    ("value", "inside"),
    [(9, False), (10, True), (15, True), (20, True), (20.5, False), (-3, False)],
)
def test_ends_are_included(value: float, inside: bool) -> None:
    assert compare("in", value, (10, 20)) is inside
    assert compare("not in", value, (10, 20)) is not inside


def test_non_numbers_are_never_inside() -> None:
    assert compare("in", True, (0, 5)) is False
    assert compare("in", "7", (0, 10)) is False
    assert compare("not in", "7", (0, 10)) is True


def test_model_keeps_the_range_and_roundtrips() -> None:
    proj = project(value=(10, 20.5))
    rule = proj.pages[0].widgets[0].rules[0]
    assert isinstance(rule, Condition)
    assert (rule.op, rule.value, rule.is_range) == ("in", (10, 20.5), True)
    assert isinstance(rule.value[0], int)  # 10 stays an int
    again = serializer.from_dict(serializer.to_dict(proj))
    assert again == proj
    assert serializer.to_dict(proj)["pages"][0]["widgets"][0]["rules"][0]["if"] == [
        "t",
        "in",
        [10, 20.5],
    ]


@pytest.mark.parametrize(("op", "value"), [("in", 5), (">", [1, 2])])
def test_range_only_with_range_operators(op: str, value: Any) -> None:
    with pytest.raises(ValidationError, match="діапазон"):
        Condition.model_validate({"if": ["t", op, value], "set": "color", "to": "#fff"})


def test_symbol_aliases() -> None:
    rule = Condition.model_validate({"if": ["t", "∉", [1, 2]], "set": "color", "to": "#fff"})
    assert rule.op == "not in"


def with_when(when: tuple[str, str, Any]) -> Project:
    """A valid project whose condition is replaced (serializer.from_dict would reject it)."""
    proj = project()
    rule = proj.pages[0].widgets[0].rules[0]
    assert isinstance(rule, Condition)
    proj.pages[0].widgets[0].rules[0] = rule.model_copy(update={"when": when})
    return proj


def test_checks() -> None:
    assert check_project(project()) == []
    problems = [i.message for i in check_project(with_when(("t", "in", (30, 20))))]
    assert any("«від» (30) більше за «до» (20)" in p for p in problems)
    problems = [i.message for i in check_project(with_when(("mode", "in", (1, 2))))]
    assert any("для str можна лише" in p for p in problems)


def test_preview_follows_the_range() -> None:
    proj = project()
    page = proj.pages[0]
    for t, color in ((5, "#ffffff"), (10, "#ff0000"), (20, "#ff0000"), (21, "#ffffff")):
        values = ParameterValues.for_page(page, {"t": t})
        rule = page.widgets[0].rules[0]
        assert isinstance(rule, Condition)
        assert condition_matches(rule, values) is (color == "#ff0000")
        assert effective(page.widgets[0], values).color == color


@pytest.mark.parametrize(
    ("op", "expected"),
    [("in", 'if 10 <= p["t"] <= 20:'), ("not in", 'if not (10 <= p["t"] <= 20):')],
)
def test_generated_test(op: str, expected: str) -> None:
    code = generate(project(op)).files["ui_main.py"].decode()
    assert expected in code


def test_value_follows_the_operator() -> None:
    proj = project()
    t = proj.pages[0].parameter("t")
    assert compare_value_for("in", t, 30) == [30, 100]  # from the value to the maximum
    assert compare_value_for("in", t, 200) == [200, 200]  # never an empty range
    assert compare_value_for("not in", t, [1, 2]) == [1, 2]
    assert compare_value_for(">", t, [7, 9]) == 7  # back to one value: "від"
    assert compare_value_for("==", t, 5) == 5
