# Visual check of both display drivers in all four rotations (stage 01).
#
# Upload the runtime first (pins/SPI come from ui_display.py on the board):
#     mpremote cp src/espui/generators/micropython/runtime/ui_display.py \
#                 src/espui/generators/micropython/runtime/ui_st7789.py \
#                 src/espui/generators/micropython/runtime/st7789py.py :
#     mpremote run tools/hw_driver_check.py
#
# For every driver and rotation the screen shows, for ~3 s:
#   top-left RED, top-right GREEN, bottom-left BLUE, bottom-right WHITE squares,
#   a label "<driver> r<rotation>" in the middle (white on grey, via framebuf),
#   a 1-px yellow frame along the very edge (checks offsets: no gaps, no wrap).
# Correct: colours are exactly these, the label reads normally (not mirrored),
# the frame is complete on all four sides.

import time

import framebuf
import ui_display
from ui_st7789 import color

DRIVERS = ("builtin", "st7789py")
HOLD_MS = 3000
SQUARE = 24

RED = color(255, 0, 0)
GREEN = color(0, 255, 0)
BLUE = color(0, 0, 255)
WHITE = color(255, 255, 255)
YELLOW = color(255, 255, 0)
GREY = color(64, 64, 64)
BLACK = 0


def frame(d):
    d.fill_rect(0, 0, d.width, 1, YELLOW)
    d.fill_rect(0, d.height - 1, d.width, 1, YELLOW)
    d.fill_rect(0, 0, 1, d.height, YELLOW)
    d.fill_rect(d.width - 1, 0, 1, d.height, YELLOW)


def corners(d):
    s = SQUARE
    d.fill_rect(2, 2, s, s, RED)
    d.fill_rect(d.width - s - 2, 2, s, s, GREEN)
    d.fill_rect(2, d.height - s - 2, s, s, BLUE)
    d.fill_rect(d.width - s - 2, d.height - s - 2, s, s, WHITE)


def label(d, text):
    w, h = len(text) * 8 + 8, 16
    buf = bytearray(w * h * 2)
    fb = framebuf.FrameBuffer(buf, w, h, framebuf.RGB565)
    fb.fill(GREY)
    fb.text(text, 4, 4, WHITE)
    d.blit(buf, (d.width - w) // 2, (d.height - h) // 2, w, h)


def check(driver, spi, pins):
    for rotation in range(4):
        d = ui_display.open_display(driver, spi, pins, rotation=rotation)
        d.fill_rect(0, 0, d.width, d.height, BLACK)
        frame(d)
        corners(d)
        label(d, "%s r%d" % (driver, rotation))
        print("%-9s rotation %d  %dx%d" % (driver, rotation, d.width, d.height))
        time.sleep_ms(HOLD_MS)


def main():
    spi, pins = ui_display.make_bus()
    print("SPI:", spi)
    print("pins:", ui_display.PINS)
    for driver in DRIVERS:
        try:
            check(driver, spi, pins)
        except ImportError as exc:
            print("skip", driver, "-", exc)
    print("done")


main()
