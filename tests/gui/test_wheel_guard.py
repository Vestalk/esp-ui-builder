"""The mouse wheel scrolls panels and never changes a drop-down, slider or spin box."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from pytestqt.qtbot import QtBot

from espui.gui import wheel_guard


def wheel(widget: QWidget, dy: int = -120) -> None:
    pos = QPointF(widget.rect().center())
    event = QWheelEvent(
        pos,
        QPointF(widget.mapToGlobal(pos.toPoint())),
        QPoint(0, 0),
        QPoint(0, dy),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, event)


def panel(qtbot: QtBot) -> tuple[QScrollArea, QComboBox]:
    area = QScrollArea()
    inner = QWidget()
    layout = QVBoxLayout(inner)
    combo = QComboBox()
    combo.addItems(["a", "b", "c"])
    layout.addWidget(combo)
    for _ in range(40):
        layout.addWidget(QComboBox())
    area.setWidget(inner)
    area.resize(200, 150)
    qtbot.addWidget(area)
    area.show()
    return area, combo


def test_without_guard_the_wheel_flips_the_combo(qtbot: QtBot) -> None:
    """The problem being fixed (guard not installed in this test)."""
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    if wheel_guard._guard is not None:
        app.removeEventFilter(wheel_guard._guard)
    try:
        _, combo = panel(qtbot)
        wheel(combo)
        assert combo.currentIndex() == 1
    finally:
        if wheel_guard._guard is not None:
            app.installEventFilter(wheel_guard._guard)


def test_wheel_scrolls_the_panel_not_the_combo(qtbot: QtBot) -> None:
    guard = wheel_guard.install()
    assert wheel_guard.install() is guard  # once per application
    area, combo = panel(qtbot)
    bar = area.verticalScrollBar()
    assert bar.value() == 0
    wheel(combo)
    assert combo.currentIndex() == 0
    assert bar.value() > 0  # the panel scrolled instead
    combo.setEditable(True)
    line_edit = combo.lineEdit()
    assert line_edit is not None
    wheel(line_edit)
    assert combo.currentIndex() == 0


def test_sliders_and_spin_boxes_ignore_the_wheel(qtbot: QtBot) -> None:
    wheel_guard.install()
    area, _ = panel(qtbot)
    inner = area.widget()
    assert inner is not None
    layout = inner.layout()
    assert layout is not None
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(0, 100)
    slider.setValue(50)
    spin = QSpinBox()
    spin.setValue(5)
    real = QDoubleSpinBox()
    real.setValue(1.5)
    for w in (slider, spin, real):
        layout.addWidget(w)
    area.show()
    bar = area.verticalScrollBar()
    for w in (slider, spin, real):
        before = bar.value()
        wheel(w)
        assert bar.value() != before or bar.value() == bar.maximum()  # the panel scrolled
    line_edit = spin.lineEdit()
    assert line_edit is not None
    wheel(line_edit)
    assert (slider.value(), spin.value(), real.value()) == (50, 5, 1.5)
    bar.setValue(0)
    wheel(bar)  # the scroll bar itself still scrolls
    assert bar.value() > 0
