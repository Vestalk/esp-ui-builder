"""Parameters of the page, their test values and the ``DEFAULTS`` of the generated code.

* "Параметри екрана": list with type and range, ✎ / double click edits, × deletes
  (with every reference); rows can be dragged onto the canvas.
* "Тестові значення": a slider, check box, list, path field or ``x:y; x:y``
  field per parameter; the preview follows at once.
* "Параметри в коді": the ``DEFAULTS`` block exactly as generated.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import QByteArray, QMimeData, QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from espui.core.evaluate import SeriesParseError, format_value, parse_series, series_to_text
from espui.core.models import (
    BoolParameter,
    EnumParameter,
    FloatParameter,
    IntParameter,
    Parameter,
    SeriesParameter,
    SeriesPoint,
    StrParameter,
)
from espui.core.params import parameter_summary
from espui.generators.micropython.generator import defaults_source
from espui.gui.document import Document
from espui.gui.parameter_dialog import ParameterDialog
from espui.gui.properties import Section

PARAM_MIME = "application/x-espui-parameter"
"""Drag of a parameter row: its name as text."""
NAME_ROLE = Qt.ItemDataRole.UserRole
SLIDER_STEPS = 1000


class ParameterList(QListWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setToolTip("Перетягніть на елемент — прив'язка; на вільне місце — новий елемент")

    def mimeData(self, items: Sequence[QListWidgetItem]) -> QMimeData:
        data = QMimeData()
        if items:
            data.setData(PARAM_MIME, QByteArray(items[0].data(NAME_ROLE).encode()))
        return data

    def mimeTypes(self) -> list[str]:
        return [PARAM_MIME]


class ParametersPanel(QWidget):
    message = Signal(str)

    def __init__(self, doc: Document) -> None:
        super().__init__()
        self.doc = doc
        self.add_button = QPushButton("+ Параметр")
        self.add_button.clicked.connect(self.add_dialog)
        self.list = ParameterList()
        self.list.itemDoubleClicked.connect(lambda item: self.edit_dialog(item.data(NAME_ROLE)))
        self.code_section = Section("Параметри в коді", help_topic="parameters")
        self.code = QPlainTextEdit()
        self.code.setReadOnly(True)
        font = QFont("Menlo")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.code.setFont(font)
        self.code.setMinimumHeight(120)
        self.code_section.form.addRow(self.code)
        screen = Section("Параметри екрана", help_topic="parameters")
        screen.form.addRow(self.add_button)
        screen.form.addRow(self.list)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(screen, 1)
        layout.addWidget(self.code_section)
        self._signature: tuple[object, ...] = ()
        doc.changed.connect(self.refresh)
        doc.current_page_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        """Rebuild the list only when the parameters change; the scroll stays put."""
        params = self.doc.page.parameters
        signature = (self.doc.current, *(p.model_dump_json() for p in params))
        code = defaults_source(self.doc.page)
        if self.code.toPlainText() != code:
            self.code.setPlainText(code)
        if signature == self._signature:
            return
        self._signature = signature
        scroll = self.list.verticalScrollBar().value()
        self.list.clear()
        for param in params:
            item = QListWidgetItem()
            item.setData(NAME_ROLE, param.name)
            item.setSizeHint(QSize(100, 26))
            self.list.addItem(item)
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(4, 0, 2, 0)
            label = QLabel(f"{param.name} · {parameter_summary(param)}")
            layout.addWidget(label, 1)
            edit = QToolButton()
            edit.setText("✎")
            edit.setToolTip("Редагувати")
            edit.clicked.connect(lambda _=False, n=param.name: self.edit_dialog(n))
            remove = QToolButton()
            remove.setText("×")
            remove.setToolTip("Видалити разом з усіма посиланнями")
            remove.clicked.connect(lambda _=False, n=param.name: self.remove(n))
            layout.addWidget(edit)
            layout.addWidget(remove)
            self.list.setItemWidget(item, row)
        self.list.verticalScrollBar().setValue(scroll)

    # ------------------------------------------------------------------ actions
    def dialog(self, param: Parameter | None = None) -> ParameterDialog:
        old = param.name if param else None
        return ParameterDialog(param, lambda p: self.doc.parameter_problem(p, old), self)

    def add_dialog(self) -> None:
        dialog = self.dialog()
        if dialog.exec():
            param, _ = dialog.parameter()
            if param is not None:
                self.doc.add_parameter(param)

    def edit_dialog(self, name: str) -> None:
        param = self.doc.page.parameter(name)
        if param is None:
            return
        dialog = self.dialog(param)
        if dialog.exec():
            new, _ = dialog.parameter()
            if new is not None:
                self.save(name, new)

    def save(self, old_name: str, new: Parameter) -> list[str]:
        notes = self.doc.update_parameter(old_name, new)
        if notes:
            self.message.emit(" ".join(notes))
        return notes

    def remove(self, name: str) -> int:
        removed = self.doc.remove_parameter(name)
        self.message.emit(
            f"Параметр «{name}» видалено" + (f", умов: {removed}." if removed else ".")
        )
        return removed


# ---------------------------------------------------------------------- test values
def random_series(param: SeriesParameter) -> list[SeriesPoint]:
    """Plausible points within the Y range (as the mock-up's "↻ випадкові")."""
    count = min(8, param.max_points)
    mid, amp = (param.min + param.max) / 2, (param.max - param.min) / 3
    phase = random.uniform(0, 6.28)

    labels = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд", "P8"]
    return [
        SeriesPoint(
            x=float(i * 3) if param.x_kind == "number" else labels[i],
            y=round(mid + amp * math.sin(phase + i * 0.8), 1),
        )
        for i in range(count)
    ]


class TestValuesPanel(QScrollArea):
    """One editor per parameter; changes go to ``page.test_values`` (undoable)."""

    def __init__(self, doc: Document) -> None:
        super().__init__()
        self.doc = doc
        self.setWidgetResizable(True)
        self.editors: dict[str, QWidget] = {}
        self.series_errors: dict[str, QLabel] = {}
        self._signature: tuple[Any, ...] = ()
        self._loading = False
        doc.changed.connect(self.refresh)
        doc.current_page_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        params = self.doc.page.parameters
        signature = (*tuple(p.model_dump_json() for p in params), self.doc.current)
        if signature != self._signature:
            self._signature = signature
            self._build(params)
        self._load()

    def _build(self, params: Sequence[Parameter]) -> None:
        root = QWidget()
        form = QFormLayout(root)
        self.editors.clear()
        self.series_errors.clear()
        if not params:
            label = QLabel("На сторінці ще немає параметрів.")
            label.setEnabled(False)
            form.addRow(label)
        for param in params:
            form.addRow(param.name, self._editor(param))
        self.setWidget(root)

    def _editor(self, param: Parameter) -> QWidget:
        name = param.name
        if isinstance(param, FloatParameter | IntParameter):
            box = QWidget()
            row = QHBoxLayout(box)
            row.setContentsMargins(0, 0, 0, 0)
            slider = QSlider(Qt.Orientation.Horizontal)
            if isinstance(param, IntParameter):
                slider.setRange(param.min, param.max)
            else:
                slider.setRange(0, SLIDER_STEPS)
            label = QLabel()
            label.setMinimumWidth(60)
            slider.valueChanged.connect(lambda v, p=param, lb=label: self._slider(p, v, lb))
            row.addWidget(slider, 1)
            row.addWidget(label)
            self.editors[name] = slider
            box.setProperty("label", label)
            return box
        if isinstance(param, BoolParameter):
            check = QCheckBox()
            check.toggled.connect(lambda on, n=name: self._set(n, on))
            self.editors[name] = check
            return check
        if isinstance(param, EnumParameter):
            combo = QComboBox()
            combo.addItems(param.values)
            combo.activated.connect(lambda _i, n=name, c=combo: self._set(n, c.currentText()))
            self.editors[name] = combo
            return combo
        if isinstance(param, StrParameter):
            combo = QComboBox()
            combo.setEditable(True)
            combo.addItems([a.path for a in self.doc.project.images.values()])  # path hints
            line = combo.lineEdit()
            assert line is not None
            line.setMaxLength(param.max_len - 1)
            line.editingFinished.connect(lambda n=name, c=combo: self._set(n, c.currentText()))
            combo.activated.connect(lambda _i, n=name, c=combo: self._set(n, c.currentText()))
            self.editors[name] = combo
            return combo
        assert isinstance(param, SeriesParameter)
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        edit = QLineEdit()
        edit.setPlaceholderText("x:y; x:y")
        edit.editingFinished.connect(lambda p=param, e=edit: self._series(p, e.text()))
        shuffle = QToolButton()
        shuffle.setText("↻ випадкові")
        shuffle.clicked.connect(lambda _=False, p=param: self._set(p.name, random_series(p)))
        row.addWidget(edit, 1)
        row.addWidget(shuffle)
        error = QLabel()
        error.setStyleSheet("color: #c0392b")
        error.setVisible(False)
        column.addLayout(row)
        column.addWidget(error)
        self.editors[name] = edit
        self.series_errors[name] = error
        return box

    def _load(self) -> None:
        self._loading = True
        page = self.doc.page
        for param in page.parameters:
            editor = self.editors.get(param.name)
            value = page.value_of(param.name)
            if editor is None:
                continue
            editor.blockSignals(True)
            if isinstance(editor, QSlider) and isinstance(param, FloatParameter | IntParameter):
                if isinstance(param, IntParameter):
                    editor.setValue(int(value))  # type: ignore[arg-type]
                else:
                    span = param.max - param.min
                    editor.setValue(round((float(value) - param.min) / span * SLIDER_STEPS))  # type: ignore[arg-type]
                label = editor.parentWidget().property("label")  # type: ignore[union-attr]
                label.setText(
                    format_value("%.1f" if isinstance(param, FloatParameter) else "%d", value)
                )
            elif isinstance(editor, QCheckBox):
                editor.setChecked(bool(value))
            elif isinstance(editor, QComboBox):
                editor.setCurrentText(str(value))
            elif isinstance(editor, QLineEdit):
                editor.setText(series_to_text(value))  # type: ignore[arg-type]
            editor.blockSignals(False)
        self._loading = False

    # ------------------------------------------------------------------ changes
    def _set(self, name: str, value: Any) -> None:
        if not self._loading and self.doc.page.value_of(name) != value:
            self.doc.set_test_value(name, value)

    def _slider(self, param: FloatParameter | IntParameter, position: int, label: QLabel) -> None:
        if isinstance(param, IntParameter):
            value: float = position
        else:
            value = round(param.min + (param.max - param.min) * position / SLIDER_STEPS, 2)
        label.setText(format_value("%.1f" if isinstance(param, FloatParameter) else "%d", value))
        self._set(param.name, value)

    def _series(self, param: SeriesParameter, text: str) -> bool:
        error = self.series_errors[param.name]
        try:
            points = parse_series(text, param)
        except SeriesParseError as problem:
            error.setText(str(problem))
            error.setVisible(True)
            return False
        error.setVisible(False)
        self._set(param.name, points)
        return True
