"""Picture library, conversion for the board and generated image files (stage 08)."""

from __future__ import annotations

import base64
import json
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw

from espui.assets import images as img
from espui.core import serializer
from espui.core.colors import to_wire
from espui.core.models import Project
from espui.generators.micropython.generator import generate, vscode_settings

ROOT = Path(__file__).resolve().parents[2]


def png(path: Path, size: tuple[int, int] = (40, 20), color: Any = (255, 0, 0, 255)) -> Path:
    Image.new("RGBA", size, color).save(path)
    return path


def gif(path: Path, frames: int, duration: int = 80, size: tuple[int, int] = (16, 16)) -> Path:
    images = []
    for i in range(frames):
        im = Image.new("RGB", size, (0, 0, 0))
        ImageDraw.Draw(im).rectangle((0, 0, i % size[0], size[1] - 1), fill=(255, 255, 255))
        images.append(im)
    images[0].save(path, save_all=True, append_images=images[1:], duration=duration, loop=0)
    return path


# ------------------------------------------------------------------ library import
def test_import_static_picture(tmp_path: Path) -> None:
    key, asset = img.import_image(png(tmp_path / "Weather Icon.PNG"), taken={"weather_icon"})
    assert key == "weather_icon_2"
    assert asset.path == "/img/weather_icon_2.bin"
    assert (asset.name, asset.mime, asset.width, asset.height) == (
        "Weather Icon.PNG",
        "image/png",
        40,
        20,
    )
    assert not asset.is_animation
    assert (
        base64.b64decode(asset.data) == (tmp_path / "Weather Icon.PNG").read_bytes()
    )  # original kept


def test_import_jpeg(tmp_path: Path) -> None:
    Image.new("RGB", (8, 4), (0, 128, 255)).save(tmp_path / "logo.jpg")
    key, asset = img.import_image(tmp_path / "logo.jpg")
    assert (key, asset.mime, asset.path) == ("logo", "image/jpeg", "/img/logo.bin")


def test_gif_with_12_frames(tmp_path: Path) -> None:
    key, asset = img.import_image(gif(tmp_path / "fire.gif", 12, duration=80))
    assert key == "fire"
    assert asset.path == "/img/fire/"
    assert asset.frames is not None
    assert len(asset.frames) == 12
    assert asset.delay_ms == 80
    assert len(img.decode(asset)) == 12


def test_long_gif_is_thinned_to_48_frames(tmp_path: Path) -> None:
    _, asset = img.import_image(gif(tmp_path / "long.gif", 100, duration=40))
    assert asset.frames is not None
    assert len(asset.frames) == 48
    assert asset.delay_ms == round(100 * 40 / 48)  # total duration is kept
    assert img.thin(list(range(100)), 48)[0] == 0  # type: ignore[arg-type]
    assert img.thin(list(range(100)), 48)[-1] == 99  # type: ignore[arg-type]
    assert img.thin([1, 2], 1) == [1]  # type: ignore[list-item]


def test_video_of_2_seconds(tmp_path: Path) -> None:
    av = pytest.importorskip("av")
    path = tmp_path / "clip.mp4"
    with av.open(str(path), "w") as out:
        stream = out.add_stream("mpeg4", rate=24)
        stream.width, stream.height, stream.pix_fmt = 32, 32, "yuv420p"
        stream.time_base = Fraction(1, 24)
        for i in range(48):  # 2 s at 24 fps
            frame = av.VideoFrame.from_image(Image.new("RGB", (32, 32), (i * 5, 0, 0)))
            frame.pts = i
            for packet in stream.encode(frame):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)
    key, asset = img.import_image(path)
    assert asset.path == f"/img/{key}/"
    assert asset.mime == "video/mp4"
    assert asset.frames is not None
    assert len(asset.frames) == 24  # 2 s at <= 12 fps
    assert asset.delay_ms == 83


