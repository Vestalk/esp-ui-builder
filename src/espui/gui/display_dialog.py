"""The "Display" dialog: panel, orientation, SPI, chip, driver, pins and memory."""

from __future__ import annotations

import re
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from espui.core.checks import check_display
from espui.core.hardware import CHIP_RULES, Chip, Driver, driver_drives
from espui.core.models import (
    DEFAULT_BUF_BYTES,
    MAX_BUF_BYTES,
    MAX_IMAGE_CACHE,
    MIN_BUF_BYTES,
    CustomPanel,
    Display,
    Pins,
    SdCard,
    Touch,
)
from espui.displays import CONTROLLERS, CUSTOM_MODEL, load_profiles
from espui.generators.micropython.drivers import DRIVERS

ROTATION_NAMES = ("портрет", "альбом", "портрет, перевернутий", "альбом, перевернутий")
COLOR_ORDERS = ((None, "як у контролера"), (False, "RGB"), (True, "BGR (червоний ↔ синій)"))


def rotation_text(rotation: int, size: tuple[int, int]) -> str:
    """``1 — альбом 480×320``."""
    w, h = (size[1], size[0]) if rotation % 2 else size
    return f"{rotation} — {ROTATION_NAMES[rotation]} {w}×{h}"


SPI_MHZ = (20, 40, 80)
# Module silk-screen -> Pins field (the dialog shows the names printed on the board).
PIN_LABELS = (
    ("SCL", "sck"),
    ("SDA", "mosi"),
    ("RES", "rst"),
    ("DC", "dc"),
    ("CS", "cs"),
    ("BLK", "bl"),
    ("MISO", "miso"),
)
OPTIONAL_PINS = frozenset({"cs", "rst", "bl", "miso"})
"""May stay empty: the module has no such pin (MISO: only for a touch panel / SD card)."""
TOUCH_KINDS = ((None, "немає"), ("xpt2046", "XPT2046 — резистивний, SPI"),
               ("cst816s", "CST816S — ємнісний, I2C"))  # fmt: skip
# (label, Touch field, which kinds, suggested GPIO on ESP32-S3)
TOUCH_PINS = (
    ("T_CS", "cs", "xpt2046", 14),
    ("T_IRQ", "irq", "xpt2046", 15),
    ("SDA", "sda", "cst816s", 16),
    ("SCL", "scl", "cst816s", 17),
    ("INT", "irq", "cst816s", 18),
    ("RST", "rst", "cst816s", None),
)
OPTIONAL_TOUCH = frozenset({"irq", "rst"})
SUGGESTED_MISO = 13
SUGGESTED_SD_CS = 21


def parse_pin(text: str, label: str, optional: bool) -> tuple[int | None, str | None]:
    """(GPIO or None, problem or None) of a pin field."""
    text = text.strip()
    if not text:
        return None, None if optional else f"{label}: вкажіть номер GPIO"
    try:
        value = int(text)
    except ValueError:
        return None, f"{label}: «{text}» — не число"
    if value < 0:
        return None, f"{label}: номер GPIO не може бути від'ємним"
    return value, None


KB = 1024
MB = 1024 * KB
SCREEN = -1
"""Stands for "a whole screen" in MEMORY_PRESETS (2 * width * height of the panel)."""
# (title, region buffer, picture cache): typical boards; anything else is "Своє".
MEMORY_PRESETS = (
    ("Без PSRAM — буфер 16 КБ, без кешу (типово)", DEFAULT_BUF_BYTES, 0),
    ("Без PSRAM, більше RAM — буфер 32 КБ", 32 * KB, 0),
    ("PSRAM 2 МБ — буфер на весь екран, кеш 1 МБ", SCREEN, 1 * MB),
    ("PSRAM 8 МБ — буфер на весь екран, кеш 4 МБ", SCREEN, 4 * MB),
)
CUSTOM = "Своє"
PSRAM_HINT = 32 * KB
"""Bigger region buffers need PSRAM (docs/benchmarks.md)."""


