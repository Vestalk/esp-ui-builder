"""Target hardware vocabulary shared by the model, generators and GUI.

Only domain facts live here (chips, their GPIO rules, driver keys and which
chips a driver supports). What a driver ships as files is the generator's
business (``espui.generators.micropython.drivers``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from espui.i18n import tr


class Chip(StrEnum):
    """Microcontrollers a project can target (``display.mcu`` in ``.espui``)."""

    ESP32S3 = "esp32s3"
    ESP32 = "esp32"
    ESP32C3 = "esp32c3"

    @property
    def label(self) -> str:
        return CHIP_RULES[self].label


@dataclass(frozen=True, slots=True)
class ChipPinRules:
    label: str
    max_gpio: int
    reserved: Mapping[int, str]
    """GPIO -> why it cannot be used (Ukrainian, shown to the user)."""
    input_only: frozenset[int] = field(default_factory=frozenset)

    def problem(self, gpio: int, input_only_ok: bool = False) -> str | None:
        """Ukrainian description of why ``gpio`` can't drive a display pin, or None.

        ``input_only_ok``: the pin is only read (MISO, an IRQ), input-only GPIOs suit it.
        """
        if not 0 <= gpio <= self.max_gpio:
            return tr("на {label} GPIO від 0 до {max_gpio}").format(
                label=self.label, max_gpio=self.max_gpio
            )
        if gpio in self.reserved:
            return tr("GPIO{gpio} зайнятий ({v1})").format(gpio=gpio, v1=self.reserved[gpio])
        if gpio in self.input_only and not input_only_ok:
            return tr("GPIO{gpio} на {label} працює лише на вхід").format(
                gpio=gpio, label=self.label
            )
        return None


def _reserved(pins: range | tuple[int, ...], why: str) -> dict[int, str]:
    return dict.fromkeys(pins, why)


CHIP_RULES: Mapping[Chip, ChipPinRules] = MappingProxyType(
    {
        Chip.ESP32S3: ChipPinRules("ESP32-S3", 48, _reserved((19, 20), "USB")),
        Chip.ESP32: ChipPinRules(
            "ESP32",
            39,
            _reserved(range(6, 12), tr("внутрішній флеш")),
            input_only=frozenset(range(34, 40)),
        ),
        Chip.ESP32C3: ChipPinRules(
            "ESP32-C3",
            21,
            {**_reserved(range(12, 18), tr("флеш")), **_reserved((18, 19), "USB")},
        ),
    }
)


class Driver(StrEnum):
    """Python display drivers (``display.driver`` in ``.espui``)."""

    BUILTIN = "builtin"
    ST7789PY = "st7789py"


DEFAULT_DRIVER = Driver.BUILTIN

DRIVER_CHIPS: Mapping[Driver, frozenset[Chip]] = MappingProxyType(
    {
        Driver.BUILTIN: frozenset(Chip),
        Driver.ST7789PY: frozenset(Chip),
    }
)


DRIVER_CONTROLLERS: Mapping[Driver, frozenset[str]] = MappingProxyType(
    {
        Driver.BUILTIN: frozenset({"ST7789", "ILI9488", "ILI9341", "GC9A01"}),
        Driver.ST7789PY: frozenset({"ST7789"}),
    }
)
"""Display controllers each driver can drive (generators.micropython.drivers agrees)."""


def driver_supports(driver: Driver, chip: Chip) -> bool:
    return chip in DRIVER_CHIPS[driver]


def driver_drives(driver: Driver, controller: str) -> bool:
    return controller in DRIVER_CONTROLLERS[driver]
