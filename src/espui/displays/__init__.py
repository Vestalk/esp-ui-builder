"""Display profiles: one YAML file per supported panel, loaded via importlib.resources.

Adding a display = dropping another ``*.yaml`` next to ``gmt020_02.yaml``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from types import MappingProxyType
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_MODEL = "GMT020-02-8B"
CUSTOM_MODEL = "custom"
"""``Display.model`` of a panel described by hand (``Display.custom``)."""

Controller = Literal["ST7789", "ILI9488", "ILI9341", "GC9A01"]


@dataclass(frozen=True, slots=True)
class ControllerInfo:
    """What a display controller chip can do, for the driver and the checks."""

    title: str
    ram: tuple[int, int]
    """Frame memory (width, height) in portrait: panel + offsets must fit in it."""
    color_format: Literal["RGB565", "RGB666"]
    """RGB666: 3 bytes per pixel (ILI9488 over SPI has no 16-bit mode)."""
    madctl: tuple[int, int, int, int]
    """MADCTL per rotation 0-3 without the BGR bit (MY=0x80, MX=0x40, MV=0x20)."""
    bgr: bool
    """Whether its panels usually want the BGR bit (0x08)."""
    invert: bool
    """Whether its panels usually need colour inversion (IPS ST7789 / GC9A01 do)."""


CONTROLLERS: Mapping[str, ControllerInfo] = MappingProxyType(
    {
        "ST7789": ControllerInfo(
            "ST7789", (240, 320), "RGB565", (0x00, 0x60, 0xC0, 0xA0), False, True
        ),
        "ILI9488": ControllerInfo(
            "ILI9488 (18-біт колір)", (320, 480), "RGB666", (0x40, 0x20, 0x80, 0xE0), True, False
        ),
        "ILI9341": ControllerInfo(
            "ILI9341", (240, 320), "RGB565", (0x40, 0x20, 0x80, 0xE0), True, False
        ),
        "GC9A01": ControllerInfo(
            "GC9A01 (круглий)", (240, 240), "RGB565", (0x40, 0x20, 0x80, 0xE0), True, True
        ),
    }
)


class SpiRange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    default: int = Field(gt=0)
    max: int = Field(gt=0)


class DisplayProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str
    title: str
    controller: Controller
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    color_format: Literal["RGB565", "RGB666"]
    interface: str
    invert: bool
    spi_hz: SpiRange
    default_pins: dict[str, int | None]
    x_offset: int = Field(0, ge=0)
    """Where the panel starts in the controller's memory (portrait), e.g. 240×240 ST7789."""
    y_offset: int = Field(0, ge=0)
    bgr: bool | None = None
    """Colour order bit; None = the controller's usual one."""
    shape: Literal["rect", "round"] = "rect"
    """A round panel shows only the circle inscribed in its square."""
    touch: Literal["xpt2046", "cst816s"] | None = None
    """The touch panel modules of this model usually carry (suggested in "Дисплей")."""
    board: str | None = None
    """A board with the display built in (e.g. the CYD): its chip ("esp32"); choosing
    the model sets the chip, the pins and the touch panel as wired on the board."""
    touch_pins: dict[str, int | None] | None = None
    """The touch panel's wiring on such a board (cs, irq, and sck/mosi/miso of its own bus)."""

    def size(self, rotation: int) -> tuple[int, int]:
        """Logical (width, height) for ``rotation`` 0-3."""
        return (self.height, self.width) if rotation % 2 else (self.width, self.height)

    @property
    def controller_info(self) -> ControllerInfo:
        return CONTROLLERS[self.controller]

    @property
    def uses_bgr(self) -> bool:
        return self.controller_info.bgr if self.bgr is None else self.bgr

    def rotation_table(self) -> tuple[tuple[int, int, int, int, int], ...]:
        """(madctl, width, height, x_offset, y_offset) per rotation 0-3, as the driver wants.

        The offsets move with the rotation: turned by 180° the panel sits at the
        other end of the controller's memory.
        """
        info = self.controller_info
        ram_w, ram_h = info.ram
        w, h, ox, oy = self.width, self.height, self.x_offset, self.y_offset
        bgr = 0x08 if self.uses_bgr else 0
        far_x, far_y = ram_w - w - ox, ram_h - h - oy
        sizes = (
            (w, h, ox, oy),
            (h, w, oy, far_x),
            (w, h, far_x, far_y),
            (h, w, far_y, ox),
        )
        return tuple((madctl | bgr, *size) for madctl, size in zip(info.madctl, sizes, strict=True))


def custom_profile(
    controller: str,
    width: int,
    height: int,
    *,
    x_offset: int = 0,
    y_offset: int = 0,
    invert: bool | None = None,
    bgr: bool | None = None,
    round_panel: bool = False,
) -> DisplayProfile:
    """The profile of a panel described by hand ("Свій розмір")."""
    info = CONTROLLERS[controller]
    if invert is None:
        invert = info.invert
    return DisplayProfile(
        model=CUSTOM_MODEL,
        title=f"Свій: {width}×{height} {controller}",
        controller=controller,
        width=width,
        height=height,
        color_format=info.color_format,
        interface="spi-4wire",
        invert=invert,
        spi_hz=SpiRange(default=40_000_000, max=80_000_000),
        default_pins=dict(load_profiles()[DEFAULT_MODEL].default_pins),
        x_offset=x_offset,
        y_offset=y_offset,
        bgr=bgr,
        shape="round" if round_panel else "rect",
    )


class UnknownDisplayError(KeyError):
    def __init__(self, model: str) -> None:
        super().__init__(model)
        self.model = model

    def __str__(self) -> str:
        known = ", ".join(load_profiles())
        return f"невідомий дисплей «{self.model}»; підтримуються: {known}"


@cache
def load_profiles() -> Mapping[str, DisplayProfile]:
    profiles: dict[str, DisplayProfile] = {}
    for entry in sorted(resources.files(__package__).iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".yaml"):
            profile = DisplayProfile.model_validate(yaml.safe_load(entry.read_text("utf-8")))
            profiles[profile.model] = profile
    return MappingProxyType(profiles)


def get_profile(model: str) -> DisplayProfile:
    try:
        return load_profiles()[model]
    except KeyError:
        raise UnknownDisplayError(model) from None
