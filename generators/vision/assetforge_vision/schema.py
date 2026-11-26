"""The structured house description a vision model must produce, with strict validation.

It is deliberately COARSE: only things a model can read reliably from one picture (storeys, roof type, materials, colours, presence of a
porch / garage). Proportions and fine layout come from a base house of the kit, not from the model.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, fields
from typing import Any

COLORS = ("white", "cream", "beige", "tan", "yellow", "orange", "brown", "red", "brick_red", "green", "sage_green", "dark_green",
          "blue", "gray_blue", "gray", "dark_gray", "black")
ROOF_TYPES = ("gable", "hip", "shed", "flat")
WALL_MATERIALS = ("siding", "brick", "stucco", "stone", "wood")
PORCHES = ("none", "covered_porch", "portico", "small_roof")
VOLUMES = ("single", "l_shape", "with_side_wing", "stepped")
POSITIONS = ("left", "center", "right")


@dataclass
class HouseDescription:
    floors: int = 1
    roof_type: str = "gable"
    roof_color: str = "dark_gray"
    wall_material: str = "siding"
    wall_color: str = "beige"
    lower_wall_material: str = "none"  # material of the lower storey when different ("brick" under siding), else "none"
    lower_wall_color: str = "none"
    trim_color: str = "cream"
    door_color: str = "brown"
    door_position: str = "center"
    windows_front_per_floor: list[int] = field(default_factory=lambda: [2])
    porch: str = "none"
    garage: bool = False
    garage_side: str = "none"  # left | right | none
    chimney: bool = False
    volumes: str = "single"
    bay_window: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_ENUMS = {"roof_type": ROOF_TYPES, "wall_material": WALL_MATERIALS, "porch": PORCHES, "volumes": VOLUMES, "door_position": POSITIONS}
_COLOR_FIELDS = ("roof_color", "wall_color", "trim_color", "door_color")


class DescriptionError(ValueError):
    pass


def extract_json(text: str) -> dict[str, Any]:
    """Take the first balanced JSON object from a model answer (models often wrap it in prose or ``` fences)."""
    start = text.find("{")
    if start < 0:
        raise DescriptionError("no JSON object in the model answer")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            esc = (c == "\\") and not esc
            if c == '"' and not esc:
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError as exc:
                    raise DescriptionError(f"invalid JSON: {exc}") from exc
    raise DescriptionError("unterminated JSON object")


def _norm(s: Any) -> str:
    return re.sub(r"[\s\-]+", "_", str(s).strip().lower())


def parse_description(data: dict[str, Any] | str) -> HouseDescription:
    """Validate and normalise a model answer. Unknown / invalid values raise :class:`DescriptionError` (no silent guessing)."""
    if isinstance(data, str):
        data = extract_json(data)
    allowed = {f.name for f in fields(HouseDescription)}
    d = {k: v for k, v in data.items() if k in allowed}
    missing = [k for k in ("floors", "roof_type", "wall_material", "wall_color", "roof_color") if k not in d]
    if missing:
        raise DescriptionError(f"missing field(s): {missing}")
    try:
        d["floors"] = int(d["floors"])
    except (TypeError, ValueError) as exc:
        raise DescriptionError("floors must be an integer") from exc
    if not 1 <= d["floors"] <= 3:
        raise DescriptionError("floors must be 1..3")
    for k, allowed_values in _ENUMS.items():
        if k in d:
            d[k] = _norm(d[k])
            if d[k] not in allowed_values:
                raise DescriptionError(f"{k}={d[k]!r} not in {allowed_values}")
    for k in _COLOR_FIELDS + ("lower_wall_color",):
        if k in d:
            d[k] = _norm(d[k])
            if d[k] not in COLORS and not (k == "lower_wall_color" and d[k] == "none"):
                raise DescriptionError(f"{k}={d[k]!r} not in the colour list")
    if "lower_wall_material" in d:
        d["lower_wall_material"] = _norm(d["lower_wall_material"])
        if d["lower_wall_material"] not in WALL_MATERIALS + ("none",):
            raise DescriptionError("invalid lower_wall_material")
    if "windows_front_per_floor" in d:
        w = d["windows_front_per_floor"]
        if not isinstance(w, list) or not all(isinstance(n, int) and 0 <= n <= 8 for n in w):
            raise DescriptionError("windows_front_per_floor must be a list of small integers")
        d["windows_front_per_floor"] = w[:3]
    for k in ("garage", "chimney", "bay_window"):
        if k in d and not isinstance(d[k], bool):
            raise DescriptionError(f"{k} must be true/false")
    if "garage_side" in d:
        d["garage_side"] = _norm(d["garage_side"])
        if d["garage_side"] not in ("left", "right", "none"):
            raise DescriptionError("garage_side must be left/right/none")
    return HouseDescription(**d)
