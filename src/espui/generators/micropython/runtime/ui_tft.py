# ui_tft — built-in driver of ESP UI Builder for ILI9488, ILI9341 and GC9A01 panels.
#
# Pure Python for stock MicroPython; copied unchanged into a generated project
# whose display is not an ST7789 (that one has ui_st7789.py). Pages never use it
# directly: they talk to the `Display` adapter from ui_display.py.
#
# Colours come in "wire order" RGB565, as everywhere in the runtime (see
# ui_st7789.py). ILI9488 over SPI has no 16-bit mode: every pixel is sent as
# three bytes (RGB666, 6 bits per colour in the high bits of each byte); the
# conversion runs in strips through a small reusable buffer, compiled with
# @micropython.viper where the firmware allows it.

try:
    from micropython import const
except ImportError:  # CPython (tests)

    def const(value):
        return value


try:
    from time import sleep_ms
except ImportError:  # CPython
    from time import sleep as _sleep

    def sleep_ms(ms):
        _sleep(ms / 1000)


_SWRESET = const(0x01)
_SLPOUT = const(0x11)
_NORON = const(0x13)
_INVOFF = const(0x20)
_INVON = const(0x21)
_DISPON = const(0x29)
_CASET = const(0x2A)
_RASET = const(0x2B)
_RAMWR = const(0x2C)
_MADCTL = const(0x36)
_COLMOD = const(0x3A)

STRIP_BYTES = const(4608)  # reusable buffer: 1536 RGB666 pixels, a multiple of 2 and 3

# controller: (frame memory width, height in portrait, bytes per pixel, COLMOD,
#              MADCTL per rotation incl. the BGR bit, vendor init [(command, data, ms)])
CONTROLLERS = {
    "ILI9488": (
        320,
        480,
        3,
        0x66,
        (0x48, 0x28, 0x88, 0xE8),
        (
            (0xE0, b"\x00\x03\x09\x08\x16\x0a\x3f\x78\x4c\x09\x0a\x08\x16\x1a\x0f", 0),
            (0xE1, b"\x00\x16\x19\x03\x0f\x05\x32\x45\x46\x04\x0e\x0d\x35\x37\x0f", 0),
            (0xC0, b"\x17\x15", 0),  # power control 1
            (0xC1, b"\x41", 0),  # power control 2
            (0xC5, b"\x00\x12\x80", 0),  # VCOM
            (0xB0, b"\x00", 0),  # interface mode
            (0xB1, b"\xa0", 0),  # frame rate 60 Hz
            (0xB4, b"\x02", 0),  # inversion control: 2 dot
            (0xB6, b"\x02\x02\x3b", 0),  # display function
            (0xB7, b"\xc6", 0),  # entry mode
            (0xF7, b"\xa9\x51\x2c\x82", 0),  # adjust control 3
        ),
    ),
    "ILI9341": (
        240,
        320,
        2,
        0x55,
        (0x48, 0x28, 0x88, 0xE8),
        (
            (0xEF, b"\x03\x80\x02", 0),
            (0xCF, b"\x00\xc1\x30", 0),
            (0xED, b"\x64\x03\x12\x81", 0),
            (0xE8, b"\x85\x00\x78", 0),
            (0xCB, b"\x39\x2c\x00\x34\x02", 0),
            (0xF7, b"\x20", 0),
            (0xEA, b"\x00\x00", 0),
            (0xC0, b"\x23", 0),
            (0xC1, b"\x10", 0),
            (0xC5, b"\x3e\x28", 0),
            (0xC7, b"\x86", 0),
            (0xB1, b"\x00\x18", 0),
            (0xB6, b"\x08\x82\x27", 0),
            (0xF2, b"\x00", 0),
            (0x26, b"\x01", 0),
            (0xE0, b"\x0f\x31\x2b\x0c\x0e\x08\x4e\xf1\x37\x07\x10\x03\x0e\x09\x00", 0),
            (0xE1, b"\x00\x0e\x14\x03\x11\x07\x31\xc1\x48\x08\x0f\x0c\x31\x36\x0f", 0),
        ),
    ),
    "GC9A01": (
        240,
        240,
        2,
        0x05,
        (0x48, 0x28, 0x88, 0xE8),
        (
            (0xEF, None, 0),
            (0xEB, b"\x14", 0),
            (0xFE, None, 0),
            (0xEF, None, 0),
            (0xEB, b"\x14", 0),
            (0x84, b"\x40", 0),
            (0x85, b"\xff", 0),
            (0x86, b"\xff", 0),
            (0x87, b"\xff", 0),
            (0x88, b"\x0a", 0),
            (0x89, b"\x21", 0),
            (0x8A, b"\x00", 0),
            (0x8B, b"\x80", 0),
            (0x8C, b"\x01", 0),
            (0x8D, b"\x01", 0),
            (0x8E, b"\xff", 0),
            (0x8F, b"\xff", 0),
            (0xB6, b"\x00\x20", 0),
            (0x90, b"\x08\x08\x08\x08", 0),
            (0xBD, b"\x06", 0),
            (0xBC, b"\x00", 0),
            (0xFF, b"\x60\x01\x04", 0),
            (0xC3, b"\x13", 0),
            (0xC4, b"\x13", 0),
            (0xC9, b"\x22", 0),
            (0xBE, b"\x11", 0),
            (0xE1, b"\x10\x0e", 0),
            (0xDF, b"\x21\x0c\x02", 0),
            (0xF0, b"\x45\x09\x08\x08\x26\x2a", 0),
            (0xF1, b"\x43\x70\x72\x36\x37\x6f", 0),
            (0xF2, b"\x45\x09\x08\x08\x26\x2a", 0),
            (0xF3, b"\x43\x70\x72\x36\x37\x6f", 0),
            (0xED, b"\x1b\x0b", 0),
            (0xAE, b"\x77", 0),
            (0xCD, b"\x63", 0),
            (0x70, b"\x07\x07\x04\x0e\x0f\x09\x07\x08\x03", 0),
            (0xE8, b"\x34", 0),
            (0x62, b"\x18\x0d\x71\xed\x70\x70\x18\x0f\x71\xef\x70\x70", 0),
            (0x63, b"\x18\x11\x71\xf1\x70\x70\x18\x13\x71\xf3\x70\x70", 0),
            (0x64, b"\x28\x29\xf1\x01\xf1\x00\x07", 0),
            (0x66, b"\x3c\x00\xcd\x67\x45\x45\x10\x00\x00\x00", 0),
            (0x67, b"\x00\x3c\x00\x00\x00\x01\x54\x10\x32\x98", 0),
            (0x74, b"\x10\x85\x80\x00\x00\x4e\x00", 0),
            (0x98, b"\x3e\x07", 0),
            (0x35, None, 0),  # tearing effect line on
        ),
    ),
}


