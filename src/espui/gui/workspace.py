"""The work area: every page side by side, the active one outlined and editable.

Pages are drawn by :mod:`espui.preview` (the same pixels as the display) and
scaled without smoothing, so 400 % shows the real pixels of the panel.

Editing (active page only): click selects the top-most widget under the
cursor, dragging moves it on a 4 px grid (Alt: free), the 8 handles resize it,
arrows nudge it (Shift: 10 px), Delete removes it, widgets dropped from the
palette land where they are dropped. A drag is previewed live and becomes one
undo step when the mouse is released. Geometry is computed in page pixels,
so it works the same at 50 % and at 400 %.
"""

from __future__ import annotations

import math
import time
from array import array
from typing import cast

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QHideEvent,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QShowEvent,
    QTransform,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QRubberBand,
    QStyleOptionGraphicsItem,
    QWidget,
)

from espui.core.evaluate import ParameterValues, effective
from espui.core.models import Page, PivotPoint, Project, Widget, WidgetType
from espui.core.touch import TapZone, tap_at, tap_box, tap_zones
from espui.gui import theme
from espui.gui.document import Document
from espui.gui.parameters import PARAM_MIME
from espui.gui.theme import SCREEN_OUTLINE
from espui.gui.widgets_catalog import MIN_SIZE, new_widget, shift_widget
from espui.preview.raster import Canvas, render_page

ZOOM_MIN = 0.5
ZOOM_MAX = 4.0
ZOOM_STEP = 1.25
PAGE_GAP = 40
LABEL_HEIGHT = 22
SCENE_MARGIN = 2000
GHOST_COLOR = QColor("#efa627")
"""Yellow "мін" / "макс" frames of position mappings (as in the mock-up)."""
DOT_STEP = 12
"""Dot grid of the canvas background, screen px (the mock-up's radial-gradient)."""
HANDLE_PX = 7
"""Selection handles keep this on-screen size at any zoom."""
GRID = 4
"""Moving and resizing snap to this grid (page pixels); Alt turns it off."""
GRAB_PX = 4
"""Thin widgets (lines) can be grabbed this many screen pixels around them."""
THIN = 6
"""Widgets thinner than this (page px) get the extra grab zone."""
WIDGET_MIME = "application/x-espui-widget"
"""Drag from the palette: the widget type as text."""
HANDLES = ("nw", "n", "ne", "e", "se", "s", "sw", "w")


_ARGB: array[int] | None = None


def _argb_table() -> array[int]:
    """Wire-order RGB565 value -> 0xAARRGGBB (low bits replicated: white stays white)."""
    global _ARGB
    if _ARGB is None:
        table = array("I", bytes(4 * 65536))
        for wire in range(65536):
            v = ((wire & 0xFF) << 8) | (wire >> 8)
            r5, g6, b5 = v >> 11, (v >> 5) & 63, v & 31
            r, g, b = r5 << 3 | r5 >> 2, g6 << 2 | g6 >> 4, b5 << 3 | b5 >> 2
            table[wire] = 0xFF000000 | r << 16 | g << 8 | b
        _ARGB = table
    return _ARGB


def canvas_to_image(canvas: Canvas) -> QImage:
    """Wire-order RGB565 pixels -> QImage (RGB32)."""
    table = _argb_table()
    data = array("I", [table[v] for v in canvas.pixels]).tobytes()
    image = QImage(data, canvas.width, canvas.height, 4 * canvas.width, QImage.Format.Format_RGB32)
    return image.copy()  # own the pixels: ``data`` goes away


def pickable(widget: Widget) -> bool:
    """The canvas can pick / move it: not 🔒 locked and not 👁 hidden in the editor."""
    return not (widget.locked or widget.editor_hidden)


def snap(value: float, grid: int = GRID) -> int:
    """Nearest grid line (halves go up, as everywhere in the project)."""
    return math.floor(value / grid + 0.5) * grid


def resize_box(
    box: tuple[int, int, int, int], role: str, dx: float, dy: float, line: bool, free: bool
) -> tuple[int, int, int, int]:
    """New (x, y, w, h) after dragging handle ``role`` by (dx, dy) page pixels."""
    x0, y0, w, h = box
    x1, y1 = x0 + w, y0 + h
    s = (lambda v: round(v)) if free else snap
    if "w" in role:
        x0 = min(s(x0 + dx), x1 - MIN_SIZE)
    if "e" in role:
        x1 = max(s(x1 + dx), x0 + MIN_SIZE)
    min_h = 0 if line else MIN_SIZE
    if "n" in role:
        y0 = min(s(y0 + dy), y1 - min_h)
    if "s" in role:
        y1 = max(s(y1 + dy), y0 + min_h)
    return x0, y0, x1 - x0, y1 - y0


