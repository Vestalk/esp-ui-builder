"""Touch panels of display modules, on the MicroPython unix port (fakes)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from espui.generators.micropython.drivers import RUNTIME_DIR
from tests.mpy.conftest import RunMpy

FAKES = r"""
import json

class Pin:
    def __init__(self, v=1):
        self.v = v
        self.history = []
    def value(self, v=None):
        if v is None:
            return self.v
        self.v = v
        self.history.append(v)

def out(tag, value):
    print(tag + " " + json.dumps(value))
"""

TOUCH = (
    FAKES
    + r'''
import ui_touch

class XptBus:
    """write_readinto: the raw 12-bit value of the channel asked for, << 3."""
    def __init__(self, x, y, z):
        self.raw = {0xD1: x, 0x91: y, 0xB1: z, 0x90: 0}
        self.bauds = []
    def init(self, baudrate):
        self.bauds.append(baudrate)
    def write_readinto(self, tx, rx):
        v = self.raw[tx[0]] << 3
        rx[0] = 0
        rx[1] = v >> 8
        rx[2] = v & 0xFF

cal = (200, 3900, 200, 3900)
for rotation in (0, 1, 2, 3):
    bus = XptBus(200, 3900, 1000)  # left edge, bottom edge (portrait)
    t = ui_touch.XPT2046(bus, Pin(), None, 320, 480, rotation, cal, 40_000_000)
    out("xpt%d" % rotation, t.read())
out("bauds", bus.bauds)
bus = XptBus(2050, 2050, 1000)
out("middle", ui_touch.XPT2046(bus, Pin(), None, 320, 480, 0, cal, 1).read())
out("mirrored", ui_touch.XPT2046(bus, Pin(), None, 320, 480, 0, (3900, 200, 200, 3900), 1).read())
out("light", ui_touch.XPT2046(XptBus(2000, 2000, 50), Pin(), None, 320, 480, 0, cal, 1).read())
out("irq_up", ui_touch.XPT2046(bus, Pin(), Pin(1), 320, 480, 0, cal, 1).read())
own = XptBus(2050, 2050, 1000)
out("own_bus", ui_touch.XPT2046(own, Pin(), None, 240, 320, 0, cal, 0).read())
out("own_bauds", own.bauds)

class CstBus:
    def __init__(self, data, fail=False):
        self.data = data
        self.fail = fail
    def readfrom_mem_into(self, addr, reg, buf):
        if self.fail:
            raise OSError(19)
        assert addr == 0x15 and reg == 0x01
        buf[:] = bytes(self.data)

rst = Pin()
c = ui_touch.CST816S(CstBus([0, 1, 0, 30, 0, 200]), None, rst, 240, 240, 0)
out("cst", c.read())
out("cst_rst", rst.history)
out("cst_rot1", ui_touch.CST816S(CstBus([0, 1, 0, 30, 0, 200]), None, None, 240, 240, 1).read())
out("cst_none", ui_touch.CST816S(CstBus([0, 0, 0, 0, 0, 0]), None, None, 240, 240, 0).read())
out("cst_asleep", ui_touch.CST816S(CstBus([], True), None, None, 240, 240, 0).read())
'''
)


def run(run_mpy: RunMpy, tmp_path: Path, source: str, *modules: str) -> dict[str, object]:
    for name in modules:
        shutil.copy(RUNTIME_DIR / name, tmp_path / name)
    proc = run_mpy(source)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    return {
        line.split(" ", 1)[0]: json.loads(line.split(" ", 1)[1])
        for line in proc.stdout.splitlines()
    }


def test_touch_panels(run_mpy: RunMpy, tmp_path: Path) -> None:
    r = run(run_mpy, tmp_path, TOUCH, "ui_touch.py")
    # raw (200, 3900) = the bottom-left corner in portrait 320×480, turned with the screen
    assert r["xpt0"] == [0, 479]
    assert r["xpt1"] == [479, 319]
    assert r["xpt2"] == [319, 0]
    assert r["xpt3"] == [0, 0]
    assert r["bauds"] == [2_000_000, 40_000_000]  # read slowly, then back to the display's
    assert r["middle"] == [159, 239]
    assert r["mirrored"] == [159, 239]  # the middle stays the middle
    assert r["light"] is None  # too little pressure
    assert r["irq_up"] is None  # T_IRQ high: not touched
    assert r["own_bus"] == [119, 159]
    assert r["own_bauds"] == []  # a bus of its own: its speed is never switched
    assert r["cst"] == [30, 200]
    assert r["cst_rst"] == [0, 1]
    assert r["cst_rot1"] == [200, 209]
    assert r["cst_none"] is None
    assert r["cst_asleep"] is None


FAKE_MACHINE = r"""
log = []