def default_rotations(controller):
    """The rotation table of a panel as big as the controller's memory."""
    w, h, _bpp, _colmod, madctl, _init = CONTROLLERS[controller]
    return (
        (madctl[0], w, h, 0, 0),
        (madctl[1], h, w, 0, 0),
        (madctl[2], w, h, 0, 0),
        (madctl[3], h, w, 0, 0),
    )


def _to666_py(src, dst, pixels):
    """Wire-order RGB565 (2 bytes) -> RGB666 (3 bytes: R, G, B in the high 6 bits)."""
    j = 0
    for i in range(0, 2 * pixels, 2):
        hi = src[i]
        lo = src[i + 1]
        dst[j] = hi & 0xF8
        dst[j + 1] = ((hi & 0x07) << 5) | ((lo & 0xE0) >> 3)
        dst[j + 2] = (lo & 0x1F) << 3
        j += 3


# The same loop compiled to machine code; a port without the native emitter keeps
# the Python loop (compiled from a string so that the module still imports).
_TO666_VIPER = """
@micropython.viper
def to666(src, dst, pixels: int):
    s = ptr8(src)
    d = ptr8(dst)
    i = 0
    j = 0
    n = 2 * pixels
    while i < n:
        hi = s[i]
        lo = s[i + 1]
        d[j] = hi & 0xF8
        d[j + 1] = ((hi & 0x07) << 5) | ((lo & 0xE0) >> 3)
        d[j + 2] = (lo & 0x1F) << 3
        i += 2
        j += 3
"""
try:
    import micropython

    _ns = {"micropython": micropython}
    exec(_TO666_VIPER, _ns)
    to666 = _ns["to666"]
except Exception:  # no native emitter (or not MicroPython)
    to666 = _to666_py


def _noop(*_args):
    pass


