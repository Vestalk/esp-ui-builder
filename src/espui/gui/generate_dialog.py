"""The result of "▶ Згенерувати": files with sizes, a viewer and "Відкрити папку"."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from espui.i18n import tr

HINT = tr(
    "Відкрийте цю папку у VS Code і виконайте команду MicroPico «Upload project to Pico»: "
    "завантажаться і .py, і картинки img/*.bin (.vscode/settings.json це вже налаштовує)."
)
PATH_ROLE = Qt.ItemDataRole.UserRole


def size_text(size: int) -> str:
    return (
        tr("{size} Б").format(size=size)
        if size < 1024
        else tr("{v1:.1f} КБ").format(v1=size / 1024).replace(".", ",")
    )


class GenerateResultDialog(QDialog):
    def __init__(
        self,
        folder: Path,
        written: Sequence[Path],
        notes: Sequence[str] = (),
        warnings: Sequence[str] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.folder = folder
        self.setWindowTitle(tr("Згенеровано"))
        self.resize(900, 560)
        summary = QLabel(tr("Папка: {folder}").format(folder=folder))
        summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lines = [*notes, *(f"⚠ {w}" for w in warnings)]
        self.info = QLabel("\n".join(lines))
        self.info.setWordWrap(True)
        hint = QLabel(HINT)
        hint.setWordWrap(True)
        hint.setEnabled(False)

        self.files = QListWidget()
        for path in sorted(written, key=lambda p: (p.parent != folder, p.as_posix())):
            name = path.relative_to(folder).as_posix()
            item = QListWidgetItem(f"{name} · {size_text(path.stat().st_size)}")
            item.setData(PATH_ROLE, str(path))
            self.files.addItem(item)
        self.viewer = QPlainTextEdit()
        self.viewer.setReadOnly(True)
        font = QFont("Menlo")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.viewer.setFont(font)
        self.files.currentItemChanged.connect(self._show)
        split = QSplitter()
        split.addWidget(self.files)
        split.addWidget(self.viewer)
        split.setSizes([300, 600])

        self.open_folder = QPushButton(tr("Відкрити папку"))
        self.open_folder.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.folder)))
        )
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.addButton(self.open_folder, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addWidget(self.info)
        layout.addWidget(split, 1)
        layout.addWidget(hint)
        layout.addWidget(buttons)
        if self.files.count():
            self.files.setCurrentRow(0)

    def _show(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        path = Path(item.data(PATH_ROLE))
        data = path.read_bytes()
        if path.suffix == ".bin":
            self.viewer.setPlainText(
                tr("{name}: RGB565, {v1} байт (картинка для дисплея)").format(
                    name=path.name, v1=len(data)
                )
            )
            return
        try:
            self.viewer.setPlainText(data.decode("utf-8"))
        except UnicodeDecodeError:
            self.viewer.setPlainText(tr("{name}: {v1} байт").format(name=path.name, v1=len(data)))