class Handle(QGraphicsItem):
    """A square marker with a constant screen size (ignores the view's zoom)."""

    def __init__(self, parent: QGraphicsItem, role: str = "") -> None:
        super().__init__(parent)
        self.role = role
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        if role:
            cursors = {
                "n": Qt.CursorShape.SizeVerCursor,
                "s": Qt.CursorShape.SizeVerCursor,
                "e": Qt.CursorShape.SizeHorCursor,
                "w": Qt.CursorShape.SizeHorCursor,
                "nw": Qt.CursorShape.SizeFDiagCursor,
                "se": Qt.CursorShape.SizeFDiagCursor,
                "ne": Qt.CursorShape.SizeBDiagCursor,
                "sw": Qt.CursorShape.SizeBDiagCursor,
            }
            self.setCursor(cursors[role])

    def boundingRect(self) -> QRectF:
        half = HANDLE_PX / 2
        return QRectF(-half, -half, HANDLE_PX, HANDLE_PX)

    def paint(
        self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None
    ) -> None:
        painter.setPen(QPen(QColor("#1b1b1b"), 1))
        painter.setBrush(
            QBrush(theme.current().color("blue") if not self.role else QColor("#ffffff"))
        )
        painter.drawRect(self.boundingRect())


class SelectionBox(QGraphicsItem):
    """Dashed outline of the selected widget + 8 resize handles."""

    def __init__(self, parent: QGraphicsItem) -> None:
        super().__init__(parent)
        self.box = QRectF()
        self.handles = {role: Handle(self, role) for role in HANDLES}
        self.setZValue(10)

    def set_box(
        self,
        box: tuple[int, int, int, int] | None,
        angle: float = 0.0,
        pivot: tuple[float, float] = (0.0, 0.0),
    ) -> None:
        """Outline ``box`` turned by ``angle`` around ``pivot`` (page pixels), as drawn."""
        self.prepareGeometryChange()
        if box is None:
            self.setVisible(False)
            return
        px, py = pivot
        self.setTransform(QTransform().translate(px, py).rotate(angle).translate(-px, -py))
        x, y, w, h = box
        self.box = QRectF(x, y, w, h)
        cx, cy = x + w / 2, y + h / 2
        points = {
            "nw": (x, y),
            "n": (cx, y),
            "ne": (x + w, y),
            "e": (x + w, cy),
            "se": (x + w, y + h),
            "s": (cx, y + h),
            "sw": (x, y + h),
            "w": (x, cy),
        }
        for role, handle in self.handles.items():
            handle.setPos(*points[role])
        self.setVisible(True)

    def boundingRect(self) -> QRectF:
        return self.box.adjusted(-1, -1, 1, 1)

    def paint(
        self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None
    ) -> None:
        pen = QPen(QColor("#ffffff"), 1, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.box)


class PivotHandle(QGraphicsItem):
    """Red cross at the rotation point; it can be dragged (constant screen size)."""

    SIZE = 9

    def __init__(self, parent: QGraphicsItem) -> None:
        super().__init__(parent)
        self.role = "pivot"
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setZValue(12)

    def boundingRect(self) -> QRectF:
        half = self.SIZE / 2 + 1
        return QRectF(-half, -half, 2 * half, 2 * half)

    def paint(
        self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None
    ) -> None:
        half = self.SIZE / 2
        painter.setPen(QPen(QColor("#ff3030"), 2))
        painter.drawLine(QPointF(-half, 0), QPointF(half, 0))
        painter.drawLine(QPointF(0, -half), QPointF(0, half))


