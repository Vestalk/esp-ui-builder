"""ui_draw's alpha blending: the viper loop (board) and the Python loop (fallback) agree.

The unix port used in tests has no native emitter, so the viper source is run
here as plain Python (``ptr8`` = the buffer itself) against the fallback.
"""

from __future__ import annotations

import ast
import math
import random
from array import array
from collections.abc import Callable
from typing import Any

from espui.generators.micropython.drivers import RUNTIME_DIR

SOURCE = (RUNTIME_DIR / "ui_draw.py").read_text("utf-8")


def _namespace() -> dict[str, Any]:
    tree = ast.parse(SOURCE)
    wanted = {
        "ALPHA_LEVELS",
        "_BLEND_VIPER",
        "blend565",
        "_blend_rect_py",
        "ROT_ONE",
        "_ROTATE_VIPER",
        "_rotate_copy_py",
        "rotation_terms",
    }
    nodes = [
        n
        for n in tree.body
        if (isinstance(n, ast.FunctionDef) and n.name in wanted)
        or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in wanted for t in n.targets))
    ]
    ns: dict[str, Any] = {"floor": math.floor}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "ui_draw", "exec"), ns)
    return ns


def _viper_as_python(ns: dict[str, Any]) -> Callable[..., None]:
    code = ns["_BLEND_VIPER"].replace("@micropython.viper\n", "")
    scope: dict[str, Any] = {"ptr8": lambda buf: buf}
    exec(code, scope)
    return scope["blend_rect"]  # type: ignore[no-any-return]


def test_viper_and_python_blending_agree() -> None:
    ns = _namespace()
    assert ns["ALPHA_LEVELS"] == 32  # the viper loop has 32 / 16 written in
    viper = _viper_as_python(ns)
    python = ns["_blend_rect_py"]
    rng = random.Random(7)
    sw, sh = 29, 17
    for a in (1, 2, 11, 16, 31):
        src = bytearray(rng.getrandbits(8) for _ in range(2 * sw * sh))
        dst = bytearray(rng.getrandbits(8) for _ in range(2 * sw * sh))
        dst[::5] = src[::5]  # equal bytes are skipped by both
        box = (rng.randint(0, 4), rng.randint(0, 4), rng.randint(15, sw), rng.randint(8, sh))
        one, two = bytearray(dst), bytearray(dst)
        viper(one, src, sw, *box, a)
        python(two, src, sw, *box, a)
        assert one == two, a
        assert one != dst  # something was blended


def test_board_uses_viper_and_falls_back_quietly() -> None:
    assert "@micropython.viper" in ns_source()
    assert "except Exception:  # no native emitter" in SOURCE
    assert "blend_rect = _blend_rect_py" in SOURCE


def ns_source() -> str:
    return str(_namespace()["_BLEND_VIPER"])


def test_viper_and_python_turned_copy_agree() -> None:
    ns = _namespace()
    code = ns["_ROTATE_VIPER"].replace("@micropython.viper\n", "")
    scope: dict[str, Any] = {"ptr8": lambda b: b, "ptr32": lambda b: b}
    exec(code, scope)
    viper, python = scope["rotate_copy"], ns["_rotate_copy_py"]
    rng = random.Random(3)
    sw, sh, dw, dh = 23, 17, 64, 40
    src = bytearray(rng.getrandbits(8) for _ in range(2 * sw * sh))
    for angle in (12.0, 90.0, 147.5, 271.0):
        rad = math.radians(angle)
        r = (math.cos(rad), math.sin(rad), 30.5, 18.0)
        ku, kv, c, s = ns["rotation_terms"](r, 20, 10)
        q = array("i", (dw, 0, 0, dw, dh, sw, sh, ku, kv, c, s))
        one, two = bytearray(2 * dw * dh), bytearray(2 * dw * dh)
        viper(one, src, q)
        python(two, src, q)
        assert one == two, angle
        assert any(one)  # the picture landed in the strip


def test_preview_and_board_turn_pictures_alike() -> None:
    from espui.preview.raster import rotation_terms

    ns = _namespace()
    for angle, pivot, pos in ((30.0, (60.0, 40.0), (10, 5)), (200.0, (-7.5, 300.0), (-40, 120))):
        rad = math.radians(angle)
        r = (math.cos(rad), math.sin(rad), *pivot)
        assert rotation_terms(r, *pos) == ns["rotation_terms"](r, *pos)


def test_rgb666_conversion_viper_and_python_agree() -> None:
    source = (RUNTIME_DIR / "ui_tft.py").read_text("utf-8")
    tree = ast.parse(source)
    wanted = {"_TO666_VIPER", "_to666_py"}
    nodes = [
        n
        for n in tree.body
        if (isinstance(n, ast.FunctionDef) and n.name in wanted)
        or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in wanted for t in n.targets))
    ]
    ns: dict[str, Any] = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "ui_tft", "exec"), ns)
    scope: dict[str, Any] = {"ptr8": lambda b: b}
    exec(ns["_TO666_VIPER"].replace("@micropython.viper\n", ""), scope)
    src = bytes(random.Random(5).getrandbits(8) for _ in range(2 * 997))
    one, two = bytearray(3 * 997), bytearray(3 * 997)
    scope["to666"](src, one, 997)
    ns["_to666_py"](src, two, 997)
    assert one == two
    assert one[:3] == bytes((src[0] & 0xF8, ((src[0] & 7) << 5) | ((src[1] & 0xE0) >> 3),
                             (src[1] & 0x1F) << 3))  # fmt: skip
