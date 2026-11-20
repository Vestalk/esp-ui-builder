"""Page tabs: ``ui_<name>.py · N``, add, rename (double click), delete with confirmation."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QMenu,
    QTabBar,
    QToolButton,
    QWidget,
)

from espui.gui.document import Document

CONFIRM_TEXT = "Видалити?"


def tab_text(name: str, widgets: int) -> str:
    return f"ui_{name}.py · {widgets}"


class PageTabs(QTabBar):
    """Tabs with a close button; the first click on × asks, the second deletes."""

    delete_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTabsClosable(True)
        self.setMovable(False)
        self.setExpanding(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.armed: int | None = None
        """Tab whose × was clicked once (shows "Видалити?")."""
        self._texts: list[str] = []
        self.tabCloseRequested.connect(self._close_clicked)

    def set_tabs(self, texts: list[str], current: int) -> None:
        self.blockSignals(True)
        self.disarm()
        while self.count():
            self.removeTab(0)
        for text in texts:
            self.addTab(text)
        self._texts = list(texts)
        self.setCurrentIndex(current)
        self.blockSignals(False)

    def _close_clicked(self, index: int) -> None:
        if self.count() <= 1:
            return  # the last page can't be deleted
        if self.armed == index:
            self.disarm()
            self.delete_requested.emit(index)
            return
        self.disarm()
        self.armed = index
        self.setTabText(index, CONFIRM_TEXT)
        self.setTabToolTip(index, "Натисніть × ще раз, щоб видалити; Esc — скасувати")

    def disarm(self) -> None:
        if self.armed is not None and self.armed < len(self._texts):
            self.setTabText(self.armed, self._texts[self.armed])
            self.setTabToolTip(self.armed, "")
        self.armed = None

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.disarm()
            return
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self.disarm()
            step = -1 if key == Qt.Key.Key_Left else 1
            self.setCurrentIndex(max(0, min(self.count() - 1, self.currentIndex() + step)))
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: object) -> None:
        index = self.tabAt(event.position().toPoint())  # type: ignore[attr-defined]
        if self.armed is not None and index != self.armed:
            self.disarm()  # a click elsewhere cancels the deletion
        super().mousePressEvent(event)  # type: ignore[arg-type]


class PagesBar(QWidget):
    """Tabs + "+ Сторінка" (empty page or a copy of the current one)."""

    def __init__(self, doc: Document, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.doc = doc
        self.tabs = PageTabs()
        self.setObjectName("pages_bar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.add_button = QToolButton()
        self.add_button.setObjectName("add_page")
        self.add_button.setText("+ Сторінка")
        self.add_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        menu = QMenu(self.add_button)
        menu.addAction("Порожня сторінка", lambda: self.doc.add_page(copy_current=False))
        menu.addAction("Копія поточної", lambda: self.doc.add_page(copy_current=True))
        self.add_button.setMenu(menu)
        self.add_button.clicked.connect(lambda: self.doc.add_page(copy_current=False))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.add_button)

        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabBarDoubleClicked.connect(self.rename)
        self.tabs.delete_requested.connect(self.doc.remove_page)
        doc.changed.connect(self.refresh)
        doc.current_page_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        pages = self.doc.project.pages
        self.tabs.set_tabs([tab_text(p.name, len(p.widgets)) for p in pages], self.doc.current)

    def _tab_changed(self, index: int) -> None:
        if index >= 0:
            self.doc.set_current(index)

    def rename(self, index: int | None = None, name: str | None = None) -> str | None:
        """Rename a page (asks for the name if not given); returns a problem or None."""
        if index is None or index < 0:
            index = self.doc.current
        page = self.doc.project.pages[index]
        if name is None:
            name, ok = QInputDialog.getText(
                self, "Перейменувати сторінку", "Назва (ідентифікатор Python):", text=page.name
            )
            if not ok:
                return None
            while (problem := self.doc.rename_problem(index, name)) is not None:
                name, ok = QInputDialog.getText(
                    self, "Перейменувати сторінку", f"{problem}\nНазва:", text=name
                )
                if not ok:
                    return None
        return self.doc.rename_page(index, name)
