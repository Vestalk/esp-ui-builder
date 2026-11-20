"""Stage 12: parameters, their dialog, drag & drop, test values and the live preview."""

from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QComboBox, QDialogButtonBox, QLineEdit, QSlider
from pytestqt.qtbot import QtBot

from espui.core.models import Condition, SeriesParameter
from espui.gui.document import Document
from espui.gui.main_window import MainWindow
from espui.gui.parameter_dialog import ParameterDialog
from espui.gui.parameters import PARAM_MIME, random_series
from espui.gui.workspace import canvas_to_image
from espui.preview.raster import render_page
from tests.gui.conftest import ROOT

WEATHER = ROOT / "examples" / "weather.espui"


@pytest.fixture
def window(qtbot: QtBot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1400, 900)
    win.show()
    win.open_file(WEATHER)
    return win


def ok(dialog: ParameterDialog) -> bool:
    return dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()


# ------------------------------------------------------------------ dialog
@pytest.mark.parametrize(
    ("kind", "fill", "expected"),
    [
        (
            "float",
            {"min": -10, "max": 30, "default": 5.5},
            {"min": -10.0, "max": 30.0, "default": 5.5},
        ),
        ("int", {"min": 0, "max": 9, "default": 3}, {"min": 0, "max": 9, "default": 3}),
        ("bool", {"default": True}, {"default": True}),
        (
            "str",
            {"max_len": 20, "default": "Київ"},
            {"max_len": 20, "default": "Київ", "charset": "latin_uk"},
        ),
        ("enum", {"values": "Норма\nУвага"}, {"values": ["Норма", "Увага"], "default": "Норма"}),
        ("series", {"max_points": 6, "default": "0:1; 2:3"}, {"max_points": 6, "x_kind": "number"}),
    ],
)
def test_new_parameter_of_each_type(
    qtbot: QtBot, kind: str, fill: dict[str, Any], expected: dict[str, Any]
) -> None:
    dialog = ParameterDialog(None)
    qtbot.addWidget(dialog)
    dialog.name.setText(f"p_{kind}")
    dialog.type.setCurrentIndex(dialog.type.findData(kind))
    fields = dialog.fields[kind]
    for key, value in fill.items():
        widget = fields[key]
        if key == "values":
            widget.setPlainText(value)  # type: ignore[attr-defined]
        elif hasattr(widget, "setValue"):
            widget.setValue(value)
        elif hasattr(widget, "setChecked"):
            widget.setChecked(value)
        else:
            widget.setText(value)  # type: ignore[attr-defined]
    param, issues = dialog.parameter()
    assert issues == []
    assert param is not None
    assert ok(dialog)
    data = param.model_dump()
    assert data["name"] == f"p_{kind}"
    assert data["type"] == kind
    for key, value in expected.items():
        assert data[key] == value, key
    if isinstance(param, SeriesParameter):
        assert [(p.x, p.y) for p in param.default] == [(0, 1), (2, 3)]


@pytest.mark.parametrize(
    ("setup", "field", "message"),
    [
        (lambda d: d.name.setText("1x"), "name", "лише латинські малі літери"),
        (lambda d: d.name.setText("class"), "name", "зарезервоване слово"),
        (
            lambda d: d.fields["float"]["max"].setValue(-5),
            "float.max",
            "max має бути більше за min",
        ),
        (lambda d: d.fields["float"]["default"].setValue(500), "float.default", "в межах"),
    ],
)
def test_validation_next_to_the_field(qtbot: QtBot, setup: Any, field: str, message: str) -> None:
    dialog = ParameterDialog(None)
    qtbot.addWidget(dialog)
    dialog.type.setCurrentIndex(dialog.type.findData("float"))
    setup(dialog)
    assert not ok(dialog)
    label = dialog.errors[field]
    assert label.isVisibleTo(dialog)
    assert message in label.text()


