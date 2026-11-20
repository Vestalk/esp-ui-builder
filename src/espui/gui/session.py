"""Not losing work: autosave, recovery of a never-saved project, recent projects.

* A project with a file is saved into that file ~1.5 s after a change (only if
  something changed); Ctrl/⌘+S saves at once.
* A new project without a file is saved into the application's data folder
  (``recovery.espui``); on the next start the program offers to restore it.
* Drafts are saved even if the checks find problems: they are reported when
  generating, and nothing typed is lost.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QStandardPaths, QTimer, Signal

from espui.core import serializer
from espui.core.issues import ProjectError
from espui.gui.document import Document

AUTOSAVE_MS = 1500
RECOVERY_FILE = "recovery.espui"
RECENT_KEY = "recent_projects"
RECENT_MAX = 8


def data_dir() -> Path:
    """The application's own folder for the recovery file."""
    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    return Path(location or Path.home() / ".espui")


class AutoSaver(QObject):
    enabled = True
    """Tests turn autosaving off so that opened example files are never written."""

    status = Signal(str)
    """«Зберігаю…», «Збережено о 01:20», or what went wrong."""

    def __init__(
        self,
        doc: Document,
        folder: Path | None = None,
        before_save: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(doc)
        self.doc = doc
        self.folder = folder or data_dir()
        self.before_save = before_save or (lambda: None)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(AUTOSAVE_MS)
        self.timer.timeout.connect(self.save_now)
        doc.changed.connect(self.schedule)

    @property
    def recovery_path(self) -> Path:
        return self.folder / RECOVERY_FILE

    def schedule(self) -> None:
        if self.enabled and self.doc.dirty:
            self.timer.start()

    def save_now(self) -> bool:
        """Save into the project's file, or into the recovery file if it has none."""
        self.timer.stop()
        if not self.enabled:
            return False
        self.status.emit("Зберігаю…")
        self.before_save()
        try:
            if self.doc.path is not None:
                self.doc.save()
                self.discard_recovery()
                self.status.emit(f"Збережено о {time.strftime('%H:%M')}")
            else:
                self.folder.mkdir(parents=True, exist_ok=True)
                serializer.save(self.doc.project, self.recovery_path, check=False)
                self.status.emit(
                    f"Чернетку збережено о {time.strftime('%H:%M')} (файл ще не вибрано)"
                )
        except (OSError, ProjectError) as error:
            self.status.emit(f"Не вдалося зберегти: {error}")
            return False
        return True

    # ------------------------------------------------------------------ recovery
    def recovery_available(self) -> bool:
        return self.recovery_path.is_file()

    def restore(self) -> bool:
        """Load the recovery file as an unsaved project."""
        try:
            project = serializer.load(self.recovery_path, check=False)
        except ProjectError as error:
            self.status.emit(f"Не вдалося відновити: {error}")
            return False
        self.doc.load(project, None)
        self.doc.undo_stack.resetClean()  # unsaved: it still has to get a file
        self.doc.file_changed.emit()
        self.status.emit("Відновлено незбережений проєкт")
        return True

    def discard_recovery(self) -> None:
        self.recovery_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------- recent projects
def recent_projects() -> list[Path]:
    value = QSettings().value(RECENT_KEY, [])
    items = value if isinstance(value, list) else [value] if value else []
    return [Path(str(p)) for p in items if p and Path(str(p)).is_file()]


def add_recent(path: Path) -> list[Path]:
    paths = [path.resolve(), *(p for p in recent_projects() if p.resolve() != path.resolve())]
    paths = paths[:RECENT_MAX]
    QSettings().setValue(RECENT_KEY, [str(p) for p in paths])
    return paths


# ---------------------------------------------------------------------- generation folder
def generate_dir(project_path: Path | None) -> Path | None:
    """The folder last used to generate this project."""
    value = QSettings().value(f"generate_dir/{project_path or ''}", "")
    return Path(str(value)) if value else None


def remember_generate_dir(project_path: Path | None, folder: Path) -> None:
    QSettings().setValue(f"generate_dir/{project_path or ''}", str(folder))
