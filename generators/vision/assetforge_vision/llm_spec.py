"""Full building specification written by a cloud multimodal model (Gemini / Grok), plus the critique loop prompts.

The model fills a JSON document constrained by :data:`SPEC_SCHEMA` (JSON Schema, structured output). :func:`to_house_spec` converts it to the
kit's ``HouseSpec`` dict and ``HouseSpec.from_dict`` validates every value. Nothing the model writes is executed: it can only choose values
for the fields of this schema. Lists replace dicts (``skip``, ``side_wall``) because structured-output schemas handle arrays better.
"""

from __future__ import annotations

import json
from typing import Any

PROMPT_VERSION = "spec-v3"
SIDES = ["front", "back", "left", "right"]
FEATURES = ["porch", "portico", "chimney", "dormer", "balcony", "panel", "shrubs", "balcony_stack", "glass_strip", "pilaster", "canopy", "roof_screen"]
HEX = {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"}

_WINDOW = {
    "type": "object",
    "properties": {
        "w": {"type": "number", "minimum": 0.3, "maximum": 6}, "h": {"type": "number", "minimum": 0.3, "maximum": 6},
        "sill": {"type": "number", "minimum": 0, "maximum": 3}, "arch": {"type": "number", "minimum": 0, "maximum": 1},
        "shutters": {"type": "boolean"}, "flower_boxes": {"type": "boolean"}, "casing": {"type": "boolean"}, "lite": {"type": "boolean"},
        "mullions_x": {"type": "integer", "minimum": 1, "maximum": 6}, "mullions_y": {"type": "integer", "minimum": 1, "maximum": 6},
    },
    "required": ["w", "h", "sill"],
}
_RANGE = {"type": "object", "properties": {"side": {"type": "string", "enum": SIDES}, "x0": {"type": "number"}, "x1": {"type": "number"}}, "required": ["side", "x0", "x1"]}
_WING = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "w": {"type": "number", "minimum": 0.8, "maximum": 40}, "d": {"type": "number", "minimum": 0.8, "maximum": 40},
        "floors": {"type": "integer", "minimum": 1, "maximum": 40}, "fh": {"type": "number", "minimum": 1.4, "maximum": 5},
        "ground_fh": {"type": "number", "minimum": 0, "maximum": 8},
        "cx": {"type": "number"}, "cz": {"type": "number"}, "y0": {"type": "number", "minimum": 0},
        "foundation": {"type": "number", "minimum": 0, "maximum": 2}, "pad": {"type": "number", "minimum": 0, "maximum": 1},
        "wall": {"type": "string", "enum": ["wall", "wall2"]}, "wall_lower": {"type": "string", "enum": ["", "wall2"]},
        "lower_h": {"type": "number", "minimum": 0, "maximum": 10},
        "roof": {"type": "string", "enum": ["gable", "hip", "shed", "flat", "none"]}, "ridge": {"type": "string", "enum": ["x", "z"]},
        "pitch": {"type": "number", "minimum": 8, "maximum": 65}, "overhang": {"type": "number", "minimum": 0, "maximum": 2},
        "rake": {"type": "number", "minimum": 0, "maximum": 2}, "shed_high": {"type": "string", "enum": ["-z", "+z", "-x", "+x"]},
        "sides": {"type": "array", "items": {"type": "string", "enum": SIDES}},
        "bay": {"type": "number", "minimum": 0.8, "maximum": 8},
        "window": _WINDOW, "ground_window": _WINDOW,
        "door_side": {"type": "string", "enum": SIDES + ["none"]}, "door_w": {"type": "number", "minimum": 0.6, "maximum": 6},
        "door_h": {"type": "number", "minimum": 1.8, "maximum": 6}, "door_x": {"type": "number"}, "door_arch": {"type": "number", "minimum": 0, "maximum": 1},
        "garage": {"type": "boolean"}, "timber": {"type": "boolean"}, "belt": {"type": "boolean"}, "corner_posts": {"type": "boolean"},
        "gable_window": {"type": "boolean"}, "hide_end": {"type": "string", "enum": ["", "a", "b"]},
        "skip": {"type": "array", "items": _RANGE}, "skip_ground": {"type": "array", "items": _RANGE},
        "no_windows": {"type": "array", "items": {"type": "string", "enum": SIDES}},
        "side_wall": {"type": "array", "items": {"type": "object", "properties": {"side": {"type": "string", "enum": SIDES}, "wall": {"type": "string", "enum": ["wall", "wall2"]}},
                                                  "required": ["side", "wall"]}},
    },
    "required": ["name", "w", "d", "floors", "fh", "roof"],
}
_FEATURE = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": FEATURES}, "wing": {"type": "string"}, "side": {"type": "string", "enum": SIDES},
        "x": {"type": "number"}, "w": {"type": "number", "minimum": 0}, "depth": {"type": "number", "minimum": 0}, "floor": {"type": "integer", "minimum": 0},
        "height": {"type": "number", "minimum": 0}, "y": {"type": "number"}, "pitch": {"type": "number", "minimum": 0, "maximum": 45},
        "style": {"type": "string", "enum": ["shed", "gable", "open"]}, "mode": {"type": "string", "enum": ["", "craftsman", "trim", "exterior", "interior"]},
        "columns": {"type": "boolean"}, "rail": {"type": "boolean"}, "posts": {"type": "boolean"},
    },
    "required": ["type", "wing", "side"],
}
PALETTE_KEYS = ["wall", "wall2", "trim", "base", "roof", "accent", "door", "frame", "shutter", "metal", "glass", "timber", "brick", "deck", "flower"]
SPEC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "category": {"type": "string", "enum": ["house", "apartment", "commercial", "skyscraper", "school", "hospital", "industrial", "warehouse", "government", "police",
                                                  "fire_station", "transport_station", "university"]},
        "wall_kind": {"type": "string", "enum": ["stucco", "clapboard", "plaster", "brick", "stone", "wood"]},
        "wall2_kind": {"type": "string", "enum": ["", "stucco", "clapboard", "plaster", "brick", "planks", "cobble"]},
        "roof_kind": {"type": "string", "enum": ["shingles", "tiles", "metal", "plaster"]},
        "base_kind": {"type": "string", "enum": ["cobble", "plaster", "brick", "concrete"]},
        "ground": {"type": "boolean"}, "wear": {"type": "number", "minimum": 0, "maximum": 1},
        "palette": {"type": "object", "properties": {k: HEX for k in PALETTE_KEYS}, "required": ["wall", "trim", "roof", "door", "frame"]},
        "wings": {"type": "array", "minItems": 1, "maxItems": 8, "items": _WING},
        "features": {"type": "array", "maxItems": 40, "items": _FEATURE},
        "notes": {"type": "string"},
    },
    "required": ["name", "category", "wall_kind", "roof_kind", "palette", "wings", "features"],
}
CRITIQUE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "score": {"type": "number", "minimum": 0, "maximum": 10},
        "issues": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
        "spec": SPEC_SCHEMA,
    },
    "required": ["score", "issues", "spec"],
}

