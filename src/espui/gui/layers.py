"""Layers: the stacking order of the current page. The top row is drawn over all others.

Order changes: drag a row (a line shows where it lands), the ↑/↓ buttons of a
row, ↑/↓ while the list has focus, Ctrl/⌘+↑/↓ anywhere (main window actions).
👁 hides a widget in the editor and 🔒 locks it on the canvas — the board draws
the page the same either way.
"""

from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, QSize, Qt
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
    if widget.group:
        extra = f"▣ {widget.group}" + (f" {extra}" if extra else "")
    return f"{level}  " + " · ".join(parts) + (f"  {extra}" if extra else "")


HIDE_TIP = "Сховати в редакторі (на платі елемент лишається)"
SHOW_TIP = "Сховано в редакторі — натисніть, щоб показати (на платі він є)"
LOCK_TIP = "Заблокувати: на полотні не вибирається й не рухається"
UNLOCK_TIP = "Заблоковано — натисніть, щоб розблокувати"


class LayerRow(QWidget):
    def __init__(
        self,
        text: str,
        on_up: object,
        on_down: object,
        on_eye: object = None,
        on_lock: object = None,
    ) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        self.eye = QToolButton()
        self.eye.setObjectName("layer_eye")
        self.eye.setCheckable(True)
        self.eye.setAutoRaise(True)
        self.lock = QToolButton()
        self.lock.setObjectName("layer_lock")
        self.lock.setCheckable(True)
        self.lock.setAutoRaise(True)
        if on_eye is not None:
            self.eye.clicked.connect(on_eye)
        if on_lock is not None:
            self.lock.clicked.connect(on_lock)
        layout.addWidget(self.eye)
        layout.addWidget(self.lock)
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
        self.set_flags(False, False)

    def set_flags(self, hidden: bool, locked: bool) -> None:
        """👁 / 🔒 as the widget has them; a hidden one reads greyed out."""
        self.eye.setChecked(hidden)
        self.eye.setText("◌" if hidden else "👁")
        self.eye.setToolTip(SHOW_TIP if hidden else HIDE_TIP)
        self.lock.setChecked(locked)
        self.lock.setText("🔒" if locked else "🔓")
        self.lock.setToolTip(UNLOCK_TIP if locked else LOCK_TIP)
        self.label.setEnabled(not hidden)


class LayersPanel(QListWidget):
    def __init__(self, doc: Document) -> None:
        super().__init__()
        self.doc = doc
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(True)
        # Shift / Ctrl(⌘)+click select several rows: the same selection as on the canvas.
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
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
        flags = tuple((w.editor_hidden, w.locked) for w in widgets)
        signature = (self.doc.current, tuple(w.id for w in widgets), texts, flags)
        if signature == self._signature:
            self._show_selection()
            return
        if signature[:2] == self._signature[:2]:  # same rows, only a label changed (↻, ◐…)
            self._signature = signature
            for i, (text, flag) in enumerate(zip(reversed(texts), reversed(flags), strict=True)):
                row = self.itemWidget(self.item(i))
                if isinstance(row, LayerRow):
                    row.label.setText(text)
                    row.set_flags(*flag)
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
                lambda _=False, i=widget.id: self._flag("editor_hidden", i),
                lambda _=False, i=widget.id: self._flag("locked", i),
            )
            row.set_flags(widget.editor_hidden, widget.locked)
            row.up.setEnabled(list_index < len(widgets) - 1)
            row.down.setEnabled(list_index > 0)
            self.setItemWidget(item, row)
        self._loading = False
        self._show_selection()
        self.verticalScrollBar().setValue(scroll)

    def _flag(self, field: str, widget_id: str) -> None:
        """👁 / 🔒 of a row: for the whole selection if the row is in it, else for that row."""
        ids = self.doc.selected_ids
        self.doc.toggle_flag(field, ids if widget_id in ids else [widget_id])

    def _show_selection(self) -> None:
        self._loading = True
        chosen = set(self.doc.selected_ids)
        self.clearSelection()
        for i in range(self.count()):
            item = self.item(i)
            wid = item.data(ID_ROLE)
            if wid == self.doc.selected:
                self.setCurrentItem(item, QItemSelectionModel.SelectionFlag.NoUpdate)
            item.setSelected(wid in chosen)
        self._loading = False

    def _selected(self) -> None:
        if self._loading:
            return
        ids = [item.data(ID_ROLE) for item in self.selectedItems()]
        current = self.currentItem()
        main = current.data(ID_ROLE) if current is not None and current.isSelected() else None
        if len(ids) <= 1:
            self.doc.select(ids[0] if ids else None)
        else:
            self.doc.select_many(ids, main)

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
            ids = self.doc.selected_ids
            if len(ids) > 1:
                self.doc.remove_widgets(ids)
            else:
                self.doc.remove_widget()
            return
        super().keyPressEvent(event)
