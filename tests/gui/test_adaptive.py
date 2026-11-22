"""The window stays usable when it gets smaller."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QTabBar
from pytestqt.qtbot import QtBot

from espui.gui.main_window import MainWindow
from tests.gui.conftest import ROOT

EXAMPLES = ("weather", "transforms", "images", "chart", "sensors")


@pytest.fixture
def window(qtbot: QtBot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    win.open_file(ROOT / "examples" / "transforms.espui")
    return win


def resize(window: MainWindow, width: int, height: int) -> None:
    window.resize(width, height)
    QApplication.processEvents()
    QApplication.processEvents()


@pytest.mark.parametrize("width", [1500, 1100, 900, 780])
def test_toolbar_fits_and_generate_stays_visible(window: MainWindow, width: int) -> None:
    resize(window, width, 700)
    assert window.tools.sizeHint().width() <= window.width()
    button = window.tools.widgetForAction(window.act_generate)
    assert button is not None
    assert button.isVisible()
    assert button.geometry().right() <= window.tools.width()


def test_compact_toolbar_keeps_the_menu_names(window: MainWindow) -> None:
    resize(window, 780, 600)
    assert window.compact_level >= 3
    assert window.act_zoom_in.iconText() == "+"
    assert window.act_zoom_in.text() == "Збільшити"  # the menu entry is unchanged
    assert window.display_button.text() == "Дисплей…"
    assert "GMT020-02-8B" in window.display_button.toolTip()
    resize(window, 1600, 900)
    assert window.compact_level == 0
    assert window.display_button.text().startswith("Дисплей: GMT020-02-8B")
    assert window.act_zoom_in.iconText() == "Збільшити"


def test_dock_tabs_show_whole_titles(window: MainWindow) -> None:
    for width in (1400, 800):
        resize(window, width, 600)
        bars = [b for b in window.findChildren(QTabBar) if b.parent() is window and b.count()]
        assert bars
        for bar in bars:
            for i in range(bar.count()):
                text = bar.tabText(i)
                assert bar.tabRect(i).width() > bar.fontMetrics().horizontalAdvance(text), text


@pytest.mark.parametrize("name", EXAMPLES)
def test_properties_fit_their_panel_without_sideways_scrolling(qtbot: QtBot, name: str) -> None:
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    win.open_file(ROOT / "examples" / f"{name}.espui")
    resize(win, 900, 700)
    for page in range(len(win.doc.project.pages)):
        win.doc.set_current(page)
        for widget in win.doc.page.widgets:
            win.doc.select(widget.id)
            QApplication.processEvents()
            assert win.properties.horizontalScrollBar().maximum() == 0, widget.id


def test_short_window_keeps_the_properties_readable(window: MainWindow) -> None:
    window.doc.select("needle")
    resize(window, 780, 560)
    props, params = window.docks["Властивості"], window.docks["Параметри"]
    assert props.height() >= params.height()
    assert window.docks["Елементи"].width() < 150  # narrow window: a narrower palette
    resize(window, 1400, 900)
    assert window.docks["Елементи"].width() == 150