SYSTEM = (
    "You are the architectural modeller of AssetForge's procedural building agent. The goal is fidelity to the same real structure across the supplied views. "
    "You never write code. You only fill the JSON document of the given schema; the kit turns it into geometry."
)

CONVENTIONS = """Conventions of the kit (use them exactly):
- Meters. A building is made of WINGS (rectangular volumes). Each wing: width w along X, depth d along Z, centred at (cx, cz); the FRONT facade faces +Z.
  y0 = base height (only for volumes stacked on others, e.g. a rooftop penthouse); foundation = plinth height; floors and fh = storey count and height;
  ground_fh = a taller ground floor (shops/lobby), 0 = same as fh.
- Facade coordinates for skip/door_x/features: x runs along that facade, 0 = its centre; for front/back the facade length is w, for left/right it is d.
- Windows are laid out automatically in bays of width `bay`; `window` sets size/sill; `ground_window` sets ground-floor (storefront) windows;
  `lite: true` = simple glazing for tall buildings; `mullions_x/y` = panes. `skip` = x-ranges of a facade with no windows (all floors).
- Roofs: gable (ridge along `ridge`), hip, shed (rises toward `shed_high`), flat (with parapet), none. A wing whose gable end is buried in another
  wing uses hide_end ("a" = -x end, "b" = +x end in the roof's own frame).
- Walls use material "wall" (palette.wall + wall_kind) or "wall2" (palette.wall2 + wall2_kind); `wall_lower` + `lower_h` = a different lower band
  (e.g. brick under siding); `side_wall` = another material on one side.
- Features (attached to a wing and side): porch/portico (x,w,depth,height,style,mode craftsman|trim,rail,posts,pitch), chimney (x,w,depth,height,mode
  exterior|interior), dormer (x,w), balcony (x,w,depth,floor), balcony_stack (x,w,depth, from `floor` to storey `height`, 0 = top), glass_strip
  (x,w, curtain wall from `floor` up), pilaster (x,w,depth, vertical strip in palette.accent from `floor` up), canopy (x,w,depth, height above the
  ground floor), roof_screen (x,w along the wing width, y,depth along its depth, height), panel (x,w,depth: cladding in wall2), shrubs (x,w,depth).
- Colours are hex. Match the reference colours; frames/metal are usually dark; keep the Premium Stylized look (clean shapes, readable details).
Composition rules (very important):
- Most towers and blocks are ONE slab: use ONE wing for the whole shaft (all floors) and add a second wing only for a clearly different volume
  (podium, rooftop penthouse, side annex). Never split one shaft into several stacked wings or side-by-side wings "to add detail".
- Volumes must touch or overlap: a wing on top of another has y0 = top of the one below; a side annex shares a wall (its cx/cz places it against the shaft,
  not floating beside it). Keep the main shaft centred at cx=0, cz=0 unless the reference clearly shows an offset.
- Balcony columns, vertical glass strips, pilasters, awnings and rooftop equipment are FEATURES on the facade, not extra wings. A dark/coloured vertical
  band on the facade = feature (balcony_stack / glass_strip / pilaster) plus palette, not a different volume.
- Use repeating window rows to count storeys of the main shaft. Count a double-height lobby once and keep roof screens separate from occupied storeys.
- Before filling the spec, reconcile the silhouette, volume breakpoints and facade grids across the views. Use the clearest view for each measurement.
- Preserve the ratio of width, height and visible depth, the spacing and alignment of openings, and the relative dimensions of major facade elements.
- Choose one consistent front facade. Tie side assignments across the images using matching corners, bands and features. Use the category as a hint only.
- Ignore streets, people, trees, ground shadows and perspective distortion. Set ground=false unless a platform is physically part of the building.
- For occluded facades use a conservative continuation of visible materials and structure. Explain inferred sides, estimated dimensions and any salient
  detail the schema cannot express in notes. Do not invent balconies, rooftop equipment, annexes or wall openings.

Worked example (a 19-storey residential slab: beige walls, olive balcony column, central glass strip, shop ground floor with canopy, penthouse):
{"name":"Torre residencial","category":"apartment","wall_kind":"plaster","roof_kind":"plaster","palette":{"wall":"#E8D1AC","trim":"#EFE1C6","roof":"#8A8A86","door":"#3A3E44","frame":"#3A3E44","accent":"#878B55","glass":"#566069"},
 "wings":[{"name":"main","w":22,"d":16,"floors":19,"fh":3.1,"ground_fh":4.6,"cx":0,"cz":0,"foundation":0.3,"roof":"flat","bay":2.2,"door_side":"front","door_w":2.6,"door_h":3.3,"door_x":-1,
   "window":{"w":1.35,"h":1.75,"sill":0.65,"lite":true,"mullions_x":2,"mullions_y":1},"ground_window":{"w":3,"h":3.1,"sill":0.35,"lite":true,"mullions_x":3,"mullions_y":1},
   "skip":[{"side":"front","x0":-10.2,"x1":-3.6}]},
  {"name":"penthouse","w":6,"d":6,"floors":1,"fh":3.4,"cx":-6.5,"cz":-1.5,"y0":60.9,"roof":"flat","window":{"w":1.6,"h":1.9,"sill":0.6,"lite":true}}],
 "features":[{"type":"balcony_stack","wing":"main","side":"front","x":-6.9,"w":5.8,"depth":1.25,"floor":1},{"type":"glass_strip","wing":"main","side":"front","x":-0.9,"w":4.6,"floor":1},
   {"type":"pilaster","wing":"main","side":"front","x":-10,"w":0.55,"depth":0.35,"floor":1},{"type":"canopy","wing":"main","side":"front","x":-0.9,"w":5.6,"depth":2.3,"height":3.9},
   {"type":"roof_screen","wing":"main","side":"front","x":4.5,"w":10,"depth":6,"y":1,"height":1.5}]}
This is only an example of the format and level of detail; describe what the REFERENCE shows.

Reproduce the reference as faithfully as the kit allows: storey count, proportions (estimate real sizes; a storey is ~2.8-3.2 m), window rhythm,
roof shape, materials and colours, porches/balconies/garage and the rooftop. Add wings only for visibly distinct attached masses."""


