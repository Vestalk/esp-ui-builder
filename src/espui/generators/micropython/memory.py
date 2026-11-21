"""How much of the board a project takes: flash for the files, RAM while drawing.

An estimate for the status bar, from the same generation the board gets
(pictures are only sized, not converted):

* flash: code (``*.py``), fonts (``ui_fonts.py``), pictures (``img/``);
* RAM: the region buffer shared by all pages (twice with translucent widgets),
  the decoded glyph bitmaps, one row of the widest picture and the picture
  cache (at most the pictures themselves). Interpreter,
  modules and parameters come on top and depend on the firmware.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from espui.core.models import Project
from espui.generators.micropython.fonts import FONTS_FILE
from espui.generators.micropython.generator import IMG_DIR, generate

_GLYPH_BYTES_RE = re.compile(r"glyphs, (\d+) bytes")


@dataclass(frozen=True, slots=True)
class MemoryEstimate:
    code: int
    fonts: int
    images: int
    ram: int

    @property
    def flash(self) -> int:
        return self.code + self.fonts + self.images

    def summary(self) -> str:
        """``Флеш ≈ 312 КБ (код 50 · шрифти 18 · картинки 244) · RAM ≈ 40 КБ``."""
        return (
            f"Флеш ≈ {_kb(self.flash)} (код {_kb(self.code, unit=False)} · "
            f"шрифти {_kb(self.fonts, unit=False)} · картинки {_kb(self.images, unit=False)})"
            f" · RAM ≈ {_kb(self.ram)}"
        )


def _kb(size: int, unit: bool = True) -> str:
    if size == 0:
        return "0 КБ" if unit else "0"
    text = f"{size / 1024:.0f}" if size >= 10 * 1024 else f"{size / 1024:.1f}".replace(".", ",")
    return f"{text} КБ" if unit else text


def estimate(project: Project) -> MemoryEstimate:
    result = generate(project, convert_images=False)
    code = fonts = images = 0
    for name, data in result.files.items():
        if name.startswith(IMG_DIR + "/"):
            images += len(data)
        elif name == FONTS_FILE:
            fonts += len(data)
        elif name.endswith(".py"):
            code += len(data)
    translucent = any(b"USES_ALPHA = True" in data for name, data in result.files.items()
                      if name.startswith("ui_") and name.endswith(".py"))  # fmt: skip
    glyphs = sum(
        int(n) for n in _GLYPH_BYTES_RE.findall(result.files.get(FONTS_FILE, b"").decode())
    )
    widest = max(
        (w.w for page in project.pages for w in page.widgets if w.type == "image"), default=0
    )
    display = project.display
    region = min(display.buf_bytes, display.screen_bytes)
    cache = min(display.image_cache, images)
    ram = region * (2 if translucent else 1) + glyphs + 2 * widest + cache
    return MemoryEstimate(code, fonts, images, ram)
