"""The open project: data, file, current page and the undo stack.

Every change goes through a ``QUndoCommand`` so it can be undone; views only
listen to the signals and never change the project directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from espui.assets.images import import_image
from espui.core import serializer
from espui.core.compat import can_bind
from espui.core.identifiers import identifier_problem, page_name_problem
from espui.core.models import (
    BoolParameter,
    Condition,
    Display,
    FloatParameter,
    ImageAsset,
    ImageSettings,
    IntParameter,
    Page,
    Parameter,
    ParamValue,
    Project,
    SeriesParameter,
    Widget,
    WidgetType,
)
from espui.core.params import unused_parameters, update_parameter
from espui.gui.widgets_catalog import new_widget

NEW_PAGE_NAME = "page"


def new_project() -> Project:
    return Project.model_validate({"pages": [{"name": "main"}]})


class Document(QObject):
    """Signals carry no data: views re-read what they need."""

    changed = Signal()
    """Anything in the project changed (pages, display, ...)."""
    current_page_changed = Signal(int)
    file_changed = Signal()
    """Path or saved/unsaved state changed."""
    selection_changed = Signal()
    """Another widget (or none) is selected on the current page."""

    def __init__(self, project: Project | None = None, path: Path | None = None) -> None:
        super().__init__()
        self.project = project or new_project()
        self.path = path
        self.current = 0
        self.selected: str | None = None
        """Id of the selected widget of the current page."""
        self.undo_stack = QUndoStack(self)
        self.undo_stack.indexChanged.connect(self._index_changed)
        self.undo_stack.cleanChanged.connect(self._clean_changed)

    def _index_changed(self, _index: int) -> None:
        if self.selected is not None and self.page.widget(self.selected) is None:
            self.selected = None  # e.g. an added widget was undone
            self.selection_changed.emit()
        self.changed.emit()

    def _clean_changed(self, _clean: bool) -> None:
        self.file_changed.emit()

    # ------------------------------------------------------------------ file
    def load(self, project: Project, path: Path | None = None) -> None:
        """Replace the whole project (new / open): undo history starts over."""
        self.project = project
        self.path = path
        self.current = 0
        self.selected = None
        self.undo_stack.clear()
        self.changed.emit()
        self.current_page_changed.emit(0)
        self.file_changed.emit()

    def open(self, path: str | Path) -> None:
        """Open a project file; a mock-up export (*.espui.json) is saved as a new .espui."""
        file = Path(path)
        self.load(
            serializer.load(file, check=False), file if file.name.endswith(".espui") else None
        )

    def save(self, path: str | Path | None = None) -> Path:
        target = Path(path) if path is not None else self.path
        if target is None:
            raise ValueError("no file name")
        # Drafts are saved as they are: problems are reported when generating.
        self.path = serializer.save(self.project, target, check=False)
        self.undo_stack.setClean()
        self.file_changed.emit()
        return self.path

    @property
    def dirty(self) -> bool:
        return not self.undo_stack.isClean()

    @property
    def title(self) -> str:
        return self.path.name if self.path else "Без назви.espui"

    # ------------------------------------------------------------------ pages
    @property
    def page(self) -> Page:
        return self.project.pages[self.current]

    def set_current(self, index: int) -> None:
        index = max(0, min(index, len(self.project.pages) - 1))
        if index != self.current:
            self.current = index
            self.selected = None
            self.current_page_changed.emit(index)
            self.selection_changed.emit()

    def free_page_name(self, base: str = NEW_PAGE_NAME) -> str:
        names = {p.name for p in self.project.pages}
        if base not in names and not page_name_problem(base):
            return base
        n = 2
        while f"{base}_{n}" in names or page_name_problem(f"{base}_{n}"):
            n += 1
        return f"{base}_{n}"

    def rename_problem(self, index: int, name: str) -> str | None:
        """Ukrainian reason why page ``index`` can't be called ``name``, or None."""
        problem = page_name_problem(name)
        if problem:
            return problem
        if any(p.name == name for i, p in enumerate(self.project.pages) if i != index):
            return f"сторінка «{name}» вже є"
        return None

    def add_page(self, copy_current: bool = False) -> None:
        if copy_current:
            page = self.page.model_copy(deep=True)
            page.name = self.free_page_name(f"{self.page.name}_copy")
        else:
            page = Page(name=self.free_page_name(), background=self.page.background)
        self.undo_stack.push(_AddPage(self, page, self.current + 1))

    def remove_page(self, index: int) -> bool:
        """Delete a page; the last one can't be deleted."""
        if len(self.project.pages) <= 1:
            return False
        self.undo_stack.push(_RemovePage(self, index))
        return True

    def rename_page(self, index: int, name: str) -> str | None:
        """Rename a page; returns the problem instead if the name isn't valid."""
        problem = self.rename_problem(index, name)
        if problem is None and name != self.project.pages[index].name:
            self.undo_stack.push(_RenamePage(self, index, name))
        return problem

    # ------------------------------------------------------------------ widgets
    @property
    def widget(self) -> Widget | None:
        """The selected widget of the current page."""
        return self.page.widget(self.selected) if self.selected else None

    def select(self, widget_id: str | None) -> None:
        if widget_id is not None and self.page.widget(widget_id) is None:
            widget_id = None
        if widget_id != self.selected:
            self.selected = widget_id
            self.selection_changed.emit()

    def index_of(self, widget_id: str) -> int:
        return next(i for i, w in enumerate(self.page.widgets) if w.id == widget_id)

    def add_widget(self, widget: Widget) -> None:
        """Add on top of the current page and select it."""
        self.undo_stack.push(_AddWidget(self, self.current, widget, len(self.page.widgets)))
        self.select(widget.id)

    def remove_widget(self, widget_id: str | None = None) -> bool:
        widget_id = widget_id or self.selected
        if widget_id is None or self.page.widget(widget_id) is None:
            return False
        self.undo_stack.push(_RemoveWidget(self, self.current, self.index_of(widget_id)))
        return True

    def change_widget(self, new: Widget, text: str = "Змінити елемент", merge: str = "") -> None:
        """Replace the selected (or same-id) widget; ``merge`` joins repeated steps (nudges)."""
        old_id = self.selected if self.selected and self.page.widget(self.selected) else new.id
        index = self.index_of(old_id)
        old = self.page.widgets[index]
        if old == new:
            return
        self.undo_stack.push(_ChangeWidget(self, self.current, index, old, new, text, merge))
        if new.id != old_id:
            self.select(new.id)

    def id_problem(self, widget_id: str, new_id: str) -> str | None:
        problem = identifier_problem(new_id)
        if problem:
            return problem
        if any(w.id == new_id and w.id != widget_id for w in self.page.widgets):
            return f"елемент «{new_id}» вже є"
        return None

    def move_layer(self, widget_id: str, to: int) -> bool:
        """Move to list index ``to`` (0 = lowest layer)."""
        widgets = self.page.widgets
        src = self.index_of(widget_id)
        to = max(0, min(len(widgets) - 1, to))
        if src == to:
            return False
        self.undo_stack.push(_MoveLayer(self, self.current, src, to))
        return True

    def raise_layer(self, widget_id: str | None = None, step: int = 1) -> bool:
        """``step`` > 0 brings it up (over others), < 0 sends it down."""
        widget_id = widget_id or self.selected
        if widget_id is None:
            return False
        return self.move_layer(widget_id, self.index_of(widget_id) + step)

    def apply_font_to_all(self, font: str) -> None:
        """The font of every text-bearing widget of the current page."""
        self.undo_stack.beginMacro("Шрифт для всіх елементів сторінки")
        for widget in list(self.page.widgets):
            if widget.font is not None and widget.font != font:
                self.undo_stack.push(
                    _ChangeWidget(self, self.current, self.index_of(widget.id), widget,
                                  widget.model_copy(update={"font": font}), "Шрифт", "")
                )  # fmt: skip
        self.undo_stack.endMacro()

    def apply_opacity_to_all(self, opacity: int) -> None:
        """The base opacity of every widget of the current page."""
        self.undo_stack.beginMacro("Непрозорість для всіх елементів сторінки")
        for widget in list(self.page.widgets):
            if widget.opacity != opacity:
                new = widget.model_copy(update={"opacity": opacity})
                index = self.index_of(widget.id)
                self.undo_stack.push(
                    _ChangeWidget(self, self.current, index, widget, new, "Непрозорість", "")
                )
        self.undo_stack.endMacro()

    def add_library_images(self, paths: list[str]) -> list[str]:
        """Add files to the project library (pictures for the board); returns their keys."""
        keys = []
        self.undo_stack.beginMacro("Додати картинки")
        for path in paths:
            key, asset = import_image(path, set(self.project.images))
            self.undo_stack.push(_SetImageAsset(self, key, asset))
            keys.append(key)
        self.undo_stack.endMacro()
        return keys

    def remove_image(self, key: str) -> None:
        """Remove a picture from the library (widgets showing it get a grey box)."""
        if key in self.project.images:
            self.undo_stack.push(_SetImageAsset(self, key, None))

    def add_image(self, path: str | Path) -> str:
        """Add a file to the project library and show it in the selected image widget."""
        key, asset = import_image(path, set(self.project.images))
        self.undo_stack.beginMacro(f"Додати картинку «{asset.name}»")
        self.undo_stack.push(_SetImageAsset(self, key, asset))
        widget = self.widget
        if widget is not None and widget.type == "image":
            settings = (widget.image or ImageSettings()).model_copy(update={"file": key})
            self.change_widget(
                widget.model_copy(update={"image": settings, "bind": None}), "Картинка"
            )
        self.undo_stack.endMacro()
        return key

    def set_animation_delay(self, key: str, delay_ms: int) -> None:
        asset = self.project.images[key]
        if asset.delay_ms != delay_ms:
            self.undo_stack.push(
                _SetImageAsset(self, key, asset.model_copy(update={"delay_ms": delay_ms}))
            )

    # ------------------------------------------------------------------ parameters
    def _replace_page(self, page: Page, text: str, merge: str = "") -> None:
        if page != self.page:
            self.undo_stack.push(_ReplacePage(self, self.current, page, text, merge))

    def parameter_problem(self, param: Parameter, old_name: str | None = None) -> str | None:
        """Why ``param`` can't be saved under its name (the edited one doesn't count)."""
        if any(p.name == param.name and p.name != old_name for p in self.page.parameters):
            return f"параметр «{param.name}» вже є"
        return None

    def add_parameter(self, param: Parameter) -> None:
        page = self.page.model_copy(deep=True)
        page.parameters.append(param)
        self._replace_page(page, f"Новий параметр «{param.name}»")

    def update_parameter(self, old_name: str, param: Parameter) -> list[str]:
        """Save an edited parameter; returns the summary of what else changed."""
        page, notes = update_parameter(self.page, old_name, param)
        self._replace_page(page, f"Змінити параметр «{old_name}»")
        return notes

    def remove_parameter(self, name: str) -> int:
        """Delete a parameter and every reference to it; returns removed rules."""
        page = self.page.model_copy(deep=True)
        removed = page.remove_parameter(name)
        self._replace_page(page, f"Видалити параметр «{name}»")
        return removed

    def set_test_value(self, name: str, value: ParamValue) -> None:
        """Preview value of a parameter; repeated changes (a slider) are one undo step."""
        page = self.page.model_copy(deep=True)
        page.test_values[name] = value
        self._replace_page(page, f"Тестове значення «{name}»", merge=f"test:{name}")

    def bind_parameter(self, widget_id: str, name: str) -> str:
        """A parameter dropped on a widget: bind it, or for a bool add "hide when false".

        Returns a message for the user.
        """
        widget = self.page.widget(widget_id)
        param = self.page.parameter(name)
        if widget is None or param is None:
            return ""
        if can_bind(widget.type, param):
            self.select(widget_id)
            self.change_widget(widget.model_copy(update={"bind": name}), f"Прив'язати «{name}»")
            return f"«{widget_id}» показує «{name}»."
        if isinstance(param, BoolParameter):
            rule = Condition.model_validate(
                {"if": [name, "==", False], "set": "visible", "to": False}
            )
            self.select(widget_id)
            self.change_widget(widget.model_copy(update={"rules": [*widget.rules, rule]}), "Умова")
            return f"«{widget_id}» ховається, коли «{name}» = false."
        return f"«{widget_id}» не може показати параметр типу {param.type}."

    def add_parameter_widget(self, name: str, x: int, y: int) -> Widget | None:
        """A parameter dropped on free space: a new widget that shows it."""
        param = self.page.parameter(name)
        if param is None:
            return None
        kind: WidgetType = (
            "chart" if isinstance(param, SeriesParameter)
            else "value" if isinstance(param, FloatParameter | IntParameter)
            else "text"
        )  # fmt: skip
        widget = new_widget(self.page, kind, x, y)
        fmt = {"float": "%.1f", "int": "%d"}.get(param.type, "%s")
        update: dict[str, Any] = {"bind": name}
        if kind != "chart":
            update["format"] = fmt
        widget = widget.model_copy(update=update)
        self.add_widget(widget)
        return widget

    # ------------------------------------------------------------------ display
    def set_display(self, display: Display) -> None:
        if display != self.project.display:
            self.undo_stack.push(_SetDisplay(self, display))

    def problems(self) -> list[str]:
        """For the status bar: widgets off the screen, unused parameters, images without a file."""
        out = [f"поза екраном: {name}" for name in self.widgets_outside()]
        for page in self.project.pages:
            out += [f"не використано: {page.name}/{n}" for n in unused_parameters(page)]
            for w in page.widgets:
                file = w.image.file if w.image else None
                if (
                    w.type == "image"
                    and not w.bind
                    and (not file or file not in self.project.images)
                ):
                    out.append(f"картинка без файлу: {page.name}/{w.id}")
        return out

    def widgets_outside(self) -> list[str]:
        """``page/widget`` ids that don't fit the screen of the current orientation."""
        width, height = self.project.display.size
        out = []
        for page in self.project.pages:
            for w in page.widgets:
                if w.x < 0 or w.y < 0 or w.x + w.w > width or w.y + w.h > height:
                    out.append(f"{page.name}/{w.id}")
        return out


