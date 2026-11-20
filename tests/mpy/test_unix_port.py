"""Sanity check that the MicroPython unix port works and has what generated code needs."""

from __future__ import annotations

from tests.mpy.conftest import RunMpy


def test_framebuf_rgb565(run_mpy: RunMpy) -> None:
    result = run_mpy(
        "import framebuf\n"
        "buf = bytearray(4 * 2 * 2)\n"
        "fb = framebuf.FrameBuffer(buf, 4, 2, framebuf.RGB565)\n"
        "fb.fill(0xF800)\n"
        "print(fb.pixel(3, 1))\n"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(0xF800)
