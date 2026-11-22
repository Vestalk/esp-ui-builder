"""Behaviour every display driver must show through the ``Display`` adapter.

Subclasses provide a ``backend`` fixture (CPython or MicroPython unix port);
each test runs for every driver key.
"""

from __future__ import annotations

import pytest

from espui.generators.micropython.drivers import DRIVERS
from tests.runtime.harness import Backend

SWRESET, SLPOUT, NORON, INVOFF, INVON, DISPON = 0x01, 0x11, 0x13, 0x20, 0x21, 0x29
COLMOD, MADCTL = 0x3A, 0x36

MADCTL_BY_ROTATION = {0: 0x00, 1: 0x60, 2: 0xC0, 3: 0xA0}
SIZE_BY_ROTATION = {0: [240, 320], 1: [320, 240], 2: [240, 320], 3: [320, 240]}
MAX_WRITE = {"builtin": 4096, "st7789py": 512}

# Wire-order colours (bytes pre-swapped): what generated code passes around.
WIRE_RED = 0x00F8
WIRE_BLUE = 0x1F00


def _window(x: int, y: int, w: int, h: int) -> list[str]:
    return [f"{x:04x}{x + w - 1:04x}", f"{y:04x}{y + h - 1:04x}"]


class DisplayRuntimeContract:
    @pytest.fixture(params=sorted(DRIVERS))
    def driver(self, request: pytest.FixtureRequest, backend: Backend) -> str:
        key: str = request.param
        if key == "st7789py" and not backend.has_native_emitter:
            pytest.skip(f"{backend.name}: no native emitter, st7789py uses @micropython.viper")
        return key

    @pytest.mark.parametrize("rotation", [0, 1, 2, 3])
    def test_init_per_rotation(self, backend: Backend, driver: str, rotation: int) -> None:
        r = backend.run("init_sequence", driver, rotation, True, True)
        assert r["driver"] == driver
        assert r["size"] == SIZE_BY_ROTATION[rotation]
        assert r["madctl"] == MADCTL_BY_ROTATION[rotation], "wrong MADCTL / BGR bit set"
        assert r["colmod"] == "55"
        assert {SLPOUT, COLMOD, MADCTL, INVON, NORON, DISPON} <= set(r["commands"])
        assert r["rst"] == [1, 0, 1]
        assert r["blk"][-1] == 1
        assert r["cs_high_writes"] == 0

    def test_builtin_init_order(self, backend: Backend) -> None:
        r = backend.run("init_sequence", "builtin", 0, True, True)
        setup = [c for c in r["commands"] if c not in (0x2A, 0x2B, 0x2C)]
        assert setup == [SWRESET, SLPOUT, COLMOD, MADCTL, INVON, NORON, DISPON]

    def test_inversion_off(self, backend: Backend, driver: str) -> None:
        r = backend.run("init_sequence", driver, 0, False, True)
        inversion = [c for c in r["commands"] if c in (INVON, INVOFF)]
        assert inversion[-1] == INVOFF

    def test_without_backlight_pin(self, backend: Backend, driver: str) -> None:
        r = backend.run("init_sequence", driver, 0, True, False)
        assert r["blk"] is None
        assert backend.run("backlight", driver, False) is None

    def test_backlight_toggle(self, backend: Backend, driver: str) -> None:
        assert backend.run("backlight", driver, True) == [1, 0, 1]

    @pytest.mark.parametrize(
        ("rotation", "area"),
        [
            (0, (0, 0, 240, 320)),
            (0, (10, 20, 100, 48)),
            (0, (239, 319, 1, 1)),
            (1, (300, 200, 20, 40)),
            (0, (3, 5, 37, 41)),  # size not a multiple of the strip
        ],
    )
    def test_fill_rect(
        self, backend: Backend, driver: str, rotation: int, area: tuple[int, int, int, int]
    ) -> None:
        x, y, w, h = area
        r = backend.run("fill_rect", driver, rotation, x, y, w, h, WIRE_RED)
        assert r["window"] == _window(x, y, w, h)
        assert r["pixel_bytes"] == w * h * 2
        assert r["pairs"] == ["f800"], "panel must receive RGB565 big-endian"
        assert r["max_write"] <= MAX_WRITE[driver]
        assert r["cs_high_writes"] == 0

    def test_blit_framebuf_buffer(self, backend: Backend, driver: str) -> None:
        r = backend.run("blit", driver, 50, 100, 150, 48, WIRE_BLUE)
        assert r["window"] == _window(50, 100, 150, 48)
        assert r["same_bytes"]
        assert r["first_pixel"] == "001f", "framebuf with wire-order colour must be big-endian"
        assert r["data_writes"] == 1, "blit must be a single SPI write"

    def test_bad_areas_raise(self, backend: Backend, driver: str) -> None:
        r = backend.run("errors", driver)
        assert all(r.values()), r

    def test_unknown_driver(self, backend: Backend) -> None:
        assert "nope" in backend.run("unknown_driver")

    def test_color_helpers(self, backend: Backend) -> None:
        assert backend.run("color_helpers") == {
            "red": 0x00F8,
            "green": 0xE007,
            "blue": 0x1F00,
            "white": 0xFFFF,
            "swap": 0x3412,
        }


