# ui_display — display adapter of ESP UI Builder.
#
# Pages (ui_<page>.py) draw only through `Display`; which Python driver sits
# behind it (built-in ui_st7789 or st7789py) is chosen by DRIVER below, so
# switching drivers never changes page code.
#
# Colours passed to Display are RGB565 in wire order (bytes pre-swapped, see
# ui_st7789.color); framebuf buffers filled with such colours are blitted as is.
#
# The settings block is filled in by the generator (stage 03) from the
# project's display settings.

# --- settings ---------------------------------------------------------------
DRIVER = "builtin"  # "builtin" | "st7789py"
PINS = {"sck": 12, "mosi": 11, "cs": 10, "dc": 9, "rst": 8, "blk": 7}  # blk: None if absent
SPI_ID = 1
SPI_HZ = 40_000_000
WIDTH = 240  # physical panel size, portrait
HEIGHT = 320
ROTATION = 0  # 0-3
INVERT = True
CONTROLLER = "ST7789"  # ST7789 | ILI9488 | ILI9341 | GC9A01
ROTATIONS = None  # ((MADCTL, width, height, x offset, y offset), ...) per rotation; None: driver's
TOUCH = None  # touch panel: None, or {"kind": "xpt2046" | "cst816s", pins…, calibration}
SD = None  # microSD slot: None, or {"cs": GPIO, "mount": "/sd", "spi_hz": 20_000_000}
BUF_BYTES = 16_384  # region buffer: one strip of what is redrawn
IMAGE_CACHE = 0  # RAM for keeping pictures (0 = read from flash each time)
# -----------------------------------------------------------------------------

_CONTROL_PINS = ("cs", "dc", "rst", "blk")


class Display:
    """What pages draw on: blit(buf, x, y, w, h), fill_rect(x, y, w, h, color), backlight(on).

    The methods are the driver's own bound callables (or thin wrappers),
    so the adapter adds no per-call overhead for the built-in driver.
    """

    def __init__(self, driver, width, height, blit, fill_rect, backlight):
        self.driver = driver
        self.width = width
        self.height = height
        self.blit = blit
        self.fill_rect = fill_rect
        self.backlight = backlight
        self.buf_bytes = BUF_BYTES  # read by ui_draw.Page
        self.image_cache = IMAGE_CACHE
        self.spi = None  # the bus, set by create(): the touch panel and SD card share it


def check_area(x, y, w, h, width, height):
    if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > width or y + h > height:
        raise ValueError("area %d,%d %dx%d is outside %dx%d" % (x, y, w, h, width, height))


# --- adapters: one function per driver key ------------------------------------
def _open_builtin(spi, pins, width, height, rotation, invert, controller="ST7789", rotations=None):
    if controller == "ST7789":
        import ui_st7789

        drv = ui_st7789.ST7789(
            spi,
            width,
            height,
            dc=pins["dc"],
            cs=pins.get("cs"),
            reset=pins.get("rst"),
            backlight=pins.get("blk"),
            rotation=rotation,
            invert=invert,
            rotations=rotations,
        )
    else:  # ILI9488 / ILI9341 / GC9A01: the generic driver
        import ui_tft

        drv = ui_tft.TFT(
            spi,
            controller,
            dc=pins["dc"],
            cs=pins.get("cs"),
            reset=pins.get("rst"),
            backlight=pins.get("blk"),
            rotation=rotation,
            invert=invert,
            rotations=rotations,
        )
    return Display("builtin", drv.width, drv.height, drv.blit, drv.fill_rect, drv.backlight)