# ---------------------------------------------------------------------- commands
class _AddPage(QUndoCommand):
    def __init__(self, doc: Document, page: Page, index: int) -> None:
        super().__init__(f"Додати сторінку «{page.name}»")
        self.doc, self.page, self.index, self.previous = doc, page, index, doc.current

    def redo(self) -> None:
        self.doc.project.pages.insert(self.index, self.page)
        self.doc.current = -1
        self.doc.set_current(self.index)

    def undo(self) -> None:
        del self.doc.project.pages[self.index]
        self.doc.current = -1
        self.doc.set_current(self.previous)


class _RemovePage(QUndoCommand):
    def __init__(self, doc: Document, index: int) -> None:
        super().__init__(f"Видалити сторінку «{doc.project.pages[index].name}»")
        self.doc, self.index, self.previous = doc, index, doc.current
        self.page = doc.project.pages[index]

    def redo(self) -> None:
        del self.doc.project.pages[self.index]
        self.doc.current = -1
        self.doc.set_current(min(self.index, len(self.doc.project.pages) - 1))

    def undo(self) -> None:
        self.doc.project.pages.insert(self.index, self.page)
        self.doc.current = -1
        self.doc.set_current(self.previous)


class _RenamePage(QUndoCommand):
    def __init__(self, doc: Document, index: int, name: str) -> None:
        old = doc.project.pages[index].name
        super().__init__(f"Перейменувати «{old}» на «{name}»")
        self.doc, self.index, self.old, self.new = doc, index, old, name

    def redo(self) -> None:
        self.doc.project.pages[self.index].name = self.new

    def undo(self) -> None:
        self.doc.project.pages[self.index].name = self.old


