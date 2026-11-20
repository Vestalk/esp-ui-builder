"""What a new widget looks like, and what changes when its type changes.

Defaults follow the mock-up (``DEF`` in docs/plan.html).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from espui.core.compat import can_bind, condition_props, mapping_props
from espui.core.models import WIDGET_TYPES, Condition, MappingRule, Page, Widget, WidgetType

TITLES: dict[str, str] = {
    "rect": "Прямокутник",
    "circle": "Коло",
    "line": "Лінія",
    "text": "Текст",
    "value": "Число",
    "bar": "Смуга прогресу",
    "arc": "Дуга",
    "image": "Картинка",
    "chart": "Графік",
}


@dataclass(frozen=True, slots=True)
class Defaults:
    w: int
    h: int
    color: str
    format: str = ""
    font_size: int | None = None


DEFAULTS: dict[str, Defaults] = {
    "rect": Defaults(120, 60, "#1d3a4a"),
    "circle": Defaults(40, 40, "#378add"),
    "line": Defaults(120, 0, "#56707c"),
    "text": Defaults(150, 22, "#ffffff", "Текст", 16),
    "value": Defaults(130, 32, "#ffffff", "0", 24),
    "bar": Defaults(200, 36, "#5dcaa5", "Підпис", 12),
    "arc": Defaults(120, 66, "#efa627", "", 14),
    "image": Defaults(64, 64, "#ffffff"),
    "chart": Defaults(200, 60, "#4da3ff"),
}
assert set(DEFAULTS) == set(WIDGET_TYPES)

MIN_SIZE = 4
"""Smallest width/height a widget can be resized to (a line may have height 0)."""


def free_id(page: Page, kind: str) -> str:
    """``<type>_<N>`` not yet used on the page."""
    taken = {w.id for w in page.widgets}
    n = 1
    while f"{kind}_{n}" in taken:
        n += 1
    return f"{kind}_{n}"


def new_widget(page: Page, kind: WidgetType, x: int, y: int, centered: bool = True) -> Widget:
    """A widget of ``kind`` with the mock-up's defaults; (x, y) is its centre if ``centered``."""
    d = DEFAULTS[kind]
    data: dict[str, Any] = {
        "id": free_id(page, kind),
        "type": kind,
        "w": d.w,
        "h": d.h,
        "color": d.color,
    }
    if d.format:
        data["format"] = d.format
    if d.font_size:
        data["font_size"] = d.font_size
    if centered:
        x, y = x - d.w // 2, y - d.h // 2
    data["x"], data["y"] = x, y
    return Widget.model_validate(data)


def change_type(widget: Widget, kind: WidgetType, page: Page) -> tuple[Widget, list[str]]:
    """``widget`` as another type: default size/format of the new type, same id, position,
    colour and the rules that still make sense. Returns (widget, Ukrainian messages)."""
    if kind == widget.type:
        return widget, []
    d = DEFAULTS[kind]
    messages = []
    param = page.parameter(widget.bind)
    bind = widget.bind
    if param is not None and not can_bind(kind, param):
        messages.append(
            f"Прив'язку до «{param.name}» знято: {TITLES[kind].lower()} не може її показати."
        )
        bind = None
    rules = []
    dropped = 0
    for rule in widget.rules:
        allowed = condition_props(kind) if isinstance(rule, Condition) else mapping_props(kind)
        if rule.prop in allowed:
            rules.append(rule)
        else:
            dropped += 1
    if dropped:
        messages.append(f"Умов, що не підходять до нового типу, видалено: {dropped}.")
    data: dict[str, Any] = {
        "id": widget.id,
        "type": kind,
        "x": widget.x,
        "y": widget.y,
        "w": d.w,
        "h": d.h,
        "color": widget.color,
        "bind": bind,
        "format": d.format if kind in ("text", "value", "bar") else "",
        "opacity": widget.opacity,
        "rotation_deg": 0 if kind == "chart" else widget.rotation_deg,
        "pivot": widget.pivot,
        "rules": rules,
    }
    if d.font_size:
        data["font_size"] = d.font_size
    if widget.font and kind in ("text", "value", "bar", "arc", "chart"):
        data["font"] = widget.font
    return Widget.model_validate(data), messages


def badges(widget: Widget) -> str:
    """Icons for the layers list: ↻ angle, ◐ opacity, ⇄ position, conditions count."""
    out = []
    props = {r.prop for r in widget.rules}
    if widget.rotation_deg or "angle" in props:
        out.append("↻")
    if widget.opacity < 100 or "opacity" in props:
        out.append("◐")
    if props & {"x", "y"}:
        out.append("⇄")
    conditions = sum(isinstance(r, Condition) for r in widget.rules)
    mappings = sum(isinstance(r, MappingRule) for r in widget.rules)
    if conditions + mappings:
        out.append(f"умов: {conditions + mappings}")
    return " ".join(out)


def controlled_props(widget: Widget) -> dict[str, list[str]]:
    """Property -> parameters that change it through conditions / mappings."""
    out: dict[str, list[str]] = {}
    for rule in widget.rules:
        names = out.setdefault(rule.prop, [])
        if rule.param not in names:
            names.append(rule.param)
    return out


def shift_widget(widget: Widget, dx: int, dy: int) -> Widget:
    """Move the base position and every x/y value of its conditions and mappings together."""
    if not dx and not dy:
        return widget
    rules: list[Condition | MappingRule] = []
    for rule in widget.rules:
        delta = dx if rule.prop == "x" else dy if rule.prop == "y" else 0
        if not delta:
            rules.append(rule)
        elif isinstance(rule, MappingRule):
            rules.append(
                rule.model_copy(
                    update={"at_min": rule.at_min + delta, "at_max": rule.at_max + delta}
                )
            )
        elif isinstance(rule.to, int | float) and not isinstance(rule.to, bool):
            rules.append(rule.model_copy(update={"to": rule.to + delta}))
        else:
            rules.append(rule)
    return widget.model_copy(update={"x": widget.x + dx, "y": widget.y + dy, "rules": rules})


def mapping_defaults(prop: str, widget: Widget, screen: tuple[int, int]) -> tuple[float, float]:
    """Sensible (at_min, at_max) for a new mapping (the mock-up's ``dmap``)."""
    width, height = screen
    if prop == "opacity":
        return 0, 100
    if prop == "angle":
        return -90, 90
    if prop == "x":
        return widget.x, max(0, min(width - widget.w, widget.x + 100))
    return widget.y, max(0, min(height - widget.h, widget.y + 60))


def condition_default_to(prop: str, widget: Widget) -> Any:
    """Value a new condition sets (the mock-up's ``dto``)."""
    return {
        "color": "#ff4b55",
        "text": "ТРИВОГА",
        "visible": False,
        "opacity": 30,
        "angle": 45,
        "x": widget.x + 40,
        "y": widget.y + 20,
    }[prop]
