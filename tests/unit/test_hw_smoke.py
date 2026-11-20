"""CPython checks of tools/hw_smoke.py with fake SPI and pins (no hardware)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "hw_smoke.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("hw_smoke", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hw = _load()


class Bus:
    """Records SPI traffic split into (dc, bytes) transactions."""

    def __init__(self) -> None:
        self.dc = 1
        self.cs = 1
        self.log: list[tuple[int, bytes]] = []

    def write(self, data: bytes) -> None:
        assert self.cs == 0, "SPI write with CS high"
        self.log.append((self.dc, bytes(data)))

    def set_dc(self, value: int) -> None:
        self.dc = value

    def set_cs(self, value: int) -> None:
        self.cs = value

    def commands(self) -> list[int]:
        return [data[0] for dc, data in self.log if dc == 0]

    def payload_after(self, command: int) -> bytes:
        for i, (dc, data) in enumerate(self.log):
            if dc == 0 and data[0] == command:
                payload = bytearray()
                for flag, chunk in self.log[i + 1 :]:
                    if flag == 0:
                        break
                    payload += chunk
                return bytes(payload)
        raise AssertionError(f"command {command:#x} not sent")


@pytest.fixture
def bus() -> Bus:
    return Bus()


def make_panel(bus: Bus, blk: list[int] | None = None) -> Any:
    return hw.St7789Smoke(
        bus,
        cs=bus.set_cs,
        dc=bus.set_dc,
        rst=lambda _v: None,
        blk=None if blk is None else blk.append,
        sleep_ms=lambda _ms: None,
    )


def test_rgb565_is_big_endian() -> None:
    assert hw.rgb565_bytes(hw.RED) == b"\xf8\x00"
    assert hw.rgb565_bytes(hw.GREEN) == b"\x07\xe0"
    assert hw.rgb565_bytes(hw.BLUE) == b"\x00\x1f"


def test_init_sequence(bus: Bus) -> None:
    blk: list[int] = []
    make_panel(bus, blk).init(invert=True)
    assert bus.commands() == [
        hw.SWRESET,
        hw.SLPOUT,
        hw.COLMOD,
        hw.MADCTL,
        hw.INVON,
        hw.NORON,
        hw.DISPON,
    ]
    assert bus.payload_after(hw.COLMOD) == bytes([hw.COLMOD_RGB565])
    assert blk == [1]
    assert bus.cs == 1


def test_init_without_backlight_pin(bus: Bus) -> None:
    make_panel(bus).init(invert=False)
    assert hw.INVOFF in bus.commands()


def test_fill_covers_whole_screen(bus: Bus) -> None:
    make_panel(bus).fill(hw.RED)
    assert bus.commands() == [hw.CASET, hw.RASET, hw.RAMWR]
    assert bus.payload_after(hw.CASET) == bytes([0, 0, 0, 239])
    assert bus.payload_after(hw.RASET) == bytes([0, 0, 0x01, 0x3F])
    pixels = bus.payload_after(hw.RAMWR)
    assert len(pixels) == hw.WIDTH * hw.HEIGHT * 2
    assert pixels == b"\xf8\x00" * (hw.WIDTH * hw.HEIGHT)


def test_fill_handles_height_not_multiple_of_chunk(bus: Bus) -> None:
    panel = hw.St7789Smoke(
        bus, bus.set_cs, bus.set_dc, lambda _v: None, None, lambda _ms: None, width=10, height=37
    )
    panel.fill(hw.BLUE)
    assert len(bus.payload_after(hw.RAMWR)) == 10 * 37 * 2


def test_pins_avoid_usb_and_strapping() -> None:
    forbidden = {0, 3, 19, 20, 45, 46}
    used = {pin for pin in hw.PINS.values() if pin is not None}
    assert not used & forbidden
    assert len(used) == len([p for p in hw.PINS.values() if p is not None]), "duplicate pins"
