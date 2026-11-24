"""Colour swatches: the project's palette and the colours used on the page, one click applies.

``＋`` adds the current colour to the palette; right-click on a palette swatch takes it
out. The palette is saved in the project (``project.colors``) and is offered in the
colour dialog too (its custom colours).
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QGridLayout, QToolButton, QWidget

from espui.gui.document import Document

COLUMNS = 10
PAGE_COLORS = 8
"""Colours of the page shown besides the palette (those not in it yet)."""
SIZE = 18


def swatch_style(color: str, dashed: bool = False) -> str:
    border = "1px dashed #8fa3ad" if dashed else "1px solid #5b6770"
    return f"QToolButton {{ background: {color}; border: {border}; border-radius: 3px; }}"


def offer_in_dialog(colors: list[str]) -> None:
    """The palette as the colour dialog's custom colours (16 slots)."""
    for i in range(QColorDialog.customCount()):
        QColorDialog.setCustomColor(i, QColor(colors[i]) if i < len(colors) else QColor("#ffffff"))


class ColorSwatches(QWidget):
    def __init__(
        self,
        doc: Document,
        on_pick: Callable[[str], object],
        current: Callable[[], str | None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.doc = doc
        self.on_pick = on_pick
        self.current = current
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(3)
        self.buttons: dict[str, QToolButton] = {}
        """Colour -> its swatch (palette and page colours)."""
        self.add_button = QToolButton()
        self.add_button.setObjectName("swatch_add")
        self.add_button.setText("＋")
        self.add_button.setFixedSize(SIZE + 4, SIZE)
        self.add_button.setToolTip("Додати поточний колір у кольори проєкту")
        self.add_button.clicked.connect(self._add_current)
        self._signature: tuple[object, ...] = ()
        self.refresh()

    def refresh(self) -> None:
        palette = list(self.doc.project.colors)
        used = [c for c in self.doc.page_colors() if c not in palette][:PAGE_COLORS]
        signature = (tuple(palette), tuple(used))
        if signature == self._signature:
            return
        self._signature = signature
        for button in self.buttons.values():
            self.grid.removeWidget(button)
            button.deleteLater()
        self.buttons = {}
        self.grid.removeWidget(self.add_button)
        cells: list[QWidget] = []
        for color in palette:
            cells.append(self._swatch(color, in_palette=True))
        for color in used:
            cells.append(self._swatch(color, in_palette=False))
        cells.append(self.add_button)
        for i, cell in enumerate(cells):
            self.grid.addWidget(cell, i // COLUMNS, i % COLUMNS)
        self.grid.setColumnStretch(COLUMNS, 1)

    def _swatch(self, color: str, in_palette: bool) -> QToolButton:
        button = QToolButton()
        button.setObjectName("swatch")
        button.setProperty("color", color)
        button.setFixedSize(SIZE, SIZE)
        button.setStyleSheet(swatch_style(color, dashed=not in_palette))
        if in_palette:
            button.setToolTip(f"{color} — колір проєкту (правий клік — прибрати)")
            button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            button.customContextMenuRequested.connect(
                lambda _pos, c=color: self.doc.remove_color(c)
            )
        else:
            button.setToolTip(f"{color} — є на сторінці (правий клік — у кольори проєкту)")
            button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            button.customContextMenuRequested.connect(lambda _pos, c=color: self.doc.add_color(c))
        button.clicked.connect(lambda _=False, c=color: self.on_pick(c))
        self.buttons[color] = button
        return button

    def _add_current(self) -> None:
        color = self.current()
        if color:
            self.doc.add_color(color)
