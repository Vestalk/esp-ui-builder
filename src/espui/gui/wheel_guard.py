"""The mouse wheel never changes a value: it scrolls the panel instead.

Scrolling the properties panel used to flip any drop-down, slider or number
field that happened to pass under the cursor. One application-wide event
filter stops that for every QComboBox, QAbstractSlider (QSlider, QDial) and
QAbstractSpinBox (dialogs included); an open drop-down list and scroll bars
still scroll as usual.
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QEvent, QObject
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QAbstractSlider,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QScrollBar,
    QWidget,
)

GUARDED = (QComboBox, QAbstractSlider, QAbstractSpinBox)


def _guarded_of(obj: QObject) -> QWidget | None:
    """The value widget ``obj`` belongs to (a combo's or spin box's line edit is its child)."""
    widget = obj if isinstance(obj, QWidget) else None
    while widget is not None:
        if isinstance(widget, QScrollBar):
            return None  # scroll bars are for scrolling
        if isinstance(widget, GUARDED):
            return widget
        if widget.isWindow():
            return None
        widget = widget.parentWidget()
    return None


def _scroll_area_of(widget: QWidget) -> QAbstractScrollArea | None:
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QAbstractScrollArea):
            return parent
        parent = parent.parentWidget()
    return None


class WheelGuard(QObject):
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.Wheel:
            return False
        target = _guarded_of(obj)
        if target is None or (isinstance(target, QComboBox) and target.view().isVisible()):
            return False  # not a value widget, or a drop-down list is open: scroll normally
        area = _scroll_area_of(target)
        if area is not None:
            QCoreApplication.sendEvent(area.viewport(), event)
        return True  # the combo itself never sees the wheel


_guard: WheelGuard | None = None


def install(app: QApplication | None = None) -> WheelGuard:
    """Install the guard once per application (calling again is harmless)."""
    global _guard
    app = app or QApplication.instance()  # type: ignore[assignment]
    assert app is not None
    if _guard is None or _guard.parent() is not app:
        _guard = WheelGuard(app)
        app.installEventFilter(_guard)
    return _guard
