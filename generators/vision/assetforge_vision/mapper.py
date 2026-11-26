"""Turn a validated :class:`HouseDescription` into a :class:`HouseSpec` of the procedural kit.

The model only supplies coarse facts (storeys, roof type, materials, colours, porch, garage). Proportions and layout come from a BASE house of
the kit chosen by those facts, then the base is repainted and edited (porch, garage wing, chimney, lower wall). Nothing is invented by the model.
"""

from __future__ import annotations

import copy

from assetforge_procedural.house import ARCHETYPES, Feature, HouseSpec

from .schema import HouseDescription

HEX = {
    "white": "#F4F1EA", "cream": "#EEE4CE", "beige": "#E2D2B0", "tan": "#CDB48C", "yellow": "#D9A85F", "orange": "#C27A32", "brown": "#6B4A32",
    "red": "#B3392F", "brick_red": "#A5503E", "green": "#4C8A3E", "sage_green": "#9DAD8E", "dark_green": "#2D5B4A", "blue": "#5E7798",
    "gray_blue": "#6F86A0", "gray": "#8A8D92", "dark_gray": "#3A3D43", "black": "#1F2125",
}
WALL_KIND = {"siding": "clapboard", "brick": "brick", "stucco": "stucco", "stone": "stucco", "wood": "clapboard"}


def has_split_wall(d: HouseDescription) -> bool:
    """A lower wall counts only when it is brick under a different upper wall. Measured: the 7B model invented a lower wall in 4 of 6 houses
    (same material as the upper one, or wood), so every other combination is ignored."""
    return d.lower_wall_material == "brick" and d.lower_wall_color != "none" and d.wall_material != "brick"


def pick_base(d: HouseDescription) -> str:
    """Name of the kit house whose volumes are closest to the description."""
    if d.garage:
        return "ref06"
    if has_split_wall(d) and d.floors >= 2:
        return "ref03"
    if d.roof_type == "shed":
        return "ref04"
    if d.volumes == "with_side_wing" and d.floors >= 2:
        return "ref06"
    if d.wall_material == "brick" and d.floors >= 2:
        return "ref05"
    if d.floors >= 2:
        return "ref02" if d.roof_type == "hip" or d.porch == "portico" else "ref06"
    if d.roof_type == "flat":
        return "bungalow"
    return "ref01"


def description_to_spec(d: HouseDescription, seed: int = 1) -> HouseSpec:
    base = pick_base(d)
    spec = copy.deepcopy(ARCHETYPES[base](seed))
    spec.archetype = f"vision:{base}"
    spec.name = f"Casa (visão) base {base}"
    pal = spec.palette
    pal.update(wall=HEX[d.wall_color], trim=HEX[d.trim_color], roof=HEX[d.roof_color], door=HEX[d.door_color], accent=HEX[d.door_color])
    spec.wall_kind = WALL_KIND[d.wall_material]
    spec.roof_kind = "metal" if d.roof_type == "shed" or d.roof_color in ("green", "dark_green") else "shingles"
    main = spec.wings[0]
    if main.floors != d.floors and d.floors in (1, 2, 3):
        main.floors = d.floors
    # lower wall (e.g. brick under siding)
    if has_split_wall(d):
        main.wall_lower, main.lower_h = "wall2", main.fh
        pal["wall2"] = HEX[d.lower_wall_color]
        spec.wall2_kind = WALL_KIND[d.lower_wall_material]
    elif main.wall_lower and base != "ref03":
        main.wall_lower, main.lower_h = "", 0.0
    # garage wing
    if not d.garage:
        gone = {w.name for w in spec.wings if w.garage}
        spec.wings = [w for w in spec.wings if not w.garage]
        spec.features = [f for f in spec.features if f.wing not in gone]
    # porch
    porch_feats = [f for f in spec.features if f.type in ("porch", "portico")]
    if d.porch == "none":
        spec.features = [f for f in spec.features if f.type not in ("porch", "portico")]
    else:
        for f in porch_feats:
            if d.porch == "portico":
                f.style, f.mode, f.rail = "gable", "craftsman", False
            elif d.porch == "covered_porch":
                f.style, f.mode, f.rail = "shed", "trim", True
            else:
                f.style, f.mode, f.rail, f.pitch = "shed", "trim", False, 7
    # chimney
    if d.chimney and not any(f.type == "chimney" for f in spec.features):
        spec.features.append(Feature("chimney", main.name, "left", x=0.0, w=1.0, depth=0.85, height=0.8, mode="interior"))
    if not d.chimney:
        spec.features = [f for f in spec.features if f.type != "chimney"]
    spec.validate()
    return spec