# ------------------------------------------------------------------ ui_tft
TFT_SIZES = {
    "ILI9488": ([320, 480], [480, 320]),
    "GC9A01": ([240, 240], [240, 240]),
    "ILI9341": ([240, 320], [320, 240]),
}
TFT_COLMOD = {"ILI9488": "66", "GC9A01": "05", "ILI9341": "55"}
BYTES_PER_PIXEL = {"ILI9488": 3, "GC9A01": 2, "ILI9341": 2}


class TftRuntimeContract:
    """The generic built-in driver for the controllers other than ST7789."""

    @pytest.fixture(params=sorted(TFT_SIZES))
    def controller(self, request: pytest.FixtureRequest) -> str:
        return str(request.param)

    @pytest.mark.parametrize("rotation", [0, 1, 2, 3])
    def test_init(self, backend: Backend, controller: str, rotation: int) -> None:
        r = backend.run("tft_init", controller, rotation, True)
        assert r["size"] == TFT_SIZES[controller][rotation % 2]
        assert r["madctl"] == (0x48, 0x28, 0x88, 0xE8)[rotation]  # BGR bit set
        assert r["colmod"] == TFT_COLMOD[controller]
        commands = r["commands"]
        assert commands[0] == SWRESET
        assert commands.index(COLMOD) < commands.index(MADCTL) < commands.index(INVON)
        assert commands.index(INVON) < commands.index(SLPOUT) < commands.index(DISPON)
        assert r["rst"] == [1, 0, 1]
        assert r["blk"][-1] == 1
        assert r["cs_high_writes"] == 0
        w, h = r["size"]
        assert r["clear_bytes"] == w * h * BYTES_PER_PIXEL[controller]

    def test_inversion_off(self, backend: Backend, controller: str) -> None:
        r = backend.run("tft_init", controller, 0, False)
        assert INVOFF in r["commands"]
        assert INVON not in r["commands"]

    def test_blit(self, backend: Backend, controller: str) -> None:
        r = backend.run("tft_blit", controller, WIRE_RED, 5, 3)
        assert r["window"] == _window(3, 4, 5, 3)
        assert r["bytes"] == 5 * 3 * BYTES_PER_PIXEL[controller]
        # RGB565 red f800 -> RGB666 f8 00 00 (ILI9488); others send it as is
        expected = "f80000" * 3 if controller == "ILI9488" else "f800" * 4 + "f8"
        assert r["head"] == expected

    def test_fill(self, backend: Backend, controller: str) -> None:
        r = backend.run("tft_fill", controller, WIRE_BLUE, 60, 40)  # several strips for 666
        assert r["window"] == _window(1, 2, 60, 40)
        assert r["bytes"] == 60 * 40 * BYTES_PER_PIXEL[controller]
        expected = "0000f8" * 3 if controller == "ILI9488" else "001f" * 4 + "00"
        assert r["head"] == expected