def spec_prompt(n_images: int, category_hint: str = "", validation_error: str = "", previous: dict | None = None) -> str:
    p = [f"You get {n_images} reference image(s) of ONE building (different views of the same building when more than one).",
         CONVENTIONS, "Write the complete specification JSON."]
    if category_hint:
        p.append(f"The user says it is a: {category_hint}.")
    if validation_error and previous is not None:
        p.append("Your previous answer was rejected by the validator with this error; fix it and answer the full JSON again.\n"
                 f"ERROR: {validation_error}\nPREVIOUS: {json.dumps(previous)[:12000]}")
    return "\n\n".join(p)


def critique_prompt(n_refs: int, n_renders: int, spec: dict, iteration: int) -> str:
    return "\n\n".join([
        f"The first {n_refs} image(s) are the REFERENCE. The next {n_renders} image(s) are RENDERS of the model the kit built from the specification below "
        f"(iteration {iteration}).",
        CONVENTIONS,
        "Compare the renders with the reference: storey count, proportions, window rhythm and sizes, roof, materials, colours, balconies, entrance, rooftop.",
        "Be a strict reviewer. First check the SILHOUETTE: number of volumes, their relative size and whether they line up like the reference (a shaft split into offset volumes is a major error). Then storeys, window rhythm, colours, balconies, entrance, rooftop. "
        "Return: score = fidelity 0-10 (10 = indistinguishable; 7 = same idea but visible differences in volumes or proportions; below 5 = different building); you must list at least 3 differences unless the match is nearly perfect; issues = concrete differences, most important first; "
        "spec = the FULL corrected specification (not a diff). Change only what makes it closer to the reference.",
        f"CURRENT SPEC: {json.dumps(spec)[:16000]}",
    ])


