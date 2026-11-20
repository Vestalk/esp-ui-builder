"""The "Display" dialog: panel, orientation, SPI, chip, driver and pins."""

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
    QVBoxLayout,
    QWidget,
)

from espui.core.checks import check_display
from espui.core.hardware import CHIP_RULES, Chip
from espui.core.models import Display, Pins
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
        layout.addWidget(self.errors)
        layout.addWidget(self.buttons)

        self.chip.currentIndexChanged.connect(self._chip_changed)
        for combo in (self.rotation, self.spi, self.driver):
            combo.currentIndexChanged.connect(self._validate)
        self._chip_changed()

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
        problems = self.problems()
        self.errors.setText("\n".join(problems))
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(not problems)