def test_enum_and_series_errors(qtbot: QtBot) -> None:
    dialog = ParameterDialog(None)
    qtbot.addWidget(dialog)
    dialog.type.setCurrentIndex(dialog.type.findData("enum"))
    dialog.fields["enum"]["values"].setPlainText("a\na")  # type: ignore[attr-defined]
    assert "варіанти повторюються: a" in dialog.errors["enum.values"].text()
    dialog.type.setCurrentIndex(dialog.type.findData("series"))
    dialog.fields["series"]["default"].setText("1:1; 1:2")  # type: ignore[attr-defined]
    assert "Ключі x мають бути різними" in dialog.errors["series.default"].text()


def test_unique_name_ignores_the_edited_parameter(window: MainWindow) -> None:
    doc = window.doc
    temperature = doc.page.parameter("temperature")
    assert temperature is not None
    dialog = window.parameters.dialog(temperature)
    assert dialog.windowTitle() == "Редагувати параметр"
    assert dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).text() == "Зберегти зміни"
    assert ok(dialog)  # its own name is fine
    dialog.name.setText("humidity")
    assert "параметр «humidity» вже є" in dialog.errors["name"].text()


# ------------------------------------------------------------------ panel
def test_add_edit_remove(window: MainWindow) -> None:
    doc = window.doc
    panel = window.parameters
    rows = [panel.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(panel.list.count())]
    assert rows == ["temperature", "humidity", "pressure", "status", "city", "alarm"]
    assert 'DEFAULTS = {\n    "temperature": 21.5,' in panel.code.toPlainText()

    from espui.core.models import IntParameter

    doc.add_parameter(IntParameter(name="level", min=0, max=5, default=2))
    assert panel.list.count() == 7
    assert '"level": 2,  # int, 0…5' in panel.code.toPlainText()

    temperature = doc.page.parameter("temperature")
    assert temperature is not None
    notes = panel.save("temperature", temperature.model_copy(update={"name": "temp"}))
    assert notes == []
    assert doc.page.widget("t_val").bind == "temp"  # type: ignore[union-attr]

    removed = panel.remove("alarm")
    assert removed == 2  # the conditions of t_val and alarm_lbl
    assert doc.page.parameter("alarm") is None
    assert all(r.param != "alarm" for w in doc.page.widgets for r in w.rules)
    doc.undo_stack.undo()
    assert doc.page.parameter("alarm") is not None


# ------------------------------------------------------------------ drag & drop
def drop_parameter(window: MainWindow, name: str, page_x: float, page_y: float) -> None:
    ws = window.workspace
    item = ws.active_item()
    assert item is not None
    pos = ws.mapFromScene(item.mapToScene(QPointF(page_x, page_y)))
    data = QMimeData()
    data.setData(PARAM_MIME, name.encode())
    ws.dropEvent(QDropEvent(QPointF(pos), Qt.DropAction.CopyAction, data, Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier))  # fmt: skip


def test_parameter_list_drag_data(window: MainWindow) -> None:
    data = window.parameters.list.mimeData([window.parameters.list.item(0)])
    assert bytes(data.data(PARAM_MIME).data()) == b"temperature"


def test_drop_on_a_compatible_widget_binds(window: MainWindow) -> None:
    doc = window.doc
    title = doc.page.widget("title")
    assert title is not None
    assert title.bind is None
    drop_parameter(window, "city", 30, 20)  # the "Погода" title
    assert doc.page.widget("title").bind == "city"  # type: ignore[union-attr]
    assert doc.selected == "title"


def test_drop_bool_adds_a_hide_condition(window: MainWindow) -> None:
    doc = window.doc
    drop_parameter(window, "alarm", 158, 198)  # the status dot
    rules = doc.page.widget("st_dot").rules  # type: ignore[union-attr]
    last = rules[-1]
    assert isinstance(last, Condition)
    assert (last.param, last.op, last.value, last.prop, last.to) == (
        "alarm",
        "==",
        False,
        "visible",
        False,
    )