# ---------------------------------------------------------------------------------------------------------- conversion
def _window(d: dict | None) -> dict | None:
    if not d:
        return None
    out = {k: d[k] for k in ("w", "h", "sill", "arch", "shutters", "flower_boxes", "casing", "lite") if k in d}
    out["mullions"] = [int(d.get("mullions_x", 2)), int(d.get("mullions_y", 2))]
    return out


def to_house_spec(llm: dict[str, Any], seed: int = 1) -> dict[str, Any]:
    """Convert the model's JSON into a ``HouseSpec`` dict (validate it with ``HouseSpec.from_dict``)."""
    wings = []
    for w in llm.get("wings", []):
        x = {k: w[k] for k in ("name", "w", "d", "floors", "fh", "ground_fh", "cx", "cz", "y0", "foundation", "pad", "wall", "wall_lower", "lower_h", "roof",
                               "ridge", "pitch", "overhang", "rake", "shed_high", "bay", "door_w", "door_h", "door_x", "door_arch", "garage", "timber",
                               "belt", "corner_posts", "gable_window", "hide_end") if k in w}
        if w.get("sides"):
            x["sides"] = list(dict.fromkeys(w["sides"]))
        if "window" in w:
            x["window"] = _window(w["window"])
        if w.get("ground_window"):
            x["ground_window"] = _window(w["ground_window"])
        ds = w.get("door_side", "none")
        x["door_side"] = None if ds in ("none", "", None) else ds
        for key in ("skip", "skip_ground"):
            if w.get(key):
                d: dict[str, list] = {}
                for r in w[key]:
                    d.setdefault(r["side"], []).append([min(r["x0"], r["x1"]), max(r["x0"], r["x1"])])
                x[key] = d
        if w.get("no_windows"):
            x["no_windows"] = list(w["no_windows"])
        if w.get("side_wall"):
            x["side_wall"] = {r["side"]: r["wall"] for r in w["side_wall"]}
        wings.append(x)
    feats = []
    for f in llm.get("features", []):
        feats.append({k: f[k] for k in ("type", "wing", "side", "x", "w", "depth", "floor", "height", "y", "pitch", "style", "mode", "columns", "rail", "posts")
                      if k in f})
    pal = {k: v for k, v in (llm.get("palette") or {}).items() if k in PALETTE_KEYS and isinstance(v, str)}
    return {
        "name": str(llm.get("name", "building"))[:80], "archetype": "ai", "seed": seed, "wear": float(llm.get("wear", 0.06)),
        "wall_kind": llm.get("wall_kind", "stucco"), "roof_kind": llm.get("roof_kind", "shingles"), "base_kind": llm.get("base_kind", "plaster"),
        "wall2_kind": llm.get("wall2_kind", ""), "palette": pal, "wings": wings, "features": feats, "ground": bool(llm.get("ground", False)),
    }


def category_of(llm: dict[str, Any]) -> str:
    c = str(llm.get("category", "house"))
    return c if c in SPEC_SCHEMA["properties"]["category"]["enum"] else "house"