def _open_st7789py(spi, pins, width, height, rotation, invert, controller="ST7789", rotations=None):
    import st7789py

    blk = pins.get("blk")
    drv = st7789py.ST7789(
        spi,
        width,
        height,
        reset=pins.get("rst"),
        dc=pins["dc"],
        cs=pins.get("cs"),
        backlight=blk,
        rotation=rotation,
        color_order=st7789py.RGB,  # its default is BGR
    )
    if not invert:  # its init sequence always enables inversion
        drv.inversion_mode(False)

    # st7789py silently ignores out-of-range windows and then writes the data
    # into the previous window, so bounds are checked here.
    def blit(buf, x, y, w, h):
        check_area(x, y, w, h, drv.width, drv.height)
        if len(buf) < w * h * 2:
            raise ValueError("buffer too small for %dx%d" % (w, h))
        drv.blit_buffer(buf, x, y, w, h)

    def fill_rect(x, y, w, h, color):
        check_area(x, y, w, h, drv.width, drv.height)
        # st7789py packs colours big-endian itself: undo the wire-order swap.
        drv.fill_rect(x, y, w, h, ((color & 0xFF) << 8) | ((color >> 8) & 0xFF))

    def backlight(on):
        if blk is not None:
            blk.value(1 if on else 0)

    return Display("st7789py", drv.width, drv.height, blit, fill_rect, backlight)


ADAPTERS = {
    "builtin": _open_builtin,
    "st7789py": _open_st7789py,
}


def open_display(
    driver,
    spi,
    pins,
    width=WIDTH,
    height=HEIGHT,
    rotation=ROTATION,
    invert=INVERT,
    controller=CONTROLLER,
    rotations=ROTATIONS,
):
    """Wrap an already configured SPI bus and Pin objects into a Display."""
    try:
        adapter = ADAPTERS[driver]
    except KeyError:
        raise ValueError("unknown display driver %r" % (driver,)) from None
    return adapter(spi, pins, width, height, rotation, invert, controller, rotations)


def spi_mode(pins=PINS):
    """(polarity, phase): a module without CS (its CS tied low) wants SPI mode 3."""
    return (0, 0) if pins.get("cs") is not None else (1, 1)


def make_bus(pins=PINS, spi_id=SPI_ID, spi_hz=SPI_HZ):
    """Create machine.SPI and output Pins from pin numbers. Returns (spi, pins)."""
    import machine

    polarity, phase = spi_mode(pins)
    extra = {}
    if pins.get("miso") is not None:  # touch panel / SD card answer on it
        extra["miso"] = machine.Pin(pins["miso"])
    spi = machine.SPI(
        spi_id,
        baudrate=spi_hz,
        polarity=polarity,
        phase=phase,
        sck=machine.Pin(pins["sck"]),
        mosi=machine.Pin(pins["mosi"]),
        **extra,
    )
    out = {}
    for name in _CONTROL_PINS:
        number = pins.get(name)
        out[name] = None if number is None else machine.Pin(number, machine.Pin.OUT, value=1)
    # CS lines of the other devices on the bus stay high (deselected) from the start.
    for number in (_extra_cs(TOUCH), _extra_cs(SD)):
        if number is not None:
            machine.Pin(number, machine.Pin.OUT, value=1)
    return spi, out


def _extra_cs(device):
    if device is None or (device.get("kind", "spi") not in ("spi", "xpt2046")):
        return None
    return device.get("cs")


def create(driver=DRIVER):
    """Initialise the configured driver and return a Display (``display.spi``: its bus)."""
    spi, pins = make_bus()
    display = open_display(driver, spi, pins)
    display.spi = spi
    return display


def create_touch(display, settings=None):
    """The touch panel of the module (ui_touch), or None if the display has none.

    ``touch.read()`` gives (x, y) in screen coordinates of the current rotation, or None.
    """
    settings = TOUCH if settings is None else settings
    if not settings:
        return None
    import ui_touch

    return ui_touch.open_touch(settings, display, getattr(display, "spi", None), SPI_HZ, ROTATION)


def mount_sd(display, settings=None):
    """Mount the module's microSD card (ui_sd) at SD["mount"]; returns the path, or None."""
    settings = SD if settings is None else settings
    if not settings:
        return None
    import ui_sd

    return ui_sd.mount(display.spi, settings, SPI_HZ)