class TFT:
    def __init__(
        self,
        spi,
        controller,
        dc,
        cs,
        reset,
        backlight=None,
        rotation=0,
        invert=False,
        rotations=None,
        strip_bytes=STRIP_BYTES,
    ):
        if controller not in CONTROLLERS:
            raise ValueError("unsupported display controller %r" % (controller,))
        self.controller = controller
        _w, _h, self._bpp, self._colmod, _madctl, self._init_seq = CONTROLLERS[controller]
        self._table = rotations or default_rotations(controller)
        self._spi_write = spi.write
        self._dc = dc.value
        self._cs = cs.value if cs is not None else _noop
        self._reset = reset
        self._backlight = backlight
        self._args = bytearray(4)
        self._cmd = bytearray(1)
        self._strip = memoryview(bytearray(strip_bytes - strip_bytes % 6))
        self.width = self._table[0][1]
        self.height = self._table[0][2]
        self.rotation = 0
        self._x_off = 0
        self._y_off = 0
        self._cs(1)
        self.hard_reset()
        self.init(rotation, invert)

    # ------------------------------------------------------------ bus level
    def _command(self, command, data=None):
        # Caller holds CS low.
        cmd = self._cmd
        cmd[0] = command
        self._dc(0)
        self._spi_write(cmd)
        if data is not None:
            self._dc(1)
            self._spi_write(data)

    def _send(self, command, data=None):
        self._cs(0)
        self._command(command, data)
        self._cs(1)

    def _window(self, x0, y0, x1, y1):
        # Caller holds CS low. Leaves the panel in RAMWR with DC high.
        args = self._args
        x0 += self._x_off
        x1 += self._x_off
        y0 += self._y_off
        y1 += self._y_off
        args[0] = x0 >> 8
        args[1] = x0 & 0xFF
        args[2] = x1 >> 8
        args[3] = x1 & 0xFF
        self._command(_CASET, args)
        args[0] = y0 >> 8
        args[1] = y0 & 0xFF
        args[2] = y1 >> 8
        args[3] = y1 & 0xFF
        self._command(_RASET, args)
        self._command(_RAMWR)
        self._dc(1)

    def _check_area(self, x, y, w, h):
        if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > self.width or y + h > self.height:
            raise ValueError(
                "area %d,%d %dx%d is outside %dx%d" % (x, y, w, h, self.width, self.height)
            )

    # ------------------------------------------------------------ panel
    def hard_reset(self):
        reset = self._reset
        if reset is None:
            return
        reset.value(1)
        sleep_ms(10)
        reset.value(0)
        sleep_ms(10)
        reset.value(1)
        sleep_ms(120)

    def init(self, rotation=0, invert=False):
        self._send(_SWRESET)
        sleep_ms(150)
        for command, data, delay in self._init_seq:
            self._send(command, data)
            if delay:
                sleep_ms(delay)
        self._send(_COLMOD, bytes((self._colmod,)))
        self.set_rotation(rotation)
        self._send(_INVON if invert else _INVOFF)
        self._send(_SLPOUT)
        sleep_ms(120)
        self._send(_NORON)
        sleep_ms(10)
        self.fill_rect(0, 0, self.width, self.height, 0)
        self._send(_DISPON)
        sleep_ms(20)
        self.backlight(True)

    def set_rotation(self, rotation):
        if not 0 <= rotation < len(self._table):
            raise ValueError("rotation must be 0..%d" % (len(self._table) - 1))
        madctl, self.width, self.height, self._x_off, self._y_off = self._table[rotation]
        self.rotation = rotation
        self._send(_MADCTL, bytes((madctl,)))

    def backlight(self, on):
        if self._backlight is not None:
            self._backlight.value(1 if on else 0)

    # ------------------------------------------------------------ drawing
    def blit(self, buf, x, y, w, h):
        """Write a wire-order RGB565 buffer (e.g. a framebuf's) into the window."""
        self._check_area(x, y, w, h)
        n = w * h
        if len(buf) < n * 2:
            raise ValueError("buffer too small for %dx%d" % (w, h))
        self._cs(0)
        self._window(x, y, x + w - 1, y + h - 1)
        if self._bpp == 2:
            self._spi_write(buf if len(buf) == n * 2 else memoryview(buf)[: n * 2])
        else:
            src = memoryview(buf)
            strip = self._strip
            step = len(strip) // 3
            done = 0
            while done < n:
                count = step if n - done > step else n - done
                to666(src[2 * done : 2 * (done + count)], strip, count)
                self._spi_write(strip[: 3 * count])
                done += count
        self._cs(1)

    def fill_rect(self, x, y, w, h, color):
        """Fill an area with a wire-order colour, in strips (no full-screen buffer)."""
        self._check_area(x, y, w, h)
        strip = self._strip
        if self._bpp == 2:
            pattern = bytes((color & 0xFF, (color >> 8) & 0xFF))
        else:
            hi = color & 0xFF
            lo = (color >> 8) & 0xFF
            pattern = bytes((hi & 0xF8, ((hi & 0x07) << 5) | ((lo & 0xE0) >> 3), (lo & 0x1F) << 3))
        bpp = self._bpp
        total = w * h * bpp
        size = min(len(strip) - len(strip) % bpp, total)
        strip[0:bpp] = pattern
        done = bpp
        while done < size:  # fill the reusable strip by doubling: no allocations
            step = min(done, size - done)
            strip[done : done + step] = strip[0:step]
            done += step
        self._cs(0)
        self._window(x, y, x + w - 1, y + h - 1)
        chunk = strip[0:size]
        while total >= size:
            self._spi_write(chunk)
            total -= size
        if total:
            self._spi_write(strip[0:total])
        self._cs(1)
