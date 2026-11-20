"""Changing a parameter of a page and everything that refers to it.

Used by the GUI's "edit parameter" dialog, but pure: it takes a page and returns
a new one, plus a Ukrainian summary of what had to change elsewhere.
"""

from __future__ import annotations

from typing import Any

from espui.core.compat import can_bind, operators_for, value_problem
from espui.core.models import (
    BoolParameter,
    Condition,
    EnumParameter,
    FloatParameter,
    IntParameter,
    MappingRule,
    Page,
    Parameter,
    ParamValue,
    SeriesParameter,
    StrParameter,
)


def is_numeric(param: Parameter) -> bool:
    return isinstance(param, FloatParameter | IntParameter)


def default_compare_value(param: Parameter) -> Any:
    """Value a condition starts with for ``param`` (as the mock-up's ``dval``)."""
    if isinstance(param, BoolParameter):
        return True
    if isinstance(param, EnumParameter):
        return param.values[0]
    if isinstance(param, StrParameter):
        return ""
    if isinstance(param, IntParameter):
        return (param.min + param.max) // 2
    if isinstance(param, FloatParameter):
        return (param.min + param.max) / 2
    return None


def fit_value(param: Parameter, value: Any) -> ParamValue:
    """``value`` made valid for ``param``: clamped to the range, or the default."""
    if (
        isinstance(param, FloatParameter | IntParameter)
        and isinstance(value, int | float)
        and not isinstance(value, bool)
    ):
        clamped = min(max(value, param.min), param.max)
        return round(clamped) if isinstance(param, IntParameter) else float(clamped)
    if value_problem(param, value) is None:
        return value  # type: ignore[no-any-return]
    return param.default


def update_parameter(page: Page, old_name: str, new: Parameter) -> tuple[Page, list[str]]:
    """Replace parameter ``old_name`` with ``new`` and fix every reference.

    Renaming updates bindings, rules and the test value. New bounds clamp the
    test value; removed enum variants are replaced in conditions. A new type
    drops bindings the widgets can't show and mappings from a non-number, and
    resets conditions to the operator and value of the new type.
    """
    page = page.model_copy(deep=True)
    old = page.parameter(old_name)
    if old is None:
        raise KeyError(old_name)
    notes: list[str] = []
    page.parameters = [new if p.name == old_name else p for p in page.parameters]
    retyped = old.type != new.type

    if old_name in page.test_values:
        value = page.test_values.pop(old_name)
        fitted = fit_value(new, value) if not retyped else new.default
        page.test_values[new.name] = fitted
        if fitted != value and not retyped:
            notes.append(
                f"Тестове значення «{new.name}» змінено на {fitted!r}: воно поза новими межами."
            )

    unbound = dropped = reset = replaced = 0
    for widget in page.widgets:
        if widget.bind == old_name:
            if can_bind(widget.type, new):
                widget.bind = new.name
            else:
                widget.bind = None
                unbound += 1
        rules = []
        for rule in widget.rules:
            if rule.param != old_name:
                rules.append(rule)
                continue
            if isinstance(rule, MappingRule):
                if is_numeric(new):
                    rules.append(rule.model_copy(update={"param": new.name}))
                else:
                    dropped += 1
                continue
            fixed = _fix_condition(rule, new, retyped)
            rules.append(fixed)
            if retyped:
                reset += 1
            elif fixed.value != rule.value:
                replaced += 1
        widget.rules = rules

    if unbound:
        notes.append(f"Прив'язок знято: {unbound} (елементи не можуть показати {new.type}).")
    if dropped:
        notes.append(f"Залежностей видалено: {dropped} (потрібен числовий параметр).")
    if reset:
        notes.append(f"Умов скинуто до значень за замовчуванням: {reset}.")
    if replaced:
        notes.append(f"Умов зі зміненим значенням: {replaced} (такого варіанта більше немає).")
    return page, notes


def _fix_condition(rule: Condition, new: Parameter, retyped: bool) -> Condition:
    op, value = rule.op, rule.value
    if retyped:
        ops = operators_for(new) or ("==",)
        op, value = ops[0], default_compare_value(new)
    elif isinstance(new, EnumParameter) and value not in new.values:
        value = new.values[0]
    return Condition.model_validate(
        {"kind": "condition", "if": [new.name, op, value], "set": rule.prop, "to": rule.to}
    )


def unused_parameters(page: Page) -> list[str]:
    """Parameters no widget shows or depends on."""
    used = set()
    for widget in page.widgets:
        used |= widget.dependencies()
    return [p.name for p in page.parameters if p.name not in used]


def parameter_summary(param: Parameter) -> str:
    """``float · -40…85``, ``enum · OK, Увага``, ``series · ≤ 24 точок``."""
    if isinstance(param, FloatParameter | IntParameter):
        return f"{param.type} · {param.min:g}…{param.max:g}"
    if isinstance(param, EnumParameter):
        return "enum · " + ", ".join(param.values)
    if isinstance(param, StrParameter):
        return f"str · < {param.max_len} символів"
    if isinstance(param, SeriesParameter):
        return f"series · ≤ {param.max_points} точок · y {param.min:g}…{param.max:g}"
    return "bool"
