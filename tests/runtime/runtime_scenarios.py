# Scenarios for the on-device runtime (ui_display + drivers), with fake SPI/Pins.
#
# Must stay MicroPython-compatible: it is executed both in-process on CPython
# and on the MicroPython unix port (see tests/runtime/harness.py). Every
# scenario returns JSON-serialisable data; assertions live in the pytest side.

import ui_display


class FakePin:
    def __init__(self, name):
        self.name = name
        self.state = None
        self.history = []

    def value(self, v=None):
        if v is None:
            return self.state
        self.state = 1 if v else 0
        self.history.append(self.state)
        return None

    def on(self):
        self.value(1)

    def off(self):
        self.value(0)

    def __call__(self, v=None):
        return self.value(v)


class FakeSPI:
    """Records each write together with the DC and CS levels at that moment."""

    def __init__(self, pins):
        self._dc = pins["dc"]
        self._cs = pins.get("cs")
        self.writes = []

    def write(self, data):
        cs = None if self._cs is None else self._cs.state
        self.writes.append((self._dc.state, cs, bytes(data)))

    def transactions(self):
        """[[command, payload_bytes], ...] in bus order."""
        out = []
        for dc, _cs, data in self.writes:
            if dc == 0:
                for byte in data:
                    out.append([byte, bytearray()])
            elif out:
                out[-1][1].extend(data)
        return out

    def writes_with_cs_high(self):
        return len([w for w in self.writes if w[1] == 1])

    def reset(self):
        self.writes = []


def _bus(with_blk=True):
    pins = {"cs": FakePin("cs"), "dc": FakePin("dc"), "rst": FakePin("rst")}
    pins["blk"] = FakePin("blk") if with_blk else None
    return FakeSPI(pins), pins


def _open(driver, rotation=0, invert=True, with_blk=True):
    spi, pins = _bus(with_blk)
    display = ui_display.open_display(driver, spi, pins, 240, 320, rotation, invert)
    return display, spi, pins


def _hex(data):
    return "".join("%02x" % b for b in data)


def _rgb565_buffer(w, h, wire_color):
    """A w*h RGB565 buffer as framebuf would hold it (real framebuf if available)."""
    buf = bytearray(w * h * 2)
    try:
        import framebuf
    except ImportError:  # CPython: emulate little-endian framebuf storage
        lo, hi = wire_color & 0xFF, (wire_color >> 8) & 0xFF
        for i in range(0, len(buf), 2):
            buf[i] = lo
            buf[i + 1] = hi
        return buf, False
    fb = framebuf.FrameBuffer(buf, w, h, framebuf.RGB565)
    fb.fill(wire_color)
    return buf, True


def _last_window(tx):
    caset = [p for c, p in tx if c == 0x2A]
    raset = [p for c, p in tx if c == 0x2B]
    return [_hex(caset[-1]), _hex(raset[-1])]


def _pixels_after_last_ramwr(tx):
    payload = [p for c, p in tx if c == 0x2C][-1]
    return payload


# ------------------------------------------------------------------ scenarios
def init_sequence(driver, rotation, invert, with_blk):
    display, spi, pins = _open(driver, rotation, invert, with_blk)
    tx = spi.transactions()
    madctl = [p for c, p in tx if c == 0x36]
    return {
        "commands": [c for c, _p in tx],
        "madctl": madctl[-1][0],
        "colmod": _hex([p for c, p in tx if c == 0x3A][-1]),
        "size": [display.width, display.height],
        "driver": display.driver,
        "rst": pins["rst"].history,
        "blk": None if pins["blk"] is None else pins["blk"].history,
        "cs_high_writes": spi.writes_with_cs_high(),
    }


def fill_rect(driver, rotation, x, y, w, h, wire_color):
    display, spi, _pins = _open(driver, rotation)
    spi.reset()
    display.fill_rect(x, y, w, h, wire_color)
    tx = spi.transactions()
    pixels = _pixels_after_last_ramwr(tx)
    pairs = {}
    for i in range(0, len(pixels), 2):
        pairs[_hex(pixels[i : i + 2])] = 1
    return {
        "window": _last_window(tx),
        "pixel_bytes": len(pixels),
        "pairs": sorted(pairs),
        "max_write": max(len(d) for _dc, _cs, d in spi.writes),
        "cs_high_writes": spi.writes_with_cs_high(),
    }