class Ghosts(QGraphicsItem):
    """Yellow dashed "мін" / "макс" frames of x/y mappings of the selected widget."""

    def __init__(self, parent: QGraphicsItem) -> None:
        super().__init__(parent)
        self.frames: list[tuple[QRectF, str]] = []
        self.setZValue(9)

    def set_frames(self, frames: list[tuple[QRectF, str]]) -> None:
        self.prepareGeometryChange()
        self.frames = frames
        self.setVisible(bool(frames))

    def boundingRect(self) -> QRectF:
        rect = QRectF()
        for frame, _ in self.frames:
            rect = rect.united(frame.adjusted(-2, -14, 2, 2))
        return rect

    def paint(
        self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None
    ) -> None:
        pen = QPen(GHOST_COLOR, 1, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        font = QFont()
        font.setPixelSize(9)
        painter.setFont(font)
        for frame, label in self.frames:
            painter.drawRect(frame)
            painter.drawText(QPointF(frame.x() + 2, frame.y() - 3), label)


class PageItem(QGraphicsItem):
    """One page: its preview, name and outline."""

    def __init__(self, index: int, page: Page, project: Project) -> None:
        super().__init__()
        self.index = index
        self.name = page.name
        self.size = project.display.size
        self.round = project.display.profile.shape == "round"
        """A round panel: only the inscribed circle is visible on the board."""
        self.fingerprint = ""
        self.image = QImage()
        self.active = False
        self.handles = [Handle(self) for _ in range(4)]
        w, h = self.size
        for handle, (x, y) in zip(self.handles, ((0, 0), (w, 0), (0, h), (w, h)), strict=True):
            handle.setPos(x, y)
        self.selection = SelectionBox(self)
        self.selection.setVisible(False)
        self.pivot = PivotHandle(self)
        self.pivot.setVisible(False)
        self.ghosts = Ghosts(self)
        self.ghosts.setVisible(False)
        self.group_boxes: list[QRectF] = []
        """Boxes of the other selected widgets (a multi-selection): dashed outlines."""
        self.hidden: list[QRectF] = []
        """Boxes of widgets hidden by conditions (outlined on the active page only)."""
        self.group_frame: QRectF | None = None
        """Around a selected group (all its widgets), drawn while the page is active."""
        self.taps: list[TapZone] = []
        """Where widgets with "При натиску" catch taps (as on the board)."""
        self.show_taps = False
        self.flash: tuple[QRectF, bool] | None = None
        """The zone a simulated tap just reached (or the point, if it reached none)."""
        self.set_page(page, project)
        self.set_active(False)

    def set_page(self, page: Page, project: Project, frames: dict[str, int] | None = None) -> None:
        """Re-render if the page (or an animation frame) changed."""
        fingerprint = (
            f"{page.model_dump_json()}|{sorted((frames or {}).items())}|{len(project.images)}"
        )
        if fingerprint == self.fingerprint:
            return
        self.fingerprint = fingerprint
        self.name = page.name
        self.taps = tap_zones(page)  # 👁-hidden ones too: the board has them
        shown = [w for w in page.widgets if not w.editor_hidden]  # 👁: not drawn in the editor
        if len(shown) != len(page.widgets):
            page = page.model_copy(update={"widgets": shown})
        canvas = render_page(page, self.size, images=project.images, frames=frames)
        self.image = canvas_to_image(canvas)
        values = ParameterValues.for_page(page)
        self.hidden = []
        for w in page.widgets:
            e = effective(w, values)
            if not e.visible:
                self.hidden.append(QRectF(e.x, e.y, max(e.w, 2), max(e.h, 2)))
        self.update()

    def set_active(self, active: bool) -> None:
        self.active = active
        for handle in self.handles:
            handle.setVisible(active)
        if not active:
            self.selection.setVisible(False)
            self.pivot.setVisible(False)
            self.ghosts.setVisible(False)
        self.update()

    def boundingRect(self) -> QRectF:
        w, h = self.size
        return QRectF(-2, -LABEL_HEIGHT, w + 4, h + LABEL_HEIGHT + 2)

    def paint(
        self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None
    ) -> None:
        w, h = self.size
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.drawImage(QRectF(0, 0, w, h), self.image)
        if self.active and self.group_boxes:  # the other widgets of a multi-selection
            group_pen = QPen(theme.current().color("blue"), 1, Qt.PenStyle.DashLine)
            group_pen.setCosmetic(True)
            painter.setPen(group_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for rect in self.group_boxes:
                painter.drawRect(rect)
        if self.active and self.group_frame is not None:
            frame_pen = QPen(theme.current().color("blue"), 1, Qt.PenStyle.DashDotLine)
            frame_pen.setCosmetic(True)
            painter.setPen(frame_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.group_frame.adjusted(-3, -3, 3, 3))
        if self.active and self.hidden:  # hidden as on the board, but still findable
            hidden_pen = QPen(QColor(143, 163, 173, 150), 1, Qt.PenStyle.DashLine)
            hidden_pen.setCosmetic(True)
            painter.setPen(hidden_pen)
            for rect in self.hidden:
                painter.drawRect(rect)
        if self.active and self.show_taps:
            self._paint_taps(painter)
        if self.active and self.flash is not None:
            rect, hit = self.flash
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(60, 200, 110, 150) if hit else QColor(230, 80, 80, 170))
            painter.drawRect(rect)
        t = theme.current()
        color = t.color("blue") if self.active else QColor(SCREEN_OUTLINE)
        pen = QPen(color, 2 if self.active else 1)
        pen.setCosmetic(True)
        if self.round:  # the corners are not on the panel: shade them, outline the circle
            outside = QPainterPath()
            outside.addRect(QRectF(0, 0, w, h))
            circle = QPainterPath()
            circle.addEllipse(QRectF(0, 0, w, h))
            painter.fillPath(outside.subtracted(circle), QColor(110, 120, 135, 170))
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(0, 0, w, h))
            faint = QPen(color, 1, Qt.PenStyle.DotLine)
            faint.setCosmetic(True)
            painter.setPen(faint)
            painter.drawRect(QRectF(0, 0, w, h))
        else:
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(0, 0, w, h))
        painter.setPen(t.color("blue") if self.active else t.color("mut"))
        painter.setFont(theme.mono_font(12))
        painter.drawText(
            QRectF(0, -LABEL_HEIGHT, w, LABEL_HEIGHT - 4),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
            f"ui_{self.name}.py",
        )

    def _paint_taps(self, painter: QPainter) -> None:
        """Tap zones: green, orange if too small for a finger, grey while hidden by a rule."""
        font = theme.mono_font(9)
        painter.setFont(font)
        for zone in self.taps:
            x, y, w, h = zone.box
            rect = QRectF(x, y, max(w, 1), max(h, 1))
            if not zone.shown:
                fill, line = QColor(150, 160, 170, 40), QColor(150, 160, 170, 160)
            elif zone.small:
                fill, line = QColor(255, 150, 40, 70), QColor(255, 140, 20, 230)
            else:
                fill, line = QColor(60, 200, 110, 55), QColor(40, 180, 90, 230)
            pen = QPen(line, 1, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(fill)
            painter.drawRect(rect)
            painter.setPen(line)
            painter.drawText(
                rect.adjusted(2, 1, 0, 0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                f"▶ {zone.widget.on_tap}",
            )


class _Gesture:
    """A mouse drag in progress: move or resize of one widget."""

    def __init__(
        self,
        widget: Widget,
        start: QPointF,
        role: str,
        angle: float = 0.0,
        origin: tuple[int, int] = (0, 0),
    ) -> None:
        self.widget = widget
        self.start = start
        self.role = role  # "" = move, a handle name = resize, "pivot" = rotation point
        self.current = widget
        self.angle = angle
        """Angle the widget is drawn at: resizing works in its turned frame."""
        self.origin = origin
        """Effective top-left (with rules) when the gesture started."""
        self.group: list[Widget] = []
        """The other selected widgets moving along (a multi-selection)."""
        self.shift = (0, 0)
        """Where the group has moved so far (snapped like the dragged widget)."""


class Workspace(QGraphicsView):
    """Pages in a row; zoom 50-400 % around the cursor or the centre; editing."""

    page_clicked = Signal(int)
    zoom_changed = Signal(float)
    message = Signal(str)
    preview_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(theme.current().color("soft"))
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.items_: list[PageItem] = []
        self.zoom = 1.0
        self.grid = False
        self.doc: Document | None = None
        self._gesture: _Gesture | None = None
        self._pan: QPoint | None = None
        self._band: tuple[QPoint, bool] | None = None
        """A selection frame being dragged: (start in the view, add to the selection)."""
        self._rubber = QRubberBand(QRubberBand.Shape.Rectangle, self.viewport())
        self.preview = False
        """"Перегляд": a click is a tap (as on the board), nothing is selected or moved."""
        self.show_taps = False
        self.last_tap: tuple[int, int, str | None] | None = None
        """(x, y, widget id or None) of the last simulated tap."""
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.setInterval(450)
        self._flash_timer.timeout.connect(self._end_flash)
        self._anim_start: dict[tuple[str, str], float] = {}
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(40)
        self._anim_timer.timeout.connect(self._animate)

    # ------------------------------------------------------------------ taps
    def set_show_taps(self, on: bool) -> None:
        """Outline the tap zones ("Зони натиску"); always on in "Перегляд"."""
        self.show_taps = on
        self._apply_taps()

    def set_preview(self, on: bool) -> None:
        """ "Перегляд": clicks become taps; leaving it (Esc too) returns to editing."""
        if on == self.preview:
            return
        self.preview = on
        self._gesture = None
        self._band = None
        self._rubber.hide()
        self.viewport().setCursor(
            Qt.CursorShape.PointingHandCursor if on else Qt.CursorShape.ArrowCursor
        )
        self._apply_taps()
        self.update_selection()
        self.preview_changed.emit(on)
        if on:
            self.message.emit(
                "Перегляд: клацайте по сторінці як пальцем — видно, яка процедура "
                "спрацює (Esc — назад до редагування)"
            )

    def _apply_taps(self) -> None:
        for item in self.items_:
            item.show_taps = self.show_taps or self.preview
            item.update()

    def simulate_tap(self, x: float, y: float) -> Widget | None:
        """A tap at page pixels (x, y) of the current page, as the board handles it."""
        item, doc = self.active_item(), self.doc
        if item is None or doc is None:
            return None
        px, py = int(x), int(y)
        widget = tap_at(doc.page, px, py)
        self.last_tap = (px, py, widget.id if widget else None)
        no_touch = "" if doc.project.display.touch else " — увага: дисплей без сенсора"
        if widget is not None:
            bx, by, bw, bh = tap_box(widget, ParameterValues.for_page(doc.page))
            item.flash = (QRectF(bx, by, max(bw, 1), max(bh, 1)), True)
            self.message.emit(f"Натиск ({px}, {py}) → «{widget.id}»: {widget.on_tap}(){no_touch}")
        else:
            item.flash = (QRectF(px - 3, py - 3, 7, 7), False)
            self.message.emit(f"Натиск ({px}, {py}): тут немає елемента з «При натиску»{no_touch}")
        item.update()
        self._flash_timer.start()
        return widget

    def _end_flash(self) -> None:
        for item in self.items_:
            if item.flash is not None:
                item.flash = None
                item.update()

    # ------------------------------------------------------------------ content
    def set_document(self, doc: Document) -> None:
        self.doc = doc
        doc.changed.connect(self.refresh)
        doc.current_page_changed.connect(self.set_current)
        doc.selection_changed.connect(self.update_selection)
        self.refresh()

    def refresh(self) -> None:
        if self.doc is not None:
            self.show_project(self.doc.project, self.doc.current)

    def show_project(self, project: Project, current: int) -> None:
        """Keep the page items that still fit and re-render only changed pages."""
        scene = self.scene()
        round_panel = project.display.profile.shape == "round"
        if len(self.items_) != len(project.pages) or (
            self.items_
            and (self.items_[0].size != project.display.size or self.items_[0].round != round_panel)
        ):
            scene.clear()
            self.items_ = [PageItem(i, p, project) for i, p in enumerate(project.pages)]
            for page_item in self.items_:
                page_item.show_taps = self.show_taps or self.preview
            for item in self.items_:
                scene.addItem(item)
        x = 0.0
        for index, (item, page) in enumerate(zip(self.items_, project.pages, strict=True)):
            item.index = index
            item.set_page(page, project, self._frames(page, project))
            item.setPos(x, 0)
            x += item.size[0] + PAGE_GAP
        _, height = project.display.size
        # A wide margin around the pages: the canvas can always be panned, so zooming
        # keeps the point under the cursor in place even when the pages fit the view.
        pages = QRectF(
            -PAGE_GAP, -PAGE_GAP - LABEL_HEIGHT, x + PAGE_GAP, height + 2 * PAGE_GAP + LABEL_HEIGHT
        )
        scene.setSceneRect(pages.adjusted(-SCENE_MARGIN, -SCENE_MARGIN, SCENE_MARGIN, SCENE_MARGIN))
        self._update_animations(project)
        self.set_current(current, scroll=False)

    def set_current(self, index: int, scroll: bool = True) -> None:
        for item in self.items_:
            item.set_active(item.index == index)
        if scroll and 0 <= index < len(self.items_):
            self.ensureVisible(self.items_[index], 20, 20)
        self.update_selection()

    def active_item(self) -> PageItem | None:
        return next((item for item in self.items_ if item.active), None)

    # ------------------------------------------------------------------ selection
    def widget_box(self, widget: Widget) -> tuple[int, int, int, int]:
        """Box of a widget as drawn with the current test values (lines: + 2 px)."""
        assert self.doc is not None
        e = effective(widget, ParameterValues.for_page(self.doc.page))
        x, y, w, h = e.bounds
        if widget.type == "line":
            return x, y, w + 2, h + 2
        return x, y, w, h

    def update_selection(self) -> None:
        item = self.active_item()
        if item is None or self.doc is None:
            return
        if self.preview:  # "Перегляд": the page as on the board, no selection marks
            item.group_boxes = []
            item.group_frame = None
            item.selection.set_box(None)
            item.pivot.setVisible(False)
            item.ghosts.set_frames([])
            item.update()
            return
        group = self._gesture.group if self._gesture else []
        dx, dy = self._gesture.shift if self._gesture else (0, 0)
        others = group or [w for w in self.doc.page.widgets if w.id in self.doc.also_selected]
        boxes = [self.widget_box(shift_widget(w, dx, dy) if group else w) for w in others]
        item.group_boxes = [QRectF(x, y, max(w, 2), max(h, 2)) for x, y, w, h in boxes]
        item.group_frame = self._group_frame(item.group_boxes)
        item.update()
        widget = self._gesture.current if self._gesture else self.doc.widget
        if widget is None:
            item.selection.set_box(None)
            item.pivot.setVisible(False)
            item.ghosts.set_frames([])
            return
        e = effective(widget, ParameterValues.for_page(self.doc.page))
        item.selection.set_box(self.widget_box(widget), e.angle, e.pivot)
        free = pickable(widget)  # 🔒 / 👁: an outline only, no handles to pull
        for handle in item.selection.handles.values():
            handle.setVisible(free)
        single = not self.doc.also_selected  # several: the centre grabs them all, no pivot
        item.pivot.setVisible(free and single and widget.type != "chart")
        item.pivot.setPos(*e.pivot)
        item.ghosts.set_frames(self.mapping_frames(widget))

    def _group_frame(self, others: list[QRectF]) -> QRectF | None:
        """The box around the selection when it is exactly one whole group."""
        doc = self.doc
        if doc is None or doc.selected is None or not others:
            return None
        main = doc.page.widget(doc.selected)
        if main is None or not main.group:
            return None
        if set(doc.group_members(main.id)) != set(doc.selected_ids):
            return None
        widget = self._gesture.current if self._gesture else main
        x, y, w, h = self.widget_box(widget)
        frame = QRectF(x, y, max(w, 2), max(h, 2))
        for rect in others:
            frame = frame.united(rect)
        return frame

    def mapping_frames(self, widget: Widget) -> list[tuple[QRectF, str]]:
        """Where x/y mappings put the widget at the parameter's min and max."""
        xs = next((r for r in widget.mappings() if r.prop == "x"), None)
        ys = next((r for r in widget.mappings() if r.prop == "y"), None)
        if xs is None and ys is None:
            return []
        frames = []
        for end, label in (("at_min", "мін"), ("at_max", "макс")):
            x = getattr(xs, end) if xs else widget.x
            y = getattr(ys, end) if ys else widget.y
            frames.append((QRectF(x, y, max(widget.w, 2), max(widget.h, 2)), label))
        return frames

    def _turned(self, widget: Widget, point: QPointF) -> QPointF:
        """``point`` in the widget's unrotated frame (inverse of its current rotation)."""
        assert self.doc is not None
        e = effective(widget, ParameterValues.for_page(self.doc.page))
        if not e.angle:
            return point
        px, py = e.pivot
        return QTransform().translate(px, py).rotate(-e.angle).translate(-px, -py).map(point)

    def locked_message(self) -> None:
        window = self.window()
        bar = getattr(window, "statusBar", None)
        if callable(bar):
            bar().showMessage("Елемент заблоковано (🔒 у «Шарах»): розблокуйте, щоб рухати", 4000)

    def widget_at(self, page_point: QPointF) -> Widget | None:
        """Top-most widget under a point (page pixels); thin widgets get a wider grab zone."""
        assert self.doc is not None
        grab = GRAB_PX / self.zoom
        for widget in reversed(self.doc.page.widgets):
            if not pickable(widget):
                continue
            x, y, w, h = self.widget_box(widget)
            pad_x = grab if w < THIN else 0.0
            pad_y = grab if h < THIN else 0.0
            local = self._turned(widget, page_point)
            if QRectF(x - pad_x, y - pad_y, w + 2 * pad_x, h + 2 * pad_y).contains(local):
                return widget
        return None

    # ------------------------------------------------------------------ mouse
    def _page_at(self, view_pos: QPoint) -> PageItem | None:
        scene_pos = self.mapToScene(view_pos)
        for item in self.items_:
            w, h = item.size
            if QRectF(item.pos(), QPointF(item.pos().x() + w, item.pos().y() + h)).contains(
                scene_pos
            ):
                return item
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.setFocus()
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        pos = event.position().toPoint()
        active = self.active_item()
        handle = self.itemAt(pos)
        grabbed = isinstance(handle, Handle | PivotHandle) and handle.role
        if (
            grabbed
            and not self.preview
            and active
            and self.doc
            and self.doc.widget
            and pickable(self.doc.widget)
        ):
            start = active.mapFromScene(self.mapToScene(pos))
            self._gesture = self._start(self.doc.widget, start, cast(str, handle.role))  # type: ignore[union-attr]
            return
        item = self._page_at(pos)
        if item is None:
            self._pan = pos  # dragging the background pans the canvas
            return
        if not item.active:
            self.page_clicked.emit(item.index)
            return
        if self.doc is None:
            return
        point = item.mapFromScene(self.mapToScene(pos))
        if self.preview:  # a tap, as on the board
            self.simulate_tap(point.x(), point.y())
            return
        widget = self.widget_at(point)
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if widget is None:  # an empty place of the page: a selection frame
            self._band = (pos, shift)
            self._rubber.setGeometry(QRect(pos, QSize()))
            self._rubber.show()
            return
        # Ctrl(⌘)+click: one widget of a group (Alt is "no snapping" while dragging)
        deep = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        members = [widget.id] if deep else self.doc.group_members(widget.id)
        if shift:  # Shift+click: into the selection, or out of it (a whole group)
            if len(members) > 1:
                ids = self.doc.selected_ids
                if widget.id in ids:
                    self.doc.select_many([i for i in ids if i not in members])
                else:
                    self.doc.select_many([*ids, *members], widget.id)
            else:
                self.doc.toggle_selected(widget.id)
            return
        ids = self.doc.selected_ids
        if len(members) > 1 and not set(members) <= set(ids):  # a group: all of it
            self.doc.select_many(members, widget.id)
            ids = self.doc.selected_ids
        if not deep and widget.id in ids and len(ids) > 1:  # drag the whole selection
            self.doc.select_many(ids, widget.id)  # the grabbed one leads (and snaps)
            self._gesture = self._start(widget, point, "")
            self._gesture.group = [
                w
                for w in self.doc.page.widgets
                if w.id in ids and w.id != widget.id and pickable(w)  # 🔒 ones stay put
            ]
            return
        self.doc.select(widget.id)
        self._gesture = self._start(widget, point, "")

    def _start(self, widget: Widget, point: QPointF, role: str) -> _Gesture:
        assert self.doc is not None
        e = effective(widget, ParameterValues.for_page(self.doc.page))
        return _Gesture(widget, point, role, e.angle, (e.x, e.y))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        if self._band is not None:
            self._rubber.setGeometry(QRect(self._band[0], pos).normalized())
            return
        if self._pan is not None:
            delta = pos - self._pan
            self._pan = pos
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            return
        gesture, item = self._gesture, self.active_item()
        if gesture is None or item is None or self.doc is None:
            super().mouseMoveEvent(event)
            return
        point = item.mapFromScene(self.mapToScene(pos))
        dx, dy = point.x() - gesture.start.x(), point.y() - gesture.start.y()
        free = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
        gesture.current = self._dragged(gesture, dx, dy, free)
        page = self.doc.page.model_copy()
        if gesture.group:  # the others follow the dragged one, by the same (snapped) step
            gesture.shift = (
                gesture.current.x - gesture.widget.x,
                gesture.current.y - gesture.widget.y,
            )
            moving = {w.id for w in gesture.group}
            page.widgets = [
                gesture.current
                if w.id == gesture.widget.id
                else shift_widget(w, *gesture.shift)
                if w.id in moving
                else w
                for w in page.widgets
            ]
        else:
            page.widgets = [
                gesture.current if w.id == gesture.widget.id else w for w in page.widgets
            ]
        item.set_page(page, self.doc.project, self._frames(page, self.doc.project))
        self.update_selection()

    def _dragged(self, gesture: _Gesture, dx: float, dy: float, free: bool) -> Widget:
        w = gesture.widget
        if gesture.role == "pivot":
            px = round(gesture.start.x() + dx - gesture.origin[0])
            py = round(gesture.start.y() + dy - gesture.origin[1])
            return w.model_copy(update={"pivot": PivotPoint(x=px, y=py)})
        if not gesture.role:
            x = round(w.x + dx) if free else snap(w.x + dx)
            y = round(w.y + dy) if free else snap(w.y + dy)
            # The base position and every x/y of conditions and mappings move together.
            return shift_widget(w, x - w.x, y - w.y)
        if gesture.angle:  # resize along the widget's own (turned) axes
            rad = math.radians(gesture.angle)
            dx, dy = (
                dx * math.cos(rad) + dy * math.sin(rad),
                -dx * math.sin(rad) + dy * math.cos(rad),
            )
        x, y, width, height = resize_box(
            (w.x, w.y, w.w, w.h), gesture.role, dx, dy, w.type == "line", free
        )
        return w.model_copy(update={"x": x, "y": y, "w": width, "h": height})

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._pan = None
        if self._band is not None:
            self._finish_band(event.position().toPoint())
            return
        gesture, self._gesture = self._gesture, None
        if gesture is None or self.doc is None:
            super().mouseReleaseEvent(event)
            return
        if gesture.group:
            ids = [gesture.widget.id, *(w.id for w in gesture.group)]
            self.doc.move_widgets(ids, *gesture.shift, f"Перемістити елементи: {len(ids)}")
            self.refresh()
            return
        if gesture.current != gesture.widget:
            text = {"": "Перемістити", "pivot": "Точка повороту"}.get(
                gesture.role, "Змінити розмір"
            )
            self.doc.change_widget(gesture.current, text)  # one undo step per gesture
        else:
            self.refresh()

    def _finish_band(self, pos: QPoint) -> None:
        """Select the widgets the frame touches (with Shift: add them to the selection)."""
        assert self._band is not None
        start, add = self._band
        self._band = None
        self._rubber.hide()
        item, doc = self.active_item(), self.doc
        if item is None or doc is None:
            return
        frame = QRect(start, pos).normalized()
        if frame.width() < 3 and frame.height() < 3:  # a click on an empty place
            if not add:
                doc.select(None)
            return
        a = item.mapFromScene(self.mapToScene(frame.topLeft()))
        b = item.mapFromScene(self.mapToScene(frame.bottomRight()))
        area = QRectF(a, b).normalized()
        hit = []
        for w in doc.page.widgets:
            if not pickable(w):
                continue
            x, y, width, height = self.widget_box(w)
            if area.intersects(QRectF(x, y, max(width, 1), max(height, 1))):
                hit.append(w.id)
        hit = doc.with_groups(hit)  # a frame touching a group takes all of it
        ids = [*doc.selected_ids, *hit] if add else hit
        doc.select_many(ids, hit[-1] if hit else doc.selected)

    # ------------------------------------------------------------------ keyboard
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self.preview:  # nothing to edit in "Перегляд"
            if event.key() == Qt.Key.Key_Escape:
                self.set_preview(False)
                return
            super().keyPressEvent(event)
            return
        doc = self.doc
        widget = doc.widget if doc else None
        key = event.key()
        if doc is not None and widget is not None:
            ids = doc.selected_ids
            if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                if len(ids) > 1:
                    doc.remove_widgets(ids)
                else:
                    doc.remove_widget(widget.id)
                return
            steps = {
                Qt.Key.Key_Left: (-1, 0),
                Qt.Key.Key_Right: (1, 0),
                Qt.Key.Key_Up: (0, -1),
                Qt.Key.Key_Down: (0, 1),
            }
            mods = event.modifiers()
            if key in steps and not mods & (
                Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
            ):
                step = 10 if mods & Qt.KeyboardModifier.ShiftModifier else 1
                dx, dy = steps[cast(Qt.Key, key)]
                ids = [w.id for w in doc.page.widgets if w.id in ids and pickable(w)]
                if not ids:  # 🔒 locked (or 👁 hidden): stays put
                    self.locked_message()
                    return
                if len(ids) > 1:
                    doc.move_widgets(ids, dx * step, dy * step, "Зсунути елементи", merge="nudge")
                    return
                widget = doc.page.widget(ids[0]) or widget
                moved = shift_widget(widget, dx * step, dy * step)
                doc.change_widget(moved, "Зсунути", merge="nudge")
                return
            if key == Qt.Key.Key_Escape:
                doc.select(None)
                return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------ drop from the palette
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(WIDGET_MIME) or event.mimeData().hasFormat(PARAM_MIME):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        accepted = event.mimeData().hasFormat(WIDGET_MIME) or event.mimeData().hasFormat(PARAM_MIME)
        if accepted and self._page_at(event.position().toPoint()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        data = event.mimeData()
        pos = event.position().toPoint()
        item = self._page_at(pos)
        if self.doc is None or item is None:
            event.ignore()
            return
        if data.hasFormat(WIDGET_MIME):
            kind = bytes(data.data(WIDGET_MIME).data()).decode()
            self.doc.set_current(item.index)
            self.add_widget(cast(WidgetType, kind), item.mapFromScene(self.mapToScene(pos)))
        elif data.hasFormat(PARAM_MIME):
            if not item.active:  # parameters belong to the current page
                event.ignore()
                return
            name = bytes(data.data(PARAM_MIME).data()).decode()
            self.drop_parameter(name, item.mapFromScene(self.mapToScene(pos)))
        else:
            event.ignore()
            return
        event.acceptProposedAction()

    def drop_parameter(self, name: str, point: QPointF) -> None:
        """On a widget: bind it (a bool: "hide when false"); on free space: a new widget."""
        if self.doc is None:
            return
        widget = self.widget_at(point)
        if widget is not None:
            self.message.emit(self.doc.bind_parameter(widget.id, name))
        else:
            created = self.doc.add_parameter_widget(name, snap(point.x()), snap(point.y()))
            if created is not None:
                self.message.emit(f"Новий елемент «{created.id}» показує «{name}».")

    def add_widget(self, kind: WidgetType, point: QPointF | None = None) -> None:
        """Add a widget to the current page: at ``point`` (page pixels) or in the centre."""
        if self.doc is None:
            return
        page = self.doc.page
        if point is None:
            w, h = self.doc.project.display.size
            point = QPointF(w / 2, h / 2)
        widget = new_widget(page, kind, snap(point.x()), snap(point.y()))
        self.doc.add_widget(widget)
        self.setFocus()

    # ------------------------------------------------------------------ animations
    def _frames(self, page: Page, project: Project) -> dict[str, int]:
        frames = {}
        now = time.monotonic()
        for widget in page.widgets:
            key = widget.image.file if widget.type == "image" and widget.image else None
            asset = project.images.get(key) if key else None
            if asset is None or not asset.is_animation or not asset.frames:
                continue
            started = self._anim_start.setdefault((page.name, widget.id), now)
            index = int((now - started) * 1000 / (asset.delay_ms or 100))
            count = len(asset.frames)
            loop = widget.image is None or widget.image.play == "loop"
            frames[widget.id] = index % count if loop else min(index, count - 1)
        return frames

    def hideEvent(self, event: QHideEvent) -> None:
        self._anim_timer.stop()  # nothing to animate while the work area isn't shown
        super().hideEvent(event)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self.doc is not None:
            self._update_animations(self.doc.project)

    def _update_animations(self, project: Project) -> None:
        animated = self.isVisible() and any(self._frames(page, project) for page in project.pages)
        if animated and not self._anim_timer.isActive():
            self._anim_timer.start()
        elif not animated:
            self._anim_timer.stop()

    def _animate(self) -> None:
        if self.doc is None or self._gesture is not None:
            return
        project = self.doc.project
        for item, page in zip(self.items_, project.pages, strict=False):
            item.set_page(page, project, self._frames(page, project))

    def restart_animation(self, widget_id: str) -> None:
        """ "Програти з початку" for an animated image of the current page."""
        if self.doc is not None:
            self._anim_start[(self.doc.page.name, widget_id)] = time.monotonic()
            self._animate()

    # ------------------------------------------------------------------ zoom
    def set_zoom(self, zoom: float, anchor: QPointF | None = None) -> None:
        """Zoom to ``zoom`` (clamped to 50-400 %) keeping ``anchor`` (view coords) in place.

        Without an anchor the view centre stays in place.
        """
        zoom = max(ZOOM_MIN, min(ZOOM_MAX, zoom))
        if abs(zoom - self.zoom) < 1e-6:
            return
        point = anchor if anchor is not None else QPointF(self.viewport().rect().center())
        fixed = self.mapToScene(point.toPoint())
        factor = zoom / self.zoom
        self.scale(factor, factor)
        self.zoom = zoom
        moved = self.mapFromScene(fixed)
        delta = moved - point.toPoint()
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + delta.x())
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + delta.y())
        self.zoom_changed.emit(zoom)

    def zoom_in(self) -> None:
        self.set_zoom(self.zoom * ZOOM_STEP)

    def zoom_out(self) -> None:
        self.set_zoom(self.zoom / ZOOM_STEP)

    def zoom_reset(self) -> None:
        self.set_zoom(1.0)

    def fit_all(self) -> None:
        """Zoom so that every page is visible (within 50-400 %)."""
        rect = self.scene().itemsBoundingRect()  # the pages, not the panning margin
        if rect.isEmpty():
            return
        view = self.viewport().rect()
        zoom = min(view.width() / rect.width(), view.height() / rect.height()) * 0.95
        self.set_zoom(zoom)
        self.centerOn(rect.center())

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
        ):
            steps = event.angleDelta().y() / 120
            if steps:
                self.set_zoom(self.zoom * ZOOM_STEP**steps, event.position())
            event.accept()
            return
        super().wheelEvent(event)

    def drawBackground(self, painter: QPainter, rect: QRectF | QRect) -> None:
        """The mock-up's canvas: soft background with a dot grid fixed to the screen."""
        t = theme.current()
        key = (t.soft, t.line)
        if getattr(self, "_dots_key", None) != key:  # one 12x12 tile, drawn tiled
            tile = QPixmap(DOT_STEP, DOT_STEP)
            tile.fill(t.color("soft"))
            dot = QPainter(tile)
            dot.setPen(QPen(t.color("line"), 1.5))
            dot.drawPoint(0, 0)
            dot.end()
            self._dots, self._dots_key = tile, key
        painter.save()
        painter.resetTransform()
        painter.drawTiledPixmap(self.viewport().rect(), self._dots)
        painter.restore()

    def drawForeground(self, painter: QPainter, rect: QRectF | QRect) -> None:
        if not self.grid:
            return
        pen = QPen(QColor(255, 255, 255, 28), 1)
        pen.setCosmetic(True)
        painter.setPen(pen)
        for item in self.items_:
            w, h = item.size
            origin = item.pos()
            for x in range(0, w + 1, 10):
                painter.drawLine(
                    QPointF(origin.x() + x, origin.y()), QPointF(origin.x() + x, origin.y() + h)
                )
            for y in range(0, h + 1, 10):
                painter.drawLine(
                    QPointF(origin.x(), origin.y() + y), QPointF(origin.x() + w, origin.y() + y)
                )