class _SetDisplay(QUndoCommand):
    def __init__(self, doc: Document, display: Display) -> None:
        super().__init__("Налаштування дисплея")
        self.doc, self.old, self.new = doc, doc.project.display, display

    def redo(self) -> None:
        self.doc.project.display = self.new

    def undo(self) -> None:
        self.doc.project.display = self.old


class _AddWidget(QUndoCommand):
    def __init__(self, doc: Document, page: int, widget: Widget, index: int) -> None:
        super().__init__(f"Додати «{widget.id}»")
        self.doc, self.page, self.widget, self.index = doc, page, widget, index

    def redo(self) -> None:
        self.doc.project.pages[self.page].widgets.insert(self.index, self.widget)

    def undo(self) -> None:
        del self.doc.project.pages[self.page].widgets[self.index]


class _RemoveWidget(QUndoCommand):
    def __init__(self, doc: Document, page: int, index: int) -> None:
        self.widget = doc.project.pages[page].widgets[index]
        super().__init__(f"Видалити «{self.widget.id}»")
        self.doc, self.page, self.index = doc, page, index

    def redo(self) -> None:
        del self.doc.project.pages[self.page].widgets[self.index]

    def undo(self) -> None:
        self.doc.project.pages[self.page].widgets.insert(self.index, self.widget)