def blit(driver, x, y, w, h, wire_color):
    display, spi, _pins = _open(driver)
    buf, real_framebuf = _rgb565_buffer(w, h, wire_color)
    spi.reset()
    display.blit(buf, x, y, w, h)
    tx = spi.transactions()
    pixels = _pixels_after_last_ramwr(tx)
    data_writes = [d for dc, _cs, d in spi.writes if dc == 1 and len(d) > 4]
    return {
        "window": _last_window(tx),
        "same_bytes": bytes(pixels) == bytes(buf),
        "first_pixel": _hex(pixels[0:2]),
        "data_writes": len(data_writes),
        "real_framebuf": real_framebuf,
    }


def errors(driver):
    display, _spi, _pins = _open(driver)
    result = {}
    cases = {
        "fill_outside": lambda: display.fill_rect(200, 300, 50, 50, 0),
        "fill_negative": lambda: display.fill_rect(-1, 0, 5, 5, 0),
        "blit_outside": lambda: display.blit(bytearray(8), 239, 319, 2, 2),
        "blit_short_buffer": lambda: display.blit(bytearray(4), 0, 0, 2, 2),
    }
    for name in sorted(cases):
        try:
            cases[name]()
            result[name] = None
        except ValueError as exc:
            result[name] = str(exc)
    return result


def unknown_driver():
    spi, pins = _bus()
    try:
        ui_display.open_display("nope", spi, pins)
    except ValueError as exc:
        return str(exc)
    return None


def backlight(driver, with_blk):
    display, _spi, pins = _open(driver, with_blk=with_blk)
    display.backlight(False)
    display.backlight(True)
    return None if pins["blk"] is None else pins["blk"].history


def color_helpers():
    import ui_st7789

    return {
        "red": ui_st7789.color(255, 0, 0),
        "green": ui_st7789.color(0, 255, 0),
        "blue": ui_st7789.color(0, 0, 255),
        "white": ui_st7789.color(255, 255, 255),
        "swap": ui_st7789.swap16(0x1234),
    }


# ------------------------------------------------- ui_tft (ILI9488 / GC9A01 / ILI9341)
def _open_tft(controller, rotation=0, invert=False):
    spi, pins = _bus(True)
    display = ui_display.open_display(
        "builtin", spi, pins, 0, 0, rotation, invert, controller=controller, rotations=None
    )
    return display, spi, pins


def tft_init(controller, rotation, invert):
    display, spi, pins = _open_tft(controller, rotation, invert)
    tx = spi.transactions()
    commands = [c for c, _p in tx]
    return {
        "commands": commands,
        "madctl": [p for c, p in tx if c == 0x36][-1][0],
        "colmod": _hex([p for c, p in tx if c == 0x3A][-1]),
        "size": [display.width, display.height],
        "rst": pins["rst"].history,
        "blk": pins["blk"].history,
        "cs_high_writes": spi.writes_with_cs_high(),
        # the full-screen clear at start-up: how many bytes went after its RAMWR
        "clear_bytes": len(_pixels_after_last_ramwr(tx)),
    }


def tft_blit(controller, wire_color, w, h):
    display, spi, _pins = _open_tft(controller)
    spi.reset()
    buf, _real = _rgb565_buffer(w, h, wire_color)
    display.blit(buf, 3, 4, w, h)
    tx = spi.transactions()
    pixels = _pixels_after_last_ramwr(tx)
    return {"window": _last_window(tx), "bytes": len(pixels), "head": _hex(pixels[:9])}


def tft_fill(controller, wire_color, w, h):
    display, spi, _pins = _open_tft(controller)
    spi.reset()
    display.fill_rect(1, 2, w, h, wire_color)
    tx = spi.transactions()
    pixels = _pixels_after_last_ramwr(tx)
    return {"window": _last_window(tx), "bytes": len(pixels), "head": _hex(pixels[:9])}
