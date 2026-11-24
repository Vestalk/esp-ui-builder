# ui_touch — touch panels of display modules for ESP UI Builder (stock MicroPython).
#
# Copied into a generated project only when its display has a touch panel.
#   touch = ui_display.create_touch(display)
#   point = touch.read()   # (x, y) in screen coordinates of the current rotation, or None
#
# * XPT2046 (resistive, most 3.5" ILI9488 modules): on the display's SPI bus with
#   its own CS; read at 2 MHz (the bus is switched back to the display's speed
#   afterwards). Or on pins of its own (T_CLK / T_DIN / T_DO, e.g. the CYD board):
#   then a software SPI of its own, the display's bus is not touched.
#   Raw 12-bit readings are calibrated with x_min/x_max/y_min/y_max:
#   the raw values at the left / right / top / bottom edges in portrait (give them
#   the other way round to mirror an axis).
# * CST816S (capacitive, round GC9A01 touch modules): on I2C, address 0x15.

try:
    from time import sleep_ms
except ImportError:  # CPython (tests)
    from time import sleep as _sleep

    def sleep_ms(ms):
        _sleep(ms / 1000)


XPT_HZ = 2_000_000  # the XPT2046 is slow: SPI clock while reading it
XPT_SAMPLES = 5  # readings per axis; the median is used
XPT_PRESSURE = 300  # raw Z1 below this: not touched
CST_ADDR = 0x15


def to_screen(px, py, width, height, rotation):
    """Portrait point (0..width-1, 0..height-1) -> screen point for ``rotation`` 0-3."""
    if rotation == 1:
        return py, width - 1 - px
    if rotation == 2:
        return width - 1 - px, height - 1 - py
    if rotation == 3:
        return height - 1 - py, px
    return px, py


def calibrate(raw, low, high, size):
    """Raw reading -> 0..size-1 (``low`` > ``high`` mirrors the axis), clamped."""
    if high == low:
        return 0
    v = (raw - low) * (size - 1) // (high - low)
    return 0 if v < 0 else size - 1 if v > size - 1 else v


def _median(values):
    values = sorted(values)
    return values[len(values) // 2]


class XPT2046:
    def __init__(self, spi, cs, irq, width, height, rotation, cal, bus_hz, swap_xy=False):
        self._spi = spi
        self._cs = cs
        self._irq = irq
        self.width = width  # portrait size of the panel
        self.height = height
        self.rotation = rotation
        self.cal = cal  # (x_min, x_max, y_min, y_max)
        self.swap_xy = swap_xy
        self._bus_hz = bus_hz
        self._tx = bytearray(3)
        self._rx = bytearray(3)
        cs.value(1)

    def _channel(self, command):
        tx = self._tx
        tx[0] = command
        tx[1] = 0
        tx[2] = 0
        self._spi.write_readinto(tx, self._rx)
        rx = self._rx
        return ((rx[1] << 8) | rx[2]) >> 3  # 12 bits

    def raw(self):
        """Median raw (x, y, z1), or None if the panel isn't pressed."""
        if self._irq is not None and self._irq.value():
            return None  # T_IRQ is high while nothing touches the panel
        if self._bus_hz:  # the display's bus: slow it down for the panel
            self._spi.init(baudrate=XPT_HZ)
        self._cs.value(0)
        try:
            z1 = self._channel(0xB1)
            xs = [self._channel(0xD1) for _ in range(XPT_SAMPLES)]
            ys = [self._channel(0x91) for _ in range(XPT_SAMPLES)]
            self._channel(0x90)  # last conversion with power-down: T_IRQ works again
        finally:
            self._cs.value(1)
            if self._bus_hz:
                self._spi.init(baudrate=self._bus_hz)
        if z1 < XPT_PRESSURE:
            return None
        return _median(xs), _median(ys), z1

    def read(self):
        """(x, y) in screen coordinates, or None."""
        raw = self.raw()
        if raw is None:
            return None
        rx, ry = (raw[1], raw[0]) if self.swap_xy else (raw[0], raw[1])
        x_min, x_max, y_min, y_max = self.cal
        px = calibrate(rx, x_min, x_max, self.width)
        py = calibrate(ry, y_min, y_max, self.height)
        return to_screen(px, py, self.width, self.height, self.rotation)


class CST816S:
    def __init__(self, i2c, irq, rst, width, height, rotation):
        self._i2c = i2c
        self._irq = irq
        self.width = width
        self.height = height
        self.rotation = rotation
        self._buf = bytearray(6)
        if rst is not None:
            rst.value(0)
            sleep_ms(5)
            rst.value(1)
            sleep_ms(50)

    def read(self):
        """(x, y) in screen coordinates, or None (also while the chip sleeps)."""
        if self._irq is not None and self._irq.value():
            return None  # INT is low while touched
        try:
            self._i2c.readfrom_mem_into(CST_ADDR, 0x01, self._buf)
        except OSError:  # it sleeps between touches and does not answer then
            return None
        b = self._buf  # gesture, fingers, x high, x low, y high, y low
        if b[1] == 0:
            return None
        px = ((b[2] & 0x0F) << 8) | b[3]
        py = ((b[4] & 0x0F) << 8) | b[5]
        px = px if px < self.width else self.width - 1
        py = py if py < self.height else self.height - 1
        return to_screen(px, py, self.width, self.height, self.rotation)


def portrait_size(display, rotation):
    w, h = display.width, display.height
    return (h, w) if rotation % 2 else (w, h)


def open_touch(settings, display, spi, bus_hz, rotation):
    """The touch panel described by ``settings`` (ui_display.TOUCH)."""
    import machine

    width, height = portrait_size(display, rotation)

    def pin(name, mode):
        number = settings.get(name)
        return None if number is None else machine.Pin(number, mode)

    irq = pin("irq", machine.Pin.IN)
    if settings["kind"] == "xpt2046":
        if settings.get("sck") is not None:  # pins of its own (the CYD): a bus of its own
            spi = machine.SoftSPI(
                baudrate=XPT_HZ,
                polarity=0,
                phase=0,
                sck=machine.Pin(settings["sck"], machine.Pin.OUT),
                mosi=machine.Pin(settings["mosi"], machine.Pin.OUT),
                miso=machine.Pin(settings["miso"], machine.Pin.IN),
            )
            bus_hz = 0  # nothing to switch back
        elif spi is None:
            raise ValueError("XPT2046 needs the display's SPI bus: create the display first")
        cs = machine.Pin(settings["cs"], machine.Pin.OUT, value=1)
        cal = (settings["x_min"], settings["x_max"], settings["y_min"], settings["y_max"])
        return XPT2046(
            spi, cs, irq, width, height, rotation, cal, bus_hz, settings.get("swap_xy", False)
        )
    i2c = machine.I2C(
        0, sda=machine.Pin(settings["sda"]), scl=machine.Pin(settings["scl"]), freq=400_000
    )
    rst = pin("rst", machine.Pin.OUT)
    return CST816S(i2c, irq, rst, width, height, rotation)