class _ChangeWidget(QUndoCommand):
    MERGE_ID = 1101

    def __init__(
        self, doc: Document, page: int, index: int, old: Widget, new: Widget, text: str, merge: str
    ) -> None:
        super().__init__(f"{text} «{old.id}»")
        self.doc, self.page, self.index, self.old, self.new, self.merge = (
            doc, page, index, old, new, merge,
        )  # fmt: skip

    def id(self) -> int:
        return self.MERGE_ID if self.merge else -1

    def mergeWith(self, other: QUndoCommand) -> bool:
        if not isinstance(other, _ChangeWidget) or other.merge != self.merge:
            return False
        if (other.page, other.index, other.old.id) != (self.page, self.index, self.new.id):
            return False
        self.new = other.new
        return True

    def redo(self) -> None:
        self.doc.project.pages[self.page].widgets[self.index] = self.new

    def undo(self) -> None:
        self.doc.project.pages[self.page].widgets[self.index] = self.old


class _MoveLayer(QUndoCommand):
    def __init__(self, doc: Document, page: int, src: int, to: int) -> None:
        widget = doc.project.pages[page].widgets[src]
        super().__init__(f"Шар «{widget.id}»")
        self.doc, self.page, self.src, self.to = doc, page, src, to

    def redo(self) -> None:
        widgets = self.doc.project.pages[self.page].widgets
        widgets.insert(self.to, widgets.pop(self.src))

    def undo(self) -> None:
        widgets = self.doc.project.pages[self.page].widgets
        widgets.insert(self.src, widgets.pop(self.to))


