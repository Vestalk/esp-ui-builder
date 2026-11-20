"""Display profiles: one YAML file per supported panel, loaded via importlib.resources.

Adding a display = dropping another ``*.yaml`` next to ``gmt020_02.yaml``.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import cache
from importlib import resources
from types import MappingProxyType

import yaml
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_MODEL = "GMT020-02-8B"


class SpiRange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    default: int = Field(gt=0)
    max: int = Field(gt=0)


class DisplayProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str
    title: str
    controller: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    color_format: str
    interface: str
    invert: bool
    spi_hz: SpiRange
    default_pins: dict[str, int | None]

    def size(self, rotation: int) -> tuple[int, int]:
        """Logical (width, height) for ``rotation`` 0-3."""
        return (self.height, self.width) if rotation % 2 else (self.width, self.height)


class UnknownDisplayError(KeyError):
    def __init__(self, model: str) -> None:
        super().__init__(model)
        self.model = model

    def __str__(self) -> str:
        known = ", ".join(load_profiles())
        return f"невідомий дисплей «{self.model}»; підтримуються: {known}"


@cache
def load_profiles() -> Mapping[str, DisplayProfile]:
    profiles: dict[str, DisplayProfile] = {}
    for entry in sorted(resources.files(__package__).iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".yaml"):
            profile = DisplayProfile.model_validate(yaml.safe_load(entry.read_text("utf-8")))
            profiles[profile.model] = profile
    return MappingProxyType(profiles)


def get_profile(model: str) -> DisplayProfile:
    try:
        return load_profiles()[model]
    except KeyError:
        raise UnknownDisplayError(model) from None
