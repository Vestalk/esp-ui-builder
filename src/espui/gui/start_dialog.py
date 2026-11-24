"""The start window: a new project (then its display), open, recent projects, examples."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from espui.gui.session import recent_projects

SHOW_KEY = "start/show"
EXAMPLES_DIR = Path(__file__).resolve().parents[3] / "examples"
"""In a source checkout: examples/*.espui (a packaged build may have none)."""

EXAMPLE_TITLES = {
    "weather": "Погода: текст, шкала, дуга, умови",
    "sensors": "Датчики: кілька значень і стани",
    "transforms": "Поворот і рух за параметром",
    "images": "Картинки й анімація",
    "chart": "Графік (series)",
    "pages": "Дві сторінки й перемикання",
}
PATH_ROLE = Qt.ItemDataRole.UserRole


def show_on_start() -> bool:
    return bool(QSettings().value(SHOW_KEY, True, type=bool))


def examples() -> list[Path]:
    if not EXAMPLES_DIR.is_dir():
        return []
    files = sorted(EXAMPLES_DIR.glob("*.espui"))
    order = list(EXAMPLE_TITLES)
    return sorted(files, key=lambda p: order.index(p.stem) if p.stem in order else len(order))


class StartDialog(QDialog):
    """``choice``: "new", "open", or "file" (then ``path``); None if just closed."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ESP UI Builder")
        self.setObjectName("start_dialog")
        self.resize(720, 440)
        self.choice: str | None = None
        self.path: Path | None = None

        title = QLabel("<h2>ESP UI Builder</h2>Екрани для ESP32 і MicroPython: намалюйте сторінку, "
                       "прив'яжіть до параметрів і згенеруйте код для плати.")  # fmt: skip
        title.setWordWrap(True)
        self.new_button = QPushButton("＋ Новий проєкт…")
        self.new_button.setObjectName("start_new")
        self.new_button.setToolTip("Порожня сторінка; одразу відкриється вибір дисплея")
        self.new_button.clicked.connect(lambda: self._done("new"))
        self.open_button = QPushButton("Відкрити…")
        self.open_button.setObjectName("start_open")
        self.open_button.clicked.connect(lambda: self._done("open"))
        self.help_button = QPushButton("Як почати?")
        self.help_button.setObjectName("start_help")
        self.help_button.clicked.connect(self._help)
        actions = QVBoxLayout()
        for button in (self.new_button, self.open_button, self.help_button):
            button.setMinimumHeight(34)
            actions.addWidget(button)
        actions.addStretch(1)

        self.recent = self._list("start_recent")
        for path in recent_projects():
            self._add(self.recent, path.name, path, str(path))
        if not self.recent.count():
            self.recent.addItem("— ще немає —")
            self.recent.item(0).setFlags(Qt.ItemFlag.NoItemFlags)
        self.samples = self._list("start_examples")
        for path in examples():
            self._add(self.samples, EXAMPLE_TITLES.get(path.stem, path.stem), path, path.name)
        lists = QVBoxLayout()
        lists.addWidget(QLabel("<b>Останні проєкти</b>"))
        lists.addWidget(self.recent, 2)
        self.examples_label = QLabel("<b>Приклади</b>")
        lists.addWidget(self.examples_label)
        lists.addWidget(self.samples, 2)
        self.examples_label.setVisible(self.samples.count() > 0)
        self.samples.setVisible(self.samples.count() > 0)

        self.show_again = QCheckBox("Показувати під час запуску")
        self.show_again.setObjectName("start_show")
        self.show_again.setChecked(show_on_start())
        self.show_again.toggled.connect(lambda on: QSettings().setValue(SHOW_KEY, on))
        close = QPushButton("Закрити")
        close.clicked.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(self.show_again)
        bottom.addStretch(1)
        bottom.addWidget(close)

        body = QHBoxLayout()
        body.addLayout(actions, 1)
        body.addLayout(lists, 2)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addLayout(body, 1)
        layout.addLayout(bottom)

    def _list(self, name: str) -> QListWidget:
        widget = QListWidget()
        widget.setObjectName(name)
        widget.itemActivated.connect(self._open_item)
        widget.itemDoubleClicked.connect(self._open_item)
        return widget

    def _add(self, widget: QListWidget, text: str, path: Path, tip: str) -> None:
        item = QListWidgetItem(text)
        item.setData(PATH_ROLE, str(path))
        item.setToolTip(tip)
        widget.addItem(item)

    def _open_item(self, item: QListWidgetItem) -> None:
        path = item.data(PATH_ROLE)
        if path:
            self.path = Path(path)
            self._done("file")

    def _done(self, choice: str) -> None:
        self.choice = choice
        self.accept()

    def _help(self) -> None:
        from espui.gui.help import show_help

        show_help("start", self.parentWidget() or self)
