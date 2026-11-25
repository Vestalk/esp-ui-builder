"""Pictures of the project library: import, decoding and RGB565 conversion.

* :func:`import_image` turns a file (PNG, JPG, WebP, GIF, APNG; MP4/WebM with
  the optional ``av`` package) into an :class:`~espui.core.models.ImageAsset`:
  the original is embedded in the project, animations are split into frames
  (at most 48, videos at <= 12 fps and <= 30 s).
* :func:`render` fits a picture into a widget box (contain / cover / fill)
  and :func:`to_rgb565` produces what the board reads: raw RGB565 rows in
  wire order (see ``ui_st7789.color``), no header.
"""

from __future__ import annotations

import base64
import io
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PIL import Image, ImageSequence

from espui.core.colors import parse_hex
from espui.core.models import MAX_ANIMATION_FRAMES, ImageAsset
from espui.i18n import tr

Fit = Literal["contain", "cover", "fill"]
VIDEO_SUFFIXES = frozenset({".mp4", ".webm", ".mov", ".mkv"})
MAX_VIDEO_FPS = 12
MAX_VIDEO_SECONDS = 30
DEFAULT_DELAY_MS = 100
_NAME_RE = re.compile(r"[^a-z0-9_-]+")


class ImageImportError(ValueError):
    """The file can't be added to the library (Ukrainian message)."""


@dataclass(frozen=True, slots=True)
class Frames:
    images: list[Image.Image]
    delay_ms: int


def slug(name: str) -> str:
    """File name -> board name: latin letters, digits, ``_`` and ``-``."""
    stem = Path(name).stem.lower()
    return _NAME_RE.sub("_", stem).strip("_") or "image"


def unique(name: str, taken: Sequence[str] | set[str]) -> str:
    """``name``, or ``name_2``, ``name_3``... if it is taken."""
    if name not in taken:
        return name
    n = 2
    while f"{name}_{n}" in taken:
        n += 1
    return f"{name}_{n}"


def _png(image: Image.Image) -> str:
    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    return base64.b64encode(out.getvalue()).decode("ascii")


def thin(items: Sequence[Image.Image], limit: int = MAX_ANIMATION_FRAMES) -> list[Image.Image]:
    """At most ``limit`` items, picked evenly (first and last kept)."""
    n = len(items)
    if n <= limit:
        return list(items)
    if limit == 1:
        return [items[0]]
    return [items[round(i * (n - 1) / (limit - 1))] for i in range(limit)]


def _animated_frames(image: Image.Image) -> Frames:
    frames, delays = [], []
    for frame in ImageSequence.Iterator(image):
        frames.append(frame.convert("RGBA"))
        delays.append(int(frame.info.get("duration") or DEFAULT_DELAY_MS))
    picked = thin(frames)
    total = sum(delays)
    # One delay for the whole animation (anim.json): keep the total duration.
    delay = round(total / len(picked)) if total else DEFAULT_DELAY_MS
    return Frames(picked, max(20, min(5000, delay)))


def _video_frames(path: Path) -> Frames:
    try:
        import av
    except ImportError:  # pragma: no cover - depends on the environment
        raise ImageImportError(tr("Для відео встановіть пакет «av» (pip install av).")) from None
    try:
        container = av.open(str(path))
    except Exception as error:
        raise ImageImportError(
            tr("Не вдалося відкрити відео «{name}»: {error}").format(name=path.name, error=error)
        ) from None
    with container:
        stream = container.streams.video[0]
        rate = float(stream.average_rate or MAX_VIDEO_FPS)
        step = max(1, round(rate / MAX_VIDEO_FPS))
        frames = []
        for index, frame in enumerate(container.decode(stream)):
            if frame.time is not None and frame.time > MAX_VIDEO_SECONDS:
                break
            if index % step == 0:
                frames.append(frame.to_image().convert("RGBA"))  # type: ignore[no-untyped-call]
    if not frames:
        raise ImageImportError(tr("У відео «{name}» немає кадрів").format(name=path.name))
    picked = thin(frames)
    duration_ms = len(frames) * step * 1000 / rate
    return Frames(picked, max(20, min(5000, round(duration_ms / len(picked)))))


