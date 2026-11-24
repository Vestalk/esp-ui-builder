"""Copy, paste and duplicate of widgets (the editor's Ctrl+C / Ctrl+V / Ctrl+D).

A copied widget travels as JSON together with the definitions of the parameters
it depends on (``bind`` and rules), so it can be pasted onto another page — even
another project — and keep working: missing parameters come along, a parameter
of the same name but another type is left as it is and the references to it are
dropped (with a note).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import TypeAdapter, ValidationError

from espui.core.models import Condition, MappingRule, Page, Parameter, Widget

MIME = "application/x-espui-widget"
"""Clipboard type of a copied widget (its text is the same JSON)."""
FORMAT = "espui-widget/1"
MAX_ID = 32
PASTE_OFFSET = 8
"""A pasted copy moves by this many px while it would sit exactly on another widget."""

_PARAMETER = TypeAdapter(Parameter)
_SUFFIX = re.compile(r"^(.*?)(?:_(\d+))?$")


class ClipboardError(ValueError):
    """Not a copied widget (or a damaged one)."""


@dataclass(slots=True)
class Pasted:
    page: Page
    widget_ids: list[str]
    """The new widgets, in layer order."""
    notes: list[str] = field(default_factory=list)
    """Parameters that came along / references dropped (for the status bar)."""

    @property
    def widget_id(self) -> str:
        """The (last) pasted widget."""
        return self.widget_ids[-1]


def copy_payload(page: Page, widgets: Widget | list[Widget]) -> str:
    """Widgets (in layer order) and the parameters they depend on, as clipboard text."""
    group = [widgets] if isinstance(widgets, Widget) else list(widgets)
    needed = set().union(*(w.dependencies() for w in group))
    params = [p.model_dump(mode="json") for p in page.parameters if p.name in needed]
    data = {"format": FORMAT,
            "widgets": [w.model_dump(mode="json", by_alias=True) for w in group],
            "parameters": params}  # fmt: skip
    return json.dumps(data, ensure_ascii=False)


def parse_payload(text: str) -> tuple[list[Widget], list[Parameter]]:
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise ClipboardError("у буфері немає скопійованого елемента") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ClipboardError("у буфері немає скопійованого елемента")
    try:
        raw = data["widgets"] if "widgets" in data else [data["widget"]]
        widgets = [Widget.model_validate(w) for w in raw]
        params = [_PARAMETER.validate_python(p) for p in data.get("parameters", [])]
    except (KeyError, TypeError, ValidationError):
        raise ClipboardError("скопійований елемент пошкоджено") from None
    if not widgets:
        raise ClipboardError("у буфері немає скопійованого елемента")
    return widgets, params


def free_copy_id(page: Page, widget_id: str) -> str:
    """``btn`` -> ``btn_2``; ``btn_2`` -> ``btn_3``: the first id not taken on the page."""
    taken = {w.id for w in page.widgets}
    if widget_id not in taken:
        return widget_id
    match = _SUFFIX.match(widget_id)
    base = (match.group(1) if match else "") or widget_id
    n = int(match.group(2)) + 1 if match and match.group(2) else 2
    while True:
        suffix = f"_{n}"
        candidate = base[: MAX_ID - len(suffix)] + suffix  # ids are at most 32 characters
        if candidate not in taken:
            return candidate
        n += 1


def _free_offset(page: Page, widgets: list[Widget]) -> int:
    """How far the group moves: by PASTE_OFFSET while any of it would sit exactly on a widget."""
    places = {(w.x, w.y, w.w, w.h) for w in page.widgets}
    offset = 0
    while any((w.x + offset, w.y + offset, w.w, w.h) in places for w in widgets):
        offset += PASTE_OFFSET
    return offset


def shift_widget(widget: Widget, dx: int, dy: int) -> Widget:
    """Move the base position and every x / y of its conditions and mappings together."""
    if not dx and not dy:
        return widget
    rules: list[Condition | MappingRule] = []
    for rule in widget.rules:
        delta = dx if rule.prop == "x" else dy if rule.prop == "y" else 0
        if not delta:
            rules.append(rule)
        elif isinstance(rule, MappingRule):
            rules.append(rule.model_copy(update={"at_min": rule.at_min + delta,
                                                 "at_max": rule.at_max + delta}))  # fmt: skip
        elif isinstance(rule.to, int | float) and not isinstance(rule.to, bool):
            rules.append(rule.model_copy(update={"to": rule.to + delta}))
        else:
            rules.append(rule)
    return widget.model_copy(update={"x": widget.x + dx, "y": widget.y + dy, "rules": rules})


def _without(widget: Widget, names: set[str]) -> Widget:
    """The widget with its references to ``names`` removed."""
    update: dict[str, Any] = {"rules": [r for r in widget.rules if r.param not in names]}
    if widget.bind in names:
        update["bind"] = None
    return widget.model_copy(update=update)


def paste(page: Page, text: str) -> Pasted:
    """``page`` with the copied widgets added on top (free ids, a free place, same layout)."""
    widgets, params = parse_payload(text)
    page = page.model_copy(deep=True)
    notes = []
    dropped = set()
    for param in params:
        existing = page.parameter(param.name)
        if existing is None:
            page.parameters.append(param)
            notes.append(f"додано параметр «{param.name}»")
        elif existing.type != param.type:
            dropped.add(param.name)
            notes.append(
                f"«{param.name}» на цій сторінці — {existing.type}, а не {param.type}: "
                "прив'язку й умови з ним прибрано"
            )
    if dropped:
        widgets = [_without(w, dropped) for w in widgets]
    offset = _free_offset(page, widgets)
    new_ids = []
    for widget in widgets:
        new_id = free_copy_id(page, widget.id)
        moved = shift_widget(widget, offset, offset)
        page.widgets.append(moved.model_copy(update={"id": new_id}))
        new_ids.append(new_id)
    return Pasted(page, new_ids, notes)
