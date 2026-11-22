"""Right column: properties of the selected widget in collapsible blocks.

Only static values live here; everything that depends on parameters is in the
"Умови" block (stage 13). Each edit becomes an undo step; repeated steps of the
same field (spin box arrows, typing) are merged into one.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from pydantic import ValidationError
from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from espui.assets.fonts import FONTS
from espui.assets.images import ImageImportError
from espui.core.compat import can_bind
from espui.core.issues import issues_from_validation_error
from espui.core.models import (
    FONT_SIZE_TYPES,
    FONT_TYPES,
    PIVOT_FRACTIONS,
    SCALE_TYPES,
    WIDGET_TYPES,
    ChartSettings,
    ImageSettings,
    PivotPoint,
    Widget,
    WidgetType,
)
from espui.gui.document import Document
from espui.gui.rules_editor import PROP_TITLES, RulesEditor
from espui.gui.widgets_catalog import TITLES, change_type, controlled_props

PIVOT_TITLES = {
    "center": "центр",
    "top_left": "лівий верхній кут",
    "top": "середина верху",
    "top_right": "правий верхній кут",
    "left": "середина лівого краю",
    "right": "середина правого краю",
    "bottom_left": "лівий нижній кут",
    "bottom": "середина низу",
    "bottom_right": "правий нижній кут",
}
IMAGE_FILTER = "Картинки й відео (*.png *.jpg *.jpeg *.webp *.gif *.apng *.mp4 *.webm *.mov)"


class ErrorLabel(QLabel):
    """Red message that takes no room while it is empty."""

    def __init__(self) -> None:
        super().__init__()
        self.setWordWrap(True)
        self.setStyleSheet("color: #c0392b")
        self.setVisible(False)

    def setText(self, text: str) -> None:
        super().setText(text)
        self.setVisible(bool(text))


class Section(QWidget):
    """A block with a clickable ``▾ Title`` header; the collapsed state is remembered."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        self.header = QToolButton()
        self.header.setObjectName("section_header")
        self.header.setCheckable(True)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.body = QWidget()
        self.form = QFormLayout(self.body)
        self.form.setContentsMargins(8, 0, 0, 6)
        # A narrow panel puts the label above its field instead of cutting the field off.
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.header)
        layout.addWidget(self.body)
        collapsed = QSettings().value(f"sections/{title}", False, type=bool)
        self.header.setChecked(not collapsed)
        self.header.toggled.connect(self._toggled)
        self._toggled(not collapsed)

    @property
    def collapsed(self) -> bool:
        return not self.header.isChecked()

    def _toggled(self, expanded: bool) -> None:
        self.header.setText(("▾ " if expanded else "▸ ") + self.title)
        self.body.setVisible(expanded)
        # A collapsed block is only its header (layouts don't shrink a hidden body by themselves).
        self.setMaximumHeight(16777215 if expanded else self.header.sizeHint().height() + 4)
        QSettings().setValue(f"sections/{self.title}", not expanded)


MIN_COMBO_CHARS = 6


def shrinkable_combos(root: QWidget) -> None:
    """Drop-downs may get narrower than their longest item (the open list still shows it)."""
    for combo in root.findChildren(QComboBox):
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(MIN_COMBO_CHARS)
    for spin in root.findChildren(QAbstractSpinBox):
        spin.setMinimumWidth(0)  # spin boxes may share a narrow row


