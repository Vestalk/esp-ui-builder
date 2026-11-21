# Hardware smoke test for the GMT020-02-8B (ST7789, 240x320, 4-wire SPI, RGB565).
#
# Runs on a stock MicroPython firmware (ESP32_GENERIC_S3). Upload with MicroPico
# ("Run current file on Pico") or:
#     mpremote run tools/hw_smoke.py
#
# Expected result: the screen is filled red, green, blue in turn (each ~1 s),
# without stripes, noise or shifted areas. Timings are printed to the REPL.
#
# Pins: edit PINS to match docs/hardware.md. Do NOT use GPIO19/20 (USB) or the
# strapping pins GPIO0, 3, 45, 46.
#
# The panel logic (St7789Smoke) gets SPI, pins and a sleep function from outside,
# so it is unit-tested on CPython with fakes (tests/unit/test_hw_smoke.py);
# only main() touches the `machine` module.

PINS = {
    "sck": 12,  # SCL on the module
    "mosi": 11,  # SDA on the module
    "cs": 10,
    "dc": 9,
    "rst": 8,
    "blk": 7,  # set to None if the module has no BLK pin
}
SPI_ID = 1  # hardware SPI: SPI(1) = FSPI on ESP32-S3 (SPI(2) resets the board)
SPI_BAUDRATE = 40_000_000
WIDTH = 240
HEIGHT = 320
# Most 240x320 ST7789 panels show inverted colours without INVON.
# If red shows as cyan, flip this flag.
INVERT = True

# ST7789 commands
SWRESET = 0x01
SLPOUT = 0x11
NORON = 0x13
INVOFF = 0x20
INVON = 0x21
DISPON = 0x29
CASET = 0x2A
RASET = 0x2B
RAMWR = 0x2C
MADCTL = 0x36
COLMOD = 0x3A

COLMOD_RGB565 = 0x55
MADCTL_PORTRAIT_RGB = 0x00

# RGB565 colours, big-endian as the panel expects them on the wire.
RED = 0xF800
GREEN = 0x07E0
BLUE = 0x001F
BLACK = 0x0000

CHUNK_ROWS = 16  # rows per SPI write: 240*16*2 = 7.5 KB buffer


def rgb565_bytes(color):
    return bytes(((color >> 8) & 0xFF, color & 0xFF))


class St7789Smoke:
    """Minimal ST7789 init + full-screen fill. Not the project driver (stage 01)."""

    def __init__(self, spi, cs, dc, rst, blk, sleep_ms, width=WIDTH, height=HEIGHT):
        self._spi = spi
        self._cs = cs
        self._dc = dc
        self._rst = rst
        self._blk = blk
        self._sleep_ms = sleep_ms
        self.width = width
        self.height = height

    # -- low level -------------------------------------------------------
    def _write(self, command, data=None):
        self._cs(0)
        self._dc(0)
        self._spi.write(bytes((command,)))
        if data:
            self._dc(1)
            self._spi.write(data)
        self._cs(1)

    def _write_data(self, data):
        self._cs(0)
        self._dc(1)
        self._spi.write(data)
        self._cs(1)

    # -- panel -----------------------------------------------------------
    def hard_reset(self):
        self._cs(1)
        self._rst(1)
        self._sleep_ms(10)
        self._rst(0)
        self._sleep_ms(10)
        self._rst(1)
        self._sleep_ms(120)

    def init(self, invert=INVERT):
        self.hard_reset()
        self._write(SWRESET)
        self._sleep_ms(150)
        self._write(SLPOUT)
        self._sleep_ms(120)
        self._write(COLMOD, bytes((COLMOD_RGB565,)))
        self._sleep_ms(10)
        self._write(MADCTL, bytes((MADCTL_PORTRAIT_RGB,)))
        self._write(INVON if invert else INVOFF)
        self._write(NORON)
        self._sleep_ms(10)
        self._write(DISPON)
        self._sleep_ms(20)
        if self._blk is not None:
            self._blk(1)

    def set_window(self, x0, y0, x1, y1):
        self._write(CASET, bytes((x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF)))
        self._write(RASET, bytes((y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF)))
        self._write(RAMWR)

    def fill(self, color):
        self.set_window(0, 0, self.width - 1, self.height - 1)
        rows = min(CHUNK_ROWS, self.height)
        chunk = rgb565_bytes(color) * (self.width * rows)
        full, rest = divmod(self.height, rows)
        for _ in range(full):
            self._write_data(chunk)
        if rest:
            self._write_data(chunk[: self.width * rest * 2])


def main():
    import time

    import machine

    def out(pin_no):
        return None if pin_no is None else machine.Pin(pin_no, machine.Pin.OUT, value=1)

    spi = machine.SPI(
        SPI_ID,
        baudrate=SPI_BAUDRATE,
        polarity=0,
        phase=0,
        sck=machine.Pin(PINS["sck"]),
        mosi=machine.Pin(PINS["mosi"]),
    )
    panel = St7789Smoke(
        spi,
        cs=out(PINS["cs"]),
        dc=out(PINS["dc"]),
        rst=out(PINS["rst"]),
        blk=out(PINS["blk"]),
        sleep_ms=time.sleep_ms,
    )
    print("hw_smoke: SPI", spi)
    panel.init()
    for name, color in (("red", RED), ("green", GREEN), ("blue", BLUE)):
        start = time.ticks_ms()
        panel.fill(color)
        print("hw_smoke: fill", name, time.ticks_diff(time.ticks_ms(), start), "ms")
        time.sleep_ms(1000)
    panel.fill(BLACK)
    print("hw_smoke: done")


if __name__ == "__main__":
    main()