def test_drop_on_free_space_creates_a_widget(window: MainWindow) -> None:
    doc = window.doc
    for name, kind, fmt in (("pressure", "value", "%.1f"), ("status", "text", "%s")):
        drop_parameter(window, name, 3, 236)  # an empty corner
        widget = doc.page.widgets[-1]
        assert (widget.type, widget.bind, widget.format) == (kind, name, fmt)
        doc.undo_stack.undo()


def test_drop_incompatible_reports(window: MainWindow) -> None:
    messages: list[str] = []
    window.workspace.message.connect(messages.append)
    drop_parameter(window, "city", 158, 198)  # a str on a circle
    assert messages == ["«st_dot» не може показати параметр типу str."]


# ------------------------------------------------------------------ test values & preview
def test_test_values_drive_the_preview(window: MainWindow) -> None:
    doc = window.doc
    values = window.test_values
    slider = values.editors["humidity"]
    assert isinstance(slider, QSlider)
    before = window.workspace.items_[0].image.copy()
    steps = doc.undo_stack.count()
    for v in (50, 60, 77):
        slider.setValue(v)
    assert doc.page.test_values["humidity"] == 77
    assert doc.undo_stack.count() == steps + 1  # a slider drag is one step
    after = window.workspace.items_[0].image
    assert after != before
    expected = canvas_to_image(
        render_page(doc.page, doc.project.display.size, images=doc.project.images)
    )
    assert after == expected  # the preview is the renderer the device frames are checked against

    values.editors["alarm"].setChecked(True)  # type: ignore[attr-defined]
    status = values.editors["status"]
    assert isinstance(status, QComboBox)
    status.setCurrentText("Помилка")
    status.activated.emit(2)
    city = values.editors["city"]
    assert isinstance(city, QComboBox)
    city.setCurrentText("Львів")
    city.lineEdit().editingFinished.emit()  # type: ignore[union-attr]
    assert doc.page.test_values == {
        "humidity": 77,
        "alarm": True,
        "status": "Помилка",
        "city": "Львів",
    }


def test_float_slider_and_series(window: MainWindow, qtbot: QtBot) -> None:
    doc = window.doc
    slider = window.test_values.editors["temperature"]
    assert isinstance(slider, QSlider)
    slider.setValue(1000)
    assert doc.page.test_values["temperature"] == 85.0
    slider.setValue(0)
    assert doc.page.test_values["temperature"] == -40.0

    doc.add_parameter(SeriesParameter(name="trend", min=0, max=10, max_points=5))
    edit = window.test_values.editors["trend"]
    assert isinstance(edit, QLineEdit)
    edit.setText("3:1; 1:2")
    edit.editingFinished.emit()
    assert [(p.x, p.y) for p in doc.page.test_values["trend"]] == [(1, 2), (3, 1)]  # type: ignore[union-attr]
    edit.setText("a:1")
    edit.editingFinished.emit()
    assert "ключ x має бути числом" in window.test_values.series_errors["trend"].text()
    points = random_series(doc.page.parameter("trend"))  # type: ignore[arg-type]
    assert len(points) == 5
    assert all(0 <= p.y <= 10 for p in points)


def test_status_bar_checks(window: MainWindow) -> None:
    doc: Document = window.doc
    from espui.core.models import BoolParameter

    doc.add_parameter(BoolParameter(name="spare"))
    window.workspace.add_widget("image")
    tooltip = window.status_warnings.toolTip()
    assert "не використано: main/spare" in tooltip
    assert "картинка без файлу: main/image_1" in tooltip


def test_properties_list_only_compatible_parameters(window: MainWindow) -> None:
    window.doc.select("h_bar")
    combo = window.properties.bind_combo
    names = [combo.itemData(i) for i in range(combo.count())]
    assert names == [None, "temperature", "humidity", "pressure"]  # numbers only for a bar
