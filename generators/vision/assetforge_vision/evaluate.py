"""Field-by-field comparison of a model's description against the ground truth, with colour *families* (a coarse but honest match)."""

from __future__ import annotations

from typing import Any

from .schema import HouseDescription

FAMILIES = [
    {"white", "cream", "beige", "tan", "yellow"},
    {"orange", "brown"},
    {"red", "brick_red"},
    {"green", "sage_green", "dark_green"},
    {"blue", "gray_blue"},
    {"gray", "dark_gray", "black"},
]
EXACT = ("floors", "roof_type", "wall_material", "door_position", "porch", "volumes", "garage", "chimney", "bay_window")
COLOR = ("roof_color", "wall_color", "trim_color", "door_color")


def _family(c: str) -> set[str]:
    for f in FAMILIES:
        if c in f:
            return f
    return {c}


def _alts(v: Any) -> list:
    return v if isinstance(v, list) and not (v and isinstance(v[0], int)) else [v]


def compare(pred: HouseDescription, truth: dict[str, Any], present: set[str] | None = None) -> dict[str, dict[str, Any]]:
    """``present`` = keys the model really wrote; a missing key never counts as a hit (defaults must not inflate the score)."""
    p = pred.to_dict()
    out: dict[str, dict[str, Any]] = {}
    for k in EXACT:
        if k in truth:
            ok = p[k] in _alts(truth[k])
            out[k] = dict(ok=ok, pred=p[k], truth=truth[k])
    for k in COLOR:
        if k in truth:
            ok = any(_family(p[k]) == _family(t) for t in _alts(truth[k]))
            out[k] = dict(ok=ok, pred=p[k], truth=truth[k])
    lm = truth.get("lower_wall_material", "none")
    out["lower_wall"] = dict(ok=(p["lower_wall_material"] == lm) and (lm == "none" or _family(p["lower_wall_color"]) == _family(truth.get("lower_wall_color", "none"))),
                             pred=[p["lower_wall_material"], p["lower_wall_color"]], truth=[lm, truth.get("lower_wall_color", "none")])
    tw, pw = truth["windows_front_per_floor"], p["windows_front_per_floor"]
    out["windows"] = dict(ok=len(pw) == len(tw) and all(abs(a - b) <= 1 for a, b in zip(pw, tw, strict=False)), pred=pw, truth=tw)
    if truth.get("garage"):
        out["garage_side"] = dict(ok=p["garage_side"] == truth.get("garage_side"), pred=p["garage_side"], truth=truth.get("garage_side"))
    if present is not None:
        alias = {"lower_wall": ("lower_wall_material", "lower_wall_color"), "windows": ("windows_front_per_floor",), "garage_side": ("garage_side",)}
        for k, r in out.items():
            if any(x not in present for x in alias.get(k, (k,))):
                r["ok"], r["missing"] = False, True
    return out


def score(result: dict[str, dict[str, Any]]) -> tuple[int, int]:
    return sum(1 for r in result.values() if r["ok"]), len(result)
