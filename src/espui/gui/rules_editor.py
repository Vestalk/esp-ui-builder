"""The "Умови" block: conditions and mappings of the selected widget.

* Умова: «якщо <параметр> <оператор> <значення> → <властивість> = <значення>»;
  the one that matches the current test values is highlighted.
* Залежність: «від <числовий параметр> → <властивість>: при мін a, при макс b».

Every edit emits the whole new ``rules`` list; the properties panel validates
it with the model and pushes one undo step.
"""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from espui.core.checks import check_widget
from espui.core.compat import condition_props, mapping_props, operators_for
from espui.core.evaluate import ParameterValues, condition_matches
from espui.core.models import (
    BoolParameter,
    Condition,
    EnumParameter,
    FloatParameter,
    IntParameter,
    MappingRule,
    Page,
    Parameter,
    SeriesParameter,
    StrParameter,
    Widget,
)
from espui.core.params import compare_value_for, default_compare_value
from espui.gui.widgets_catalog import condition_default_to, mapping_defaults

PROP_TITLES = {
    "color": "колір",
    "text": "текст / формат",
    "visible": "видимість",
    "opacity": "непрозорість, %",
    "angle": "кут, °",
    "x": "x",
    "y": "y",
}
OP_TITLES = {
    "==": "=",
    "!=": "≠",
    ">": ">",
    "<": "<",
    ">=": "≥",
    "<=": "≤",
    "in": "у діапазоні",
    "not in": "поза діапазоном",
}


def _number(lo: float, hi: float, value: float, decimals: int = 1) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(lo, hi)
    spin.setDecimals(decimals)
    spin.setValue(value)
    spin.setMaximumWidth(90)
    spin.setMinimumWidth(64)  # the wide range must not widen the panel
    return spin


