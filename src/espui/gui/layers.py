"""Layers: the stacking order of the current page. The top row is drawn over all others.

Order changes: drag a row (a line shows where it lands), the ↑/↓ buttons of a
row, ↑/↓ while the list has focus, Ctrl/⌘+↑/↓ anywhere (main window actions).
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QDropEvent, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QToolButton,
    QWidget,
)

from espui.core.models import Widget
from espui.gui.document import Document
from espui.gui.widgets_catalog import TITLES, badges

ID_ROLE = Qt.ItemDataRole.UserRole


def row_text(level: int, widget: Widget) -> str:
    """``3  t_val · Число · temperature  ↻ ◐``."""
    parts = [widget.id, TITLES[widget.type]]
    if widget.bind:
        parts.append(widget.bind)
    extra = badges(widget)
    return f"{level}  " + " · ".join(parts) + (f"  {extra}" if extra else "")


class LayerRow(QWidget):
    def __init__(self, text: str, on_up: object, on_down: object) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 2, 0)
        self.label = QLabel(text)
        layout.addWidget(self.label, 1)
        self.up = QToolButton()
        self.up.setText("↑")
        self.up.setToolTip("Вище (над іншими)")
        self.up.clicked.connect(on_up)
        self.down = QToolButton()
        self.down.setText("↓")
        self.down.setToolTip("Нижче")
        self.down.clicked.connect(on_down)
        layout.addWidget(self.up)
        layout.addWidget(self.down)


class LayersPanel(QListWidget):
    def __init__(self, doc: Document) -> None:
        super().__init__()
        self.doc = doc
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._loading = False
        self._signature: tuple[object, ...] = ()
        """What the rows show (see :meth:`refresh`)."""
        self.itemSelectionChanged.connect(self._selected)
        doc.changed.connect(self.refresh)
        doc.current_page_changed.connect(self.refresh)
        doc.selection_changed.connect(self._show_selection)
        self.refresh()

    def ids(self) -> list[str]:
        """Widget ids top to bottom as listed."""
        return [self.item(i).data(ID_ROLE) for i in range(self.count())]

    def refresh(self) -> None:
        """Rebuild the rows only if they would read differently; the scroll stays put."""
        widgets = self.doc.page.widgets
        texts = tuple(row_text(i + 1, w) for i, w in enumerate(widgets))
        signature = (self.doc.current, tuple(w.id for w in widgets), texts)
        if signature == self._signature:
            self._show_selection()
            return
        if signature[:2] == self._signature[:2]:  # same rows, only a label changed (↻, ◐…)
            self._signature = signature
            for i, text in enumerate(reversed(texts)):
                row = self.itemWidget(self.item(i))
                if isinstance(row, LayerRow):
                    row.label.setText(text)
            self._show_selection()
            return
        self._signature = signature
        scroll = self.verticalScrollBar().value()
        self._loading = True
        self.clear()
        for list_index in reversed(range(len(widgets))):
            widget = widgets[list_index]
            item = QListWidgetItem()
            item.setData(ID_ROLE, widget.id)
            item.setSizeHint(QSize(100, 26))
            self.addItem(item)
            row = LayerRow(
                row_text(list_index + 1, widget),
                lambda _=False, i=widget.id: self.doc.raise_layer(i, 1),
                lambda _=False, i=widget.id: self.doc.raise_layer(i, -1),
            )
            row.up.setEnabled(list_index < len(widgets) - 1)
            row.down.setEnabled(list_index > 0)
            self.setItemWidget(item, row)
        self._loading = False
        self._show_selection()
        self.verticalScrollBar().setValue(scroll)

    def _show_selection(self) -> None:
        self._loading = True
        self.clearSelection()
        for i in range(self.count()):
            if self.item(i).data(ID_ROLE) == self.doc.selected:
                self.setCurrentRow(i)
                break
        self._loading = False

    def _selected(self) -> None:
        if self._loading:
            return
        items = self.selectedItems()
        self.doc.select(items[0].data(ID_ROLE) if items else None)

    def dropEvent(self, event: QDropEvent) -> None:
        moved = self.currentItem().data(ID_ROLE) if self.currentItem() else None
        super().dropEvent(event)
        if moved is not None:
            self.reordered(moved)

    def reordered(self, moved: str) -> None:
        """The rows were rearranged (drag & drop): apply the new place of ``moved``."""
        order = self.ids()  # top first
        to = len(order) - 1 - order.index(moved)
        self.doc.select(moved)
        if not self.doc.move_layer(moved, to):
            self.refresh()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down) and self.doc.selected:
            self.doc.raise_layer(step=1 if key == Qt.Key.Key_Up else -1)
            return
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.doc.selected:
            self.doc.remove_widget()
            return
        super().keyPressEvent(event)
