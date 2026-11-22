# ui_sd — microSD card of a display module on the display's SPI bus (stock MicroPython).
#
# Copied into a generated project only when its display has an SD card enabled.
#   path = ui_display.mount_sd(display)   # "/sd": then open("/sd/log.txt", "w") etc.
#
# The card shares the bus with the display (its own CS): every card operation
# switches the bus to the card's speed and back to the display's, so drawing
# and file access can take turns. Block device for os.VfsFat (FAT32 / FAT16 /
# exFAT is not supported by MicroPython's FAT driver: format the card as FAT32).

try:
    from time import sleep_ms
except ImportError:  # CPython (tests)
    from time import sleep as _sleep

    def sleep_ms(ms):
        _sleep(ms / 1000)


INIT_HZ = 400_000  # the card must be started slowly
BLOCK = 512
_TOKEN_DATA = 0xFE


class SDError(OSError):
    pass


class SDCard:
    """SD / SDHC / SDXC card in SPI mode: readblocks / writeblocks / ioctl for VfsFat."""

    def __init__(self, spi, cs, hz=20_000_000, bus_hz=None):
        self._spi = spi
        self._cs = cs
        self._hz = hz
        self._bus_hz = bus_hz  # the display's speed, restored after each operation
        self._cmd = bytearray(6)
        self._one = bytearray(1)
        self._crc = bytearray(2)
        self._ff = b"\xff"
        self.block_addressing = False
        self.sectors = 0
        cs.value(1)
        self._init_card()

    # ------------------------------------------------------------ bus
    def _begin(self, hz):
        self._spi.init(baudrate=hz)
        self._cs.value(0)

    def _end(self):
        self._cs.value(1)
        self._spi.write(self._ff)  # one more clock with CS high: the card lets MISO go
        if self._bus_hz:
            self._spi.init(baudrate=self._bus_hz)

    def _byte(self):
        self._spi.readinto(self._one, 0xFF)
        return self._one[0]

    def _command(self, cmd, arg, crc=0x01, skip=0):
        """Send a command (CS low already); returns R1, the first byte that isn't 0xFF."""
        buf = self._cmd
        buf[0] = 0x40 | cmd
        buf[1] = arg >> 24
        buf[2] = (arg >> 16) & 0xFF
        buf[3] = (arg >> 8) & 0xFF
        buf[4] = arg & 0xFF
        buf[5] = crc
        self._spi.write(buf)
        for _ in range(skip):
            self._byte()
        for _ in range(16):
            r1 = self._byte()
            if not r1 & 0x80:
                return r1
        return 0xFF

    def _wait_token(self):
        for _ in range(50_000):
            token = self._byte()
            if token == _TOKEN_DATA:
                return
            if token != 0xFF:
                break
        raise SDError("SD: no data token")

    def _wait_ready(self):
        for _ in range(100_000):
            if self._byte() == 0xFF:
                return
        raise SDError("SD: card stays busy")

    # ------------------------------------------------------------ start-up
    def _init_card(self):
        self._spi.init(baudrate=INIT_HZ)
        self._cs.value(1)
        for _ in range(16):  # >= 74 clocks with CS high
            self._spi.write(self._ff)
        self._begin(INIT_HZ)
        try:
            for _ in range(5):
                if self._command(0, 0, 0x95) == 0x01:  # GO_IDLE_STATE
                    break
            else:
                raise SDError("SD: no card (CMD0)")
            r1 = self._command(8, 0x01AA, 0x87)  # SEND_IF_COND: v2 cards answer 0x01
            v2 = r1 == 0x01
            if v2:
                echo = bytearray(4)
                self._spi.readinto(echo, 0xFF)
                if echo[3] != 0xAA:
                    raise SDError("SD: bad CMD8 echo")
            for _ in range(1000):
                self._command(55, 0)  # APP_CMD
                if self._command(41, 0x40000000 if v2 else 0) == 0:  # SD_SEND_OP_COND
                    break
                sleep_ms(1)
            else:
                raise SDError("SD: card does not start (ACMD41)")
            if v2 and self._command(58, 0) == 0:  # READ_OCR: CCS = block addressing
                ocr = bytearray(4)
                self._spi.readinto(ocr, 0xFF)
                self.block_addressing = bool(ocr[0] & 0x40)
            if not self.block_addressing:
                self._command(16, BLOCK)  # SET_BLOCKLEN
            if self._command(9, 0) != 0:  # SEND_CSD
                raise SDError("SD: no CSD")
            self._wait_token()
            csd = bytearray(16)
            self._spi.readinto(csd, 0xFF)
            self._spi.readinto(self._crc, 0xFF)
            self.sectors = sectors_from_csd(csd)
        finally:
            self._end()

    # ------------------------------------------------------------ block device
    def _address(self, block):
        return block if self.block_addressing else block * BLOCK

    def readblocks(self, block, buf):
        mv = memoryview(buf)
        count = len(buf) // BLOCK
        self._begin(self._hz)
        try:
            for i in range(count):
                if self._command(17, self._address(block + i)) != 0:  # READ_SINGLE_BLOCK
                    raise SDError("SD: read error at block %d" % (block + i))
                self._wait_token()
                self._spi.readinto(mv[i * BLOCK : (i + 1) * BLOCK], 0xFF)
                self._spi.readinto(self._crc, 0xFF)
        finally:
            self._end()

    def writeblocks(self, block, buf):
        mv = memoryview(buf)
        count = len(buf) // BLOCK
        self._begin(self._hz)
        try:
            for i in range(count):
                if self._command(24, self._address(block + i)) != 0:  # WRITE_BLOCK
                    raise SDError("SD: write error at block %d" % (block + i))
                self._spi.write(b"\xff\xfe")  # a gap byte, then the data token
                self._spi.write(mv[i * BLOCK : (i + 1) * BLOCK])
                self._spi.write(b"\xff\xff")  # CRC (not checked in SPI mode)
                if self._byte() & 0x1F != 0x05:
                    raise SDError("SD: write rejected at block %d" % (block + i))
                self._wait_ready()
        finally:
            self._end()

    def ioctl(self, op, arg):
        if op == 4:  # number of blocks
            return self.sectors
        if op == 5:  # block size
            return BLOCK
        return 0


def sectors_from_csd(csd):
    """Number of 512-byte blocks from the CSD register (versions 1 and 2)."""
    if csd[0] >> 6 == 1:  # CSD v2 (SDHC / SDXC)
        c_size = ((csd[7] & 0x3F) << 16) | (csd[8] << 8) | csd[9]
        return (c_size + 1) * 1024
    c_size = ((csd[6] & 0x03) << 10) | (csd[7] << 2) | (csd[8] >> 6)
    mult = ((csd[9] & 0x03) << 1) | (csd[10] >> 7)
    read_bl_len = csd[5] & 0x0F
    return ((c_size + 1) << (mult + 2)) * (1 << read_bl_len) // BLOCK


def mount(spi, settings, bus_hz):
    """Start the card and mount it at settings["mount"]; returns the path."""
    import os

    import machine

    cs = machine.Pin(settings["cs"], machine.Pin.OUT, value=1)
    card = SDCard(spi, cs, settings.get("spi_hz", 20_000_000), bus_hz)
    path = settings.get("mount", "/sd")
    os.mount(os.VfsFat(card), path)
    return path
