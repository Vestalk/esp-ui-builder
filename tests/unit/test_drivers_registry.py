from __future__ import annotations

import ast
import hashlib

import pytest

from espui.core.hardware import Chip
from espui.generators.micropython.drivers import (
    ADAPTER_FILE,
    DEFAULT_DRIVER,
    DRIVERS,
    UnknownDriverError,
    drivers_for,
    get_driver,
    runtime_file,
)


def test_default_driver_is_registered() -> None:
    assert DEFAULT_DRIVER in DRIVERS


@pytest.mark.parametrize("key", sorted(DRIVERS))
def test_runtime_files_exist(key: str) -> None:
    info = DRIVERS[key]
    assert info.key == key
    assert info.files[0] == ADAPTER_FILE
    for name in info.files:
        assert runtime_file(name).is_file()
    if info.license_file:
        assert runtime_file(info.license_file).read_text(encoding="utf-8").startswith("MIT")


@pytest.mark.parametrize("key", [k for k, v in DRIVERS.items() if v.sha256])
def test_vendored_driver_is_unchanged(key: str) -> None:
    info = DRIVERS[key]
    digest = hashlib.sha256(runtime_file(info.module_file).read_bytes()).hexdigest()
    assert digest == info.sha256, "vendored file must ship exactly as pinned"


def test_every_driver_has_an_adapter() -> None:
    tree = ast.parse(runtime_file(ADAPTER_FILE).read_text(encoding="utf-8"))
    adapters = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "ADAPTERS" for t in node.targets)
    )
    assert isinstance(adapters, ast.Dict)
    keys = {k.value for k in adapters.keys if isinstance(k, ast.Constant)}
    assert keys == set(DRIVERS)


def test_get_driver_unknown() -> None:
    with pytest.raises(UnknownDriverError, match="nope"):
        get_driver("nope")


@pytest.mark.parametrize("chip", list(Chip))
def test_all_chips_have_drivers(chip: Chip) -> None:
    assert {d.key for d in drivers_for(chip)} == set(DRIVERS)


def test_runtime_file_missing() -> None:
    with pytest.raises(FileNotFoundError):
        runtime_file("missing.py")