class _SetImageAsset(QUndoCommand):
    """Add, replace or (``asset=None``) remove a picture of the library."""

    def __init__(self, doc: Document, key: str, asset: ImageAsset | None) -> None:
        super().__init__(f"Картинка «{asset.name if asset else key}»")
        self.doc, self.key, self.new = doc, key, asset
        self.old = doc.project.images.get(key)

    def redo(self) -> None:
        if self.new is None:
            del self.doc.project.images[self.key]
        else:
            self.doc.project.images[self.key] = self.new

    def undo(self) -> None:
        if self.old is None:
            del self.doc.project.images[self.key]
        else:
            self.doc.project.images[self.key] = self.old


class _ReplacePage(QUndoCommand):
    """A change of several things on one page at once (parameters and their references)."""

    MERGE_ID = 1201

    def __init__(self, doc: Document, index: int, page: Page, text: str, merge: str) -> None:
        super().__init__(text)
        self.doc, self.index, self.merge = doc, index, merge
        self.old, self.new = doc.project.pages[index], page

    def id(self) -> int:
        return self.MERGE_ID if self.merge else -1

    def mergeWith(self, other: QUndoCommand) -> bool:
        if not isinstance(other, _ReplacePage) or (other.merge, other.index) != (
            self.merge,
            self.index,
        ):
            return False
        self.new = other.new
        return True

    def redo(self) -> None:
        self.doc.project.pages[self.index] = self.new

    def undo(self) -> None:
        self.doc.project.pages[self.index] = self.old