class Pin:
    IN = 0
    OUT = 1
    def __init__(self, number, mode=None, value=None):
        self.number = number
        self.v = 1 if value is None else value
        if mode == Pin.OUT and value is not None:
            log.append(["out", number, value])
    def value(self, v=None):
        if v is None:
            return self.v
        self.v = v

class SPI:
    def __init__(self, spi_id, **kw):
        log.append(["spi", spi_id, kw["polarity"], kw["phase"], "miso" in kw])
    def write(self, data):
        pass
    def init(self, baudrate):
        pass
    def write_readinto(self, tx, rx):
        rx[0] = rx[1] = rx[2] = 0

class SoftSPI(SPI):
    def __init__(self, **kw):
        log.append(["softspi", kw["sck"].number, kw["mosi"].number, kw["miso"].number])
    def init(self, baudrate):
        log.append(["softspi_init", baudrate])

class I2C:
    def __init__(self, bus, sda, scl, freq):
        log.append(["i2c", sda.number, scl.number])
"""

SCRIPT = r"""
import json, machine, ui_display
d = ui_display.create()
t = ui_display.create_touch(d)
print(json.dumps({"log": machine.log, "touch": type(t).__name__ if t else None,
                  "size": [d.width, d.height]}))
"""


@pytest.mark.parametrize(
    ("display", "mode", "touch", "pulled_up"),
    [
        ({}, [0, 0], None, []),
        ({"pins": {"sck": 12, "mosi": 11, "dc": 9, "cs": None, "rst": None, "bl": 7}}, [1, 1],
         None, []),  # no CS: SPI mode 3
        ({"model": "ILI9488-3.5", "pins": {"sck": 12, "mosi": 11, "dc": 9, "cs": 10, "rst": 8,
          "bl": 7, "miso": 13}, "touch": {"kind": "xpt2046", "cs": 14, "irq": 15}},
         [0, 0], "XPT2046", [14]),
        ({"model": "GC9A01-1.28", "touch": {"kind": "cst816s", "sda": 16, "scl": 17}}, [0, 0],
         "CST816S", []),
    ],
)  # fmt: skip
def test_generated_display_brings_up_the_bus_and_touch(
    run_mpy: RunMpy,
    tmp_path: Path,
    display: dict[str, object],
    mode: list[int],
    touch: str | None,
    pulled_up: list[int],
) -> None:
    from espui.core import serializer
    from espui.generators.micropython.generator import generate

    project = serializer.from_dict({"display": display, "pages": [{"name": "main", "widgets": []}]})
    generate(project).write(tmp_path)
    (tmp_path / "machine.py").write_text(FAKE_MACHINE, "utf-8")
    proc = run_mpy(SCRIPT)
    assert proc.returncode == 0, proc.stderr
    r = json.loads(proc.stdout.strip().splitlines()[-1])
    spi = [entry for entry in r["log"] if entry[0] == "spi"]
    assert [spi[0][2], spi[0][3]] == mode
    assert spi[0][4] is bool(project.display.pins.miso is not None)
    outs = [entry[1] for entry in r["log"] if entry[0] == "out" and entry[2] == 1]
    for gpio in pulled_up:  # other devices on the bus deselected from the start
        assert gpio in outs
    assert r["touch"] == touch
    if touch == "CST816S":
        assert ["i2c", 16, 17] in r["log"]


@pytest.mark.parametrize("model", ["CYD-ILI9341", "CYD-ST7789"])
def test_cyd_board_display_on_hspi_and_touch_on_its_own_bus(
    run_mpy: RunMpy, tmp_path: Path, model: str
) -> None:
    """ESP32-2432S028: the display on HSPI (14/13), the XPT2046 on 25/32/39 of its own."""
    from espui.core import serializer
    from espui.core.checks import check_project
    from espui.displays import load_profiles
    from espui.generators.micropython.generator import generate

    profile = load_profiles()[model]
    display = {
        "model": model,
        "mcu": profile.board,
        "pins": profile.default_pins,
        "touch": {"kind": profile.touch, **(profile.touch_pins or {})},
    }
    project = serializer.from_dict({"display": display, "pages": [{"name": "main", "widgets": []}]})
    assert [i.message for i in check_project(project)] == []
    generate(project).write(tmp_path)
    (tmp_path / "machine.py").write_text(FAKE_MACHINE, "utf-8")
    proc = run_mpy(SCRIPT)
    assert proc.returncode == 0, proc.stderr
    r = json.loads(proc.stdout.strip().splitlines()[-1])
    spi = [entry for entry in r["log"] if entry[0] == "spi"]
    assert spi == [["spi", 1, 0, 0, False]]  # SPI(1) = HSPI: full speed on 14/13, no MISO
    assert ["softspi", 25, 32, 39] in r["log"]  # the touch panel: a bus of its own
    assert r["touch"] == "XPT2046"
    assert r["size"] == [240, 320]  # portrait (rotation 0)
    assert 33 in [entry[1] for entry in r["log"] if entry[0] == "out" and entry[2] == 1]


CALIBRATION = (
    FAKES
    + r'''
import ui_touch

ui_touch.sleep_ms = lambda ms: None  # no waiting in the test
TRUE = {"x_min": 3800, "x_max": 300, "y_min": 250, "y_max": 3700}  # x mirrored

class Screen:
    """Remembers where the last white cross was drawn (its centre)."""
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.cross = None
        self.fills = 0
    def fill_rect(self, x, y, w, h, color):
        self.fills += 1
        if color == ui_touch.WHITE and w == 17 and h == 1:
            self.cross = (x + 8, y)

class Panel:
    """A pressed panel: raw readings of the cross on screen, then a release."""
    def __init__(self, screen, rotation, swap):
        self.screen = screen
        self.width, self.height = ui_touch.portrait_size(screen, rotation)
        self.rotation = rotation
        self.swap = swap
        self.left = 0
        self.at = None
    def raw(self):
        if self.screen.cross != self.at:  # a new cross: press it
            self.at = self.screen.cross
            self.left = ui_touch.CAL_SAMPLES
        if self.left == 0:
            return None
        self.left -= 1
        px, py = ui_touch.to_portrait(*self.at, self.width, self.height, self.rotation)
        rx = TRUE["x_min"] + px * (TRUE["x_max"] - TRUE["x_min"]) / (self.width - 1)
        ry = TRUE["y_min"] + py * (TRUE["y_max"] - TRUE["y_min"]) / (self.height - 1)
        rx, ry = int(rx), int(ry)
        return (ry, rx, 900) if self.swap else (rx, ry, 900)

for rotation in (0, 1, 2, 3):
    for swap in (False, True):
        w, h = (240, 320) if rotation % 2 == 0 else (320, 240)
        screen = Screen(w, h)
        panel = Panel(screen, rotation, swap)
        cal = ui_touch.run_calibration(screen, panel)
        out("cal%d%d" % (rotation, swap), [cal["x_min"], cal["x_max"], cal["y_min"],
                                           cal["y_max"], cal["swap_xy"]])
out("applied", [list(panel.cal), panel.swap_xy])
out("portrait", [ui_touch.to_portrait(*ui_touch.to_screen(10, 20, 240, 320, r), 240, 320, r)
                 for r in range(4)])
'''
)


def test_touch_calibration_on_the_screen(run_mpy: RunMpy, tmp_path: Path) -> None:
    """Four crosses, any rotation, mirrored and swapped axes: the panel's values come back."""
    shutil.copy(RUNTIME_DIR / "ui_touch.py", tmp_path / "ui_touch.py")
    proc = run_mpy(CALIBRATION)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    printed = [line for line in proc.stdout.splitlines() if line.startswith("ESPUI-CAL ")]
    assert len(printed) == 8  # the line for the editor, once per calibration
    assert printed[-1].endswith("swap_xy=1")
    r = {
        line.split(" ", 1)[0]: json.loads(line.split(" ", 1)[1])
        for line in proc.stdout.splitlines()
        if not line.startswith("ESPUI-CAL ")
    }
    for rotation in range(4):
        for swap in (0, 1):
            x_min, x_max, y_min, y_max, swapped = r[f"cal{rotation}{swap}"]  # type: ignore[misc]
            assert swapped is bool(swap)
            for got, want in ((x_min, 3800), (x_max, 300), (y_min, 250), (y_max, 3700)):
                assert abs(got - want) <= 3, (rotation, swap, got, want)
    applied, swap_xy = r["applied"]  # type: ignore[misc]
    assert swap_xy is True
    assert abs(applied[0] - 3800) <= 3
    assert r["portrait"] == [[10, 20]] * 4  # to_portrait undoes to_screen
