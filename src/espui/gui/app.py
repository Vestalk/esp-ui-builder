"""Entry point of the desktop application: ``espui gui [project.espui]``."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QTranslator
from PySide6.QtWidgets import QApplication, QMessageBox

from espui.gui.main_window import MainWindow


def install_ukrainian(app: QCoreApplication) -> bool:
    """Qt's own texts (OK, Cancel, Close, file dialogs) in Ukrainian."""
    translator = QTranslator(app)
    path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load("qtbase_uk", path):
        return app.installTranslator(translator)
    return False


def run(argv: Sequence[str] | None = None, project: str | None = None) -> int:
    app = QApplication.instance() or QApplication(list(argv or sys.argv))
    install_ukrainian(app)
    app.setOrganizationName("ESP UI Builder")
    app.setApplicationName("ESP UI Builder")
    window = MainWindow()
    if project:
        window.open_file(project)
    elif window.autosaver.recovery_available():
        answer = QMessageBox.question(
            window,
            "Відновлення",
            "Минулого разу залишився незбережений проєкт. Відновити його?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            window.autosaver.restore()
        else:
            window.autosaver.discard_recovery()
    window.show()
    return app.exec()
