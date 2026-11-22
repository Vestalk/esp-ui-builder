"""Registry of the Python display drivers the MicroPython generator can ship.

Single source of truth for the driver key stored in a project, the files copied
into the generated folder, supported chips and the texts of the "Display"
dialog. Adding a driver = adding its runtime file, an adapter function in
``runtime/ui_display.py`` and a :class:`DriverInfo` entry here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from espui.core.hardware import Chip

RUNTIME_DIR = Path(__file__).with_name("runtime")
ADAPTER_FILE = "ui_display.py"
ALL_CHIPS = frozenset(Chip)


class UnknownDriverError(ValueError):
    def __init__(self, key: str) -> None:
        super().__init__(f"unknown display driver {key!r}; known: {', '.join(DRIVERS)}")
        self.key = key


@dataclass(frozen=True, slots=True)
class DriverInfo:
    key: str
    title: str
    module_file: str
    chips: frozenset[Chip]
    license: str
    origin: str
    speed: str
    note: str
    license_file: str | None = None
    sha256: str | None = None
    """Pinned hash of a vendored third-party file; it must be shipped unchanged."""
    controllers: frozenset[str] = frozenset({"ST7789"})
    """Display controllers it can drive."""
    other_module_file: str | None = None
    """Module for the controllers other than ST7789 (the built-in driver: ui_tft.py)."""

    @property
    def files(self) -> tuple[str, ...]:
        """Runtime files copied into the generated project for an ST7789 panel."""
        return (ADAPTER_FILE, self.module_file)

    def files_for(self, controller: str) -> tuple[str, ...]:
        """Runtime files copied into the generated project for ``controller``."""
        if controller != "ST7789" and self.other_module_file:
            return (ADAPTER_FILE, self.other_module_file)
        return self.files

    def supports(self, chip: Chip) -> bool:
        return chip in self.chips

    def drives(self, controller: str) -> bool:
        return controller in self.controllers


DEFAULT_DRIVER = "builtin"

# Speed texts are estimates until docs/benchmarks.md is filled in on hardware.
DRIVERS: Mapping[str, DriverInfo] = MappingProxyType(
    {
        "builtin": DriverInfo(
            key="builtin",
            title="Вбудований (ui_st7789 / ui_tft)",
            module_file="ui_st7789.py",
            chips=ALL_CHIPS,
            license="MIT",
            origin="ESP UI Builder",
            speed="висока: області пишуться одним блоком, заливка смугами по 4 КБ",
            note=(
                "Рекомендований. Python + framebuf, стандартна прошивка. "
                "ST7789 — ui_st7789.py; ILI9488, ILI9341, GC9A01 — ui_tft.py."
            ),
            controllers=frozenset({"ST7789", "ILI9488", "ILI9341", "GC9A01"}),
            other_module_file="ui_tft.py",
        ),
        "st7789py": DriverInfo(
            key="st7789py",
            title="st7789py_mpy (russhughes)",
            module_file="st7789py.py",
            chips=ALL_CHIPS,
            license="MIT",
            origin="https://github.com/russhughes/st7789py_mpy @ 98bc3a1f",
            speed="нижча: заливка шматками по 512 Б, більший файл і більше RAM після імпорту",
            note=(
                "Сторонній Python-драйвер фіксованої версії; "
                "власні шрифти драйвера не використовуються."
            ),
            license_file="st7789py.LICENSE",
            sha256="a071cfc56a32006b3ddefcc1b68e158fbd7674df6a363cac59ea7ce9510ed958",
        ),
    }
)


def get_driver(key: str) -> DriverInfo:
    try:
        return DRIVERS[key]
    except KeyError:
        raise UnknownDriverError(key) from None


def runtime_file(name: str) -> Path:
    path = RUNTIME_DIR / name
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def drivers_for(chip: Chip) -> tuple[DriverInfo, ...]:
    return tuple(info for info in DRIVERS.values() if info.supports(chip))