class PropertiesPanel(QScrollArea):
    """Edits the selected widget of the current page."""

    message = Signal(str)
    """Something the user should know (e.g. a binding removed by a type change)."""

    def __init__(
        self, doc: Document, restart_animation: Callable[[str], None] | None = None
    ) -> None:
        super().__init__()
        self.doc = doc
        self.restart_animation = restart_animation or (lambda _id: None)
        self._loading = False
        self.setWidgetResizable(True)
        root = QWidget()
        self.layout_ = QVBoxLayout(root)
        self.setWidget(root)

        self.empty = QLabel("Виберіть елемент на полотні або в шарах.")
        self.empty.setWordWrap(True)
        self.empty.setEnabled(False)
        self.layout_.addWidget(self.empty)
        self.error = ErrorLabel()
        self.error.setObjectName("error")
        self.layout_.addWidget(self.error)

        self._build_main()
        self._build_look()
        self._build_image()
        self._build_chart()
        self.rules_section = Section("Умови")
        self.rules_editor = RulesEditor()
        self.rules_editor.changed.connect(lambda rules: self.set_field("rules", rules, "Умови"))
        self.rules_section.form.addRow(self.rules_editor)
        self.layout_.addWidget(self.rules_section)
        self.placeholders = [self.rules_section]
        self.layout_.addStretch(1)

        content = self.widget()
        assert content is not None
        shrinkable_combos(content)
        doc.selection_changed.connect(self.load)
        doc.changed.connect(self.load)
        self.load()

    # ------------------------------------------------------------------ blocks
    def _build_main(self) -> None:
        s = self.main = Section("Властивості")
        self.id_edit = QLineEdit()
        self.id_edit.editingFinished.connect(self._id_edited)
        self.type_combo = QComboBox()
        for kind in WIDGET_TYPES:
            self.type_combo.addItem(TITLES[kind], kind)
        self.type_combo.activated.connect(self._type_chosen)
        geometry = QWidget()
        grid = QGridLayout(geometry)
        grid.setContentsMargins(0, 0, 0, 0)
        self.box_spins: dict[str, QSpinBox] = {}
        for i, field in enumerate(("x", "y", "w", "h")):
            spin = QSpinBox()
            spin.setRange(-2000 if field in "xy" else 0, 2000)
            spin.setPrefix(f"{field} ")
            spin.valueChanged.connect(lambda v, f=field: self.set_field(f, v))
            self.box_spins[field] = spin
            grid.addWidget(spin, i // 2, i % 2)
        self.color_button = QPushButton()
        self.color_button.clicked.connect(self._pick_color)
        self.color_edit = QLineEdit()
        self.color_edit.setMaximumWidth(90)
        self.color_edit.editingFinished.connect(
            lambda: self.set_field("color", self.color_edit.text().strip())
        )
        color = QWidget()
        crow = QHBoxLayout(color)
        crow.setContentsMargins(0, 0, 0, 0)
        crow.addWidget(self.color_button)
        crow.addWidget(self.color_edit)
        # Bars and arcs: the number of the value, the fixed track the value fills.
        self.show_value = QCheckBox("Показувати число")
        self.show_value.setObjectName("show_value")
        self.show_value.toggled.connect(lambda on: self.set_field("show_value", on))
        self.track_button = QPushButton()
        self.track_button.setObjectName("track_button")
        self.track_button.setToolTip("Колір доріжки, яку заповнює значення")
        self.track_button.clicked.connect(self._pick_track_color)
        self.track_edit = QLineEdit()
        self.track_edit.setObjectName("track_edit")
        self.track_edit.setMaximumWidth(90)
        self.track_edit.editingFinished.connect(
            lambda: self.set_field("track_color", self.track_edit.text().strip())
        )
        self.show_track = QCheckBox("Показувати доріжку")
        self.show_track.setObjectName("show_track")
        self.show_track.toggled.connect(lambda on: self.set_field("show_track", on))
        track = self.track_row = QWidget()
        trow = QHBoxLayout(track)
        trow.setContentsMargins(0, 0, 0, 0)
        trow.addWidget(self.track_button)
        trow.addWidget(self.track_edit)
        self.bind_combo = QComboBox()
        self.bind_combo.activated.connect(
            lambda _: self.set_field("bind", self.bind_combo.currentData())
        )
        self.format_edit = QLineEdit()
        self.format_edit.editingFinished.connect(
            lambda: self.set_field("format", self.format_edit.text())
        )
        self.font_combo = QComboBox()
        for key, info in FONTS.items():
            self.font_combo.addItem(f"{info.title} — {info.kind}", key)
        self.font_combo.activated.connect(
            lambda _: self.set_field("font", self.font_combo.currentData())
        )
        self.font_all = QPushButton("Застосувати до всіх")
        self.font_all.setToolTip("Цей шрифт для всіх елементів сторінки")
        self.font_all.clicked.connect(
            lambda: self.doc.apply_font_to_all(self.font_combo.currentData())
        )
        font = self.font_row = QWidget()
        frow = QHBoxLayout(font)
        frow.setContentsMargins(0, 0, 0, 0)
        frow.addWidget(self.font_combo, 1)
        frow.addWidget(self.font_all)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(8, 72)
        self.size_spin.setSuffix(" px")
        self.size_spin.valueChanged.connect(lambda v: self.set_field("font_size", v))
        self.delete_button = QPushButton("Видалити")
        self.delete_button.clicked.connect(lambda: self.doc.remove_widget())

        s.form.addRow("id", self.id_edit)
        s.form.addRow("Тип", self.type_combo)
        s.form.addRow("Позиція, розмір", geometry)
        s.form.addRow("Колір", color)
        s.form.addRow("Доріжка", self.track_row)
        s.form.addRow("", self.show_track)
        s.form.addRow("", self.show_value)
        s.form.addRow("Дані з параметра", self.bind_combo)
        s.form.addRow("Формат / текст", self.format_edit)
        s.form.addRow("Шрифт", font)
        s.form.addRow("Шрифт, px", self.size_spin)
        s.form.addRow(self.delete_button)
        self.layout_.addWidget(s)

    def _build_look(self) -> None:
        s = self.look = Section("Вигляд")
        self.controlled_hint = QLabel()
        self.controlled_hint.setObjectName("controlled_hint")
        self.controlled_hint.setWordWrap(True)
        self.controlled_hint.setStyleSheet("color: #b9770e")
        self.opacity_spin = QSpinBox()
        self.opacity_spin.setRange(0, 100)
        self.opacity_spin.setSuffix(" %")
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(0, 100)
        for control in (self.opacity_spin, self.opacity_slider):
            control.valueChanged.connect(lambda v: self.set_field("opacity", v))
        self.opacity_all = QPushButton("Для всіх елементів")
        self.opacity_all.setToolTip("Застосувати цю непрозорість до всіх елементів сторінки")
        self.opacity_all.clicked.connect(
            lambda: self.doc.apply_opacity_to_all(self.opacity_spin.value())
        )
        self.angle_spin = QDoubleSpinBox()
        self.angle_spin.setRange(-360, 360)
        self.angle_spin.setDecimals(0)
        self.angle_spin.setSuffix("°")
        self.angle_spin.valueChanged.connect(lambda v: self.set_field("rotation_deg", float(v)))
        self.angle_slider = QSlider(Qt.Orientation.Horizontal)
        self.angle_slider.setRange(-180, 180)
        self.angle_slider.valueChanged.connect(lambda v: self.set_field("rotation_deg", float(v)))
        self.pivot_combo = QComboBox()
        for key in PIVOT_FRACTIONS:
            self.pivot_combo.addItem(PIVOT_TITLES[key], key)
        self.pivot_combo.addItem("власна точка", "custom")
        self.pivot_combo.activated.connect(self._pivot_chosen)
        self.pivot_x = QSpinBox()
        self.pivot_y = QSpinBox()
        for spin in (self.pivot_x, self.pivot_y):
            spin.setRange(-2000, 2000)
            spin.valueChanged.connect(self._pivot_point)
        point = QWidget()
        prow = QHBoxLayout(point)
        prow.setContentsMargins(0, 0, 0, 0)
        prow.addWidget(self.pivot_x)
        prow.addWidget(self.pivot_y)
        self.pivot_point = point
        self.opacity_row = self._pair(self.opacity_spin, self.opacity_slider)
        self.angle_row = self._pair(self.angle_spin, self.angle_slider)
        s.form.addRow(self.controlled_hint)
        s.form.addRow("Непрозорість", self.opacity_row)
        s.form.addRow(self.opacity_all)
        s.form.addRow("Кут", self.angle_row)
        s.form.addRow("Точка повороту", self.pivot_combo)
        s.form.addRow("", point)
        hint = QLabel("Точку повороту можна тягнути червоним хрестиком на полотні.")
        hint.setWordWrap(True)
        hint.setEnabled(False)
        self.pivot_hint = hint
        s.form.addRow(hint)
        self.layout_.addWidget(s)

    @staticmethod
    def _pair(field: QWidget, slider: QWidget) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(field)
        row.addWidget(slider, 1)
        return box

    def _build_image(self) -> None:
        s = self.image = Section("Картинка")
        self.file_combo = QComboBox()
        self.file_combo.activated.connect(
            lambda _: self.set_image(file=self.file_combo.currentData())
        )
        self.add_file = QPushButton("+ Файл…")
        self.add_file.clicked.connect(self._add_file)
        files = QWidget()
        row = QHBoxLayout(files)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.file_combo, 1)
        row.addWidget(self.add_file)
        self.fit_combo = QComboBox()
        for key, title in (
            ("contain", "вписати повністю"),
            ("cover", "заповнити з обрізанням"),
            ("fill", "розтягнути"),
        ):
            self.fit_combo.addItem(title, key)
        self.fit_combo.activated.connect(lambda _: self.set_image(fit=self.fit_combo.currentData()))
        self.native_size = QPushButton("Розмір як у картинки")
        self.native_size.clicked.connect(self._native_size)
        self.loop_radio = QRadioButton("⟳ Цикл")
        self.once_radio = QRadioButton("→ Один раз")
        group = QButtonGroup(self)
        group.addButton(self.loop_radio)
        group.addButton(self.once_radio)
        self.loop_radio.toggled.connect(lambda on: on and self.set_image(play="loop"))
        self.once_radio.toggled.connect(lambda on: on and self.set_image(play="once"))
        play = QWidget()
        prow = QHBoxLayout(play)
        prow.setContentsMargins(0, 0, 0, 0)
        prow.addWidget(self.loop_radio)
        prow.addWidget(self.once_radio)
        self.play_box = play
        self.restart_button = QPushButton("▶ Програти з початку")
        self.restart_button.clicked.connect(
            lambda: self.doc.widget and self.restart_animation(self.doc.widget.id)
        )
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(20, 5000)
        self.delay_spin.setSuffix(" мс")
        self.delay_spin.valueChanged.connect(self._delay_changed)
        self.files_row = files
        self.image_hint = QLabel()
        self.image_hint.setObjectName("image_hint")
        self.image_hint.setWordWrap(True)
        self.image_hint.setEnabled(False)
        self.board_list = QListWidget()
        self.board_list.setMaximumHeight(120)
        self.board_list.itemClicked.connect(self._board_clicked)
        self.board_add = QPushButton("+ Файли…")
        self.board_add.clicked.connect(self._add_board_files)
        self.board_remove = QPushButton("×")
        self.board_remove.setToolTip("Прибрати вибрану картинку з бібліотеки")
        self.board_remove.clicked.connect(self._remove_board_file)
        board_buttons = QWidget()
        brow = QHBoxLayout(board_buttons)
        brow.setContentsMargins(0, 0, 0, 0)
        brow.addWidget(self.board_add, 1)
        brow.addWidget(self.board_remove)
        self.board_buttons = board_buttons
        self.board_hint = QLabel(
            "Клік — показати в прев'ю (стає тестовим значенням параметра). "
            "На платі шлях до картинки передає ваш код."
        )
        self.board_hint.setWordWrap(True)
        self.board_hint.setEnabled(False)
        s.form.addRow("Файл", files)
        s.form.addRow(self.image_hint)
        s.form.addRow("Картинки на платі (/img)", self.board_list)
        s.form.addRow(self.board_buttons)
        s.form.addRow(self.board_hint)
        s.form.addRow("Вписування", self.fit_combo)
        s.form.addRow(self.native_size)
        s.form.addRow("Відтворення", play)
        s.form.addRow(self.restart_button)
        s.form.addRow("Кадр", self.delay_spin)
        self.layout_.addWidget(s)

    def _build_chart(self) -> None:
        s = self.chart = Section("Графік")
        self.axis_x = QLineEdit()
        self.axis_x.setMaxLength(16)
        self.axis_x.editingFinished.connect(lambda: self.set_chart(axis_x=self.axis_x.text()))
        self.axis_y = QLineEdit()
        self.axis_y.setMaxLength(16)
        self.axis_y.editingFinished.connect(lambda: self.set_chart(axis_y=self.axis_y.text()))
        self.y_bounds: dict[str, QLineEdit] = {}
        rows = []
        for field, title in (("y_min", "Y мін"), ("y_max", "Y макс")):
            edit = QLineEdit()
            edit.setPlaceholderText("авто")
            edit.setToolTip("Порожньо — авто: межі параметра, розширені до даних")
            edit.editingFinished.connect(self._bounds_edited)
            self.y_bounds[field] = edit
            rows.append((title, edit))
        self.style_combo = QComboBox()
        for key, title in (("line", "лінія"), ("dots", "лінія з точками"), ("bars", "стовпці")):
            self.style_combo.addItem(title, key)
        self.style_combo.activated.connect(
            lambda _: self.set_chart(style=self.style_combo.currentData())
        )
        self.grid_check = QCheckBox("3 лінії: мін, середина, макс")
        self.grid_check.toggled.connect(lambda on: self.set_chart(grid=on))
        s.form.addRow("Підпис осі X", self.axis_x)
        s.form.addRow("Підпис осі Y", self.axis_y)
        for title, box in rows:
            s.form.addRow(title, box)
        s.form.addRow("Вигляд", self.style_combo)
        s.form.addRow("Сітка", self.grid_check)
        self.layout_.addWidget(s)

    # ------------------------------------------------------------------ load
    def load(self) -> None:
        """Show the selected widget (signals blocked: loading is not an edit).

        The panel is reloaded after every edit (an angle being dragged, too): painting is
        held until it is done and the scroll position is kept, so nothing jumps.
        """
        bar = self.verticalScrollBar()
        scroll = bar.value()
        self.setUpdatesEnabled(False)
        try:
            self._load()
        finally:
            bar.setValue(scroll)
            self.setUpdatesEnabled(True)

    def _load(self) -> None:
        widget = self.doc.widget
        self._loading = True
        try:
            self.empty.setVisible(widget is None)
            for section in (self.main, self.look, self.image, self.chart, *self.placeholders):
                section.setVisible(widget is not None)
            if widget is None:
                self.error.setText("")
                return
            self._load_main(widget)
            self._load_look(widget)
            self.rules_editor.load(widget, self.doc.page, self.doc.project.display.size)
            self.image.setVisible(widget.type == "image")
            if widget.type == "image":
                self._load_image(widget)
            self.chart.setVisible(widget.type == "chart")
            if widget.type == "chart":
                self._load_chart(widget.chart or ChartSettings())
        finally:
            self._loading = False

    def _load_main(self, w: Widget) -> None:
        self.id_edit.setText(w.id)
        self.type_combo.setCurrentIndex(self.type_combo.findData(w.type))
        for field, spin in self.box_spins.items():
            spin.setValue(getattr(w, field))
        self.color_edit.setText(w.color)
        self.color_button.setStyleSheet(f"background: {w.color}; min-width: 40px")
        self.bind_combo.clear()
        self.bind_combo.addItem("— немає —", None)
        for param in self.doc.page.parameters:
            if can_bind(w.type, param):
                self.bind_combo.addItem(f"{param.name} ({param.type})", param.name)
        self.bind_combo.setCurrentIndex(max(0, self.bind_combo.findData(w.bind)))
        self.bind_combo.setEnabled(self.bind_combo.count() > 1)
        self.format_edit.setText(w.format)
        scale = w.type in SCALE_TYPES
        for row in (self.track_row, self.show_track, self.show_value):
            self.main.form.setRowVisible(row, scale)
        if scale:
            self.show_value.setChecked(w.show_value)
            self.show_track.setChecked(w.show_track)
            self.track_edit.setText(w.track_color)
            self.track_button.setStyleSheet(f"background: {w.track_color}; min-width: 40px")
            for control in (self.track_button, self.track_edit):
                control.setEnabled(w.show_track)
        has_format = w.type in ("text", "value", "bar")
        self.main.form.setRowVisible(self.format_edit, has_format)
        self.main.form.setRowVisible(self.font_row, w.type in FONT_TYPES)
        self.main.form.setRowVisible(self.size_spin, w.type in FONT_SIZE_TYPES)
        self.font_combo.setCurrentIndex(max(0, self.font_combo.findData(w.font or "serif")))
        if w.font_size:
            self.size_spin.setValue(w.font_size)

    def _load_look(self, w: Widget) -> None:
        self.opacity_spin.setValue(w.opacity)
        self.opacity_slider.setValue(w.opacity)
        self.angle_spin.setValue(w.rotation_deg)
        self.angle_slider.setValue(int(max(-180, min(180, w.rotation_deg))))
        rotatable = w.type != "chart"
        for row in (self.angle_row, self.pivot_combo, self.pivot_hint):
            self.look.form.setRowVisible(row, rotatable)
        custom = isinstance(w.pivot, PivotPoint)
        self.pivot_combo.setCurrentIndex(self.pivot_combo.findData("custom" if custom else w.pivot))
        self.look.form.setRowVisible(self.pivot_point, rotatable and custom)
        if isinstance(w.pivot, PivotPoint):
            self.pivot_x.setValue(int(w.pivot.x))
            self.pivot_y.setValue(int(w.pivot.y))
        self._lock_controlled(w)

    def _lock_controlled(self, w: Widget) -> None:
        """Fields that conditions / mappings change are disabled, with who controls them."""
        controlled = controlled_props(w)
        groups = {
            "color": (self.color_button, self.color_edit),
            "text": (self.format_edit,),
            "opacity": (self.opacity_spin, self.opacity_slider),
            "angle": (self.angle_spin, self.angle_slider),
            "x": (self.box_spins["x"],),
            "y": (self.box_spins["y"],),
        }
        for prop, controls in groups.items():
            names = controlled.get(prop)
            for control in controls:
                control.setEnabled(not names)
                control.setToolTip(f"Керується в «Умовах»: {', '.join(names)}" if names else "")
        parts = [f"{PROP_TITLES[prop]} ({', '.join(names)})" for prop, names in controlled.items()]
        self.controlled_hint.setText("Змінюється умовами: " + "; ".join(parts) if parts else "")
        self.look.form.setRowVisible(self.controlled_hint, bool(parts))

    def _load_image(self, w: Widget) -> None:
        settings = w.image or ImageSettings()
        self.file_combo.clear()
        self.file_combo.addItem("— немає —", None)
        for key, item in self.doc.project.images.items():
            kind = "анімація" if item.is_animation else f"{item.width}×{item.height}"
            self.file_combo.addItem(f"{key} ({kind})", key)
        self.file_combo.setCurrentIndex(max(0, self.file_combo.findData(settings.file)))
        self.file_combo.setEnabled(not w.bind)
        self.file_combo.setToolTip("Шлях береться з параметра" if w.bind else "")
        self.fit_combo.setCurrentIndex(self.fit_combo.findData(settings.fit))
        asset = self.doc.project.images.get(settings.file or "")
        animated = asset is not None and asset.is_animation
        for row in (self.play_box, self.restart_button, self.delay_spin):
            self.image.form.setRowVisible(row, animated)
        self.native_size.setEnabled(asset is not None)
        bound = bool(w.bind)
        self.image.form.setRowVisible(self.files_row, not bound)
        for row in (self.board_list, self.board_buttons, self.board_hint):
            self.image.form.setRowVisible(row, bound)
        if asset is not None and not bound:
            frames = len(asset.frames or []) or 1
            size = frames * w.w * w.h * 2
            where = asset.path if not asset.is_animation else f"{asset.path} ({frames} кадрів)"
            kb = f"{size / 1024:.1f}".replace(".", ",")
            self.image_hint.setText(f"На платі: {where} · {kb} КБ")
        else:
            self.image_hint.setText("")
        self.image.form.setRowVisible(self.image_hint, bool(self.image_hint.text()))
        if bound:
            current = self.doc.page.value_of(w.bind) if w.bind else None
            self.board_list.clear()
            for key, item in self.doc.project.images.items():
                entry = QListWidgetItem(f"{item.path} · {item.name}")
                entry.setData(Qt.ItemDataRole.UserRole, key)
                if item.path == current:
                    font = entry.font()
                    font.setBold(True)
                    entry.setFont(font)
                    entry.setText("▶ " + entry.text())
                self.board_list.addItem(entry)
        (self.loop_radio if settings.play == "loop" else self.once_radio).setChecked(True)
        if asset is not None and asset.delay_ms:
            self.delay_spin.setValue(asset.delay_ms)

    def _load_chart(self, chart: ChartSettings) -> None:
        self.axis_x.setText(chart.axis_x)
        self.axis_y.setText(chart.axis_y)
        for field, edit in self.y_bounds.items():
            value = getattr(chart, field)
            edit.setText("" if value is None else f"{value:g}")
        self.style_combo.setCurrentIndex(self.style_combo.findData(chart.style))
        self.grid_check.setChecked(chart.grid)

    # ------------------------------------------------------------------ edit
    def set_field(self, field: str, value: Any, text: str = "Властивість") -> bool:
        """Validated change of one field of the selected widget (one undo step per field)."""
        widget = self.doc.widget
        if self._loading or widget is None or getattr(widget, field) == value:
            return False
        try:
            new = Widget.model_validate({**widget.model_dump(), field: value})
        except ValidationError as error:
            self.error.setText("; ".join(i.message for i in issues_from_validation_error(error)))
            self.load()
            return False
        self.error.setText("")
        self.doc.change_widget(new, text, merge=f"field:{field}")
        return True

    def _id_edited(self) -> None:
        widget = self.doc.widget
        new_id = self.id_edit.text().strip()
        if self._loading or widget is None or new_id == widget.id:
            return
        problem = self.doc.id_problem(widget.id, new_id)
        if problem:
            self.error.setText(f"id: {problem}")
            self.id_edit.setText(widget.id)
            return
        self.error.setText("")
        self.doc.change_widget(widget.model_copy(update={"id": new_id}), "Перейменувати")

    def _type_chosen(self, _index: int) -> None:
        widget = self.doc.widget
        if widget is None:
            return
        kind = cast(WidgetType, self.type_combo.currentData())
        new, messages = change_type(widget, kind, self.doc.page)
        if new != widget:
            self.doc.change_widget(new, "Змінити тип")
        for text in messages:
            self.message.emit(text)
        self.error.setText(" ".join(messages))

    def _pick_color(self) -> None:
        widget = self.doc.widget
        if widget is None:
            return
        color = QColorDialog.getColor(QColor(widget.color), self, "Колір")
        if color.isValid():
            self.set_field("color", color.name())

    def _pick_track_color(self) -> None:
        widget = self.doc.widget
        if widget is None:
            return
        color = QColorDialog.getColor(QColor(widget.track_color), self, "Колір доріжки")
        if color.isValid():
            self.set_field("track_color", color.name())

    def _pivot_chosen(self, _index: int) -> None:
        widget = self.doc.widget
        key = self.pivot_combo.currentData()
        if widget is None:
            return
        if key == "custom":
            fx, fy = (
                PIVOT_FRACTIONS.get(widget.pivot, (0.5, 0.5))
                if isinstance(widget.pivot, str)
                else (0, 0)
            )
            self.set_field("pivot", {"x": round(widget.w * fx), "y": round(widget.h * fy)})
        else:
            self.set_field("pivot", key)

    def _pivot_point(self) -> None:
        if not self._loading and self.pivot_combo.currentData() == "custom":
            self.set_field("pivot", {"x": self.pivot_x.value(), "y": self.pivot_y.value()})

    def set_image(self, **fields: Any) -> bool:
        widget = self.doc.widget
        if self._loading or widget is None:
            return False
        settings = (widget.image or ImageSettings()).model_copy(update=fields)
        return self.set_field("image", settings.model_dump(), "Картинка")

    def _add_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Додати картинку", "", IMAGE_FILTER)
        if path:
            self.add_image_file(path)

    def add_image_file(self, path: str) -> bool:
        try:
            self.doc.add_image(path)
        except (ImageImportError, OSError) as error:
            self.error.setText(str(error))
            return False
        self.error.setText("")
        return True

    def _native_size(self) -> None:
        widget = self.doc.widget
        key = widget.image.file if widget and widget.image else None
        asset = self.doc.project.images.get(key or "")
        if widget is not None and asset is not None:
            self.doc.change_widget(
                widget.model_copy(update={"w": asset.width, "h": asset.height}), "Розмір"
            )

    def _delay_changed(self, value: int) -> None:
        widget = self.doc.widget
        key = widget.image.file if widget and widget.image else None
        if not self._loading and key and key in self.doc.project.images:
            self.doc.set_animation_delay(key, value)

    def set_chart(self, **fields: Any) -> bool:
        widget = self.doc.widget
        if self._loading or widget is None:
            return False
        chart = (widget.chart or ChartSettings()).model_copy(update=fields)
        return self.set_field("chart", chart.model_dump(), "Графік")

    def _bounds_edited(self) -> None:
        values: dict[str, float | None] = {}
        for field, edit in self.y_bounds.items():
            text = edit.text().strip().replace(",", ".")
            if not text:
                values[field] = None
                continue
            try:
                values[field] = float(text)
            except ValueError:
                self.error.setText(
                    f"{'Y мін' if field == 'y_min' else 'Y макс'}: «{text}» — не число"
                )
                return
        lo, hi = values["y_min"], values["y_max"]
        if lo is not None and hi is not None and not lo < hi:
            self.error.setText("Графік: Y мін має бути менше за Y макс")
            return
        self.error.setText("")
        self.set_chart(**values)

    # ------------------------------------------------------------------ pictures on the board
    def _board_clicked(self, item: QListWidgetItem) -> None:
        widget = self.doc.widget
        key = item.data(Qt.ItemDataRole.UserRole)
        asset = self.doc.project.images.get(key)
        if widget is not None and widget.bind and asset is not None:
            self.doc.set_test_value(widget.bind, asset.path)

    def _add_board_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Картинки на платі", "", IMAGE_FILTER)
        if paths:
            self.add_board_files(paths)

    def add_board_files(self, paths: list[str]) -> bool:
        try:
            self.doc.add_library_images(paths)
        except (ImageImportError, OSError) as error:
            self.error.setText(str(error))
            return False
        self.error.setText("")
        return True

    def _remove_board_file(self) -> None:
        item = self.board_list.currentItem()
        if item is not None:
            self.doc.remove_image(item.data(Qt.ItemDataRole.UserRole))
