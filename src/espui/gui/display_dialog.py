"""The "Display" dialog: panel, orientation, SPI, chip, driver, pins and memory."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from espui.core.checks import check_display
from espui.core.hardware import CHIP_RULES, Chip
from espui.core.models import (
    DEFAULT_BUF_BYTES,
    MAX_BUF_BYTES,
    MAX_IMAGE_CACHE,
    MIN_BUF_BYTES,
    Display,
    Pins,
)
from espui.displays import load_profiles
from espui.generators.micropython.drivers import DRIVERS

ROTATIONS = (
    (0, "0 — портрет 240×320"),
    (1, "1 — альбом 320×240"),
    (2, "2 — портрет, перевернутий"),
    (3, "3 — альбом, перевернутий"),
)
SPI_MHZ = (20, 40, 80)
# Module silk-screen -> Pins field (the dialog shows the names printed on the board).
PIN_LABELS = (
    ("SCL", "sck"),
    ("SDA", "mosi"),
    ("RES", "rst"),
    ("DC", "dc"),
    ("CS", "cs"),
    ("BLK", "bl"),
)

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


def display_label(display: Display) -> str:
    """Text of the toolbar button / status bar: ``GMT020-02-8B · ESP32-S3 · ui_st7789``."""
    driver = DRIVERS[display.driver.value]
    return f"{display.model} · {display.mcu.label} · {driver.module_file.removesuffix('.py')}"


class DisplayDialog(QDialog):
    def __init__(self, display: Display, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Дисплей")
        self._display = display

        self.model = QComboBox()
        for profile in load_profiles().values():
            self.model.addItem(profile.title, profile.model)
        self.model.setEnabled(False)
        future = QLabel("Інші дисплеї з'являться в наступних версіях.")
        future.setEnabled(False)

        self.rotation = QComboBox()
        for value, text in ROTATIONS:
            self.rotation.addItem(text, value)
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
        pins_box = QGroupBox("Піни")
        grid = QGridLayout(pins_box)
        values = display.pins.model_dump()
        for i, (label, field) in enumerate(PIN_LABELS):
            edit = QLineEdit("" if values[field] is None else str(values[field]))
            edit.setObjectName(f"pin_{field}")
            edit.setPlaceholderText("немає" if field == "bl" else "GPIO")
            edit.setMaximumWidth(70)
            self.pins[field] = edit
            grid.addWidget(QLabel(label), i // 3, (i % 3) * 2)
            grid.addWidget(edit, i // 3, (i % 3) * 2 + 1)
            edit.textChanged.connect(self._validate)

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
        form.addRow("", future)
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

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(pins_box)
        layout.addWidget(memory_box)
        layout.addWidget(self.errors)
        layout.addWidget(self.buttons)

        self.chip.currentIndexChanged.connect(self._chip_changed)
        for combo in (self.rotation, self.spi, self.driver):
            combo.currentIndexChanged.connect(self._validate)
        self._chip_changed()

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

    def _pins(self) -> tuple[dict[str, int | None], list[str]]:
        values: dict[str, int | None] = {}
        errors = []
        for label, field in PIN_LABELS:
            text = self.pins[field].text().strip()
            if not text:
                if field == "bl":
                    values[field] = None
                    continue
                errors.append(f"{label}: вкажіть номер GPIO")
                values[field] = 0
                continue
            try:
                values[field] = int(text)
            except ValueError:
                errors.append(f"{label}: «{text}» — не число")
                values[field] = 0
                continue
            if values[field] < 0:  # type: ignore[operator]
                errors.append(f"{label}: номер GPIO не може бути від'ємним")
                values[field] = 0
        return values, errors

    def display(self) -> Display:
        """The display as currently set in the dialog (pins may be invalid)."""
        pins, _ = self._pins()
        return Display.model_validate(
            {
                **self._display.model_dump(),
                "rotation": self.rotation.currentData(),
                "spi_hz": self.spi.currentData(),
                "mcu": self.chip.currentData(),
                "driver": self.driver.currentData(),
                "pins": Pins.model_validate(pins),
                "buf_bytes": self._memory_bytes()[0],
                "image_cache": self._memory_bytes()[1],
            }
        )

    def problems(self) -> list[str]:
        """All problems at once: missing numbers, then pins per chip, duplicates, driver."""
        _, errors = self._pins()
        if errors:
            return errors
        labels = {field: label for label, field in PIN_LABELS}
        out = []
        for issue in check_display(self.display(), ("display",)):
            field = issue.path.rsplit(".", 1)[-1]
            name = labels.get(field, field)
            out.append(f"{name}: {issue.message}")
        return out

    def _validate(self) -> None:
        info = DRIVERS[self.driver.currentData()]
        self.driver_card.setText(
            "<b>Прошивка:</b> стандартний MicroPython<br>"
            f"<b>Файли в папці генерації:</b> {', '.join(info.files)}<br>"
            f"<b>Швидкість:</b> {info.speed}<br>{info.note}"
        )
        self.memory_note.setText(self._memory_text())
        problems = self.problems()
        self.errors.setText("\n".join(problems))
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(not problems)