class RuleRow(QFrame):
    """One record: its editors in a row and a × button."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("rule")
        lines = QVBoxLayout(self)
        lines.setContentsMargins(4, 2, 2, 2)
        lines.setSpacing(2)
        self.row = QHBoxLayout()
        """First line: the condition / the source parameter."""
        self.row2 = QHBoxLayout()
        """Second line: what changes."""
        lines.addLayout(self.row)
        lines.addLayout(self.row2)
        self.remove_button = QToolButton(self)
        self.remove_button.setText("×")
        self.remove_button.setToolTip("Видалити запис")


class RulesEditor(QWidget):
    changed = Signal(list)
    """The new ``rules`` (list of dicts)."""

    def __init__(self) -> None:
        super().__init__()
        self.widget: Widget | None = None
        self.page: Page | None = None
        self.screen_size = (320, 240)
        self.rules: list[dict[str, Any]] = []
        self.rows: list[RuleRow] = []
        self._key: tuple[Any, ...] | None = None
        """What the rows were built from (see :meth:`load`)."""
        self._emitted: str | None = None
        """The rules this editor sent last (its rows already show them)."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.rows_box = QVBoxLayout()
        layout.addLayout(self.rows_box)
        buttons = QHBoxLayout()
        self.add_condition = QPushButton("+ Умова")
        self.add_condition.clicked.connect(self._add_condition)
        self.add_mapping = QPushButton("+ Залежність")
        self.add_mapping.clicked.connect(self._add_mapping)
        buttons.addWidget(self.add_condition)
        buttons.addWidget(self.add_mapping)
        layout.addLayout(buttons)
        self.errors = QLabel()
        self.errors.setObjectName("rule_errors")
        self.errors.setWordWrap(True)
        self.errors.setStyleSheet("color: #c0392b")
        layout.addWidget(self.errors)
        self.hint = QLabel(
            "Усе, що залежить від параметрів, задається тут; у властивостях — лише базові значення."
        )
        self.hint.setWordWrap(True)
        self.hint.setEnabled(False)
        layout.addWidget(self.hint)

    # ------------------------------------------------------------------ load
    def load(self, widget: Widget, page: Page, screen: tuple[int, int]) -> None:
        self.widget, self.page, self.screen_size = widget, page, screen
        self.rules = [r.model_dump(by_alias=True) for r in widget.rules]
        # Rebuild the rows only when what they show changed: rebuilding on every edit
        # (an angle being dragged, a test value) made the panel jump and lose focus.
        rules = json.dumps(self.rules, sort_keys=True, default=str)
        key = (
            widget.id,
            widget.type,
            rules,
            json.dumps([p.model_dump() for p in page.parameters], sort_keys=True, default=str),
            screen,
        )
        # An edit made in a row comes back as the same rules: those rows already show it
        # (rebuilding would take the field being typed in away). Undo / other edits rebuild.
        old = self._key
        from_rows = (
            old is not None
            and rules == self._emitted
            and key[:2] == old[:2]  # same widget
            and key[3:] == old[3:]  # same parameters and screen
        )
        if key != old and not from_rows:
            self._rebuild(widget, page)
        self._key = key
        self._emitted = None
        values = ParameterValues.for_page(page)
        for row, rule in zip(self.rows, widget.rules, strict=True):
            active = isinstance(rule, Condition) and condition_matches(rule, values)
            if bool(row.property("active")) != active:
                row.setProperty("active", active)  # red border (theme), as in the mock-up
                row.setToolTip("Ця умова зараз спрацьовує" if active else "")
                row.style().unpolish(row)
                row.style().polish(row)
        issues = [i for i in check_widget(widget, page, ()) if i.path.startswith("rules")]
        self.errors.setText("\n".join(f"{_rule_label(i.path)}: {i.message}" for i in issues))
        self.errors.setVisible(bool(issues))

    def _rebuild(self, widget: Widget, page: Page) -> None:
        for row in self.rows:  # out of the layout now: deleteLater waits for the event loop
            self.rows_box.removeWidget(row)
            row.hide()
            row.setParent(None)
            row.deleteLater()
        self.rows = []
        for index, rule in enumerate(widget.rules):
            row = (
                self._condition_row(index, rule)
                if isinstance(rule, Condition)
                else self._mapping_row(index, rule)
            )
            row.setProperty("kind", "condition" if isinstance(rule, Condition) else "mapping")
            self.rows_box.addWidget(row)
            self.rows.append(row)
        self.add_condition.setEnabled(bool(self._condition_params()))
        self.add_mapping.setEnabled(bool(self._numeric_params()))
        for combo in self.findChildren(QComboBox):  # rows may get narrower than the longest item
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            longest = max((len(combo.itemText(i)) for i in range(combo.count())), default=1)
            combo.setMinimumContentsLength(min(longest, 4))  # "=" / "≥" need no more

    def _condition_params(self) -> list[Parameter]:
        assert self.page is not None
        return [p for p in self.page.parameters if not isinstance(p, SeriesParameter)]

    def _numeric_params(self) -> list[Parameter]:
        assert self.page is not None
        return [p for p in self.page.parameters if isinstance(p, FloatParameter | IntParameter)]

    # ------------------------------------------------------------------ rows
    def _frame(self, index: int) -> tuple[RuleRow, QHBoxLayout]:
        frame = RuleRow()
        frame.remove_button.clicked.connect(lambda: self._remove(index))
        return frame, frame.row

    def _condition_row(self, index: int, rule: Condition) -> RuleRow:
        assert self.widget is not None
        assert self.page is not None
        frame, layout = self._frame(index)
        params = self._condition_params()
        param = self.page.parameter(rule.param)
        layout.addWidget(QLabel("якщо"))
        p_combo = QComboBox()
        for p in params:
            p_combo.addItem(p.name, p.name)
        p_combo.setCurrentIndex(max(0, p_combo.findData(rule.param)))
        p_combo.activated.connect(lambda _i: self._condition_param(index, p_combo.currentData()))
        layout.addWidget(p_combo)
        op_combo = QComboBox()
        for op in operators_for(param) if param else ("==",):
            op_combo.addItem(OP_TITLES[op], op)
        op_combo.setCurrentIndex(max(0, op_combo.findData(rule.op)))
        op_combo.activated.connect(lambda _i: self._condition_op(index, op_combo.currentData()))
        layout.addWidget(op_combo)
        if isinstance(rule.value, tuple):
            layout.addWidget(self._range_editor(param, rule.value, index))
        else:
            layout.addWidget(
                self._value_editor(param, rule.value, lambda v: self._set_when(index, 2, v))
            )
        layout.addStretch(1)
        layout = frame.row2
        layout.addWidget(QLabel("→"))
        prop_combo = QComboBox()
        for prop in condition_props(self.widget.type):
            prop_combo.addItem(PROP_TITLES[prop], prop)
        prop_combo.setCurrentIndex(max(0, prop_combo.findData(rule.prop)))
        prop_combo.activated.connect(
            lambda _i: self._condition_prop(index, prop_combo.currentData())
        )
        layout.addWidget(prop_combo)
        layout.addWidget(QLabel("="))
        layout.addWidget(self._to_editor(rule.prop, rule.to, lambda v: self._set(index, "to", v)))
        layout.addStretch(1)
        layout.addWidget(frame.remove_button)
        return frame

    def _mapping_row(self, index: int, rule: MappingRule) -> RuleRow:
        assert self.widget is not None
        frame, layout = self._frame(index)
        layout.addWidget(QLabel("від"))
        p_combo = QComboBox()
        for p in self._numeric_params():
            p_combo.addItem(p.name, p.name)
        p_combo.setCurrentIndex(max(0, p_combo.findData(rule.param)))
        p_combo.activated.connect(lambda _i: self._set(index, "param", p_combo.currentData()))
        layout.addWidget(p_combo)
        layout.addWidget(QLabel("→"))
        prop_combo = QComboBox()
        for prop in mapping_props(self.widget.type):
            prop_combo.addItem(PROP_TITLES[prop], prop)
        prop_combo.setCurrentIndex(max(0, prop_combo.findData(rule.prop)))
        prop_combo.activated.connect(lambda _i: self._mapping_prop(index, prop_combo.currentData()))
        layout.addWidget(prop_combo)
        layout.addStretch(1)
        layout = frame.row2
        for field, title in (("at_min", "при мін"), ("at_max", "при макс")):
            layout.addWidget(QLabel(title))
            spin = _number(-10000, 10000, getattr(rule, field))
            spin.setObjectName(field)
            spin.valueChanged.connect(lambda v, f=field: self._set(index, f, v))
            layout.addWidget(spin)
        layout.addStretch(1)
        layout.addWidget(frame.remove_button)
        return frame

    def _value_editor(self, param: Parameter | None, value: Any, commit: Any) -> QWidget:
        if isinstance(param, BoolParameter):
            combo = QComboBox()
            combo.addItem("true", True)
            combo.addItem("false", False)
            combo.setCurrentIndex(0 if value is True else 1)
            combo.activated.connect(lambda _i: commit(combo.currentData()))
            return combo
        if isinstance(param, EnumParameter):
            combo = QComboBox()
            combo.addItems(param.values)
            combo.setCurrentText(str(value))
            combo.activated.connect(lambda _i: commit(combo.currentText()))
            return combo
        if isinstance(param, StrParameter):
            line = QLineEdit(str(value))
            line.editingFinished.connect(lambda: commit(line.text()))
            return line
        decimals = 0 if isinstance(param, IntParameter) else 2
        spin = _number(-1e6, 1e6, float(value) if isinstance(value, int | float) else 0, decimals)
        spin.valueChanged.connect(lambda v: commit(int(v) if decimals == 0 else v))
        return spin

    def _range_editor(self, param: Parameter | None, value: tuple[Any, Any], index: int) -> QWidget:
        """``від [a] до [b]``: both ends are included."""
        box = QWidget()
        box.setObjectName("range")
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        decimals = 0 if isinstance(param, IntParameter) else 2
        for pos, title in enumerate(("від", "до")):
            row.addWidget(QLabel(title))
            spin = _number(-1e6, 1e6, float(value[pos]), decimals)
            spin.setObjectName("range_from" if pos == 0 else "range_to")
            spin.valueChanged.connect(
                lambda v, p=pos: self._set_range(index, p, int(v) if decimals == 0 else v)
            )
            row.addWidget(spin)
        return box

    def _to_editor(self, prop: str, value: Any, commit: Any) -> QWidget:
        if prop == "color":
            box = QWidget()
            row = QHBoxLayout(box)
            row.setContentsMargins(0, 0, 0, 0)
            button = QPushButton()
            button.setStyleSheet(f"background: {value}; min-width: 24px")
            line = QLineEdit(str(value))
            line.setMaximumWidth(80)
            line.editingFinished.connect(lambda: commit(line.text().strip()))

            def pick() -> None:
                color = QColorDialog.getColor(QColor(str(value)), self, "Колір")
                if color.isValid():
                    commit(color.name())

            button.clicked.connect(pick)
            row.addWidget(button)
            row.addWidget(line)
            return box
        if prop == "text":
            line = QLineEdit(str(value))
            line.editingFinished.connect(lambda: commit(line.text()))
            return line
        if prop == "visible":
            combo = QComboBox()
            combo.addItem("показати", True)
            combo.addItem("сховати", False)
            combo.setCurrentIndex(0 if value else 1)
            combo.activated.connect(lambda _i: commit(combo.currentData()))
            return combo
        lo, hi = (
            (0, 100) if prop == "opacity" else (-360, 360) if prop == "angle" else (-2000, 2000)
        )
        spin = _number(lo, hi, float(value) if isinstance(value, int | float) else 0, 0)
        spin.valueChanged.connect(lambda v: commit(int(v)))
        return spin

    # ------------------------------------------------------------------ edits
    def _emit(self, rebuild: bool = True) -> None:
        """Send the rules; ``rebuild=False``: only a value typed in a row changed."""
        self._emitted = None if rebuild else json.dumps(self.rules, sort_keys=True, default=str)
        self.changed.emit([dict(r) for r in self.rules])

    def _set(self, index: int, key: str, value: Any) -> None:
        self.rules[index][key] = value
        # "to" / "at_min" / "at_max" are just values; a colour also repaints its swatch.
        colour = key == "to" and self.rules[index].get("set") == "color"
        self._emit(rebuild=key == "param" or colour)

    def _set_when(self, index: int, position: int, value: Any) -> None:
        when = list(self.rules[index]["if"])
        when[position] = value
        self.rules[index]["if"] = when
        self._emit(rebuild=position != 2)

    def _condition_op(self, index: int, op: str) -> None:
        """A new operator; the value becomes a range [від, до] for in / not in, and back."""
        assert self.page is not None
        when = list(self.rules[index]["if"])
        when[2] = compare_value_for(op, self.page.parameter(when[0]), when[2])
        when[1] = op
        self.rules[index]["if"] = when
        self._emit()

    def _set_range(self, index: int, position: int, value: Any) -> None:
        when = list(self.rules[index]["if"])
        bounds = list(when[2])
        bounds[position] = value
        when[2] = bounds
        self.rules[index]["if"] = when
        self._emit(rebuild=False)

    def _condition_param(self, index: int, name: str) -> None:
        assert self.page is not None
        param = self.page.parameter(name)
        if param is None:
            return
        ops = operators_for(param) or ("==",)
        self.rules[index]["if"] = [name, ops[0], default_compare_value(param)]
        self._emit()

    def _condition_prop(self, index: int, prop: str) -> None:
        assert self.widget is not None
        self.rules[index]["set"] = prop
        self.rules[index]["to"] = condition_default_to(prop, self.widget)
        self._emit()

    def _mapping_prop(self, index: int, prop: str) -> None:
        assert self.widget is not None
        a, b = mapping_defaults(prop, self.widget, self.screen_size)
        self.rules[index].update(prop=prop, at_min=a, at_max=b)
        self._emit()

    def _remove(self, index: int) -> None:
        del self.rules[index]
        self._emit()

    def _add_condition(self) -> None:
        assert self.widget is not None
        param = self._condition_params()[0]
        ops = operators_for(param) or ("==",)
        prop = condition_props(self.widget.type)[0]
        self.rules.append(
            {
                "kind": "condition",
                "if": [param.name, ops[0], default_compare_value(param)],
                "set": prop,
                "to": condition_default_to(prop, self.widget),
            }
        )
        self._emit()

    def _add_mapping(self) -> None:
        assert self.widget is not None
        param = self._numeric_params()[0]
        prop = mapping_props(self.widget.type)[0]
        a, b = mapping_defaults(prop, self.widget, self.screen_size)
        self.rules.append(
            {"kind": "mapping", "param": param.name, "prop": prop, "at_min": a, "at_max": b}
        )
        self._emit()


def _rule_label(path: str) -> str:
    """``rules[1].to`` -> ``запис 2``."""
    try:
        return f"запис {int(path.split('[')[1].split(']')[0]) + 1}"
    except (IndexError, ValueError):
        return "умови"
