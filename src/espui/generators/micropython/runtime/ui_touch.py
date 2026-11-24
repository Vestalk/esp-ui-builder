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
#
# Calibration (XPT2046): ui_display.calibrate_touch() shows four crosses, one after
# another; touch each one. It prints the line "ESPUI-CAL x_min=… swap_xy=…" to paste
# into the editor (Дисплей → Сенсорний екран → Калібрування) and applies it right away.

try:
    from time import sleep_ms
except ImportError:  # CPython (tests)
    from time import sleep as _sleep

    def sleep_ms(ms):
        _sleep(ms / 1000)


CAL_INSET = 20  # crosses this far from the edges of the screen
CAL_SAMPLES = 8  # readings of a steady press per cross
CAL_PREFIX = "ESPUI-CAL"
WHITE = 0xFFFF
BLACK = 0
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


def to_portrait(x, y, width, height, rotation):
    """Screen point for ``rotation`` -> portrait point (the inverse of to_screen)."""
    if rotation == 1:
        return width - 1 - y, x
    if rotation == 2:
        return width - 1 - x, height - 1 - y
    if rotation == 3:
        return y, height - 1 - x
    return x, y


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


def _cross(display, x, y, color):
    display.fill_rect(x - 8, y, 17, 1, color)
    display.fill_rect(x, y - 8, 1, 17, color)


def _press(touch):
    """Median raw (a, b) of a steady press; returns after the finger is lifted."""
    samples = []
    while len(samples) < CAL_SAMPLES:
        raw = touch.raw()
        if raw is None:
            samples = []  # lifted too early: start again
            sleep_ms(20)
            continue
        samples.append(raw)
        sleep_ms(10)
    while touch.raw() is not None:
        sleep_ms(20)
    sleep_ms(150)
    return _median([r[0] for r in samples]), _median([r[1] for r in samples])


def _fit(points, pos, raw, size):
    """Raw values at portrait 0 and size-1, from the readings at two positions."""
    lo = min(p[pos] for p in points)
    hi = max(p[pos] for p in points)
    r_lo = [p[raw] for p in points if p[pos] == lo]
    r_hi = [p[raw] for p in points if p[pos] == hi]
    r_lo = sum(r_lo) / len(r_lo)
    r_hi = sum(r_hi) / len(r_hi)
    slope = (r_hi - r_lo) / (hi - lo)
    low = r_lo - slope * lo
    return int(round(low)), int(round(low + slope * (size - 1)))


def solve(points, width, height):
    """[(portrait x, y, raw a, raw b)] at the crosses -> calibration values.

    ``swap_xy``: the panel's first raw channel follows the portrait Y.
    """

    def change(pos, raw):
        lo = min(p[pos] for p in points)
        a = [p[raw] for p in points if p[pos] == lo]
        b = [p[raw] for p in points if p[pos] != lo]
        return abs(sum(b) / len(b) - sum(a) / len(a))

    swap = change(1, 2) > change(0, 2)
    rx, ry = (3, 2) if swap else (2, 3)
    x_min, x_max = _fit(points, 0, rx, width)
    y_min, y_max = _fit(points, 1, ry, height)
    clamp = lambda v: 0 if v < 0 else 4095 if v > 4095 else v  # noqa: E731
    return {
        "x_min": clamp(x_min),
        "x_max": clamp(x_max),
        "y_min": clamp(y_min),
        "y_max": clamp(y_max),
        "swap_xy": swap,
    }


def calibration_line(cal):
    return "%s x_min=%d x_max=%d y_min=%d y_max=%d swap_xy=%d" % (
        CAL_PREFIX,
        cal["x_min"],
        cal["x_max"],
        cal["y_min"],
        cal["y_max"],
        1 if cal["swap_xy"] else 0,
    )


def run_calibration(display, touch, inset=CAL_INSET):
    """Four crosses in the corners, touched one by one: the values, applied to ``touch``."""
    if not hasattr(touch, "raw"):
        raise ValueError("calibration is for XPT2046 (resistive); CST816S needs none")
    sw, sh = display.width, display.height
    targets = (
        (inset, inset),
        (sw - 1 - inset, inset),
        (sw - 1 - inset, sh - 1 - inset),
        (inset, sh - 1 - inset),
    )
    display.fill_rect(0, 0, sw, sh, BLACK)
    points = []
    for sx, sy in targets:
        _cross(display, sx, sy, WHITE)
        a, b = _press(touch)
        _cross(display, sx, sy, BLACK)
        px, py = to_portrait(sx, sy, touch.width, touch.height, touch.rotation)
        points.append((px, py, a, b))
    cal = solve(points, touch.width, touch.height)
    touch.cal = (cal["x_min"], cal["x_max"], cal["y_min"], cal["y_max"])
    touch.swap_xy = cal["swap_xy"]
    print(calibration_line(cal))
    display.fill_rect(sw // 2 - 10, sh // 2 - 10, 21, 21, WHITE)  # done
    return cal
