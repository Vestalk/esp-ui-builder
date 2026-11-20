"""GUI tests run without a screen (Qt "offscreen" platform)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
PAGES = ROOT / "examples" / "pages.espui"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    here = Path(__file__).parent
    for item in items:
        if here in Path(item.fspath).parents:
            item.add_marker(pytest.mark.gui)


@pytest.fixture(autouse=True)
def isolated_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> Path:
    """No test writes the user's settings, data folder or the opened example files."""
    from PySide6.QtCore import QSettings

    from espui.gui import session
    from espui.gui.generate_dialog import GenerateResultDialog

    folder = tmp_path_factory.mktemp("session")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(folder / "settings")
    )
    QSettings().clear()
    monkeypatch.setattr(session, "data_dir", lambda: folder / "data")
    monkeypatch.setattr(session.AutoSaver, "enabled", False)
    monkeypatch.setattr(GenerateResultDialog, "exec", lambda self: 0)
    return folder


@pytest.fixture(autouse=True)
def no_modal_questions(monkeypatch: pytest.MonkeyPatch) -> None:
    """A modal "save changes?" would block a headless test run: answer "Discard"."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Discard)
