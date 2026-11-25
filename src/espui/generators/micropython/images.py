"""Pictures for the board: which files a page needs and their RGB565 content.

Every picture is converted for the box of the widget that shows it and lands
next to the code (``img/<name>.bin``, or ``img/<name>/000.bin``... plus
``anim.json`` for an animation), so nothing has to be converted or copied by
hand. The board path of a library picture (``ImageAsset.path``) is used for
its first size; another size of the same picture shown by a static widget gets
its own file (``img/<name>_<w>x<h>.bin``). Widgets that take the path from a
``str`` parameter can only use the library path, so they must agree on one
size (a warning otherwise).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import cast

from PIL import Image

from espui.assets.images import Fit, decode, render, to_rgb565
from espui.core.models import ImageAsset, Page, Project, Widget
from espui.i18n import tr

LARGE_ANIMATION_BYTES = 512 * 1024


@dataclass(frozen=True, slots=True)
class Variant:
    key: str
    width: int
    height: int
    fit: str
    background: str
    """Page background: transparent pixels are mixed with it (the board has no alpha)."""

    @property
    def size(self) -> tuple[int, int]:
        return self.width, self.height


@dataclass(slots=True)
class ImagePlan:
    files: dict[str, bytes] = field(default_factory=dict)
    """Relative path (``img/sun.bin``) -> content."""
    paths: dict[tuple[str, str], str] = field(default_factory=dict)
    """(page, static image widget id) -> board path (file, or folder ending with '/')."""
    animations: dict[str, tuple[str, int, int]] = field(default_factory=dict)
    """Board folder -> (folder, frames, delay_ms)."""
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> list[str]:
        if not self.files:
            return []
        folders: dict[str, int] = {}
        for path, data in self.files.items():
            top = path.split("/")[1]
            name = f"img/{top}/" if path.count("/") > 1 else path
            folders[name] = folders.get(name, 0) + len(data)
        total = sum(folders.values())
        items = ", ".join(f"{name} {_kb(size)}" for name, size in folders.items())
        return [tr("Картинки: {items} — разом {v1}").format(items=items, v1=_kb(total))]


def _kb(size: int) -> str:
    return tr("{v1:.1f} КБ").format(v1=size / 1024).replace(".", ",")


def _variant_path(asset: ImageAsset, variant: Variant, primary: Variant) -> str:
    if variant == primary:
        return asset.path
    suffix = ""
    if variant.size != primary.size or variant.fit != primary.fit:
        suffix += f"_{variant.width}x{variant.height}"
        if variant.fit != "contain":
            suffix += f"_{variant.fit}"
    if variant.background != primary.background:
        suffix += "_" + variant.background.lstrip("#")
    if asset.is_animation:
        return asset.path.rstrip("/") + suffix + "/"
    return asset.path.removesuffix(".bin") + suffix + ".bin"


def plan(
    project: Project, pages: Iterable[tuple[Page, Iterable[Widget]]], convert: bool = True
) -> ImagePlan:
    """Picture files for the image widgets of all ``pages`` (shared ``img/`` folder).

    ``convert=False`` only sizes the files (zero bytes of the right length): enough
    to estimate the flash use without decoding a single picture.
    """
    result = ImagePlan()
    primary: dict[str, Variant] = {}
    variants: dict[Variant, str] = {}
    bound: list[tuple[Page, Widget]] = []
    static: list[tuple[Page, Widget]] = []
    for page, widgets in pages:
        for w in widgets:
            if w.type != "image":
                continue
            if w.bind:
                bound.append((page, w))
            elif w.image and w.image.file:
                static.append((page, w))

    def want(key: str, page: Page, widget: Widget) -> str:
        asset = project.images[key]
        fit = widget.image.fit if widget.image else "contain"
        variant = Variant(key, widget.w, widget.h, fit, page.background)
        first = primary.setdefault(key, variant)
        path = variants.get(variant)
        if path is None:
            path = _variant_path(asset, variant, first)
            variants[variant] = path
            _convert(result, asset, variant, path, convert)
        return path

    looks = {(w.w, w.h, w.image.fit if w.image else "contain", pg.background) for pg, w in bound}
    if len(looks) > 1:
        ids = ", ".join(w.id for _, w in bound)
        result.warnings.append(
            tr(
                "Елементи {ids} беруть картинку з параметра, але мають різний "
                "розмір, вписування чи фон сторінки: файли бібліотеки конвертуються "
                "під «{id}», у решти буде сірий прямокутник або інший фон."
            ).format(ids=ids, id=bound[0][1].id)
        )
    for page, widget in bound:
        for key in project.images:
            want(key, page, widget)
    for page, widget in static:
        assert widget.image is not None
        assert widget.image.file is not None
        result.paths[(page.name, widget.id)] = want(widget.image.file, page, widget)
    return result


def _convert(
    result: ImagePlan, asset: ImageAsset, v: Variant, path: str, convert: bool = True
) -> None:
    rel = path.lstrip("/")
    size = 2 * v.width * v.height

    def pixels(frame: Image.Image | None) -> bytes:
        if frame is None:
            return bytes(size)
        return to_rgb565(render(frame, v.width, v.height, cast(Fit, v.fit), v.background))

    if convert:
        frames: list[Image.Image | None] = list(decode(asset))
    else:
        frames = [None] * (len(asset.frames or []) if asset.is_animation else 1)
    if not asset.is_animation:
        result.files[rel] = pixels(frames[0])
        return
    total = 0
    for i, frame in enumerate(frames):
        data = pixels(frame)
        result.files[f"{rel}{i:03d}.bin"] = data
        total += len(data)
    delay = asset.delay_ms or 100
    meta = {"frames": len(frames), "delay_ms": delay, "width": v.width, "height": v.height}
    result.files[f"{rel}anim.json"] = (json.dumps(meta) + "\n").encode()
    result.animations[path] = (path, len(frames), delay)
    if total > LARGE_ANIMATION_BYTES:
        result.warnings.append(
            tr(
                "Анімація {rel}: {v1} кадрів {width}×{height} ≈ {v} флешу; зменште "
                "розмір елемента або кількість кадрів."
            ).format(rel=rel, v1=len(frames), width=v.width, height=v.height, v=_kb(total))
        )
