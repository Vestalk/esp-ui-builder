# Speed and memory measurements of the display drivers (stage 01).
#
# Upload the runtime first (pins come from ui_display.py on the board):
#     mpremote cp src/espui/generators/micropython/runtime/ui_display.py \
#                 src/espui/generators/micropython/runtime/ui_st7789.py \
#                 src/espui/generators/micropython/runtime/st7789py.py :
#     mpremote run tools/bench_display.py
#
# Prints a Markdown table: paste the whole output into docs/benchmarks.md
# (or send it to whoever fills the table).

import gc
import math
import sys
import time

import framebuf
import ui_display
from ui_st7789 import color

DRIVERS = (("builtin", "ui_st7789"), ("st7789py", "st7789py"))
SPI_HZ = (40_000_000, 80_000_000)

# (name, target ms or None)
TARGETS = {
    "fill": 60,
    "blit": 10,
    "fb": 20,
    "rotate": None,
}
AREA_W, AREA_H = 150, 48  # like a "Number" element
SPRITE = 32


def avg_ms(fn, runs):
    fn()  # warm-up
    start = time.ticks_us()
    for _ in range(runs):
        fn()
    return time.ticks_diff(time.ticks_us(), start) / runs / 1000


def import_cost(module):
    sys.modules.pop(module, None)
    gc.collect()
    before = gc.mem_free()
    __import__(module)
    gc.collect()
    return before - gc.mem_free()


def heap_info():
    gc.collect()
    free = gc.mem_free()
    total = free + gc.mem_alloc()
    return free, total


def psram_note(total):
    return "так" if total > 1024 * 1024 else "ні"


# ------------------------------------------------------------------ cases
def case_fill(d):
    colors = (color(255, 0, 0), color(0, 0, 255))
    state = [0]

    def run():
        state[0] ^= 1
        d.fill_rect(0, 0, d.width, d.height, colors[state[0]])

    return avg_ms(run, 5)


def case_blit(d):
    buf = bytearray(AREA_W * AREA_H * 2)
    framebuf.FrameBuffer(buf, AREA_W, AREA_H, framebuf.RGB565).fill(color(0, 128, 255))
    return avg_ms(lambda: d.blit(buf, 40, 100, AREA_W, AREA_H), 20)


def case_fb(d):
    white, bg = color(255, 255, 255), color(20, 20, 60)

    def run():
        buf = bytearray(AREA_W * AREA_H * 2)
        fb = framebuf.FrameBuffer(buf, AREA_W, AREA_H, framebuf.RGB565)
        fb.fill(bg)
        fb.text("23.4 C", 8, 20, white)
        d.blit(buf, 40, 160, AREA_W, AREA_H)

    return avg_ms(run, 20)


def case_rotate(d):
    n = SPRITE
    src_buf = bytearray(n * n * 2)
    src = framebuf.FrameBuffer(src_buf, n, n, framebuf.RGB565)
    src.fill(color(255, 255, 0))
    src.fill_rect(0, 0, n // 2, n // 2, color(255, 0, 0))
    src.text("A", 12, 12, 0)
    dst_buf = bytearray(n * n * 2)
    dst = framebuf.FrameBuffer(dst_buf, n, n, framebuf.RGB565)
    cos_a, sin_a = math.cos(math.radians(30)), math.sin(math.radians(30))
    c = (n - 1) / 2

    def run():
        # Nearest-neighbour, inverse mapping, plain Python (no viper).
        for y in range(n):
            dy = y - c
            for x in range(n):
                dx = x - c
                sx = int(cos_a * dx + sin_a * dy + c + 0.5)
                sy = int(-sin_a * dx + cos_a * dy + c + 0.5)
                if 0 <= sx < n and 0 <= sy < n:
                    dst.pixel(x, y, src.pixel(sx, sy))
                else:
                    dst.pixel(x, y, 0)
        d.blit(dst_buf, 100, 260, n, n)

    return avg_ms(run, 5)


CASES = (("fill", case_fill), ("blit", case_blit), ("fb", case_fb), ("rotate", case_rotate))


def mark(name, ms):
    target = TARGETS[name]
    if target is None:
        return "%.1f" % ms
    return "%.1f %s" % (ms, "✅" if ms < target else "❌")


def main():
    print("MicroPython:", sys.version, "|", sys.implementation._machine)
    free, total = heap_info()
    print("heap: free %d of %d bytes, PSRAM: %s" % (free, total, psram_note(total)))
    print()
    print(
        "| Драйвер | SPI, МГц | Фактично | Заливка екрана, мс (<60) | blit 150×48, мс (<10) "
        "| FrameBuffer+text+blit, мс (<20) | Поворот 32×32, мс | Імпорт, Б | Вільно RAM, Б |"
    )
    print("|---|---|---|---|---|---|---|---|---|")
    spi = None
    for driver, module in DRIVERS:
        try:
            cost = import_cost(module)
        except ImportError as exc:
            print("| %s | — | пропущено: %s |" % (driver, exc))
            continue
        for hz in SPI_HZ:
            if spi is not None:
                spi.deinit()
            spi, pins = ui_display.make_bus(spi_hz=hz)
            actual = str(spi)
            d = ui_display.open_display(driver, spi, pins)
            results = [mark(name, fn(d)) for name, fn in CASES]
            free, _total = heap_info()
            print(
                "| %s | %d | `%s` | %s | %d | %d |"
                % (driver, hz // 1_000_000, actual, " | ".join(results), cost, free)
            )
            del d
            gc.collect()
    print()
    print("done")


main()
