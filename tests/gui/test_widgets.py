"""Page tabs, the Display dialog, the work area and the main window."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QDialogButtonBox, QGraphicsItem
from pytestqt.qtbot import QtBot

from espui.core import serializer
from espui.core.colors import to_wire
from espui.core.hardware import Chip
from espui.core.models import Display
from espui.gui.display_dialog import DisplayDialog, display_label
from espui.gui.document import Document
from espui.gui.main_window import MainWindow
from espui.gui.pages_bar import CONFIRM_TEXT, PagesBar
from espui.gui.workspace import ZOOM_MAX, ZOOM_MIN, Workspace, canvas_to_image
from espui.preview.raster import Canvas
from tests.gui.conftest import PAGES


@pytest.fixture
def doc(qtbot: QtBot) -> Document:
    return Document(serializer.load(PAGES), PAGES)


# ------------------------------------------------------------------ page tabs
@pytest.fixture
def bar(qtbot: QtBot, doc: Document) -> PagesBar:
    widget = PagesBar(doc)
    qtbot.addWidget(widget)
    widget.show()
    return widget


def test_tabs_show_pages_and_counts(bar: PagesBar) -> None:
    tabs = bar.tabs
    assert [tabs.tabText(i) for i in range(tabs.count())] == [
        "ui_main.py · 3",
        "ui_settings.py · 4",
    ]
    tabs.setCurrentIndex(1)
    assert bar.doc.current == 1


def test_delete_needs_two_clicks(bar: PagesBar, doc: Document) -> None:
    tabs = bar.tabs
    tabs.tabCloseRequested.emit(1)
    assert tabs.tabText(1) == CONFIRM_TEXT
    assert len(doc.project.pages) == 2
    tabs.tabCloseRequested.emit(1)
    assert len(doc.project.pages) == 1
    assert tabs.count() == 1
    tabs.tabCloseRequested.emit(0)
    tabs.tabCloseRequested.emit(0)
    assert len(doc.project.pages) == 1  # the last page can't be deleted
    doc.undo_stack.undo()
    assert tabs.count() == 2


def test_escape_or_another_tab_cancels(bar: PagesBar, qtbot: QtBot, doc: Document) -> None:
    tabs = bar.tabs
    tabs.tabCloseRequested.emit(1)
    qtbot.keyClick(tabs, Qt.Key.Key_Escape)
    assert tabs.tabText(1) == "ui_settings.py · 4"
    tabs.tabCloseRequested.emit(1)
    tabs.tabCloseRequested.emit(0)  # × of another tab: arms that one instead
    assert tabs.tabText(1) == "ui_settings.py · 4"
    assert tabs.tabText(0) == CONFIRM_TEXT
    qtbot.mouseClick(tabs, Qt.MouseButton.LeftButton, pos=tabs.tabRect(1).center())
    assert tabs.tabText(0) == "ui_main.py · 3"  # a click elsewhere cancels
    assert len(doc.project.pages) == 2


def test_arrow_keys_switch_pages(bar: PagesBar, qtbot: QtBot, doc: Document) -> None:
    qtbot.keyClick(bar.tabs, Qt.Key.Key_Right)
    assert doc.current == 1
    qtbot.keyClick(bar.tabs, Qt.Key.Key_Right)
    assert doc.current == 1
    qtbot.keyClick(bar.tabs, Qt.Key.Key_Left)
    assert doc.current == 0


def test_add_and_rename(bar: PagesBar, doc: Document) -> None:
    bar.add_button.click()
    assert [p.name for p in doc.project.pages] == ["main", "page", "settings"]
    assert bar.tabs.tabText(1) == "ui_page.py · 0"
    assert bar.rename(1, "about") is None
    assert bar.tabs.tabText(1) == "ui_about.py · 0"
    assert bar.rename(1, "settings") == "сторінка «settings» вже є"


# ------------------------------------------------------------------ display dialog
@pytest.fixture
def dialog(qtbot: QtBot) -> DisplayDialog:
    widget = DisplayDialog(Display())
    qtbot.addWidget(widget)
    return widget


def ok_enabled(dialog: DisplayDialog) -> bool:
    return dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()


def test_dialog_defaults(dialog: DisplayDialog) -> None:
    assert not dialog.model.isEnabled()  # one panel for now
    assert dialog.problems() == []
    assert ok_enabled(dialog)
    assert "ui_display.py, ui_st7789.py" in dialog.driver_card.text()
    assert dialog.display() == Display()
    assert display_label(Display()) == "GMT020-02-8B · ESP32-S3 · ui_st7789"


def test_dialog_lists_every_problem(dialog: DisplayDialog) -> None:
    dialog.pins["sck"].setText("19")
    dialog.pins["mosi"].setText("9")  # same as DC
    assert dialog.problems() == [
        "SCL: GPIO19 зайнятий (USB)",
        "SDA: GPIO9 вже використано для dc",
        "DC: GPIO9 вже використано для mosi",
    ]
    assert not ok_enabled(dialog)
    assert "GPIO19 зайнятий" in dialog.errors.text()


def test_dialog_number_errors(dialog: DisplayDialog) -> None:
    dialog.pins["rst"].setText("")
    dialog.pins["dc"].setText("abc")
    dialog.pins["cs"].setText("-3")
    assert dialog.problems() == [
        "RES: вкажіть номер GPIO",
        "DC: «abc» — не число",
        "CS: номер GPIO не може бути від'ємним",
    ]
    dialog.pins["rst"].setText("8")
    dialog.pins["dc"].setText("9")
    dialog.pins["cs"].setText("10")
    dialog.pins["bl"].setText("")  # no BLK pin: allowed
    assert dialog.problems() == []
    assert dialog.display().pins.bl is None


def test_dialog_chip_rules(dialog: DisplayDialog) -> None:
    dialog.chip.setCurrentIndex(dialog.chip.findData(Chip.ESP32.value))
    problems = dialog.problems()
    assert "SCL: на ESP32 GPIO від 0 до 39" not in problems
    assert any("внутрішній флеш" in p for p in problems)  # GPIO 7-11 of the S3 default wiring
    dialog.chip.setCurrentIndex(dialog.chip.findData(Chip.ESP32C3.value))
    assert any("ESP32-C3" in p or "зайнятий" in p for p in dialog.problems())
    for field, value in (("sck", 4), ("mosi", 6), ("rst", 3), ("dc", 7), ("cs", 10), ("bl", 2)):
        dialog.pins[field].setText(str(value))
    assert dialog.problems() == []
    display = dialog.display()
    assert display.mcu is Chip.ESP32C3


def test_dialog_rotation_and_spi(dialog: DisplayDialog) -> None:
    dialog.rotation.setCurrentIndex(1)
    dialog.spi.setCurrentIndex(dialog.spi.findData(80_000_000))
    display = dialog.display()
    assert (display.rotation, display.spi_hz, display.size) == (1, 80_000_000, (320, 240))


def test_dialog_keeps_an_unusual_frequency(qtbot: QtBot) -> None:
    dialog = DisplayDialog(Display(spi_hz=26_000_000))
    qtbot.addWidget(dialog)
    assert dialog.spi.currentText() == "26 МГц"
    assert dialog.display().spi_hz == 26_000_000


def test_dialog_memory_presets(dialog: DisplayDialog) -> None:
    assert dialog.memory.currentIndex() == 0  # no PSRAM: 16 KB, no cache
    assert (dialog.display().buf_bytes, dialog.display().image_cache) == (16_384, 0)
    assert "смуги по ~34 рядків" in dialog.memory_note.text()  # 16 KB / (2 * 240)
    assert "PSRAM" not in dialog.memory_note.text()
    dialog.memory.setCurrentIndex(3)  # PSRAM 8 MB
    display = dialog.display()
    assert (display.buf_bytes, display.image_cache) == (240 * 320 * 2, 4 * 1024 * 1024)
    assert (dialog.buffer_kb.value(), dialog.cache_kb.value()) == (150, 4096)
    assert "весь екран за раз" in dialog.memory_note.text()
    assert "Потрібна плата з PSRAM" in dialog.memory_note.text()
    dialog.cache_kb.setValue(512)  # an own value: the preset becomes "Своє"
    assert dialog.memory.currentText() == "Своє"
    assert dialog.display().image_cache == 512 * 1024
    dialog.buffer_kb.setValue(1000)  # more than a screen is never allocated
    assert dialog.display().buf_bytes == 240 * 320 * 2
    assert ok_enabled(dialog)


def test_dialog_reopens_with_saved_memory(qtbot: QtBot) -> None:
    dialog = DisplayDialog(Display(buf_bytes=153_600, image_cache=1024 * 1024))
    qtbot.addWidget(dialog)
    assert dialog.memory.currentIndex() == 2  # PSRAM 2 MB
    other = DisplayDialog(Display(buf_bytes=48 * 1024))
    qtbot.addWidget(other)
    assert other.memory.currentText() == "Своє"
    assert other.display().buf_bytes == 48 * 1024


# ------------------------------------------------------------------ work area
@pytest.fixture
def workspace(qtbot: QtBot, doc: Document) -> Workspace:
    view = Workspace()
    qtbot.addWidget(view)
    view.resize(800, 500)
    view.show()
    view.show_project(doc.project, 0)
    return view


def test_all_pages_side_by_side(workspace: Workspace) -> None:
    first, second = workspace.items_
    assert (first.name, second.name) == ("main", "settings")
    assert second.pos().x() > first.pos().x() + 320
    assert first.active
    assert not second.active
    assert all(h.isVisible() for h in first.handles)
    assert not any(h.isVisible() for h in second.handles)
    assert first.handles[0].flags() & QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations


def test_click_selects_page(workspace: Workspace, qtbot: QtBot) -> None:
    second = workspace.items_[1]
    workspace.fit_all()
    point = workspace.mapFromScene(second.mapToScene(QPointF(100, 100)))
    with qtbot.waitSignal(workspace.page_clicked) as signal:
        qtbot.mouseClick(workspace.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert signal.args == [1]


def test_zoom_limits(workspace: Workspace) -> None:
    for _ in range(20):
        workspace.zoom_in()
    assert workspace.zoom == ZOOM_MAX
    for _ in range(20):
        workspace.zoom_out()
    assert workspace.zoom == ZOOM_MIN
    workspace.zoom_reset()
    assert workspace.zoom == 1.0
    assert workspace.transform().m11() == pytest.approx(1.0)
    workspace.fit_all()
    assert ZOOM_MIN <= workspace.zoom <= ZOOM_MAX
    assert workspace.transform().m11() == pytest.approx(workspace.zoom)


def test_ctrl_wheel_zooms_around_cursor(workspace: Workspace) -> None:
    workspace.zoom_reset()
    pos = QPointF(200, 150)
    before = workspace.mapToScene(pos.toPoint())
    event = QWheelEvent(pos, workspace.mapToGlobal(pos), QPoint(), QPoint(0, 120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)  # fmt: skip
    workspace.wheelEvent(event)
    assert workspace.zoom == pytest.approx(1.25)
    after = workspace.mapToScene(pos.toPoint())
    assert abs(after.x() - before.x()) <= 2
    assert abs(after.y() - before.y()) <= 2


def test_preview_pixels() -> None:
    canvas = Canvas.filled(2, 1, to_wire("#ffffff"))
    canvas.set(1, 0, to_wire("#ff0000"))
    image = canvas_to_image(canvas)
    assert image.pixelColor(0, 0).name() == "#ffffff"
    assert image.pixelColor(1, 0).name() == "#ff0000"


# ------------------------------------------------------------------ main window
@pytest.fixture
def window(qtbot: QtBot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    return win


def test_window_opens_two_pages(window: MainWindow) -> None:
    assert window.open_file(PAGES)
    assert len(window.workspace.items_) == 2
    assert window.pages_bar.tabs.count() == 2
    assert window.windowTitle() == "pages.espui — ESP UI Builder"
    assert window.display_button.text() == "Дисплей: GMT020-02-8B · ESP32-S3 · ui_st7789"
    assert window.status_display.text().endswith("320×240")
    menus = [a.text() for a in window.menuBar().actions()]
    assert menus == [
        "Файл",
        "Правка",
        "Вигляд",
        "Дисплей",
        "Сторінки",
        "Параметри",
        "Генерація",
        "Довідка",
    ]


def test_window_follows_document(window: MainWindow) -> None:
    window.open_file(PAGES)
    window.doc.add_page(copy_current=True)
    assert len(window.workspace.items_) == 3
    assert window.windowTitle() == "pages.espui • — ESP UI Builder"
    assert window.status_saved.text() == "Є незбережені зміни"
    window.act_undo.trigger()
    assert len(window.workspace.items_) == 2
    window.doc.set_display(window.doc.project.display.model_copy(update={"rotation": 0}))
    assert window.status_warnings.text().startswith("⚠")
    assert "поза екраном: main/" in window.status_warnings.toolTip()


def test_window_save_and_generate(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.open_file(PAGES)
    window.doc.rename_page(0, "home")
    assert window._save_to(tmp_path / "copy.espui")
    assert window.windowTitle() == "copy.espui — ESP UI Builder"
    assert window.generate_to(tmp_path / "out")
    assert (tmp_path / "out" / "copy" / "ui_home.py").is_file()  # several pages: project name
    assert (tmp_path / "out" / "copy" / "ui_settings.py").is_file()


def test_open_error_is_reported(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(a[2]))
    (tmp_path / "bad.espui").write_text("{oops")
    assert not window.open_file(tmp_path / "bad.espui")
    assert "Це не JSON-файл проєкту" in shown[0]


def test_grid_toggle(window: MainWindow) -> None:
    window.act_grid.trigger()
    assert window.workspace.grid
    window.act_grid.trigger()
    assert not window.workspace.grid


def test_qt_texts_in_ukrainian(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QApplication

    from espui.gui.app import install_ukrainian

    app = QApplication.instance()
    assert app is not None
    assert install_ukrainian(app)
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    qtbot.addWidget(box)
    assert box.button(QDialogButtonBox.StandardButton.Close).text() == "Закрити"