def field_label(path: str) -> str:
    """``display.touch.cs`` -> ``Сенсор T_CS``, ``display.pins.rst`` -> ``RES``."""
    parts = path.split(".")
    field = parts[-1]
    if "touch" in parts:
        names = {f: label for label, f, kind, _s in TOUCH_PINS if kind != "cst816s" or f != "irq"}
        names.update({"sda": "SDA", "scl": "SCL", "rst": "RST", "x_max": "калібрування"})
        return f"Сенсор {names.get(field, field)}"
    if "sd" in parts:
        return "SD_CS" if field == "cs" else f"SD {field}"
    return {f: label for label, f in PIN_LABELS}.get(field, field)


def display_label(display: Display) -> str:
    """Text of the toolbar button / status bar: ``GMT020-02-8B · ESP32-S3 · ui_st7789``."""
    driver = DRIVERS[display.driver.value]
    module = driver.files_for(display.profile.controller)[-1].removesuffix(".py")
    name = (
        f"{display.profile.width}×{display.profile.height} {display.profile.controller}"
        if display.model == CUSTOM_MODEL
        else display.model
    )
    return f"{name} · {display.mcu.label} · {module}"


class DisplayDialog(QDialog):
    def __init__(self, display: Display, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Дисплей")
        self._display = display

        self.model = QComboBox()
        self.model.setObjectName("model")
        for profile in load_profiles().values():
            self.model.addItem(profile.title, profile.model)
        self.model.addItem("Свій розмір…", CUSTOM_MODEL)
        self.model.setCurrentIndex(max(0, self.model.findData(display.model)))

        custom = display.custom or CustomPanel()
        self.custom_box = QGroupBox("Свій дисплей")
        self.custom_box.setObjectName("custom_box")
        cform = QFormLayout(self.custom_box)
        self.controller = QComboBox()
        self.controller.setObjectName("controller")
        for ctl_key, ctl in CONTROLLERS.items():
            self.controller.addItem(ctl.title, ctl_key)
        self.controller.setCurrentIndex(max(0, self.controller.findData(custom.controller)))
        self.custom_w = self._spin(16, 800, custom.width, "custom_w")
        self.custom_h = self._spin(16, 800, custom.height, "custom_h")
        self.offset_x = self._spin(0, 400, custom.x_offset, "offset_x")
        self.offset_y = self._spin(0, 400, custom.y_offset, "offset_y")
        self.color_order = QComboBox()
        self.color_order.setObjectName("color_order")
        for order, order_text in COLOR_ORDERS:
            self.color_order.addItem(order_text, order)
        self.color_order.setCurrentIndex(max(0, [v for v, _ in COLOR_ORDERS].index(custom.bgr)))
        self.round_panel = QCheckBox("Круглий (видно лише вписане коло)")
        self.round_panel.setObjectName("round_panel")
        self.round_panel.setChecked(custom.round)
        size_row = QWidget()
        size_layout = QGridLayout(size_row)
        size_layout.setContentsMargins(0, 0, 0, 0)
        size_layout.addWidget(self.custom_w, 0, 0)
        size_layout.addWidget(QLabel("×"), 0, 1)
        size_layout.addWidget(self.custom_h, 0, 2)
        offset_row = QWidget()
        offset_layout = QGridLayout(offset_row)
        offset_layout.setContentsMargins(0, 0, 0, 0)
        offset_layout.addWidget(self.offset_x, 0, 0)
        offset_layout.addWidget(QLabel("/"), 0, 1)
        offset_layout.addWidget(self.offset_y, 0, 2)
        cform.addRow("Контролер", self.controller)
        cform.addRow("Розмір (портрет), px", size_row)
        cform.addRow("Зсув у пам'яті x / y", offset_row)
        cform.addRow("Порядок кольорів", self.color_order)
        cform.addRow("", self.round_panel)
        hint = QLabel(
            "Зсув потрібен, коли панель менша за пам'ять контролера (напр. 135×240 ST7789: "
            "52 / 40). Якщо червоний і синій переплутані — змініть порядок кольорів."
        )
        hint.setWordWrap(True)
        hint.setEnabled(False)
        cform.addRow(hint)

        self.invert = QCheckBox("Інверсія кольорів")
        self.invert.setObjectName("invert")
        self.invert.setToolTip("Увімкніть, якщо на платі кольори «негативні» (білий — чорний)")
        self.invert.setChecked(display.inverted)
        self._invert_touched = display.invert is not None

        self.rotation = QComboBox()
        for rot in range(4):
            self.rotation.addItem(rotation_text(rot, display.profile.size(0)), rot)
        self.rotation.setCurrentIndex(display.rotation)

        self.spi = QComboBox()
        for mhz in SPI_MHZ:
            self.spi.addItem(f"{mhz} МГц", mhz * 1_000_000)
        index = self.spi.findData(display.spi_hz)
        if index < 0:
            self.spi.addItem(f"{display.spi_hz / 1_000_000:g} МГц", display.spi_hz)
            index = self.spi.count() - 1
        self.spi.setCurrentIndex(index)

        self.chip = QComboBox()
        for chip in Chip:
            self.chip.addItem(CHIP_RULES[chip].label, chip.value)
        self.chip.setCurrentIndex(self.chip.findData(display.mcu.value))

        self.driver = QComboBox()
        for info in DRIVERS.values():
            self.driver.addItem(info.title, info.key)
        self.driver.setCurrentIndex(self.driver.findData(display.driver.value))
        self.driver_card = QLabel()
        self.driver_card.setWordWrap(True)
        self.driver_card.setTextFormat(Qt.TextFormat.RichText)

        self.pins: dict[str, QLineEdit] = {}
        self.pin_labels: dict[str, QLabel] = {}
        pins_box = QGroupBox("Піни")
        grid = QGridLayout(pins_box)
        values = display.pins.model_dump()
        for i, (label, field) in enumerate(PIN_LABELS):
            edit = QLineEdit("" if values[field] is None else str(values[field]))
            edit.setObjectName(f"pin_{field}")
            edit.setPlaceholderText("немає" if field in OPTIONAL_PINS else "GPIO")
            edit.setMaximumWidth(70)
            self.pins[field] = edit
            caption = QLabel(label)
            self.pin_labels[field] = caption
            grid.addWidget(caption, i // 3, (i % 3) * 2)
            grid.addWidget(edit, i // 3, (i % 3) * 2 + 1)
            edit.textChanged.connect(self._validate)
        miso_tip = "Спільний для сенсора XPT2046 і SD-карти: по ньому вони відповідають платі"
        self.pins["miso"].setToolTip(miso_tip)
        self.pin_labels["miso"].setToolTip(miso_tip)

        memory_box = QGroupBox("Пам'ять")
        memory = QFormLayout(memory_box)
        self.memory = QComboBox()
        self.memory.setObjectName("memory_preset")
        for title, _, _ in MEMORY_PRESETS:
            self.memory.addItem(title)
        self.memory.addItem(CUSTOM)
        self.buffer_kb = QSpinBox()
        self.buffer_kb.setObjectName("buffer_kb")
        self.buffer_kb.setRange(MIN_BUF_BYTES // KB, MAX_BUF_BYTES // KB)
        self.buffer_kb.setSuffix(" КБ")
        self.buffer_kb.setToolTip(
            "Скільки RAM на одну смугу області, що перемальовується. Більше — менше смуг\n"
            "і плавніша зміна; весь екран потребує PSRAM. Більше за екран не виділяється."
        )
        self.cache_kb = QSpinBox()
        self.cache_kb.setObjectName("cache_kb")
        self.cache_kb.setRange(0, MAX_IMAGE_CACHE // KB)
        self.cache_kb.setSingleStep(256)
        self.cache_kb.setSuffix(" КБ")
        self.cache_kb.setSpecialValueText("вимкнено")
        self.cache_kb.setToolTip(
            "Картинки, прочитані один раз, лишаються в RAM: перемальовування над ними\n"
            "в кілька разів швидше. Лише для плат з PSRAM; що не влазить — читається з флешу."
        )
        self.memory_note = QLabel()
        self.memory_note.setObjectName("memory_note")
        self.memory_note.setWordWrap(True)
        memory.addRow("Плата", self.memory)
        memory.addRow("Буфер області", self.buffer_kb)
        memory.addRow("Кеш картинок", self.cache_kb)
        memory.addRow("", self.memory_note)
        self.buffer_kb.setValue(max(1, display.buf_bytes // KB))
        self.cache_kb.setValue(display.image_cache // KB)
        self.memory.setCurrentIndex(self._preset_index())
        self.memory.currentIndexChanged.connect(self._preset_chosen)
        self.buffer_kb.valueChanged.connect(self._memory_edited)
        self.cache_kb.valueChanged.connect(self._memory_edited)

        self.errors = QLabel()
        self.errors.setObjectName("errors")
        self.errors.setWordWrap(True)
        self.errors.setStyleSheet("color: #c0392b")

        form = QFormLayout()
        form.addRow("Модель", self.model)
        form.addRow(self.custom_box)
        form.addRow("", self.invert)
        form.addRow("Орієнтація", self.rotation)
        form.addRow("Частота SPI", self.spi)
        form.addRow("Чип", self.chip)
        form.addRow("Драйвер", self.driver)
        form.addRow("", self.driver_card)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        content = QWidget()
        column = QVBoxLayout(content)
        column.addLayout(form)
        column.addWidget(pins_box)
        column.addWidget(self._build_touch(display))
        column.addWidget(self._build_sd(display))
        column.addWidget(memory_box)
        column.addStretch(1)
        # Taller than a laptop screen with every option shown: the settings scroll,
        # the problems and OK / Cancel stay in view.
        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.settings_scroll.setWidget(content)
        layout = QVBoxLayout(self)
        layout.addWidget(self.settings_scroll, 1)
        self._show_miso()
        layout.addWidget(self.errors)
        layout.addWidget(self.buttons)
        self.resize(560, 760)

        self.chip.currentIndexChanged.connect(self._chip_changed)
        for combo in (self.rotation, self.spi, self.driver):
            combo.currentIndexChanged.connect(self._validate)
        for widget in (self.model, self.controller, self.color_order):
            widget.currentIndexChanged.connect(self._panel_changed)
        for spin in (self.custom_w, self.custom_h, self.offset_x, self.offset_y):
            spin.valueChanged.connect(self._panel_changed)
        self.round_panel.toggled.connect(self._panel_changed)
        self.invert.toggled.connect(self._invert_toggled)
        self._panel_changed()
        self._chip_changed()

    @staticmethod
    def _spin(lo: int, hi: int, value: int, name: str) -> QSpinBox:
        spin = QSpinBox()
        spin.setObjectName(name)
        spin.setRange(lo, hi)
        spin.setValue(value)
        return spin

    # ------------------------------------------------------------------ panel
    def _custom(self) -> CustomPanel:
        return CustomPanel(
            controller=self.controller.currentData(),
            width=self.custom_w.value(),
            height=self.custom_h.value(),
            x_offset=self.offset_x.value(),
            y_offset=self.offset_y.value(),
            bgr=self.color_order.currentData(),
            round=self.round_panel.isChecked(),
        )

    def _panel(self) -> Display:
        """The display with the chosen panel (model / custom) and the profile's inversion."""
        model = self.model.currentData()
        return Display.model_validate(
            {
                **self._display.model_dump(),
                "model": model,
                "custom": self._custom() if model == CUSTOM_MODEL else None,
                "invert": None,
            }
        )

    def _invert_toggled(self) -> None:
        self._invert_touched = True
        self._validate()

    def _panel_changed(self) -> None:
        """Another panel: its sizes in the orientations, its inversion, the drivers it allows."""
        panel = self._panel()
        self.custom_box.setVisible(panel.model == CUSTOM_MODEL)
        size = panel.profile.size(0)
        for rot in range(4):
            self.rotation.setItemText(rot, rotation_text(rot, size))
        if not self._invert_touched:
            self.invert.blockSignals(True)
            self.invert.setChecked(panel.profile.invert)
            self.invert.blockSignals(False)
        controller = panel.profile.controller
        model = self.driver.model()
        for row in range(self.driver.count()):
            key = self.driver.itemData(row)
            item = model.item(row)  # type: ignore[attr-defined]
            drives = driver_drives(Driver(key), controller)
            item.setEnabled(drives and DRIVERS[key].supports(Chip(self.chip.currentData())))
            if not drives:
                item.setToolTip(f"не працює з {controller}")
        if not driver_drives(Driver(self.driver.currentData()), controller):
            self.driver.setCurrentIndex(self.driver.findData(Driver.BUILTIN.value))
        self._validate()

    # ------------------------------------------------------------------ memory
    def _screen_bytes(self) -> int:
        return self._display.screen_bytes

    def _preset_bytes(self, index: int) -> tuple[int, int]:
        _, buffer, cache = MEMORY_PRESETS[index]
        return (self._screen_bytes() if buffer == SCREEN else buffer), cache

    def _memory_bytes(self) -> tuple[int, int]:
        """(region buffer, picture cache) in bytes as set in the dialog."""
        buffer = self.buffer_kb.value() * KB
        screen = self._screen_bytes()
        if buffer >= screen:
            buffer = screen  # "весь екран" stays exact (150 КБ = 153 600 bytes)
        return buffer, self.cache_kb.value() * KB

    def _preset_index(self) -> int:
        current = self._memory_bytes()
        for i in range(len(MEMORY_PRESETS)):
            if self._preset_bytes(i) == current:
                return i
        return len(MEMORY_PRESETS)  # "Своє"

    def _preset_chosen(self, index: int) -> None:
        if index >= len(MEMORY_PRESETS):
            return  # "Своє": keep the numbers
        buffer, cache = self._preset_bytes(index)
        for spin, value in ((self.buffer_kb, buffer), (self.cache_kb, cache)):
            spin.blockSignals(True)
            spin.setValue(-(-value // KB))
            spin.blockSignals(False)
        self._validate()

    def _memory_edited(self) -> None:
        self.memory.blockSignals(True)
        self.memory.setCurrentIndex(self._preset_index())
        self.memory.blockSignals(False)
        self._validate()

    def _memory_text(self) -> str:
        buffer, cache = self._memory_bytes()
        screen = self._screen_bytes()
        width = self._display.profile.width
        if buffer >= screen:
            strips = "весь екран за раз"
        else:
            rows = buffer // (2 * width)
            strips = f"смуги по ~{rows} рядків на всю ширину"
        text = f"Буфер: {strips} (екран = {screen // KB} КБ)."
        if buffer > PSRAM_HINT or cache:
            text += " Потрібна плата з PSRAM."
        return text

    # ------------------------------------------------------------------ state
    def _chip_changed(self) -> None:
        """Drivers that don't support the chip are disabled with an explanation."""
        chip = Chip(self.chip.currentData())
        model = self.driver.model()
        for row in range(self.driver.count()):
            info = DRIVERS[self.driver.itemData(row)]
            item = model.item(row)  # type: ignore[attr-defined]
            supported = info.supports(chip)
            item.setEnabled(supported)
            item.setToolTip("" if supported else f"не підтримує {chip.label}")
        if not DRIVERS[self.driver.currentData()].supports(chip):
            for row in range(self.driver.count()):
                if DRIVERS[self.driver.itemData(row)].supports(chip):
                    self.driver.setCurrentIndex(row)
                    break
        self._validate()

    # ------------------------------------------------------------------ touch / SD
    def _build_touch(self, display: Display) -> QGroupBox:
        touch = display.touch
        box = QGroupBox("Сенсорний екран")
        box.setObjectName("touch_box")
        form = self.touch_form = QFormLayout(box)
        self.touch_kind = QComboBox()
        self.touch_kind.setObjectName("touch_kind")
        for kind, text in TOUCH_KINDS:
            self.touch_kind.addItem(text, kind)
        self.touch_kind.setCurrentIndex(
            max(0, self.touch_kind.findData(touch.kind if touch else None))
        )
        form.addRow("Чип", self.touch_kind)
        self.touch_pins: dict[tuple[str, str], QLineEdit] = {}
        for label, field, kind, suggested in TOUCH_PINS:
            value = getattr(touch, field) if touch is not None and touch.kind == kind else None
            edit = QLineEdit("" if value is None else str(value))
            edit.setObjectName(f"touch_{kind}_{field}")
            edit.setPlaceholderText("немає" if field in OPTIONAL_TOUCH else "GPIO")
            edit.setMaximumWidth(70)
            edit.setProperty("suggested", suggested)
            edit.textChanged.connect(self._validate)
            self.touch_pins[(kind, field)] = edit
            form.addRow(label, edit)
        cal = touch or Touch()
        self.calibration: dict[str, QSpinBox] = {}
        cal_row = QWidget()
        cal_grid = QGridLayout(cal_row)
        cal_grid.setContentsMargins(0, 0, 0, 0)
        for row, (axis, low, high) in enumerate(
            (("X: ліво → право", "x_min", "x_max"), ("Y: верх → низ", "y_min", "y_max"))
        ):
            cal_grid.addWidget(QLabel(axis), row, 0)
            for col, field in enumerate((low, high)):
                spin = self._spin(0, 4095, getattr(cal, field), f"cal_{field}")
                spin.valueChanged.connect(self._validate)
                self.calibration[field] = spin
                cal_grid.addWidget(spin, row, 1 + col)
        self.cal_row = cal_row
        form.addRow("Калібрування", cal_row)
        self.swap_xy = QCheckBox("Осі X і Y переставлені")
        self.swap_xy.setObjectName("swap_xy")
        self.swap_xy.setChecked(cal.swap_xy)
        self.swap_xy.toggled.connect(self._validate)
        form.addRow("", self.swap_xy)
        self.touch_hint = QLabel()
        self.touch_hint.setWordWrap(True)
        self.touch_hint.setEnabled(False)
        form.addRow(self.touch_hint)
        self.touch_kind.currentIndexChanged.connect(self._touch_kind_changed)
        self._show_touch_rows()
        return box

    def _show_touch_rows(self) -> None:
        kind = self.touch_kind.currentData()
        for (pin_kind, _field), edit in self.touch_pins.items():
            self.touch_form.setRowVisible(edit, pin_kind == kind)
        for row in (self.cal_row, self.swap_xy):
            self.touch_form.setRowVisible(row, kind == "xpt2046")
        self.touch_hint.setText(
            {
                None: "Звичайний дисплей без сенсора.",
                "xpt2046": "T_CLK, T_DIN, T_DO — на SCL, SDA і MISO дисплея (спільна шина). "
                "Калібрування — сирі значення на краях екрана в портреті; поміняйте "
                "місцями, щоб віддзеркалити вісь.",
                "cst816s": "Окрема шина I2C (SDA, SCL); INT і RST — за бажанням.",
            }[kind]
        )

    def _touch_kind_changed(self) -> None:
        """A new touch chip: suggested free pins, MISO for the SPI one."""
        kind = self.touch_kind.currentData()
        for (pin_kind, _field), edit in self.touch_pins.items():
            suggested = edit.property("suggested")
            if pin_kind == kind and not edit.text() and suggested is not None:
                edit.setText(str(suggested))
        if kind == "xpt2046":
            self._suggest_miso()
        self._show_touch_rows()
        self._show_miso()
        self._validate()

    def miso_needed(self) -> bool:
        """MISO is shown (and used) only with an XPT2046 touch panel or an SD card."""
        return self.touch_kind.currentData() == "xpt2046" or self.sd_enabled.isChecked()

    def _show_miso(self) -> None:
        needed = self.miso_needed()
        self.pins["miso"].setVisible(needed)
        self.pin_labels["miso"].setVisible(needed)

    def _suggest_miso(self) -> None:
        if not self.pins["miso"].text().strip():
            self.pins["miso"].setText(str(SUGGESTED_MISO))

    def _build_sd(self, display: Display) -> QGroupBox:
        sd = display.sd
        box = QGroupBox("SD-карта")
        box.setObjectName("sd_box")
        form = QFormLayout(box)
        self.sd_enabled = QCheckBox("Слот microSD на модулі")
        self.sd_enabled.setObjectName("sd_enabled")
        self.sd_enabled.setChecked(sd is not None)
        self.sd_cs = QLineEdit("" if sd is None else str(sd.cs))
        self.sd_cs.setObjectName("sd_cs")
        self.sd_cs.setPlaceholderText("GPIO")
        self.sd_cs.setMaximumWidth(70)
        self.sd_mount = QLineEdit("/sd" if sd is None else sd.mount)
        self.sd_mount.setObjectName("sd_mount")
        self.sd_mount.setMaximumWidth(120)
        hint = QLabel(
            "SD_SCK, SD_MOSI, SD_MISO — на SCL, SDA і MISO дисплея (спільна шина SPI). "
            "Картка має бути FAT32; на платі: ui_display.mount_sd(display)."
        )
        hint.setWordWrap(True)
        hint.setEnabled(False)
        form.addRow("", self.sd_enabled)
        form.addRow("SD_CS", self.sd_cs)
        form.addRow("Шлях на платі", self.sd_mount)
        form.addRow(hint)
        self.sd_rows = (self.sd_cs, self.sd_mount, hint)
        for row in self.sd_rows:
            form.setRowVisible(row, sd is not None)
        self.sd_form = form
        self.sd_enabled.toggled.connect(self._sd_toggled)
        self.sd_cs.textChanged.connect(self._validate)
        self.sd_mount.textChanged.connect(self._validate)
        return box

    def _sd_toggled(self, on: bool) -> None:
        for row in self.sd_rows:
            self.sd_form.setRowVisible(row, on)
        if on:
            if not self.sd_cs.text().strip():
                self.sd_cs.setText(str(SUGGESTED_SD_CS))
            self._suggest_miso()
        self._show_miso()
        self._validate()

    def _touch(self) -> tuple[Touch | None, list[str]]:
        kind = self.touch_kind.currentData()
        if kind is None:
            return None, []
        values: dict[str, Any] = {"kind": kind, "swap_xy": self.swap_xy.isChecked()}
        errors = []
        for label, field, pin_kind, _suggested in TOUCH_PINS:
            if pin_kind != kind:
                continue
            value, problem = parse_pin(
                self.touch_pins[(pin_kind, field)].text(), f"Сенсор {label}", True
            )
            if problem:
                errors.append(problem)
            values[field] = value
        for field, spin in self.calibration.items():
            values[field] = spin.value()
        return Touch.model_validate(values), errors

    def _sd(self) -> tuple[SdCard | None, list[str]]:
        if not self.sd_enabled.isChecked():
            return None, []
        cs, problem = parse_pin(self.sd_cs.text(), "SD_CS", False)
        mount = self.sd_mount.text().strip()
        errors = [problem] if problem else []
        if not re.fullmatch(r"/[A-Za-z0-9_]{1,16}", mount):
            errors.append("SD: шлях на платі — як /sd (латиниця, цифри, _)")
            mount = "/sd"
        if cs is None:
            return None, errors
        return SdCard(cs=cs, mount=mount), errors

    def _pins(self) -> tuple[dict[str, int | None], list[str]]:
        values: dict[str, int | None] = {}
        errors = []
        for label, field in PIN_LABELS:
            if field == "miso" and not self.miso_needed():
                values[field] = None  # hidden: nothing on the bus answers the board
                continue
            value, problem = parse_pin(self.pins[field].text(), label, field in OPTIONAL_PINS)
            if problem:
                errors.append(problem)
                value = 0
            values[field] = value
        return values, errors

    def display(self) -> Display:
        """The display as currently set in the dialog (pins may be invalid)."""
        pins, _ = self._pins()
        panel = self._panel()
        invert = self.invert.isChecked()
        return Display.model_validate(
            {
                **self._display.model_dump(),
                "model": panel.model,
                "custom": panel.custom,
                "invert": None if invert == panel.profile.invert else invert,
                "rotation": self.rotation.currentData(),
                "spi_hz": self.spi.currentData(),
                "mcu": self.chip.currentData(),
                "driver": self.driver.currentData(),
                "pins": Pins.model_validate(pins),
                "touch": self._touch()[0],
                "sd": self._sd()[0],
                "buf_bytes": self._memory_bytes()[0],
                "image_cache": self._memory_bytes()[1],
            }
        )

    def problems(self) -> list[str]:
        """All problems at once: missing numbers, then pins per chip, duplicates, driver."""
        errors = self._pins()[1] + self._touch()[1] + self._sd()[1]
        if errors:
            return errors
        out = []
        for issue in check_display(self.display(), ("display",)):
            out.append(f"{field_label(issue.path)}: {issue.message}")
        return out

    def _validate(self) -> None:
        info = DRIVERS[self.driver.currentData()]
        self.driver_card.setText(
            "<b>Прошивка:</b> стандартний MicroPython<br>"
            f"<b>Файли в папці генерації:</b> "
            f"{', '.join(info.files_for(self._panel().profile.controller))}<br>"
            f"<b>Швидкість:</b> {info.speed}<br>{info.note}"
        )
        self.memory_note.setText(self._memory_text())
        problems = self.problems()
        self.errors.setText("\n".join(problems))
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(not problems)
