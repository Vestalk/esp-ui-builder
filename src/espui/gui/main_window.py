"""Main window: menus, toolbar, palette, work area, panels and status bar.

Stage 10 builds the frame (display, pages, work area, zoom); the panels are
filled in by stages 11-14 (editing, properties, parameters, sessions).
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QByteArray, QMimeData, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QGuiApplication, QKeySequence, QResizeEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDockWidget,
    QFileDialog,
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from espui import __version__
from espui.core.arrange import (
    ALIGN_TITLES,
    DISTRIBUTE_TITLES,
    Align,
    Distribute,
    align,
    distribute,
)
from espui.core.checks import check_project
from espui.core.clipboard import MIME as CLIPBOARD_MIME
from espui.core.clipboard import ClipboardError
from espui.core.issues import ProjectError
from espui.core.models import WIDGET_TYPES, EditorState
from espui.generators.micropython.generator import GenerationError, generate
from espui.generators.micropython.memory import estimate as estimate_memory
from espui.gui import theme, wheel_guard
from espui.gui.display_dialog import DisplayDialog, display_label
from espui.gui.document import Document, new_project
from espui.gui.generate_dialog import GenerateResultDialog
from espui.gui.layers import LayersPanel
from espui.gui.pages_bar import PagesBar
from espui.gui.parameters import ParametersPanel, TestValuesPanel
from espui.gui.properties import PropertiesPanel
from espui.gui.session import (
    AutoSaver,
    add_recent,
    generate_dir,
    recent_projects,
    remember_generate_dir,
)
from espui.gui.workspace import WIDGET_MIME, Workspace

WIDGET_TITLES = {
    "rect": "Прямокутник",
    "circle": "Коло",
    "line": "Лінія",
    "text": "Текст",
    "value": "Число",
    "bar": "Смуга прогресу",
    "arc": "Дуга",
    "image": "Картинка",
    "chart": "Графік",
}
FILE_FILTER = "Проєкт ESP UI Builder (*.espui *.espui.json)"
IMPORT_FILTER = "Експорт з макета (*.espui.json *.json)"


class Palette(QListWidget):
    """Widget types: click adds one in the centre, drag drops it where it lands."""

    add_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("palette")
        # A narrow palette shortens long titles ("Смуга прог…") instead of scrolling sideways.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        for kind in WIDGET_TYPES:
            item = QListWidgetItem(WIDGET_TITLES[kind])
            item.setData(Qt.ItemDataRole.UserRole, kind)
            item.setToolTip(WIDGET_TITLES[kind])
            item.setToolTip("Клік — у центр сторінки; перетягніть — у потрібне місце")
            self.addItem(item)
        self.itemClicked.connect(
            lambda item: self.add_requested.emit(item.data(Qt.ItemDataRole.UserRole))
        )

    def mimeData(self, items: Sequence[QListWidgetItem]) -> QMimeData:
        data = QMimeData()
        if items:
            data.setData(WIDGET_MIME, QByteArray(items[0].data(Qt.ItemDataRole.UserRole).encode()))
        return data

    def mimeTypes(self) -> list[str]:
        return [WIDGET_MIME]


class MainWindow(QMainWindow):
    def __init__(self, doc: Document | None = None, data_folder: Path | None = None) -> None:
        super().__init__()
        theme.apply()  # the look of docs/plan.html (light / dark as the system)
        wheel_guard.install()  # the wheel scrolls panels, never flips a closed drop-down
        self.doc = doc or Document()
        self.autosaver = AutoSaver(self.doc, data_folder, self._store_editor_state)
        self.resize(1280, 800)

        self.workspace = Workspace()
        self.pages_bar = PagesBar(self.doc)
        center = QWidget()
        layout = QVBoxLayout(center)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.pages_bar)
        layout.addWidget(self.workspace, 1)
        self.setCentralWidget(center)

        self._build_docks()
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_status()

        self.workspace.page_clicked.connect(self.doc.set_current)
        self.workspace.set_document(self.doc)
        self.workspace.zoom_changed.connect(self._zoom_changed)
        self._connect_document()
        self.autosaver.status.connect(self.status_saved.setText)
        self.refresh()

    # ------------------------------------------------------------------ layout
    def _build_docks(self) -> None:
        self.widget_palette = Palette()
        self.widget_palette.add_requested.connect(lambda kind: self.workspace.add_widget(kind))
        self.properties = PropertiesPanel(self.doc, self.workspace.restart_animation)
        self.properties.message.connect(lambda text: self.statusBar().showMessage(text, 8000))
        self.layers = LayersPanel(self.doc)
        self.parameters = ParametersPanel(self.doc)
        self.test_values = TestValuesPanel(self.doc)
        for source in (self.parameters, self.workspace):
            source.message.connect(lambda text: self.statusBar().showMessage(text, 8000))
        docks = (
            ("Елементи", self.widget_palette, Qt.DockWidgetArea.LeftDockWidgetArea),
            ("Властивості", self.properties, Qt.DockWidgetArea.RightDockWidgetArea),
            ("Параметри", self.parameters, Qt.DockWidgetArea.RightDockWidgetArea),
            ("Шари", self.layers, Qt.DockWidgetArea.BottomDockWidgetArea),
            ("Тестові значення", self.test_values, Qt.DockWidgetArea.BottomDockWidgetArea),
        )
        self.docks: dict[str, QDockWidget] = {}
        for title, widget, area in docks:
            dock = QDockWidget(title, self)
            dock.setObjectName(f"dock_{title}")
            content: QWidget = widget
            if widget is self.parameters:  # scrolls on a short window instead of squeezing
                scroll = QScrollArea()  # the properties above it
                scroll.setWidgetResizable(True)
                scroll.setFrameShape(QFrame.Shape.NoFrame)
                scroll.setWidget(widget)
                content = scroll
            dock.setWidget(content)
            self.addDockWidget(area, dock)
            self.docks[title] = dock
        self.tabifyDockWidget(self.docks["Шари"], self.docks["Тестові значення"])
        self.docks["Шари"].raise_()
        self._full_dock_tabs()
        self.tabifiedDockWidgetActivated.connect(self._dock_tab_activated)
        self.resizeDocks(
            [self.docks["Елементи"], self.docks["Властивості"]],
            [150, 360],
            Qt.Orientation.Horizontal,
        )
        self.resizeDocks([self.docks["Шари"]], [180], Qt.Orientation.Vertical)
        # Right column: the properties of the selection get most of the height.
        self.resizeDocks(
            [self.docks["Властивості"], self.docks["Параметри"]],
            [620, 260],
            Qt.Orientation.Vertical,
        )
        self.properties.setMinimumWidth(320)
        self._narrow = False

    def _action(
        self, text: str, slot: object, shortcut: QKeySequence | str | None = None
    ) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.triggered.connect(slot)
        return action

    def _build_actions(self) -> None:
        keys = QKeySequence.StandardKey
        self.act_new = self._action("Новий проєкт", self.new_project, QKeySequence(keys.New))
        self.act_open = self._action("Відкрити…", self.open_dialog, QKeySequence(keys.Open))
        self.act_save = self._action("Зберегти", self.save, QKeySequence(keys.Save))
        self.act_save_as = self._action("Зберегти як…", self.save_as, QKeySequence(keys.SaveAs))
        self.act_quit = self._action("Вийти", self.close, QKeySequence(keys.Quit))
        self.act_import = self._action("Імпорт з макета (.espui.json)…", self.import_dialog)
        self.act_undo = self.doc.undo_stack.createUndoAction(self, "Скасувати")
        self.act_undo.setShortcut(QKeySequence(keys.Undo))
        self.act_redo = self.doc.undo_stack.createRedoAction(self, "Повторити")
        self.act_redo.setShortcut(QKeySequence(keys.Redo))
        self.act_zoom_in = self._action(
            "Збільшити", self.workspace.zoom_in, QKeySequence(keys.ZoomIn)
        )
        self.act_zoom_out = self._action(
            "Зменшити", self.workspace.zoom_out, QKeySequence(keys.ZoomOut)
        )
        self.act_zoom_100 = self._action("Масштаб 100 %", self.workspace.zoom_reset, "Ctrl+0")
        self.act_fit = self._action("Вмістити все", self.workspace.fit_all, "Ctrl+9")
        self.act_grid = self._action("Сітка", self.toggle_grid, "Ctrl+'")
        self.act_grid.setCheckable(True)
        self.act_display = self._action("Дисплей…", self.edit_display)
        self.act_add_page = self._action(
            "Нова сторінка", lambda: self.doc.add_page(False), "Ctrl+Shift+N"
        )
        self.act_copy_page = self._action("Копія сторінки", lambda: self.doc.add_page(True))
        self.act_rename_page = self._action(
            "Перейменувати сторінку…", lambda: self.pages_bar.rename()
        )
        self.act_delete = self._action(
            "Видалити елемент", self._delete_selected, QKeySequence(QKeySequence.StandardKey.Delete)
        )
        self.act_delete.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        # On the canvas and in the layers only: in a text field Ctrl+C / V copy text.
        self.act_copy = self._action(
            "Копіювати елемент", self.copy_widget, QKeySequence(QKeySequence.StandardKey.Copy)
        )
        self.act_paste = self._action(
            "Вставити елемент", self.paste_widget, QKeySequence(QKeySequence.StandardKey.Paste)
        )
        self.act_duplicate = self._action("Дублювати елемент", self.duplicate_widget, "Ctrl+D")
        for act in (self.act_copy, self.act_paste, self.act_duplicate):
            act.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self.act_layer_up = self._action(
            "Шар вище", lambda: self.doc.raise_layer(step=1), "Ctrl+Up"
        )
        self.act_layer_down = self._action(
            "Шар нижче", lambda: self.doc.raise_layer(step=-1), "Ctrl+Down"
        )
        self.act_hide = self._action(
            "Сховати / показати в редакторі",
            lambda: self._toggle_flag("editor_hidden"),
            "Ctrl+Shift+H",
        )
        self.act_lock = self._action(
            "Заблокувати / розблокувати", lambda: self._toggle_flag("locked"), "Ctrl+Shift+L"
        )
        self.act_unhide_all = self._action(
            "Показати й розблокувати все на сторінці", self.unhide_all
        )
        self.act_align = {
            how: self._action(title, lambda _=False, h=how: self.align_selected(h))
            for how, title in ALIGN_TITLES.items()
        }
        self.act_distribute = {
            how: self._action(title, lambda _=False, h=how: self.distribute_selected(h))
            for how, title in DISTRIBUTE_TITLES.items()
        }
        self.act_generate = self._action("▶ Згенерувати…", self.generate_dialog, "Ctrl+G")
        self.act_about = self._action("Про програму", self.about)

    def _build_menus(self) -> None:
        bar = self.menuBar()
        file = bar.addMenu("Файл")
        for act in (self.act_new, self.act_open, self.act_save, self.act_save_as, self.act_import):
            file.addAction(act)
        self.recent_menu = file.addMenu("Останні проєкти")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        file.addSeparator()
        file.addAction(self.act_quit)
        edit = bar.addMenu("Правка")
        edit.addAction(self.act_undo)
        edit.addAction(self.act_redo)
        edit.addSeparator()
        for act in (self.act_copy, self.act_paste, self.act_duplicate):
            edit.addAction(act)
        edit.addSeparator()
        for act in (self.act_delete, self.act_layer_up, self.act_layer_down):
            edit.addAction(act)
        edit.addSeparator()
        for act in (self.act_hide, self.act_lock, self.act_unhide_all):
            edit.addAction(act)
        for target in (self.workspace, self.layers):  # their keyboard shortcuts
            target.addActions([self.act_copy, self.act_paste, self.act_duplicate])
        arrange = bar.addMenu("Розташування")
        aligns = list(self.act_align.values())  # left, centre, right; top, middle, bottom
        for act in aligns[:3]:
            arrange.addAction(act)
        arrange.addSeparator()
        for act in aligns[3:]:
            arrange.addAction(act)
        arrange.addSeparator()
        for act in self.act_distribute.values():
            arrange.addAction(act)
        self.doc.selection_changed.connect(self._arrange_enabled)
        self._arrange_enabled()
        view = bar.addMenu("Вигляд")
        for act in (
            self.act_zoom_in,
            self.act_zoom_out,
            self.act_zoom_100,
            self.act_fit,
            self.act_grid,
        ):
            view.addAction(act)
        view.addSeparator()
        for dock in self.docks.values():
            view.addAction(dock.toggleViewAction())
        display = bar.addMenu("Дисплей")
        display.addAction(self.act_display)
        pages = bar.addMenu("Сторінки")
        for act in (self.act_add_page, self.act_copy_page, self.act_rename_page):
            pages.addAction(act)
        params = bar.addMenu("Параметри")
        params.addAction(
            self._action("Новий параметр…", self.parameters.add_dialog, "Ctrl+Shift+P")
        )
        bar.addMenu("Генерація").addAction(self.act_generate)
        bar.addMenu("Довідка").addAction(self.act_about)

    def _build_toolbar(self) -> None:
        tools = self.addToolBar("Інструменти")
        tools.setObjectName("toolbar")
        tools.setMovable(False)
        self.display_button = QToolButton()
        self.display_button.setObjectName("display_button")
        self.display_button.clicked.connect(self.edit_display)
        self.display_button.setToolTip("Налаштування дисплея")
        tools.addWidget(self.display_button)
        self.tools = tools
        self.target_label = QLabel("  Ціль: MicroPython · MicroPico  ")
        self.target_label.setObjectName("target")
        self.target_action = tools.addWidget(self.target_label)
        tools.addSeparator()
        # Short buttons; the menu entries name the step ("Скасувати Додати сторінку…").
        stack = self.doc.undo_stack
        self.tool_undo = self._action("↶ Скасувати", stack.undo)
        self.tool_redo = self._action("↷ Повторити", stack.redo)
        stack.canUndoChanged.connect(self.tool_undo.setEnabled)
        stack.canRedoChanged.connect(self.tool_redo.setEnabled)
        stack.undoTextChanged.connect(self._undo_text)
        stack.redoTextChanged.connect(self._redo_text)
        self.tool_undo.setEnabled(False)
        self.tool_redo.setEnabled(False)
        tools.addAction(self.tool_undo)
        tools.addAction(self.tool_redo)
        tools.addSeparator()
        tools.addAction(self.act_grid)
        tools.addAction(self.act_zoom_out)
        self.zoom_button = QToolButton()
        self.zoom_button.setObjectName("zoom_button")
        self.zoom_button.setToolTip("Клік — 100 %")
        self.zoom_button.clicked.connect(self.workspace.zoom_reset)
        tools.addWidget(self.zoom_button)
        tools.addAction(self.act_zoom_in)
        tools.addAction(self.act_fit)
        tools.addSeparator()
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tools.addWidget(spacer)  # "Згенерувати" on the right, as in the mock-up
        tools.addAction(self.act_generate)
        generate_button = tools.widgetForAction(self.act_generate)
        if generate_button is not None:
            generate_button.setObjectName("generate")
        self.compact_level = 0

    # ------------------------------------------------------------------ adaptivity
    # Toolbar texts per compact level (0 = full); menus keep the full names (iconText only).
    COMPACT_LEVELS = 5

    def _compact(self, level: int) -> None:
        """Make the toolbar shorter step by step; "▶ Згенерувати" always stays visible."""
        self.compact_level = level
        self.target_action.setVisible(level < 1)
        label = display_label(self.doc.project.display)
        self.display_button.setText(f"Дисплей: {label}" if level < 2 else "Дисплей…")
        self.display_button.setToolTip(f"Налаштування дисплея: {label}")
        short = level >= 3
        for action, full, brief in (
            (self.act_zoom_out, "Зменшити", "−"),
            (self.act_zoom_in, "Збільшити", "+"),
            (self.act_fit, "Вмістити все", "Вмістити"),
        ):
            action.setIconText(brief if short else full)
            action.setToolTip(full)
        tiny = level >= 4
        self.tool_undo.setIconText("↶" if tiny else "↶ Скасувати")
        self.tool_redo.setIconText("↷" if tiny else "↷ Повторити")
        self.act_generate.setIconText("▶ Згенерувати" if level < 5 else "▶")

    def _fit_toolbar(self) -> None:
        """The least compact level whose toolbar fits the window width."""
        available = self.width()
        for level in range(self.COMPACT_LEVELS + 1):
            self._compact(level)
            if self.tools.sizeHint().width() <= available:
                return

    def _full_dock_tabs(self) -> None:
        """Tabs of panels docked together show their whole titles (Qt elides by default)."""
        for bar in self.findChildren(QTabBar):
            if bar.parent() is self and bar.elideMode() != Qt.TextElideMode.ElideNone:
                bar.setElideMode(Qt.TextElideMode.ElideNone)
                bar.setExpanding(False)

    def _dock_tab_activated(self, _dock: QDockWidget) -> None:
        self._full_dock_tabs()

    NARROW_WINDOW = 1100
    """Below this width the element palette gets narrower (the canvas needs the room)."""

    def _fit_docks(self) -> None:
        """Narrow the palette once when the window becomes narrow (and back), not on every
        resize: a width the user dragged stays as it is."""
        narrow = self.width() < self.NARROW_WINDOW
        if narrow != self._narrow:
            self._narrow = narrow
            self.resizeDocks(
                [self.docks["Елементи"]], [140 if narrow else 150], Qt.Orientation.Horizontal
            )
        # A shorter window takes the height from the right column without priorities: the
        # properties of the selection must not end up as a thin strip under "Параметри".
        props, params = self.docks["Властивості"], self.docks["Параметри"]
        if props.isVisible() and params.isVisible() and not props.isFloating():
            total = props.height() + params.height()
            if total > 0 and props.height() < 0.45 * total:
                self.resizeDocks(
                    [props, params], [round(total * 0.65), round(total * 0.35)],
                    Qt.Orientation.Vertical,
                )  # fmt: skip

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit_docks()
        self._fit_toolbar()
        self._full_dock_tabs()  # docks can be re-tabbed by the user: new tab bars

    # Bound methods, not lambdas: Qt disconnects them when the window is gone.
    def _undo_text(self, text: str) -> None:
        self.tool_undo.setToolTip(f"Скасувати: {text}")

    def _redo_text(self, text: str) -> None:
        self.tool_redo.setToolTip(f"Повторити: {text}")

    def update_memory(self) -> None:
        """Flash (code + fonts + pictures) and RAM (largest buffers) of the generated files."""
        try:
            memory = estimate_memory(self.doc.project)
        except (GenerationError, ProjectError, KeyError, ValueError) as error:
            self.status_memory.setText("Пам'ять: —")
            self.status_memory.setToolTip(str(error))
            return
        self.status_memory.setText(memory.summary())
        self.status_memory.setToolTip(
            "Флеш — файли для плати. RAM — буфер області малювання (×2 з прозорістю), "
            "гліфи шрифтів і рядок найширшої картинки; інтерпретатор і модулі — окремо."
        )

    def _build_status(self) -> None:
        self.status_display = QLabel()
        self.status_memory = QLabel()
        self.status_memory.setObjectName("status_memory")
        self.memory_timer = QTimer(self)
        self.memory_timer.setSingleShot(True)
        self.memory_timer.setInterval(600)
        self.memory_timer.timeout.connect(self.update_memory)
        self.status_warnings = QLabel()
        self.status_saved = QLabel()
        for label in (
            self.status_display,
            self.status_memory,
            self.status_warnings,
            self.status_saved,
        ):
            self.statusBar().addPermanentWidget(label)

    # ------------------------------------------------------------------ document
    def _connect_document(self) -> None:
        self.doc.changed.connect(self.refresh)
        self.doc.file_changed.connect(self._update_title)

    def refresh(self) -> None:
        project = self.doc.project
        label = display_label(project.display)
        self._fit_toolbar()  # the display label length changes the toolbar width
        width, height = project.display.size
        self.status_display.setText(f"{label} · {width}×{height}")
        self.memory_timer.start()  # the estimate follows a moment later
        problems = self.doc.problems()
        if problems:
            self.status_warnings.setText(f"⚠ {len(problems)}")
            self.status_warnings.setToolTip("\n".join(problems))
        else:
            self.status_warnings.setText("")
            self.status_warnings.setToolTip("")
        self._update_title()

    def _update_title(self) -> None:
        mark = " •" if self.doc.dirty else ""
        self.setWindowTitle(f"{self.doc.title}{mark} — ESP UI Builder")
        self.status_saved.setText("Є незбережені зміни" if self.doc.dirty else "Збережено")

    def _zoom_changed(self, zoom: float) -> None:
        self.zoom_button.setText(f"{round(zoom * 100)} %")

    # ------------------------------------------------------------------ actions
    def copy_widget(self) -> bool:
        """The selected widget (with its parameters) to the clipboard."""
        text = self.doc.copy_widget()
        if text is None:
            self.statusBar().showMessage("Спершу виберіть елемент", 4000)
            return False
        mime = QMimeData()
        mime.setData(CLIPBOARD_MIME, QByteArray(text.encode("utf-8")))
        mime.setText(text)
        QGuiApplication.clipboard().setMimeData(mime)
        ids = self.doc.selected_ids
        what = f"«{ids[0]}»" if len(ids) == 1 else f"елементів: {len(ids)}"
        self.statusBar().showMessage(f"Скопійовано {what}", 4000)
        return True

    def paste_widget(self) -> bool:
        """A copied widget onto the current page (also from another page or window)."""
        mime = QGuiApplication.clipboard().mimeData()
        if mime.hasFormat(CLIPBOARD_MIME):
            text = bytes(mime.data(CLIPBOARD_MIME).data()).decode("utf-8")
        else:
            text = mime.text()
        return self._paste_text(text)

    def duplicate_widget(self) -> bool:
        text = self.doc.copy_widget()
        if text is None:
            self.statusBar().showMessage("Спершу виберіть елемент", 4000)
            return False
        return self._paste_text(text)

    def _paste_text(self, text: str) -> bool:
        try:
            notes = self.doc.paste_widget(text)
        except ClipboardError as error:
            self.statusBar().showMessage(str(error), 5000)
            return False
        ids = self.doc.selected_ids
        what = f"«{ids[0]}»" if len(ids) == 1 else f"елементів: {len(ids)}"
        message = f"Вставлено {what}" + ("; " + "; ".join(notes) if notes else "")
        self.statusBar().showMessage(message, 8000)
        return True

    def _toggle_flag(self, field: str) -> None:
        """👁 / 🔒 for the selection (as the buttons in "Шари")."""
        if not self.doc.toggle_flag(field):
            self.statusBar().showMessage("Спершу виберіть елемент (на полотні або в «Шарах»)", 4000)

    def unhide_all(self) -> bool:
        """Every widget of the page shown and unlocked again (one undo step)."""
        if not self.doc.unhide_all():
            self.statusBar().showMessage("На сторінці немає схованих чи заблокованих", 4000)
            return False
        return True

    def _arrange_enabled(self) -> None:
        """Align: one widget (to the screen) or more; distribute: three or more."""
        count = len(self.doc.selected_ids)
        for act in self.act_align.values():
            act.setEnabled(count >= 1)
            act.setToolTip("" if count > 1 else "Один елемент вирівнюється відносно екрана")
        for act in self.act_distribute.values():
            act.setEnabled(count >= 3)

    def align_selected(self, how: Align) -> bool:
        ids = self.doc.selected_ids
        widgets = [w for w in self.doc.page.widgets if w.id in ids]
        moves = align(widgets, how, self.doc.project.display.size)
        target = "екрана" if len(widgets) == 1 else "виділення"
        if not self.doc.move_each(moves, ALIGN_TITLES[how]):
            self.statusBar().showMessage(f"Уже вирівняно відносно {target}", 4000)
            return False
        return True

    def distribute_selected(self, how: Distribute) -> bool:
        ids = self.doc.selected_ids
        if len(ids) < 3:
            self.statusBar().showMessage("Розподілити: виберіть щонайменше три елементи", 4000)
            return False
        widgets = [w for w in self.doc.page.widgets if w.id in ids]
        if not self.doc.move_each(distribute(widgets, how), DISTRIBUTE_TITLES[how]):
            self.statusBar().showMessage("Проміжки вже однакові", 4000)
            return False
        return True

    def _delete_selected(self) -> None:
        ids = self.doc.selected_ids
        if len(ids) > 1:
            self.doc.remove_widgets(ids)
        else:
            self.doc.remove_widget()

    def toggle_grid(self) -> None:
        self.workspace.grid = self.act_grid.isChecked()
        self.workspace.viewport().update()

    def edit_display(self) -> None:
        dialog = DisplayDialog(self.doc.project.display, self)
        if dialog.exec():
            self.doc.set_display(dialog.display())
            outside = self.doc.widgets_outside()
            if outside:
                QMessageBox.warning(
                    self,
                    "Дисплей",
                    "Після зміни орієнтації за межами екрана:\n" + "\n".join(outside),
                )

    def confirm_discard(self) -> bool:
        if not self.doc.dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Незбережені зміни",
            f"Зберегти зміни в «{self.doc.title}»?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return answer == QMessageBox.StandardButton.Discard

    def new_project(self) -> None:
        if self.confirm_discard():
            self.autosaver.discard_recovery()
            self.doc.load(new_project())

    def open_dialog(self) -> None:
        if not self.confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Відкрити проєкт", str(self._last_dir()), FILE_FILTER
        )
        if path:
            self.open_file(path)

    def import_dialog(self) -> None:
        if not self.confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Імпорт з макета", str(self._last_dir()), IMPORT_FILTER
        )
        if path:
            self.open_file(path)

    def open_file(self, path: str | Path) -> bool:
        """Open a project (a mock-up export becomes a new, unsaved project)."""
        try:
            self.doc.open(path)
        except ProjectError as error:
            QMessageBox.critical(self, "Не вдалося відкрити", str(error))
            return False
        QSettings().setValue("last_dir", str(Path(path).parent))
        if self.doc.path is not None:
            add_recent(self.doc.path)
        self._restore_editor_state()
        return True

    def _fill_recent(self) -> None:
        self.recent_menu.clear()
        paths = recent_projects()
        if not paths:
            self.recent_menu.addAction("— немає —").setEnabled(False)
        for path in paths:
            action = self.recent_menu.addAction(path.name)
            action.triggered.connect(lambda _=False, p=path: self.open_recent(p))

    def open_recent(self, path: Path) -> bool:
        return self.confirm_discard() and self.open_file(path)

    def _store_editor_state(self) -> None:
        """Zoom and page go into the project file (not an undo step)."""
        zoom = round(min(max(self.workspace.zoom, 0.5), 4.0), 3)
        self.doc.project.editor = EditorState(zoom=zoom, page=self.doc.current)

    def _restore_editor_state(self) -> None:
        state = self.doc.project.editor
        self.doc.set_current(state.page)
        self.workspace.set_zoom(state.zoom)
        self.workspace.set_current(self.doc.current)

    def save(self) -> bool:
        """Ctrl/⌘+S: save at once (asks for a file the first time)."""
        if self.doc.path is None:
            return self.save_as()
        return self.autosaver.save_now()

    def save_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(
            self, "Зберегти проєкт", str(self._last_dir() / self.doc.title), FILE_FILTER
        )
        return bool(path) and self._save_to(Path(path))

    def _save_to(self, path: Path) -> bool:
        self._store_editor_state()
        try:
            saved = self.doc.save(path)
        except (OSError, ProjectError) as error:
            QMessageBox.critical(self, "Не вдалося зберегти", str(error))
            return False
        self.autosaver.discard_recovery()
        add_recent(saved)
        self.status_saved.setText(f"Збережено о {time.strftime('%H:%M')}")
        return True

    def generate_dialog(self) -> None:
        start = generate_dir(self.doc.path) or self._last_dir()
        folder = QFileDialog.getExistingDirectory(
            self, f"Де створити папку «{self.output_name()}»", str(start)
        )
        if folder and self.confirm_generate(Path(folder)):
            self.generate_to(Path(folder))

    def confirm_generate(self, parent: Path) -> bool:
        """ "Точно записати сюди?" — with the exact folder and whether files get replaced."""
        target = parent / self.output_name()
        existing = target.is_dir() and any(target.iterdir())
        text = (
            f"Файли сторінки буде записано в папку:\n{target}\n\n"
            + (
                "Ця папка вже існує: згенеровані раніше файли буде замінено новими, "
                "старі файли попередньої генерації — видалено. Інші ваші файли в ній лишаться."
                if existing
                else "Папку буде створено."
            )
            + "\n\nПродовжити?"
        )
        answer = QMessageBox.question(
            self,
            "Згенерувати",
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel if existing else QMessageBox.StandardButton.Yes,
        )
        return answer == QMessageBox.StandardButton.Yes

    def output_name(self) -> str:
        """Name of the folder the files go into: the page, or the project for several pages."""
        pages = self.doc.project.pages
        if len(pages) == 1 or self.doc.path is None:
            return pages[0].name
        return self.doc.path.stem

    def generate_to(self, parent: Path) -> bool:
        """Check the project, write the files into ``parent/<name>``, show what was written."""
        folder = parent / self.output_name()
        problems = check_project(self.doc.project)
        if problems:
            listed = "\n".join(f"• {p}" for p in problems[:12])
            more = f"\n… ще {len(problems) - 12}" if len(problems) > 12 else ""
            QMessageBox.warning(self, "Генерація", f"Спершу виправте проєкт:\n{listed}{more}")
            return False
        try:
            result = generate(self.doc.project, source=self.doc.title)
            written = result.write(folder)
        except (OSError, ProjectError, GenerationError) as error:
            QMessageBox.critical(self, "Генерація", str(error))
            return False
        remember_generate_dir(self.doc.path, parent)
        self.statusBar().showMessage(f"Згенеровано в {folder}", 8000)
        self.last_result = GenerateResultDialog(
            folder, written, result.notes, result.warnings, self
        )
        self.last_result.exec()
        return True

    def about(self) -> None:
        QMessageBox.about(
            self,
            "ESP UI Builder",
            f"ESP UI Builder {__version__}\nКонструктор інтерфейсу дисплея ESP32 (MicroPython).",
        )

    def _last_dir(self) -> Path:
        value = QSettings().value("last_dir", "")
        return Path(str(value)) if value else Path.home()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Nothing is lost: pending changes are written (a new project to the recovery file)."""
        if self.doc.dirty:
            self.autosaver.save_now()
        event.accept()
