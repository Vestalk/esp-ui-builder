"""Touch panels and the SD card of display modules, on the MicroPython unix port (fakes)."""

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

SD = (
    FAKES
    + r'''
import os, ui_sd

class Card:
    """A fake SDHC card in SPI mode (c_size 99: 102400 blocks of 512 bytes)."""
    def __init__(self):
        self.out = []
        self.frame = []
        self.mode = "cmd"
        self.blocks = {}
        self.acmd = 0
        self.bauds = []
        self.write_block = None
        self.data = bytearray()
    def init(self, baudrate):
        self.bauds.append(baudrate)
    def readinto(self, buf, fill=0xFF):
        for i in range(len(buf)):
            buf[i] = self.out.pop(0) if self.out else 0xFF
    def write(self, data):
        for b in bytes(data):
            self.feed(b)
    def feed(self, b):
        if self.mode == "token":
            if b == 0xFE:
                self.mode = "data"
                self.data = bytearray()
            return
        if self.mode == "data":
            self.data.append(b)
            if len(self.data) == 514:
                self.blocks[self.write_block] = bytes(self.data[:512])
                self.out += [0xE5, 0x00, 0x00, 0xFF]  # accepted, busy, busy, ready
                self.mode = "cmd"
            return
        if not self.frame and b & 0xC0 != 0x40:
            return
        self.frame.append(b)
        if len(self.frame) == 6:
            cmd = self.frame[0] & 0x3F
            f = self.frame
            arg = (f[1] << 24) | (f[2] << 16) | (f[3] << 8) | f[4]
            self.frame = []
            self.answer(cmd, arg)
    def answer(self, cmd, arg):
        r = self.out
        r.append(0xFF)  # one byte of latency, as real cards
        if cmd == 0:
            r.append(0x01)
        elif cmd == 8:
            r += [0x01, 0, 0, 0x01, 0xAA]
        elif cmd == 55:
            r.append(0x01)
        elif cmd == 41:
            self.acmd += 1
            r.append(0x00 if self.acmd >= 3 else 0x01)
        elif cmd == 58:
            r += [0x00, 0xC0, 0xFF, 0x80, 0x00]
        elif cmd == 9:
            csd = [0x40, 0x0E, 0, 0x32, 0x5B, 0x59, 0, 0, 0, 99, 0x7F, 0x80, 0x0A, 0x40, 0, 0x01]
            r += [0x00, 0xFF, 0xFE] + csd + [0, 0]
        elif cmd == 17:
            r += [0x00, 0xFF, 0xFE] + list(self.blocks.get(arg, bytes(512))) + [0, 0]
        elif cmd == 24:
            r.append(0x00)
            self.write_block = arg
            self.mode = "token"
        else:
            r.append(0x04)  # illegal command

card = Card()
cs = Pin()
sd = ui_sd.SDCard(card, cs, 20_000_000, 40_000_000)
out("sectors", [sd.sectors, sd.block_addressing])
out("init_bauds", card.bauds[:2])
data = bytes((i * 7) % 256 for i in range(1024))
sd.writeblocks(5, data)
back = bytearray(1024)
sd.readblocks(5, back)
out("roundtrip", back == data)
out("blocks", sorted(card.blocks))
out("bus_back", card.bauds[-1])
out("cs_high", cs.v)
if hasattr(os, "VfsFat"):
    os.VfsFat.mkfs(sd)
    os.mount(os.VfsFat(sd), "/sdtest")
    with open("/sdtest/hello.txt", "w") as f:
        f.write("Привіт, SD")
    with open("/sdtest/hello.txt") as f:
        out("fat", f.read())
    out("listing", os.listdir("/sdtest"))
    os.umount("/sdtest")
else:
    out("fat", None)
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
    assert r["cst"] == [30, 200]
    assert r["cst_rst"] == [0, 1]
    assert r["cst_rot1"] == [200, 209]
    assert r["cst_none"] is None
    assert r["cst_asleep"] is None


def test_sd_card(run_mpy: RunMpy, tmp_path: Path) -> None:
    r = run(run_mpy, tmp_path, SD, "ui_sd.py")
    assert r["sectors"] == [100 * 1024, True]  # SDHC: block addressing
    assert r["init_bauds"] == [400_000, 400_000]
    assert r["roundtrip"] is True
    assert r["blocks"] == [5, 6]
    assert r["bus_back"] == 40_000_000  # the display gets its speed back
    assert r["cs_high"] == 1
    if r["fat"] is None:
        pytest.skip("this MicroPython build has no VfsFat")
    assert r["fat"] == "Привіт, SD"
    assert r["listing"] == ["hello.txt"]


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
          "bl": 7, "miso": 13}, "touch": {"kind": "xpt2046", "cs": 14, "irq": 15},
          "sd": {"cs": 21}}, [0, 0], "XPT2046", [14, 21]),
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
