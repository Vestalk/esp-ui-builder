# ui_st7789 — built-in ST7789 driver of ESP UI Builder.
#
# Pure Python for stock MicroPython (no C modules, no viper). Copied unchanged
# into every generated project. Pages never use it directly: they talk to the
# `Display` adapter from ui_display.py.
#
# Colour convention ("wire order"):
#   framebuf.RGB565 stores pixels little-endian on ESP32, the ST7789 expects
#   RGB565 big-endian. Every colour int in the runtime therefore has its two
#   bytes swapped in advance (see color()/swap16()), so a framebuf filled with
#   such a value already holds bytes in panel order and is sent as is.
#   fill_rect() takes colours in the same convention.

try:
    from micropython import const
except ImportError:  # CPython (tests, docs)

    def const(value):
        return value


try:
    from time import sleep_ms
except ImportError:  # CPython
    from time import sleep as _sleep

    def sleep_ms(ms):
        _sleep(ms / 1000)


# ST7789 commands
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

_COLMOD_RGB565 = const(0x55)

# Bytes written per SPI call by fill_rect(); also the size of its reusable buffer.
STRIP_BYTES = const(4096)

# Rotation tables per physical panel size (portrait width, height):
#   (madctl, width, height, x_offset, y_offset)[rotation]
# MADCTL bits: MY=0x80, MX=0x40, MV=0x20; RGB order (BGR bit 0x08 cleared).
ROTATIONS = {
    (240, 320): (
        (0x00, 240, 320, 0, 0),
        (0x60, 320, 240, 0, 0),
        (0xC0, 240, 320, 0, 0),
        (0xA0, 320, 240, 0, 0),
    ),
}


def swap16(value):
    """Swap the two bytes of a 16-bit value (true RGB565 <-> wire order)."""
    return ((value & 0xFF) << 8) | ((value >> 8) & 0xFF)


def color(red, green, blue):
    """RGB 0-255 -> RGB565 in wire order (for framebuf and fill_rect)."""
    return swap16(((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3))


def _noop(*_args):
    pass


class ST7789:
    def __init__(
        self,
        spi,
        width,
        height,
        dc,
        cs,
        reset,
        backlight=None,
        rotation=0,
        invert=True,
        rotations=None,
        strip_bytes=STRIP_BYTES,
    ):
        table = rotations or ROTATIONS.get((width, height))
        if table is None:
            raise ValueError("unsupported panel size %dx%d" % (width, height))
        self._table = table
        self._spi_write = spi.write
        self._dc = dc.value
        self._cs = cs.value if cs is not None else _noop
        self._reset = reset
        self._backlight = backlight
        self._args = bytearray(4)
        self._cmd = bytearray(1)
        self._strip = memoryview(bytearray(strip_bytes - strip_bytes % 2))
        self.width = width
        self.height = height
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

    def init(self, rotation=0, invert=True):
        self._send(_SWRESET)
        sleep_ms(150)
        self._send(_SLPOUT)
        sleep_ms(120)
        self._send(_COLMOD, bytes((_COLMOD_RGB565,)))
        sleep_ms(10)
        self.set_rotation(rotation)
        self._send(_INVON if invert else _INVOFF)
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
        if len(buf) < w * h * 2:
            raise ValueError("buffer too small for %dx%d" % (w, h))
        self._cs(0)
        self._window(x, y, x + w - 1, y + h - 1)
        self._spi_write(buf)
        self._cs(1)

    def fill_rect(self, x, y, w, h, color):
        """Fill an area with a wire-order colour, in strips (no full-screen buffer)."""
        self._check_area(x, y, w, h)
        total = w * h * 2
        strip = self._strip
        size = min(len(strip), total)
        # Fill the reusable strip by doubling: no allocations.
        strip[0] = color & 0xFF
        strip[1] = (color >> 8) & 0xFF
        done = 2
        while done < size:
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
