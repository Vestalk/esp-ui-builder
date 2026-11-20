"""Stage 14: autosave, recovery, round-trip, import, recent projects, generation."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from espui.core import serializer
from espui.gui import session
from espui.gui.main_window import MainWindow
from tests.gui.conftest import ROOT

WEATHER = ROOT / "examples" / "weather.espui"
IMAGES = ROOT / "examples" / "images.espui"
MOCKUP = ROOT / "tests" / "fixtures" / "mockup_weather.espui.json"


@pytest.fixture
def autosave(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session.AutoSaver, "enabled", True)
    monkeypatch.setattr(session, "AUTOSAVE_MS", 200)


def make_window(qtbot: QtBot, folder: Path) -> MainWindow:
    win = MainWindow(data_folder=folder)
    qtbot.addWidget(win)
    win.autosaver.timer.setInterval(200)
    win.show()
    return win


def copy(source: Path, tmp_path: Path) -> Path:
    target = tmp_path / source.name
    shutil.copy(source, target)
    return target


# ------------------------------------------------------------------ autosave
@pytest.mark.usefixtures("autosave")
def test_autosave_into_the_project_file(qtbot: QtBot, tmp_path: Path) -> None:
    path = copy(WEATHER, tmp_path)
    win = make_window(qtbot, tmp_path / "data")
    win.open_file(path)
    before = path.read_text("utf-8")
    win.doc.rename_page(0, "home")
    assert win.doc.dirty
    qtbot.waitUntil(lambda: not win.doc.dirty, timeout=3000)
    assert path.read_text("utf-8") != before
    assert serializer.load(path).pages[0].name == "home"
    assert win.status_saved.text().startswith("Збережено о ")


@pytest.mark.usefixtures("autosave")
def test_nothing_changed_nothing_written(qtbot: QtBot, tmp_path: Path) -> None:
    path = copy(WEATHER, tmp_path)
    win = make_window(qtbot, tmp_path / "data")
    win.open_file(path)
    stamp = path.stat().st_mtime_ns
    win.doc.changed.emit()  # e.g. a view refresh, not an edit
    qtbot.wait(400)
    assert path.stat().st_mtime_ns == stamp
    assert not win.autosaver.timer.isActive()


@pytest.mark.usefixtures("autosave")
def test_ctrl_s_saves_at_once(qtbot: QtBot, tmp_path: Path) -> None:
    path = copy(WEATHER, tmp_path)
    win = make_window(qtbot, tmp_path / "data")
    win.open_file(path)
    win.doc.rename_page(0, "home")
    win.act_save.trigger()
    assert not win.doc.dirty
    assert serializer.load(path).pages[0].name == "home"


# ------------------------------------------------------------------ recovery and round-trip
@pytest.mark.usefixtures("autosave")
def test_new_project_is_recovered(qtbot: QtBot, tmp_path: Path) -> None:
    data = tmp_path / "data"
    first = make_window(qtbot, data)
    first.workspace.add_widget("rect")
    first.doc.add_page()
    qtbot.waitUntil(lambda: (data / session.RECOVERY_FILE).is_file(), timeout=3000)
    assert first.status_saved.text().startswith("Чернетку збережено о ")
    first.doc.add_page()  # one more change, then the program is closed
    first.close()
    project = first.doc.project.model_copy(deep=True)

    second = make_window(qtbot, data)
    assert second.autosaver.recovery_available()
    assert second.autosaver.restore()
    assert [p.name for p in second.doc.project.pages] == [p.name for p in project.pages]
    assert second.doc.project.pages[0].widgets == project.pages[0].widgets
    assert second.doc.dirty  # it still has no file
    assert second.doc.path is None
    second._save_to(tmp_path / "mine.espui")
    assert not second.autosaver.recovery_available()  # saved for real: no draft left


@pytest.mark.usefixtures("autosave")
def test_close_and_reopen_gives_the_same_state(qtbot: QtBot, tmp_path: Path) -> None:
    path = copy(IMAGES, tmp_path)
    win = make_window(qtbot, tmp_path / "data")
    win.open_file(path)
    doc = win.doc
    doc.set_test_value("temperature", 33.5)
    doc.add_page(copy_current=True)  # current page: 1
    doc.set_display(doc.project.display.model_copy(update={"spi_hz": 26_000_000}))
    win.workspace.set_zoom(2.5)
    win.close()  # without saving: pending changes are written anyway

    again = make_window(qtbot, tmp_path / "data")
    assert again.open_file(path)
    reopened = again.doc.project
    assert reopened.pages == doc.project.pages
    assert reopened.display == doc.project.display
    assert reopened.images == doc.project.images
    assert reopened.pages[0].test_values["temperature"] == 33.5
    assert again.doc.current == 1
    assert again.workspace.zoom == pytest.approx(2.5)


def test_damaged_file(qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(a[2]))
    win = make_window(qtbot, tmp_path / "data")
    win.open_file(WEATHER)
    broken = tmp_path / "broken.espui"
    broken.write_text('{"pages": [{"name": "Main"}]', "utf-8")
    assert not win.open_file(broken)
    assert "Це не JSON-файл проєкту" in shown[0]
    assert win.doc.path == WEATHER  # the open project is kept
    invalid = tmp_path / "invalid.espui"
    invalid.write_text('{"pages": [{"name": "Main"}]}', "utf-8")
    assert not win.open_file(invalid)
    assert "pages[0].name" in shown[1]


def test_import_from_the_mockup(qtbot: QtBot, tmp_path: Path) -> None:
    win = make_window(qtbot, tmp_path / "data")
    assert win.open_file(MOCKUP)
    assert win.doc.path is None  # becomes a new project
    assert win.doc.title == "Без назви.espui"
    assert [p.name for p in win.doc.project.pages] == ["main", "settings"]
    assert win.act_import.text().startswith("Імпорт з макета")


def test_recent_projects(qtbot: QtBot, tmp_path: Path) -> None:
    first, second = copy(WEATHER, tmp_path), copy(IMAGES, tmp_path)
    win = make_window(qtbot, tmp_path / "data")
    win.open_file(first)
    win.open_file(second)
    win.open_file(first)
    assert session.recent_projects() == [first.resolve(), second.resolve()]
    win._fill_recent()
    assert [a.text() for a in win.recent_menu.actions()] == ["weather.espui", "images.espui"]
    assert win.open_recent(second)
    assert win.doc.path == second


# ------------------------------------------------------------------ generation
def test_generate_files_and_protect_main(qtbot: QtBot, tmp_path: Path) -> None:
    win = make_window(qtbot, tmp_path / "data")
    win.open_file(IMAGES)
    out = tmp_path / "board"
    assert win.generate_to(out)
    dialog = win.last_result
    names = [dialog.files.item(i).text().split(" · ")[0] for i in range(dialog.files.count())]
    for expected in ("ui_display.py", "ui_st7789.py", "ui_fonts.py", "ui_main.py", "main.py",
                     ".vscode/settings.json", "img/sun.bin", "img/spinner/000.bin"):  # fmt: skip
        assert expected in names, expected
    assert "КБ" in dialog.files.item(0).text() or " Б" in dialog.files.item(0).text()
    dialog.files.setCurrentRow(names.index("main.py"))
    assert "ui.draw(p)" in dialog.viewer.toPlainText()
    dialog.files.setCurrentRow(names.index("img/sun.bin"))
    assert dialog.viewer.toPlainText().startswith("sun.bin: RGB565, 8192 байт")
    assert session.generate_dir(win.doc.path) == out

    (out / "main.py").write_text("# my own main\n", "utf-8")
    assert win.generate_to(out)
    assert (out / "main.py").read_text("utf-8") == "# my own main\n"
    assert (out / "main.example.py").is_file()
    assert "main.example.py" in win.last_result.info.text()


def test_generation_stops_on_project_errors(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))
    win = make_window(qtbot, tmp_path / "data")
    win.open_file(WEATHER)
    widget = win.doc.page.widget("t_val")
    assert widget is not None
    win.doc.select("t_val")
    win.doc.change_widget(widget.model_copy(update={"format": "%x"}))
    assert not win.generate_to(tmp_path / "board")
    assert "«%x» не підтримується" in shown[0]
    assert not (tmp_path / "board").exists()


def test_memory_estimate_in_the_status_bar(qtbot: QtBot, tmp_path: Path) -> None:
    win = make_window(qtbot, tmp_path / "data")
    win.open_file(IMAGES)
    qtbot.waitUntil(lambda: win.status_memory.text().startswith("Флеш ≈ "), timeout=3000)
    assert "картинки 278" in win.status_memory.text()
    assert "RAM ≈ " in win.status_memory.text()
    before = win.status_memory.text()
    # "loading" has its own 128x32 variant; the library pictures stay (the icon takes any of them)
    win.doc.remove_widget("loading")
    qtbot.waitUntil(lambda: win.status_memory.text() != before, timeout=3000)
    assert "картинки 214" in win.status_memory.text()