def test_import_errors(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("hello")
    with pytest.raises(img.ImageImportError, match="не схожий на картинку"):
        img.import_image(tmp_path / "notes.txt")
    (tmp_path / "bad.mp4").write_bytes(b"nope")
    pytest.importorskip("av")
    with pytest.raises(img.ImageImportError, match="Не вдалося відкрити відео"):
        img.import_image(tmp_path / "bad.mp4")


def test_slug_and_unique() -> None:
    assert img.slug("Сонце 01.PNG") == "01"
    assert img.slug("ГІФ.gif") == "image"
    assert img.slug("my-icon_2.png") == "my-icon_2"
    assert img.unique("sun", {"sun", "sun_2"}) == "sun_3"


# ------------------------------------------------------------------ conversion
def two_colour() -> Image.Image:
    """40x20: left half red, right half blue."""
    im = Image.new("RGBA", (40, 20), (255, 0, 0, 255))
    ImageDraw.Draw(im).rectangle((20, 0, 39, 19), fill=(0, 0, 255, 255))
    return im


@pytest.mark.parametrize(
    ("fit", "expected"),
    [
        # 40x20 into 20x20: contain = letterbox (background above/below), cover = centre crop.
        ("contain", {(0, 0): (16, 32, 48), (2, 10): (255, 0, 0), (17, 10): (0, 0, 255)}),
        ("cover", {(0, 0): (255, 0, 0), (19, 19): (0, 0, 255), (0, 10): (255, 0, 0)}),
        ("fill", {(0, 0): (255, 0, 0), (19, 0): (0, 0, 255)}),
    ],
)
def test_fit_modes(fit: img.Fit, expected: dict[tuple[int, int], tuple[int, int, int]]) -> None:
    out = img.render(two_colour(), 20, 20, fit, "#102030")
    assert out.size == (20, 20)
    for xy, rgb in expected.items():
        assert out.getpixel(xy) == rgb, (fit, xy)


def test_transparency_shows_background() -> None:
    out = img.render(Image.new("RGBA", (4, 4), (0, 0, 0, 0)), 4, 4, "fill", "#ff8000")
    assert out.getpixel((1, 1)) == (255, 128, 0)


def test_rgb565_byte_order() -> None:
    im = Image.new("RGB", (2, 1))
    im.putpixel((0, 0), (255, 0, 0))
    im.putpixel((1, 0), (0, 0, 255))
    data = img.to_rgb565(im)
    assert data == b"\xf8\x00\x00\x1f"  # big-endian on the bus, as ui_st7789 sends it
    # framebuf reads the wire-order colour little-endian: the same value the generator uses.
    assert int.from_bytes(data[:2], "little") == to_wire("#ff0000")


# ------------------------------------------------------------------ generation
def images_project(widgets: list[dict[str, Any]], tmp_path: Path, **extra: Any) -> Project:
    library = {}
    for name in ("sun", "cloud"):
        key, asset = img.import_image(png(tmp_path / f"{name}.png", (64, 64)))
        library[key] = asset.model_dump(mode="json")
    key, asset = img.import_image(gif(tmp_path / "fire.gif", 4, 120))
    library[key] = asset.model_dump(mode="json")
    return serializer.from_dict(
        {
            "images": library,
            "pages": [
                {
                    "name": "main",
                    "parameters": [{"name": "icon", "type": "str", "default": "/img/sun.bin"}],
                    "widgets": widgets,
                }
            ],
            **extra,
        }
    )


def test_static_and_animated_files(tmp_path: Path) -> None:
    project = images_project(
        [
            {"id": "a", "type": "image", "w": 32, "h": 32, "image": {"file": "sun"}},
            {"id": "b", "type": "image", "w": 16, "h": 16, "image": {"file": "sun"}},
            {
                "id": "c",
                "type": "image",
                "w": 20,
                "h": 10,
                "image": {"file": "fire", "play": "once"},
            },
            {"id": "d", "type": "image", "w": 20, "h": 10},
        ],
        tmp_path,
    )
    result = generate(project)
    pictures = sorted(n for n in result.files if n.startswith("img/"))
    assert pictures == [
        "img/fire/000.bin",
        "img/fire/001.bin",
        "img/fire/002.bin",
        "img/fire/003.bin",
        "img/fire/anim.json",
        "img/sun.bin",
        "img/sun_16x16.bin",
    ]
    assert len(result.files["img/sun.bin"]) == 32 * 32 * 2
    assert len(result.files["img/sun_16x16.bin"]) == 16 * 16 * 2
    assert json.loads(result.files["img/fire/anim.json"]) == {
        "frames": 4,
        "delay_ms": 120,
        "width": 20,
        "height": 10,
    }
    text = result.files["ui_main.py"].decode()
    assert '_d.image(fb, 0 - ox, 0 - oy, 32, 32, "/img/sun.bin")' in text
    assert '_d.image(fb, 0 - ox, 0 - oy, 16, 16, "/img/sun_16x16.bin")' in text
    assert '_d.frame_path("/img/fire/", self.frame("c"))' in text
    assert 'return ("/img/fire/", 4, 120)' in text
    assert 'ANIMS = (("c", False),)' in text
    assert "def play_c(self):" in text
    assert "_d.missing(fb, 0 - ox, 0 - oy, 20, 10)" in text
    assert result.notes[-1].startswith(
        "Картинки: img/sun.bin 2,0 КБ, img/sun_16x16.bin 0,5 КБ, img/fire/ 1,6 КБ"
    )
    assert ".vscode/settings.json" in result.files
    assert "ui.tick()" in result.files["main.py"].decode()


def test_bound_image(tmp_path: Path) -> None:
    project = images_project(
        [{"id": "w", "type": "image", "w": 24, "h": 24, "bind": "icon", "image": {"fit": "cover"}}],
        tmp_path,
    )
    result = generate(project)
    assert {n for n in result.files if n.startswith("img/") and n.endswith(".bin")} == {
        "img/sun.bin",
        "img/cloud.bin",
        *(f"img/fire/{i:03d}.bin" for i in range(4)),
    }
    text = result.files["ui_main.py"].decode()
    assert 'path = p["icon"]' in text
    assert 'return _d.anim_info(self.p["icon"])' in text
    assert 'ANIMS = (("w", False),)' in text  # plays once by default
    assert result.warnings == ()
    looped = project.model_copy(deep=True)
    image = looped.pages[0].widgets[0].image
    assert image is not None
    image.play = "loop"  # "Програвати циклічно"
    assert 'ANIMS = (("w", True),)' in generate(looped).files["ui_main.py"].decode()


def test_bound_images_of_different_sizes_warn(tmp_path: Path) -> None:
    project = images_project(
        [
            {"id": "a", "type": "image", "w": 24, "h": 24, "bind": "icon"},
            {"id": "b", "type": "image", "w": 48, "h": 48, "bind": "icon"},
        ],
        tmp_path,
    )
    (warning,) = generate(project).warnings
    assert warning.startswith("Елементи a, b беруть картинку з параметра, але мають різний розмір")


def test_large_animation_warns(tmp_path: Path) -> None:
    project = images_project(
        [{"id": "c", "type": "image", "w": 320, "h": 240, "image": {"file": "fire"}}],
        tmp_path,
        display={"rotation": 1},
    )
    (warning,) = generate(project).warnings
    assert warning.startswith("Анімація img/fire/: 4 кадрів 320×240 ≈ 600,0 КБ флешу")


def test_rotated_image_is_turned_on_the_board(tmp_path: Path) -> None:
    project = images_project(
        [
            {
                "id": "a",
                "type": "image",
                "w": 32,
                "h": 32,
                "rotation_deg": 30,
                "image": {"file": "sun"},
            }
        ],
        tmp_path,
    )
    result = generate(project)
    assert result.warnings == ()
    code = result.files["ui_main.py"].decode()
    assert "r = _d.rot(30.0, 16 - ox, 16 - oy)" in code  # around the centre of the box
    assert '"/img/sun.bin",\n            r,' in code or '"/img/sun.bin", r)' in code
    assert "return _d.rbox(0, 0, 32, 32, 30.0, 16, 16)" in code  # redraw area: turned box


def test_write_removes_stale_pictures_and_merges_settings(tmp_path: Path) -> None:
    out = tmp_path / "out"
    (out / "img" / "old").mkdir(parents=True)
    (out / "img" / "old" / "000.bin").write_bytes(b"x")
    (out / "img" / "gone.bin").write_bytes(b"x")
    (out / "img" / "notes.txt").write_text("mine")
    (out / ".vscode").mkdir()
    (out / ".vscode" / "settings.json").write_text(
        '{"editor.tabSize": 2, "micropico.syncFileTypes": ["mpy"]}'
    )
    project = images_project(
        [{"id": "a", "type": "image", "w": 8, "h": 8, "image": {"file": "sun"}}], tmp_path
    )
    generate(project).write(out)
    assert sorted(p.relative_to(out).as_posix() for p in (out / "img").rglob("*")) == [
        "img/notes.txt",  # not ours: kept
        "img/sun.bin",
    ]
    settings = json.loads((out / ".vscode" / "settings.json").read_text())
    assert settings == {
        "editor.tabSize": 2,
        "micropico.syncFileTypes": ["mpy", "py", "json", "bin"],
    }


def test_vscode_settings_from_scratch_or_broken() -> None:
    expected = {
        "micropico.syncFileTypes": [
            "py",
            "txt",
            "log",
            "json",
            "xml",
            "html",
            "js",
            "css",
            "mpy",
            "bin",
        ]
    }
    assert json.loads(vscode_settings()) == expected
    assert json.loads(vscode_settings("{broken")) == expected
    assert json.loads(vscode_settings("[1, 2]")) == expected


def test_picture_bytes_match_conversion(tmp_path: Path) -> None:
    project = images_project(
        [{"id": "a", "type": "image", "w": 10, "h": 6, "image": {"file": "sun", "fit": "fill"}}],
        tmp_path,
    )
    data = generate(project).files["img/sun.bin"]
    expected = img.to_rgb565(
        img.render(Image.new("RGBA", (64, 64), (255, 0, 0, 255)), 10, 6, "fill", "#000000")
    )
    assert data == expected


def test_decode_error() -> None:
    from espui.core.models import ImageAsset

    bad = ImageAsset(
        name="x.png", path="/img/x.bin", data=base64.b64encode(b"nope").decode(), width=1, height=1
    )
    with pytest.raises(img.ImageImportError, match="не вдалося прочитати"):
        img.decode(bad)
