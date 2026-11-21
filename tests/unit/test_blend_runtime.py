"""ui_draw's alpha blending: the viper loop (board) and the Python loop (fallback) agree.

The unix port used in tests has no native emitter, so the viper source is run
here as plain Python (``ptr8`` = the buffer itself) against the fallback.
"""

from __future__ import annotations

import ast
import random
from collections.abc import Callable
from typing import Any

from espui.generators.micropython.drivers import RUNTIME_DIR

SOURCE = (RUNTIME_DIR / "ui_draw.py").read_text("utf-8")


def _namespace() -> dict[str, Any]:
    tree = ast.parse(SOURCE)
    wanted = {"ALPHA_LEVELS", "_BLEND_VIPER", "blend565", "_blend_rect_py"}
    nodes = [
        n
        for n in tree.body
        if (isinstance(n, ast.FunctionDef) and n.name in wanted)
        or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in wanted for t in n.targets))
    ]
    ns: dict[str, Any] = {}
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