def import_image(path: str | Path, taken: Sequence[str] | set[str] = ()) -> tuple[str, ImageAsset]:
    """Read a file into the project library; returns (library key, asset).

    ``taken`` are the keys already in the library: a clash gets a ``_2`` suffix.
    """
    file = Path(path)
    key = unique(slug(file.name), taken)
    data = file.read_bytes()
    original = base64.b64encode(data).decode("ascii")
    if file.suffix.lower() in VIDEO_SUFFIXES:
        frames = _video_frames(file)
        first = frames.images[0]
        return key, ImageAsset(
            name=file.name,
            path=f"/img/{key}/",
            mime="video/" + file.suffix.lower().lstrip("."),
            data=original,
            width=first.width,
            height=first.height,
            frames=[_png(f) for f in frames.images],
            delay_ms=frames.delay_ms,
        )
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:
        raise ImageImportError(
            tr("«{name}» не схожий на картинку (PNG, JPG, WebP, GIF) чи відео (MP4, WebM)").format(
                name=file.name
            )
        ) from None
    mime = Image.MIME.get(image.format or "", "application/octet-stream")
    if getattr(image, "n_frames", 1) > 1:
        frames = _animated_frames(image)
        return key, ImageAsset(
            name=file.name,
            path=f"/img/{key}/",
            mime=mime,
            data=original,
            width=image.width,
            height=image.height,
            frames=[_png(f) for f in frames.images],
            delay_ms=frames.delay_ms,
        )
    return key, ImageAsset(
        name=file.name,
        path=f"/img/{key}.bin",
        mime=mime,
        data=original,
        width=image.width,
        height=image.height,
    )


# ------------------------------------------------------------------ decoding
def decode(asset: ImageAsset) -> list[Image.Image]:
    """All frames of an asset as RGBA images (one for a static picture)."""
    sources = asset.frames if asset.is_animation and asset.frames else [asset.data]
    images = []
    for item in sources:
        try:
            image = Image.open(io.BytesIO(base64.b64decode(item)))
            image.load()
        except Exception:
            raise ImageImportError(
                tr("Картинку «{name}» не вдалося прочитати").format(name=asset.name)
            ) from None
        images.append(image.convert("RGBA"))
    return images


def render(image: Image.Image, width: int, height: int, fit: Fit, background: str) -> Image.Image:
    """``image`` fitted into ``width`` x ``height`` over ``background`` (RGB result).

    contain: whole picture, centred, margins in the background colour;
    cover: fills the box, centred crop; fill: stretched.
    Transparent pixels show the background (the board has no alpha channel).
    """
    width, height = max(1, width), max(1, height)
    src = image.convert("RGBA")
    if fit == "fill":
        fitted = src.resize((width, height), Image.Resampling.LANCZOS)
        offset = (0, 0)
    else:
        scale = (min if fit == "contain" else max)(width / src.width, height / src.height)
        size = (max(1, round(src.width * scale)), max(1, round(src.height * scale)))
        fitted = src.resize(size, Image.Resampling.LANCZOS)
        offset = ((width - size[0]) // 2, (height - size[1]) // 2)
    canvas = Image.new("RGBA", (width, height), (*parse_hex(background), 255))
    canvas.alpha_composite(fitted, dest=(max(offset[0], 0), max(offset[1], 0)),
                           source=(max(-offset[0], 0), max(-offset[1], 0)))  # fmt: skip
    return canvas.convert("RGB")


def to_rgb565(image: Image.Image) -> bytes:
    """RGB image -> raw RGB565 rows as the board stores them (wire order, see ui_st7789)."""
    rgb = image.convert("RGB").tobytes()
    out = bytearray(len(rgb) // 3 * 2)
    for i in range(len(rgb) // 3):
        r, g, b = rgb[3 * i], rgb[3 * i + 1], rgb[3 * i + 2]
        v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        out[2 * i] = v >> 8  # big-endian = what the panel reads
        out[2 * i + 1] = v & 0xFF
    return bytes(out)
