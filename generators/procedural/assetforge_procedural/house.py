"""Premium Stylized house builder: a JSON-serialisable :class:`HouseSpec` -> modular geometry (walls, openings, roofs, features).

The spec is the single source of truth. A hand-written archetype, the rule-based planner or (later) a multimodal model that reads a
reference image all produce the same spec, and each wing/feature can be edited on its own without regenerating the rest.
Output is a :class:`GeneratedBuilding` in meters, Y-up, pivot at bottom-center, front = +Z.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields
from typing import Any

import numpy as np

from . import components as C
from .building import GeneratedBuilding
from .components import Opening
from .materials import ART_PROFILE_ID
from .mesh import MeshBuilder

HOUSE_GENERATOR_ID = "procedural.house"
HOUSE_GENERATOR_VERSION = "0.2.0"
SIDES = ("front", "back", "right", "left")
ROOFS = ("gable", "hip", "shed", "flat", "none")
FEATURE_TYPES = ("porch", "portico", "chimney", "dormer", "balcony", "panel", "shrubs", "balcony_stack", "glass_strip", "pilaster", "canopy", "roof_screen")
WALL_KINDS = ("stucco", "clapboard", "plaster", "brick", "stone", "wood")


@dataclass
class WindowStyle:
    w: float = 1.0
    h: float = 1.4
    sill: float = 0.95  # height of the sill above the floor
    arch: float = 0.0  # 0 = flat head, 0.5..1 = round-headed
    shutters: bool = False
    flower_boxes: bool = False  # ground floor only
    mullions: tuple[int, int] = (2, 3)
    lit_prob: float = 0.12
    casing: bool = True
    lite: bool = False  # few-triangle windows for tall buildings


@dataclass
class WingSpec:
    name: str = "main"
    w: float = 9.0
    d: float = 6.5
    floors: int = 2
    fh: float = 2.8  # floor height
    cx: float = 0.0
    cz: float = 0.0
    y0: float = 0.0  # base elevation (volumes stacked on top of others)
    foundation: float = 0.55  # plinth height (0 for stacked volumes)
    wall: str = "wall"
    roof: str = "gable"
    ridge: str = "x"  # direction of the ridge for gable/hip roofs
    pitch: float = 35.0
    overhang: float = 0.5
    rake: float = 0.35
    shed_high: str = "-z"
    sides: tuple[str, ...] = SIDES
    bay: float = 3.0
    window: WindowStyle = field(default_factory=WindowStyle)
    door_side: str | None = None
    door_w: float = 1.15
    door_h: float = 2.15
    door_arch: float = 0.0
    garage: bool = False
    timber: bool = False
    belt: bool = False
    corner_posts: bool = True
    gable_window: bool = True
    back_overhang: bool = True
    skip: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    no_windows: tuple[str, ...] = ()
    hide_end: str = ""  # 'a' / 'b': gable end (rake + triangle) buried in a neighbouring volume
    slab: str = "trim"  # flat roof slab material
    pad: float = 0.0  # concrete pad height under the walls (construction-stage kit); replaces the stone plinth
    wall_lower: str = ""  # material of the lower part of the wall (e.g. brick under siding)
    lower_h: float = 0.0  # height of that lower part; openings must not straddle it
    side_wall: dict[str, str] = field(default_factory=dict)  # per-side wall material override
    door_x: float | None = None  # explicit door position along the facade (default: centre bay)
    skip_ground: dict[str, list[tuple[float, float]]] = field(default_factory=dict)  # x ranges free of ground-floor openings
    ground_fh: float = 0.0  # taller ground floor (shops/lobby); 0 = same as fh
    ground_window: WindowStyle | None = None  # storefront windows on the ground floor


@dataclass
class Feature:
    type: str  # porch | portico | chimney | dormer | balcony | pergola
    wing: str = "main"
    side: str = "front"
    x: float = 0.0
    w: float = 3.0
    depth: float = 1.6
    floor: int = 1
    style: str = "shed"
    columns: bool = False
    rail: bool = True
    height: float = 0.0
    mode: str = "exterior"
    pitch: float = 0.0
    posts: bool = True
    y: float = 0.0


@dataclass
class HouseSpec:
    name: str = "house"
    archetype: str = "custom"
    seed: int = 1
    wear: float = 0.12
    wall_kind: str = "stucco"
    roof_kind: str = "shingles"
    base_kind: str = "cobble"
    palette: dict[str, str] = field(default_factory=dict)
    wings: list[WingSpec] = field(default_factory=list)
    features: list[Feature] = field(default_factory=list)
    door_steps: bool = True
    wall2_kind: str = ""
    ground: bool = False  # soil base block under the house (stage-kit assets)
    ground_margin: float = 1.6

    # -------- (de)serialisation: the JSON form is what the panel edits and what the multimodal model will emit
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> HouseSpec:
        def build(cls, data: dict[str, Any]):  # noqa: ANN001
            allowed = {f.name for f in fields(cls)}
            unknown = set(data) - allowed
            if unknown:
                raise ValueError(f"unknown field(s) for {cls.__name__}: {sorted(unknown)}")
            return cls(**data)

        wings = []
        for w in d.get("wings", []):
            w = dict(w)
            for wk in ("window", "ground_window"):
                if isinstance(w.get(wk), dict):
                    wd = dict(w[wk])
                    if "mullions" in wd:
                        wd["mullions"] = tuple(wd["mullions"])
                    w[wk] = build(WindowStyle, wd)
            if "sides" in w:
                w["sides"] = tuple(w["sides"])
            if "skip" in w:
                w["skip"] = {k: [tuple(p) for p in v] for k, v in w["skip"].items()}
            if "skip_ground" in w:
                w["skip_ground"] = {k: [tuple(p) for p in v] for k, v in w["skip_ground"].items()}
            if "no_windows" in w:
                w["no_windows"] = tuple(w["no_windows"])
            wings.append(build(WingSpec, w))
        feats = [build(Feature, dict(f)) for f in d.get("features", [])]
        rest = {k: v for k, v in d.items() if k not in ("wings", "features")}
        spec = build(HouseSpec, rest)
        spec.wings, spec.features = wings, feats
        spec.validate()
        return spec

    def validate(self) -> None:
        if not self.wings:
            raise ValueError("a house needs at least one wing")
        names = [w.name for w in self.wings]
        if len(set(names)) != len(names):
            raise ValueError("wing names must be unique")
        for w in self.wings:
            if not (0.8 <= w.w <= 40 and 0.8 <= w.d <= 40):
                raise ValueError(f"wing {w.name}: width/depth must be 0.8..40 m")
            if not 1 <= w.floors <= 40 or not 1.4 <= w.fh <= 5 or not (w.ground_fh == 0 or 2.2 <= w.ground_fh <= 8):
                raise ValueError(f"wing {w.name}: floors 1..40, floor height 1.4..5 m, ground floor 2.2..8 m")
            if w.roof not in ROOFS or w.ridge not in ("x", "z") or not 8 <= w.pitch <= 65:
                raise ValueError(f"wing {w.name}: invalid roof")
            if any(s not in SIDES for s in w.sides):
                raise ValueError(f"wing {w.name}: invalid side")
        for f in self.features:
            if f.wing not in names:
                raise ValueError(f"feature {f.type}: unknown wing {f.wing!r}")
            if f.type not in FEATURE_TYPES:
                raise ValueError(f"unknown feature type {f.type!r}")
            if f.side not in SIDES:
                raise ValueError(f"feature {f.type}: invalid side")
        if self.wall_kind not in WALL_KINDS:
            raise ValueError(f"wall_kind must be one of {WALL_KINDS}")


_IDENT: dict[str, str] = {}


class HouseBuilder:
    def __init__(self, spec: HouseSpec, stage: int = 6) -> None:
        spec.validate()
        if not 1 <= stage <= 6:
            raise ValueError("construction stage must be 1..6")
        self.stage = stage
        self.s = spec
        self.rng = np.random.default_rng(spec.seed)
        self.mb = MeshBuilder()
        self.mats = C.house_materials(spec.palette, spec.wear, spec.wall_kind, spec.roof_kind, spec.base_kind, spec.wall2_kind or None)
        self.m = {k: k for k in self.mats}
        self.wings = {w.name: w for w in spec.wings}
        self.ridge_y: dict[str, float] = {}
        self.points: list[dict] = []

    # ------------------------------------------------------------------ frames
    def _frame(self, w: WingSpec, side: str):  # noqa: ANN202
        table = {
            "front": (0, (w.cx, 0, w.cz + w.d / 2), w.w),
            "back": (180, (w.cx, 0, w.cz - w.d / 2), w.w),
            "right": (90, (w.cx + w.w / 2, 0, w.cz), w.d),
            "left": (270, (w.cx - w.w / 2, 0, w.cz), w.d),
        }
        yaw, off, length = table[side]
        return yaw, off, length

    def _fl_y(self, w: WingSpec, f: int) -> float:
        """Height of the floor slab of storey ``f`` (0 = ground), honouring a taller ground floor."""
        base = w.y0 + w.foundation
        if f <= 0:
            return base
        return base + (w.ground_fh or w.fh) + (f - 1) * w.fh

    def _top(self, w: WingSpec) -> float:
        return self._fl_y(w, w.floors)

    def _feature_skips(self, w: WingSpec, side: str) -> list[tuple[float, float]]:
        """Facade x-ranges covered by curtain-wall strips: no punched windows behind them."""
        return [(f.x - f.w / 2, f.x + f.w / 2) for f in self.s.features if f.type == "glass_strip" and f.wing == w.name and f.side == side]

    # ------------------------------------------------------------------ layout
    def _layout(self, w: WingSpec, side: str, length: float) -> list[Opening]:
        st = w.window
        ops: list[Opening] = []
        fnd = w.y0 + w.foundation
        margin = max(0.5, min(max(1.0, st.w * 0.9), (length - st.w) / 2 - 0.1))
        has_door = w.door_side == side
        span = length - 2 * margin
        n = max(1, round(span / w.bay))
        if has_door and not w.garage and n % 2 == 0:
            n = n + 1 if span / (n + 1) >= st.w + 0.45 else max(1, n - 1)
        while n > 1 and span / n < st.w + 0.45:
            n -= 1
        centres = [-length / 2 + margin + span * (i + 0.5) / n for i in range(n)] if n > 1 or span > 0 else [0.0]
        skip = w.skip.get(side, []) + self._feature_skips(w, side)
        ww = min(st.w, (span / n) * 0.62) if n > 1 else min(st.w, max(0.6, length - 2 * 0.6))
        gw = w.ground_window
        for f in range(w.floors):
            y_fl = self._fl_y(w, f)
            for i, cx in enumerate(centres):
                if any(a - ww / 2 - 0.2 <= cx <= b + ww / 2 + 0.2 for a, b in skip):
                    continue
                if f == 0 and any(a - ww / 2 - 0.2 <= cx <= b + ww / 2 + 0.2 for a, b in w.skip_ground.get(side, [])):
                    continue
                if f == 0 and has_door and w.door_x is not None and abs(cx - w.door_x) < ww / 2 + w.door_w / 2 + 0.35:
                    continue
                is_door = has_door and f == 0 and w.door_x is None and (i == n // 2)
                if is_door:
                    if w.garage:
                        ops.append(Opening(cx, 2.7, y_fl, y_fl + 2.25, "garage"))
                    else:
                        rise = w.door_arch * w.door_w / 2
                        ops.append(Opening(cx, w.door_w, y_fl, y_fl + w.door_h + rise, "door", arch=w.door_arch))
                    continue
                if has_door and w.garage and f == 0:
                    continue
                if side in w.no_windows:
                    continue
                ws = gw if (f == 0 and gw is not None) else st
                wwf = min(ws.w, (span / n) * 0.9) if (ws is gw and n > 1) else ww
                rise = ws.arch * wwf / 2
                y0 = y_fl + ws.sill
                ops.append(Opening(cx, wwf, y0, y0 + ws.h + rise, "window", arch=ws.arch, shutters=ws.shutters,
                                   flower_box=ws.flower_boxes and f == 0 and not (has_door and abs(cx) < 1.0),
                                   mullions=ws.mullions, lit=bool(self.rng.random() < ws.lit_prob), casing=ws.casing, lite=ws.lite))
        if has_door and w.door_x is not None and not w.garage:
            y_fl = fnd
            rise = w.door_arch * w.door_w / 2
            ops.append(Opening(w.door_x, w.door_w, y_fl, y_fl + w.door_h + rise, "door", arch=w.door_arch))
        return ops

    # ------------------------------------------------------------------ build
    def build(self) -> GeneratedBuilding:
        st = self.stage
        if self.s.ground:
            self._ground()
        if st >= 2:
            self._pads()
        if st >= 3:
            for w in self.s.wings:
                for side in w.sides:
                    self._facade(w, side)
            for w in self.s.wings:
                self._roof(w)
        if st >= 5:
            for w in self.s.wings:  # gable-end attic windows need the ridge height
                self._gable_windows(w)
        if st >= 3:
            for f in self.s.features:
                if st >= 5 and (f.type != "shrubs" or st >= 6):
                    getattr(self, f"_feat_{f.type}")(f)
                elif st < 5 and f.type in ("porch", "portico"):
                    getattr(self, f"_feat_{f.type}")(f)
        if st >= 6 and self.s.ground:
            self._landscape()
        for w in self.s.wings:
            if st >= 5 and w.door_side and self.s.door_steps and not any(f.type in ("porch", "portico") and f.wing == w.name and f.side == w.door_side
                                                             for f in self.s.features):
                self._door_steps(w)
        spec = self.mb.build()
        lo, hi = spec.bounds()
        shift = np.array([-(lo[0] + hi[0]) / 2, -lo[1], -(lo[2] + hi[2]) / 2], dtype=np.float32)
        for part in spec.parts.values():
            part.vertices = (part.vertices + shift).astype(np.float32)
        lo, hi = spec.bounds()
        used = {m: self.mats[m] for m in spec.parts}
        return GeneratedBuilding(
            mesh=spec, materials=used, dimensions=tuple(float(x) for x in (hi - lo)),  # type: ignore[arg-type]
            connection_points=self.points,
            summary=dict(category="house", archetype=self.s.archetype, style=self.s.archetype, palette=self.s.name, seed=self.s.seed,
                         wings=len(self.s.wings), features=[f.type for f in self.s.features], art_profile=ART_PROFILE_ID,
                         spec=self.s.to_dict()),
        )

    # ------------------------------------------------------------------ facade
    def _facade(self, w: WingSpec, side: str) -> None:
        mb, m = self.mb, self.m
        yaw, off, L = self._frame(w, side)
        fnd = w.y0 + w.foundation
        top = self._top(w)
        ops = self._layout(w, side, L)
        reveal = 0.15
        if self.stage == 3:
            with mb.transform(yaw, off):
                C.framing_wall(mb, "framing", -L / 2 + 0.05, L / 2 - 0.05, fnd, top - 0.1, ops)
            return
        with mb.transform(yaw, off):
            wm = w.side_wall.get(side, w.wall)
            if w.wall_lower and w.lower_h > 0:
                split = fnd + w.lower_h
                lo_ops = [o for o in ops if (o.y0 + o.y1) / 2 < split]
                up_ops = [o for o in ops if (o.y0 + o.y1) / 2 >= split]
                C.wall_with_openings(mb, w.wall_lower, -L / 2, L / 2, fnd - 0.02, split, lo_ops, reveal, w.wall_lower)
                C.wall_with_openings(mb, wm, -L / 2, L / 2, split, top, up_ops, reveal, wm)
                C.belt_course(mb, "trim", -L / 2 - 0.04, L / 2 + 0.04, split, 0.1, 0.05)
            else:
                C.wall_with_openings(mb, wm, -L / 2, L / 2, fnd - 0.02, top, ops, reveal, wm)
            if w.foundation > 0 and w.pad <= 0:
                C.foundation(mb, "base", "trim", -L / 2, L / 2, w.foundation)
            if self.stage == 4:
                for o in ops:
                    C.bare_opening(mb, "framing", o, reveal)
                return
            for o in ops:
                if o.kind == "door":
                    C.door_dressing(mb, m, o, reveal)
                elif o.kind == "garage":
                    C.garage_dressing(mb, m, o, reveal)
                else:
                    C.window_dressing(mb, m, o, reveal)
            if w.belt:
                for f in range(1, w.floors):
                    C.belt_course(mb, "trim", -L / 2 - 0.04, L / 2 + 0.04, self._fl_y(w, f))
            if w.corner_posts:
                for x in (-L / 2, L / 2):
                    C.corner_post(mb, "trim" if not w.timber else "timber", x, fnd, top - 0.12, 0.24 if w.timber else 0.2)
            if w.timber:
                C.timber_frame(mb, "timber", -L / 2 + 0.1, L / 2 - 0.1, fnd, top - 0.12, ops, [self._fl_y(w, f) for f in range(1, w.floors)])

    def _gable_windows(self, w: WingSpec) -> None:
        if w.roof != "gable" or not w.gable_window or w.name not in self.ridge_y:
            return
        top = self._top(w)
        rise = self.ridge_y[w.name] - top
        if rise < 1.9:
            return
        sides = ("left", "right") if w.ridge == "x" else ("front", "back")
        for side in sides:
            if side not in w.sides:
                continue
            yaw, off, L = self._frame(w, side)
            with self.mb.transform(yaw, off):
                C.overlay_window(self.mb, self.m, 0.0, top + 0.45, 0.62, min(0.9, rise - 1.3), lit=bool(self.rng.random() < 0.3))

    # ------------------------------------------------------------------ roofs
    def _roof(self, w: WingSpec) -> None:
        mb, m = self.mb, self.m
        top = self._top(w)
        gw = "wall" if w.wall == "wall" else w.wall
        if self.stage <= 4:
            self._roof_stage(w)
            return
        if w.roof == "shed":
            self._shed_infill(w, top)  # outside the wing transform: it uses absolute facade frames
        with mb.transform(0, (w.cx, 0, w.cz)):
            if w.roof == "gable":
                if w.ridge == "x":
                    y = C.gable_roof(mb, m, -w.w / 2, w.w / 2, -w.d / 2, w.d / 2, top, w.pitch, w.overhang, w.rake, back_overhang=w.back_overhang, gable_wall=gw,
                                     end_a=w.hide_end != "a", end_b=w.hide_end != "b")
                else:
                    with mb.transform(90):
                        y = C.gable_roof(mb, m, -w.d / 2, w.d / 2, -w.w / 2, w.w / 2, top, w.pitch, w.overhang, w.rake, back_overhang=w.back_overhang, gable_wall=gw,
                                         end_a=w.hide_end != "a", end_b=w.hide_end != "b")
                self.ridge_y[w.name] = y
            elif w.roof == "hip":
                self.ridge_y[w.name] = C.hip_roof(mb, m, -w.w / 2, w.w / 2, -w.d / 2, w.d / 2, top, w.pitch, w.overhang)
            elif w.roof == "shed":
                if w.shed_high in ("-z", "+z"):
                    self.ridge_y[w.name] = C.shed_roof(mb, m, -w.w / 2, w.w / 2, -w.d / 2, w.d / 2, top, w.pitch, w.overhang, high_side=w.shed_high)
                else:  # rising toward -x / +x: build it rotated
                    with mb.transform(90 if w.shed_high == "-x" else 270):
                        self.ridge_y[w.name] = C.shed_roof(mb, m, -w.d / 2, w.d / 2, -w.w / 2, w.w / 2, top, w.pitch, w.overhang, high_side="-z")
            elif w.roof == "flat":
                C.flat_roof(mb, m, -w.w / 2, w.w / 2, -w.d / 2, w.d / 2, top, w.overhang, parapet=1, slab=w.slab)
                self.ridge_y[w.name] = top + 0.3

    def _roof_stage(self, w: WingSpec) -> None:
        """Stage 3: bare rafters. Stage 4: one slope shingled, the other still showing rafters and battens. Gable roofs only."""
        mb, m = self.mb, self.m
        top = self._top(w)
        stage3 = self.stage == 3
        if w.roof == "hip":
            with mb.transform(0, (w.cx, 0, w.cz)):
                shingled = () if stage3 else ("back",)
                y = C.hip_framing(mb, "framing", -w.w / 2, w.w / 2, -w.d / 2, w.d / 2, top, w.pitch, w.overhang, skip=shingled)
                if shingled:
                    C.hip_roof(mb, m, -w.w / 2, w.w / 2, -w.d / 2, w.d / 2, top, w.pitch, w.overhang, skip=("front", "endp", "endn"))
            self.ridge_y[w.name] = y
            return
        if w.roof == "shed":
            with mb.transform(0, (w.cx, 0, w.cz)):
                rot = {"-z": 0, "+z": 0, "-x": 90, "+x": 270}[w.shed_high]
                with mb.transform(rot):
                    dx, dz = (w.w, w.d) if rot == 0 else (w.d, w.w)
                    hs = w.shed_high if rot == 0 else "-z"
                    y = C.shed_framing(mb, "framing", -dx / 2, dx / 2, -dz / 2, dz / 2, top, w.pitch, w.overhang, high_side=hs)
            self.ridge_y[w.name] = y
            return
        if w.roof != "gable":
            return
        with mb.transform(0, (w.cx, 0, w.cz)):
            def go(x0, x1, z0, z1):  # noqa: ANN001, ANN202
                y = C.gable_framing(mb, "framing", x0, x1, z0, z1, top, w.pitch, w.overhang, w.rake, slopes=("front", "back") if stage3 else ("front",),
                                    battens=not stage3)
                if not stage3:
                    C.gable_roof(mb, m, x0, x1, z0, z1, top, w.pitch, w.overhang, w.rake, back_overhang=True, gable_wall=w.wall, slopes=("back",),
                                 end_a=w.hide_end != "a", end_b=w.hide_end != "b", ridge_cap=False)
                return y

            if w.ridge == "x":
                y = go(-w.w / 2, w.w / 2, -w.d / 2, w.d / 2)
            else:
                with mb.transform(90):
                    y = go(-w.d / 2, w.d / 2, -w.w / 2, w.w / 2)
        self.ridge_y[w.name] = y

    def _shed_infill(self, w: WingSpec, top: float) -> None:
        """Walls of a single-slope roof must follow the slope: the high side is taller and the two sides in between get a triangle."""
        mb = self.mb
        t = math.tan(math.radians(w.pitch))
        along = w.w if w.shed_high in ("-x", "+x") else w.d  # span the roof climbs over
        rise = along * t
        high_side = {"-x": "left", "+x": "right", "-z": "back", "+z": "front"}[w.shed_high]
        mat = w.wall
        if high_side in w.sides:
            yaw, off, L = self._frame(w, high_side)
            with mb.transform(yaw, off):
                C.facing_quad(mb, mat, -L / 2, L / 2, top, top + rise, 0.0, tile=2.4)
        for side in w.sides:
            if side == high_side or side == {"left": "right", "right": "left", "front": "back", "back": "front"}[high_side]:
                continue
            yaw, off, L = self._frame(w, side)
            # which local end of this facade is the high end?
            hi_local = {("front", "-x"): -1, ("front", "+x"): 1, ("back", "-x"): 1, ("back", "+x"): -1,
                        ("right", "-z"): 1, ("right", "+z"): -1, ("left", "-z"): -1, ("left", "+z"): 1}[(side, w.shed_high)]
            with mb.transform(yaw, off):
                a, b, c = (-hi_local * L / 2, top, 0.0), (hi_local * L / 2, top, 0.0), (hi_local * L / 2, top + rise, 0.0)
                mb.tri_out(mat, a, b, c, (0.0, top, -10.0), tile=2.4)

    # ------------------------------------------------------------------ ground / pads / landscaping
    def _extent(self, with_features: bool = False) -> tuple[float, float, float, float]:
        xs0 = min(w.cx - w.w / 2 for w in self.s.wings)
        xs1 = max(w.cx + w.w / 2 for w in self.s.wings)
        zs0 = min(w.cz - w.d / 2 for w in self.s.wings)
        zs1 = max(w.cz + w.d / 2 for w in self.s.wings)
        if with_features:  # porches and their steps must stay on the ground block at every stage
            for f in self.s.features:
                if f.type not in ("porch", "portico", "balcony"):
                    continue
                w = self.wings[f.wing]
                reach = f.depth + (0.9 if f.type != "balcony" else 0.0)
                if f.side == "front":
                    zs1 = max(zs1, w.cz + w.d / 2 + reach)
                elif f.side == "back":
                    zs0 = min(zs0, w.cz - w.d / 2 - reach)
                elif f.side == "right":
                    xs1 = max(xs1, w.cx + w.w / 2 + reach)
                else:
                    xs0 = min(xs0, w.cx - w.w / 2 - reach)
        return xs0, xs1, zs0, zs1

    def _ground(self) -> None:
        ox0, ox1, oz0, oz1 = self._extent()
        x0, x1, z0, z1 = self._extent(True)
        mg = self.s.ground_margin
        C.bbox(self.mb, "soil", (x0 - mg, -0.4, z0 - mg), (x1 + mg, 0.0, z1 + mg), 0.04, faces=("+x", "-x", "+z", "-z", "+y", "-y"))
        x0, x1, z0, z1 = ox0, ox1, oz0, oz1
        if self.stage == 1:  # the marked plot of the house
            t = 0.05
            for a, b in (((x0 - 0.2, z1 + 0.15), (x1 + 0.2, z1 + 0.2)), ((x0 - 0.2, z0 - 0.2), (x1 + 0.2, z0 - 0.15)),
                         ((x0 - 0.2, z0 - 0.15), (x0 - 0.15, z1 + 0.15)), ((x1 + 0.15, z0 - 0.15), (x1 + 0.2, z1 + 0.15))):
                C.bbox(self.mb, "dark", (a[0], 0.0, a[1]), (b[0], t, b[1]), faces=("+y",))

    def _pads(self) -> None:
        for i, w in enumerate(self.s.wings):
            if w.pad > 0:
                top = w.y0 + w.pad - 0.004 * i  # later wings sit a hair lower so overlapping pads never z-fight
                C.bbox(self.mb, "concrete", (w.cx - w.w / 2 - 0.22, w.y0, w.cz - w.d / 2 - 0.22 + 0.001 * i), (w.cx + w.w / 2 + 0.22, top, w.cz + w.d / 2 + 0.22),
                       0.02, faces=("+x", "-x", "+z", "-z", "+y"))
                if w.door_side == "front" and self.stage < 5:
                    C.bbox(self.mb, "concrete", (w.cx - 0.8, 0, w.cz + w.d / 2 + 0.2), (w.cx + 0.8, w.pad * 0.5, w.cz + w.d / 2 + 0.7), 0.02, faces=("+x", "-x", "+z", "+y"))

    def _landscape(self) -> None:
        x0, x1, z0, z1 = self._extent(True)
        mg = self.s.ground_margin
        C.bbox(self.mb, "grass", (x0 - mg + 0.02, 0.0, z0 - mg + 0.02), (x1 + mg - 0.02, 0.07, z1 + mg - 0.02), 0.03, faces=("+x", "-x", "+z", "-z", "+y"))
        for w in self.s.wings:
            if w.door_side == "front":
                zf = w.cz + w.d / 2
                C.bbox(self.mb, "concrete", (w.cx - 0.55, 0.0, zf + 0.5), (w.cx + 0.55, 0.1, z1 + mg - 0.02), 0.02, faces=("+x", "-x", "+y", "+z"))

    # ------------------------------------------------------------------ features
    def _feat_porch(self, f: Feature) -> None:
        w = self.wings[f.wing]
        mb, m = self.mb, self.m
        yaw, off, L = self._frame(w, f.side)
        fnd = w.y0 + w.foundation
        x0, x1 = f.x - f.w / 2, f.x + f.w / 2
        ph = f.height or 2.55
        with mb.transform(yaw, off):
            C.deck(mb, m, x0, x1, -0.05, f.depth, fnd)
            C.steps(mb, "base", f.x, min(f.w * 0.5, 2.0), fnd, max(2, round(fnd / 0.2)), 0.3, f.depth)
            posts = [x0 + 0.2, x1 - 0.2]
            if f.w > 4.6:
                posts.insert(1, f.x)
            for px in posts if f.posts else []:
                if self.stage < 5:
                    C.post(mb, "framing", px, f.depth - 0.2, fnd, fnd + ph, 0.2)
                elif f.mode == "craftsman":
                    C.bbox(mb, "base", (px - 0.3, fnd, f.depth - 0.5), (px + 0.3, fnd + 0.8, f.depth + 0.1), 0.025, faces=("+x", "-x", "+z", "-z", "+y"))
                    C.bbox(mb, "trim", (px - 0.2, fnd + 0.8, f.depth - 0.4), (px + 0.2, fnd + ph, f.depth), 0.02, faces=("+x", "-x", "+z", "-z", "+y"))
                    C.bbox(mb, "trim", (px - 0.27, fnd + ph - 0.18, f.depth - 0.47), (px + 0.27, fnd + ph, f.depth + 0.07), 0.02, faces=("+x", "-x", "+z", "-z", "+y", "-y"))
                elif f.mode == "trim":
                    C.post(mb, "trim", px, f.depth - 0.2, fnd, fnd + ph, 0.22)
                elif f.columns:
                    C.column(mb, m, px, f.depth - 0.18, fnd, fnd + ph, 0.12)
                else:
                    C.post(mb, "timber", px, f.depth - 0.13, fnd, fnd + ph, 0.17)
            if f.rail and self.stage >= 5:
                gap = min(f.w * 0.42, 1.7) if f.style != "open" else f.w
                for a, b in ((x0 + 0.1, f.x - gap / 2), (f.x + gap / 2, x1 - 0.1)):
                    if b - a > 0.3:
                        C.railing(mb, m, a, b, f.depth - 0.13, fnd, 0.9, 0.2, iron=False)
                for sx in (x0 + 0.13, x1 - 0.13):
                    pass
            y_roof = fnd + ph
            if self.stage == 3:
                return  # roofs of porches appear with the roof stage
            if f.style == "gable":
                with mb.transform(90, (f.x, 0, f.depth / 2 - 0.05)):
                    C.gable_roof(mb, m, -f.depth / 2 - 0.1, f.depth / 2 + 0.1, -f.w / 2 - 0.15, f.w / 2 + 0.15, y_roof + 0.15, 26, 0.22, 0.28,
                                 th=0.13, back_overhang=True, gable_wall="trim", end_b=False)
            else:
                C.shed_roof(mb, m, x0 - 0.05, x1 + 0.05, 0.0, f.depth, y_roof + 0.12, f.pitch or 14, 0.22, 0.12, high_side="-z")

    _feat_portico = _feat_porch

    def _feat_chimney(self, f: Feature) -> None:
        w = self.wings[f.wing]
        mb, m = self.mb, self.m
        top = self._ridge(w) + (f.height or 0.7)
        if f.mode == "exterior":
            yaw, off, L = self._frame(w, f.side)
            with mb.transform(yaw, off):
                C.chimney(mb, m, f.x, f.depth / 2 - 0.12, f.w, f.depth, 0.0, top, base_mat="base")
        else:
            with mb.transform(0, (w.cx, 0, w.cz)):
                yaw, off, L = self._frame(WingSpec(w=w.w, d=w.d), f.side)
                C.chimney(mb, m, f.x, off[2] if f.side in ("front", "back") else 0.0, f.w, f.depth, self._top(w) - 0.4, top)

    def _ridge(self, w: WingSpec) -> float:
        return self.ridge_y.get(w.name, self._top(w) + 1.0)

    def _feat_dormer(self, f: Feature) -> None:
        w = self.wings[f.wing]
        mb, m = self.mb, self.m
        yaw, off, L = self._frame(w, f.side)
        top = self._top(w)
        t = math.tan(math.radians(w.pitch))
        hw = f.w / 2
        zf = -0.55  # front wall plane of the dormer, inside the eave line
        y_base = top + (-zf) * t
        h = 1.35
        run = 1.5
        with mb.transform(yaw, off):
            # cheeks follow the roof slope; body walls in wall material, front carries the window
            C.bbox(mb, w.wall, (f.x - hw, y_base - 0.1, zf - run), (f.x + hw, y_base + h, zf), faces=("+z", "+x", "-x"))
            C.overlay_window(mb, m, f.x, y_base + 0.2, f.w - 0.7, h - 0.5, lit=bool(self.rng.random() < 0.25)) if False else None
            with mb.transform(0, (0, 0, zf)):
                C.overlay_window(mb, m, f.x, y_base + 0.2, f.w - 0.75, h - 0.55, lit=bool(self.rng.random() < 0.25))
            with mb.transform(90, (f.x, 0, zf - run / 2)):
                C.gable_roof(mb, m, -run / 2 - 0.05, run / 2 + 0.05, -hw - 0.05, hw + 0.05, y_base + h, 34, 0.2, 0.22, th=0.1,
                             back_overhang=True, gable_wall="wall", ridge_cap=True, tile=1.2, end_b=False)

    def _feat_balcony(self, f: Feature) -> None:
        w = self.wings[f.wing]
        mb, m = self.mb, self.m
        yaw, off, L = self._frame(w, f.side)
        y = self._fl_y(w, f.floor)
        x0, x1 = f.x - f.w / 2, f.x + f.w / 2
        with mb.transform(yaw, off):
            C.bbox(mb, "trim", (x0, y - 0.18, 0), (x1, y, f.depth), 0.03, faces=("+y", "-y", "+x", "-x", "+z"))
            C.railing(mb, m, x0 + 0.05, x1 - 0.05, f.depth - 0.07, y, 0.95, 0.16, iron=True)
            for sx in (x0 + 0.05, x1 - 0.05):
                for k in range(3):
                    C.bbox(mb, "metal", (sx - 0.02, y + 0.14, 0.1 + k * (f.depth - 0.2) / 3), (sx + 0.02, y + 0.88, 0.14 + k * (f.depth - 0.2) / 3), faces=("+x", "-x", "+z"))
            C.bracket(mb, "timber", x0 + 0.3, y - 0.18, 0.5)
            C.bracket(mb, "timber", x1 - 0.3, y - 0.18, 0.5)

    def _feat_panel(self, f: Feature) -> None:
        w = self.wings[f.wing]
        yaw, off, L = self._frame(w, f.side)
        y0 = w.y0 + w.foundation + f.y
        y1 = y0 + (f.height or self._top(w) - (w.y0 + w.foundation) - f.y - 0.14)  # stop just under the eave so it never pokes through the roof slab
        with self.mb.transform(yaw, off):
            C.bbox(self.mb, "wall2", (f.x - f.w / 2, y0, 0), (f.x + f.w / 2, y1, f.depth or 0.14), 0.025, faces=("+z", "+x", "-x", "+y", "-y"))

    def _feat_shrubs(self, f: Feature) -> None:
        w = self.wings[f.wing]
        yaw, off, L = self._frame(w, f.side)
        n = max(1, int(f.w / 0.85))
        with self.mb.transform(yaw, off):
            for i in range(n):
                x = f.x - f.w / 2 + (i + 0.5) * f.w / n
                C.shrub(self.mb, self.m, x, f.depth or 0.55, 0.36 + 0.14 * float(self.rng.random()), light=bool(i % 2))

    # ------------------------------------------------------------------ high-rise features
    def _feat_balcony_stack(self, f: Feature) -> None:
        """A balcony on every storey from ``floor`` up to ``height`` (storey index, 0 = up to the top)."""
        w = self.wings[f.wing]
        yaw, off, L = self._frame(w, f.side)
        last = int(f.height) if f.height else w.floors - 1
        x0, x1 = f.x - f.w / 2, f.x + f.w / 2
        with self.mb.transform(yaw, off):
            for fl in range(max(1, f.floor), min(last, w.floors - 1) + 1):
                y = self._fl_y(w, fl)
                C.bbox(self.mb, "trim", (x0, y - 0.16, 0), (x1, y, f.depth), 0.02, faces=("+y", "-y", "+x", "-x", "+z"))
                C.railing(self.mb, self.m, x0 + 0.05, x1 - 0.05, f.depth - 0.06, y, 1.0, 0.28, iron=True)

    def _feat_glass_strip(self, f: Feature) -> None:
        w = self.wings[f.wing]
        yaw, off, L = self._frame(w, f.side)
        y0 = self._fl_y(w, max(0, f.floor))
        y1 = self._top(w) - 0.3 if not f.height else y0 + f.height
        with self.mb.transform(yaw, off):
            C.glass_strip(self.mb, self.m, f.x - f.w / 2, f.x + f.w / 2, y0, y1, [self._fl_y(w, k) for k in range(1, w.floors)])

    def _feat_pilaster(self, f: Feature) -> None:
        w = self.wings[f.wing]
        yaw, off, L = self._frame(w, f.side)
        y0 = self._fl_y(w, max(0, f.floor))
        y1 = self._top(w) - 0.1 if not f.height else y0 + f.height
        with self.mb.transform(yaw, off):
            C.pilaster(self.mb, "accent", f.x, f.w, y0, y1, f.depth or 0.12)

    def _feat_canopy(self, f: Feature) -> None:
        w = self.wings[f.wing]
        yaw, off, L = self._frame(w, f.side)
        y = self._fl_y(w, 0) + (f.height or (w.ground_fh or w.fh) * 0.82)
        with self.mb.transform(yaw, off):
            C.canopy(self.mb, self.m, f.x - f.w / 2, f.x + f.w / 2, y, f.depth)

    def _feat_roof_screen(self, f: Feature) -> None:
        """Equipment screen on the roof of the wing; ``x`` is along the wing width, ``y`` along its depth."""
        w = self.wings[f.wing]
        top = self._top(w) + 0.22
        with self.mb.transform(0, (w.cx, 0, w.cz)):
            C.roof_screen(self.mb, self.m, f.x - f.w / 2, f.x + f.w / 2, f.y - f.depth / 2, f.y + f.depth / 2, top, f.height or 1.4)

    def _door_steps(self, w: WingSpec) -> None:
        yaw, off, L = self._frame(w, w.door_side or "front")
        if w.foundation <= 0.05:
            return
        with self.mb.transform(yaw, off):
            C.steps(self.mb, "base", 0.0, w.door_w + 0.8, w.foundation, max(2, round(w.foundation / 0.2)), 0.32, 0.0)


# ====================================================================================================== archetypes
def _pal(**k: str) -> dict[str, str]:
    return dict(k)


def archetype_tudor_cottage(seed: int = 1) -> HouseSpec:
    """Steep gables, half-timbering over cream plaster, rubble stone base, exterior stone chimney, cross-gable bay."""
    win = WindowStyle(w=0.95, h=1.25, sill=0.9, mullions=(2, 3), flower_boxes=True)
    main = WingSpec("main", 9.2, 6.2, 2, 2.65, 0, 0, foundation=0.6, wall="wall", roof="gable", ridge="x", pitch=43, overhang=0.5, rake=0.4,
                    bay=2.9, window=win, door_side="front", door_w=1.1, door_h=2.1, door_arch=0.35, timber=True,
                    skip={"front": [(-4.6, -1.2)]})
    bay = WingSpec("bay", 3.8, 2.8, 2, 2.65, -2.7, 4.4, foundation=0.6, wall="wall", roof="gable", ridge="z", pitch=43, overhang=0.45, rake=0.4,
                   bay=3.0, window=WindowStyle(w=1.0, h=1.3, sill=0.95, mullions=(2, 3), flower_boxes=True), sides=("front", "left", "right"),
                   timber=True, gable_window=True, hide_end="b")
    pal = _pal(wall="#EBDDBD", trim="#F3EBD8", base="#7F776A", roof="#4A2B21", timber="#3E2B1F", door="#3B5A48", frame="#40322A", shutter="#3B5A48",
               brick="#A05A43", deck="#8A6A4A", metal="#2E3236", accent="#3B5A48", flower="#D9574A")
    feats = [Feature("chimney", "main", "left", x=-0.6, w=1.05, depth=0.9, height=0.8, mode="exterior"),
             Feature("porch", "main", "front", x=2.2, w=2.6, depth=1.5, style="gable", height=2.5, rail=False),
             Feature("shrubs", "main", "front", x=-3.0, w=2.4, depth=0.55), Feature("shrubs", "main", "right", x=-1.2, w=2.6, depth=0.55)]
    return HouseSpec("Cottage Tudor", "tudor_cottage", seed, 0.12, "stucco", "shingles", "cobble", pal, [main, bay], feats)


def archetype_colonial(seed: int = 1) -> HouseSpec:
    """Symmetric clapboard house, hip roof with dormers, columned portico, shutters, two chimneys."""
    win = WindowStyle(w=1.05, h=1.6, sill=0.85, mullions=(2, 3), shutters=True, casing=True)
    main = WingSpec("main", 11.6, 8.0, 2, 3.0, 0, 0, foundation=0.65, wall="wall", roof="hip", pitch=30, overhang=0.6, bay=3.1, window=win,
                    door_side="front", door_w=1.25, door_h=2.3, belt=True, corner_posts=True)
    wing = WingSpec("wing", 4.6, 6.2, 1, 3.0, 8.0, -0.4, foundation=0.65, wall="wall", roof="gable", ridge="x", pitch=30, overhang=0.5, rake=0.35,
                    bay=3.0, window=win, sides=("front", "back", "right"), no_windows=(), hide_end="a")
    pal = _pal(wall="#C4D3DB", trim="#F7F5EF", base="#8D4F3D", roof="#30343B", timber="#4A3A2E", door="#2F4A3E", frame="#F3F0E8", shutter="#2F4A3E",
               brick="#9A5845", deck="#CFC8BA", metal="#2B2E33", accent="#2F4A3E", flower="#C8503F")
    feats = [Feature("portico", "main", "front", x=0.0, w=4.2, depth=2.0, style="gable", columns=True, height=3.05, rail=False),
             Feature("chimney", "main", "left", x=0.0, w=1.2, depth=0.8, height=0.9, mode="interior"),
             Feature("dormer", "main", "front", x=-3.4, w=1.9), Feature("dormer", "main", "front", x=3.4, w=1.9),
             Feature("shrubs", "main", "front", x=-3.6, w=3.4, depth=0.6), Feature("shrubs", "main", "front", x=3.6, w=3.4, depth=0.6)]
    # the second wing: keep a simple attached garage-like volume, hidden sides toward the main block
    wing.sides = ("front", "back", "right")
    return HouseSpec("Casa Colonial", "colonial", seed, 0.1, "clapboard", "shingles", "brick", pal, [main, wing], feats)


def archetype_mediterranean(seed: int = 1) -> HouseSpec:
    """Warm stucco, terracotta hip roof, arched openings, wrought-iron balcony, lower side wing."""
    win = WindowStyle(w=0.95, h=1.45, sill=0.9, arch=0.55, mullions=(2, 3), shutters=True, flower_boxes=False)
    main = WingSpec("main", 10.4, 7.4, 2, 3.0, 0, 0, foundation=0.45, wall="wall", roof="hip", pitch=22, overhang=0.7, bay=3.0, window=win,
                    door_side="front", door_w=1.3, door_h=2.2, door_arch=0.6, corner_posts=False, belt=True)
    side = WingSpec("side", 4.8, 6.0, 1, 3.0, -7.4, -0.6, foundation=0.45, wall="wall", roof="flat", overhang=0.3,
                    bay=3.0, window=win, sides=("front", "back", "left"), corner_posts=False)
    pal = _pal(wall="#E6BF86", trim="#FAF1DE", base="#A58C68", roof="#9C3F25", timber="#5A3E2B", door="#2E7C8F", frame="#2E7C8F", shutter="#2E7C8F",
               brick="#B0604A", deck="#B8A07C", metal="#25282C", accent="#2E7C8F", flower="#D8574A")
    feats = [Feature("balcony", "main", "front", x=0.0, w=3.2, depth=1.0, floor=1),
             Feature("chimney", "main", "right", x=0.0, w=0.9, depth=0.8, height=0.8, mode="interior"),
             Feature("shrubs", "main", "front", x=-3.4, w=2.2, depth=0.6), Feature("shrubs", "main", "front", x=3.4, w=2.2, depth=0.6)]
    return HouseSpec("Villa Mediterrânea", "mediterranean", seed, 0.1, "stucco", "tiles", "cobble", pal, [main, side], feats)


def archetype_nordic(seed: int = 1) -> HouseSpec:
    """Falu-red clapboard cabin: steep gable, white trim, covered deck, dormer, stone chimney."""
    win = WindowStyle(w=0.9, h=1.3, sill=0.85, mullions=(2, 2), shutters=False)
    main = WingSpec("main", 8.4, 6.2, 2, 2.6, 0, 0, foundation=0.5, wall="wall", roof="gable", ridge="x", pitch=38, overhang=0.55, rake=0.45,
                    bay=2.8, window=win, door_side="front", door_w=1.1, door_h=2.1, belt=False, corner_posts=True)
    pal = _pal(wall="#9E352E", trim="#F3EEE4", base="#625E58", roof="#2E3238", timber="#6B4A32", door="#27424F", frame="#F3EEE4", shutter="#F3EEE4",
               brick="#7A6A5C", deck="#9A7A55", metal="#2E3236", accent="#27424F", flower="#E6B84A")
    feats = [Feature("porch", "main", "front", x=0.0, w=6.4, depth=1.9, style="shed", height=2.45, rail=True),
             Feature("chimney", "main", "right", x=0.0, w=1.0, depth=0.85, height=0.8, mode="exterior"),
             Feature("dormer", "main", "back", x=0.0, w=2.0),
             Feature("shrubs", "main", "right", x=1.6, w=2.0, depth=0.55), Feature("shrubs", "main", "front", x=-3.9, w=1.4, depth=0.6)]
    return HouseSpec("Cabana Nórdica", "nordic_cabin", seed, 0.1, "clapboard", "shingles", "cobble", pal, [main], feats)


def archetype_modern(seed: int = 1) -> HouseSpec:
    """Stacked boxes with flat roofs, large glazing, warm wood cladding, entrance canopy and a garage volume."""
    big = WindowStyle(w=2.7, h=1.85, sill=0.55, mullions=(2, 1), casing=False, lit_prob=0.2)
    main = WingSpec("main", 9.0, 6.4, 2, 3.0, 1.0, -0.2, foundation=0.4, wall="wall", roof="flat", overhang=0.5, slab="frame", bay=3.4, window=big,
                    door_side="front", door_w=1.3, door_h=2.4, corner_posts=False, back_overhang=True)
    low = WingSpec("low", 6.0, 5.2, 1, 3.0, -6.4, 1.2, foundation=0.4, wall="wall2", roof="flat", overhang=0.5, slab="frame", bay=3.4, window=big,
                   door_side="front", door_w=1.2, door_h=2.3, garage=True, corner_posts=False)
    pal = _pal(wall="#E9E6DF", wall2="#7B5333", trim="#D4D1C9", base="#7F7E7A", roof="#34373C", timber="#7B5333", door="#2D3136", frame="#2D3136",
               shutter="#2D3136", brick="#8A8985", deck="#7B5333", metal="#2D3136", accent="#9C6B42", flower="#D8574A")
    feats = [Feature("panel", "main", "front", x=-3.0, w=1.7, depth=0.16),
             Feature("porch", "main", "front", x=0.0, w=2.8, depth=1.7, style="shed", pitch=3, height=2.75, rail=False, posts=False),
             Feature("balcony", "main", "front", x=2.6, w=2.2, depth=1.0, floor=1),
             Feature("shrubs", "main", "front", x=3.0, w=2.4, depth=0.7)]
    return HouseSpec("Casa Moderna", "modern", seed, 0.08, "stucco", "plaster", "plaster", pal, [main, low], feats, wall2_kind="planks")


def archetype_bungalow(seed: int = 1) -> HouseSpec:
    """Single-storey stucco bungalow with a gabled entry bay, charcoal roof, black-framed windows and a wood-clad end bay (reference image)."""
    win = WindowStyle(w=1.9, h=1.25, sill=0.9, mullions=(2, 1), casing=False, lit_prob=0.0)
    main = WingSpec("main", 9.4, 6.0, 1, 2.9, 0, 0, foundation=0.15, pad=0.15, wall="wall", roof="gable", ridge="x", pitch=22, overhang=0.6, rake=0.45,
                    bay=3.8, window=win, corner_posts=False, gable_window=False, skip={"front": [(-3.8, -0.1)]})
    entry = WingSpec("entry", 3.4, 2.6, 1, 2.9, -2.0, 3.2, foundation=0.15, pad=0.15, wall="wall", roof="gable", ridge="z", pitch=22, overhang=0.5,
                     rake=0.45, bay=3.0, window=WindowStyle(w=0.5, h=1.7, sill=0.5, mullions=(1, 3), casing=False, lit_prob=0.0),
                     door_side="front", door_w=1.15, door_h=2.2, sides=("front", "left", "right"), corner_posts=False, gable_window=False,
                     hide_end="b", no_windows=("front", "left", "right"))
    pal = _pal(wall="#F3E6CC", wall2="#C99A55", trim="#E9E1D0", base="#B8B5AE", roof="#4B4D54", timber="#C99A55", door="#D9923F", frame="#1F2125",
               shutter="#1F2125", brick="#8A6A55", deck="#C99A55", metal="#1F2125", accent="#D9923F", flower="#D8574A")
    feats = [Feature("panel", "main", "front", x=3.6, w=1.9, depth=0.1),
             Feature("shrubs", "entry", "front", x=-1.3, w=0.9, depth=0.6), Feature("shrubs", "entry", "front", x=1.3, w=0.9, depth=0.6)]
    return HouseSpec("Bangalô Moderno", "bungalow", seed, 0.06, "stucco", "metal", "plaster", pal, [main, entry], feats, wall2_kind="planks", ground=True)


# ---------------------------------------------------------------------------------------------------------------------------
# The six houses of the user's reference pack ("01_etapas_por_casa"). Their specs were written by looking at the finished
# image of each house; a vision model is expected to produce the same kind of JSON automatically.
# ---------------------------------------------------------------------------------------------------------------------------
DOOR = "#C27A32"


def archetype_ref01(seed: int = 1) -> HouseSpec:
    """Térrea bege com varanda: bangalô craftsman, empena frontal com óculo, telhado verde, varanda com pilares sobre bases de pedra."""
    win = WindowStyle(w=1.35, h=1.45, sill=0.85, mullions=(3, 2), casing=True, lit_prob=0.0)
    main = WingSpec("main", 8.6, 7.4, 1, 3.0, 0, 0, foundation=0.15, pad=0.15, wall="wall", roof="gable", ridge="z", pitch=31, overhang=0.7, rake=0.55,
                    bay=3.2, window=win, door_side="front", door_w=1.1, door_h=2.2, corner_posts=True, gable_window=True)
    pal = _pal(wall="#E2D2B0", trim="#F1E8D4", base="#BBAA8E", roof="#2D5B4A", timber="#B98C55", door=DOOR, frame="#2A2D32", shutter="#2A2D32",
               brick="#A05A43", deck="#B98C55", metal="#2A2D32", accent=DOOR, flower="#F0E6C8")
    feats = [Feature("porch", "main", "front", x=0.0, w=7.6, depth=2.1, style="shed", pitch=13, height=2.7, rail=False, mode="craftsman"),
             Feature("shrubs", "main", "front", x=-3.2, w=2.0, depth=2.6), Feature("shrubs", "main", "front", x=3.2, w=2.0, depth=2.6),
             Feature("shrubs", "main", "right", x=1.5, w=3.0, depth=0.6)]
    return HouseSpec("Térrea Bege com Varanda", "ref01", seed, 0.06, "clapboard", "metal", "cobble", pal, [main], feats, ground=True)


def archetype_ref02(seed: int = 1) -> HouseSpec:
    """Sobrado azul: tábuas azuis, lateral ocre, telhado de quatro águas escuro, pórtico com empena e pilares."""
    win = WindowStyle(w=1.7, h=1.5, sill=0.8, mullions=(3, 2), casing=True, lit_prob=0.0)
    main = WingSpec("main", 8.0, 7.0, 2, 2.9, 0, 0, foundation=0.15, pad=0.15, wall="wall", roof="hip", pitch=27, overhang=0.6, bay=3.3, window=win,
                    door_side="front", door_w=1.1, door_h=2.2, door_x=0.2, corner_posts=True, side_wall={"right": "wall2", "back": "wall2"})
    pal = _pal(wall="#5E7798", wall2="#D6A25E", trim="#EEE4CE", base="#BDB5A5", roof="#3A3D43", timber="#B98C55", door=DOOR, frame="#2A2D32",
               shutter="#2A2D32", brick="#A05A43", deck="#B98C55", metal="#2A2D32", accent=DOOR, flower="#D96AA0")
    feats = [Feature("porch", "main", "front", x=0.2, w=2.7, depth=1.7, style="gable", height=2.7, rail=False, mode="craftsman"),
             Feature("shrubs", "main", "front", x=-3.0, w=2.0, depth=0.7), Feature("shrubs", "main", "front", x=3.0, w=1.6, depth=0.7)]
    return HouseSpec("Sobrado Azul", "ref02", seed, 0.06, "clapboard", "shingles", "cobble", pal, [main], feats, ground=True)


def archetype_ref03(seed: int = 1) -> HouseSpec:
    """Casa amarela em meios níveis: bloco alto de tábuas amarelas sobre tijolo, ala baixa de quatro águas, janelas horizontais."""
    hz = WindowStyle(w=2.2, h=1.1, sill=1.0, mullions=(3, 1), casing=True, lit_prob=0.0)
    main = WingSpec("main", 6.0, 6.2, 2, 2.9, -2.4, 0, foundation=0.15, pad=0.15, wall="wall", wall_lower="wall2", lower_h=2.9, roof="gable", ridge="z",
                    pitch=30, overhang=0.6, rake=0.45, bay=3.2, window=hz, corner_posts=False, gable_window=False, sides=("front", "left", "back", "right"))
    low = WingSpec("low", 5.6, 5.2, 2, 1.7, 3.2, 0.6, foundation=0.15, pad=0.15, wall="wall", wall_lower="wall2", lower_h=1.7, roof="hip", pitch=24,
                   overhang=0.6, bay=3.0, window=WindowStyle(w=1.9, h=0.9, sill=0.6, mullions=(2, 1), casing=True, lit_prob=0.0),
                   door_side="front", door_w=1.05, door_h=2.1, door_x=-1.6, corner_posts=False, sides=("front", "right", "back"))
    pal = _pal(wall="#D9A85F", wall2="#A5503E", trim="#EEE4CE", base="#BDB5A5", roof="#3A3D43", timber="#B98C55", door=DOOR, frame="#2A2D32",
               shutter="#2A2D32", brick="#A05A43", deck="#B98C55", metal="#2A2D32", accent=DOOR, flower="#D96AA0")
    feats = [Feature("shrubs", "main", "front", x=-1.8, w=2.4, depth=0.7), Feature("shrubs", "low", "front", x=1.4, w=2.0, depth=0.7)]
    return HouseSpec("Casa Amarela Meios Níveis", "ref03", seed, 0.06, "clapboard", "shingles", "plaster", pal, [main, low], feats, wall2_kind="brick", ground=True)


def archetype_ref04(seed: int = 1) -> HouseSpec:
    """Casa moderna de telhado inclinado: reboco bege, telhado de uma água em chapa, grandes janelas pretas, varanda com pilares de madeira."""
    big = WindowStyle(w=3.2, h=1.7, sill=0.75, mullions=(4, 2), casing=False, lit_prob=0.0)
    main = WingSpec("main", 8.6, 6.4, 1, 3.0, 0, 0, foundation=0.15, pad=0.15, wall="wall", roof="shed", shed_high="-x", pitch=13, overhang=0.55,
                    bay=3.4, window=big, door_side="front", door_w=1.1, door_h=2.25, door_x=-2.6, corner_posts=False)
    pal = _pal(wall="#CBBEA6", wall2="#D1892F", trim="#CBBEA6", base="#BBB6AB", roof="#4A5160", timber="#D1892F", door=DOOR, frame="#1F2125",
               shutter="#1F2125", brick="#8A6A55", deck="#B98C55", metal="#1F2125", accent=DOOR, flower="#C9A0D8")
    feats = [Feature("porch", "main", "front", x=-2.9, w=3.2, depth=1.9, style="shed", pitch=7, height=2.6, rail=False, mode="trim"),
             Feature("panel", "main", "front", x=-2.9, w=3.2, depth=0.1, y=0.0, height=2.5),
             Feature("shrubs", "main", "front", x=-0.2, w=1.4, depth=0.7), Feature("shrubs", "main", "front", x=2.6, w=3.4, depth=0.7)]
    return HouseSpec("Casa Moderna Telhado Inclinado", "ref04", seed, 0.05, "stucco", "metal", "plaster", pal, [main], feats, wall2_kind="planks", ground=True)


def archetype_ref05(seed: int = 1) -> HouseSpec:
    """Sobrado de tijolo aparente: tijolos, telhado de quatro águas escuro, janela em bay, pórtico com empena e pilares claros."""
    win = WindowStyle(w=1.5, h=1.5, sill=0.8, mullions=(2, 3), casing=True, lit_prob=0.0)
    main = WingSpec("main", 8.8, 7.0, 2, 2.9, 0, 0, foundation=0.15, pad=0.15, wall="wall", roof="hip", pitch=27, overhang=0.55, bay=3.0, window=win,
                    door_side="front", door_w=1.1, door_h=2.2, door_x=1.7, corner_posts=False, skip_ground={"front": [(-4.4, -0.8)]})
    bay = WingSpec("bay", 3.0, 1.1, 1, 2.6, -2.7, 4.0, foundation=0.15, pad=0.15, wall="wall", roof="shed", shed_high="-z", pitch=18, overhang=0.3,
                   window=WindowStyle(w=2.0, h=1.5, sill=0.55, mullions=(3, 2), casing=True, lit_prob=0.0), sides=("front", "left", "right"),
                   corner_posts=False, no_windows=("left", "right"))
    pal = _pal(wall="#A9503C", trim="#EEE4CE", base="#C9C2B2", roof="#33363C", timber="#B98C55", door=DOOR, frame="#2A2D32", shutter="#2A2D32",
               brick="#A9503C", deck="#B98C55", metal="#2A2D32", accent=DOOR, flower="#F0E6C8")
    feats = [Feature("porch", "main", "front", x=1.7, w=2.4, depth=1.6, style="gable", height=2.7, rail=False, mode="craftsman"),
             Feature("shrubs", "main", "front", x=-1.0, w=1.2, depth=0.7), Feature("shrubs", "main", "front", x=3.7, w=1.6, depth=0.7)]
    return HouseSpec("Sobrado Tijolo Aparente", "ref05", seed, 0.05, "brick", "shingles", "plaster", pal, [main, bay], feats, ground=True)


def archetype_ref06(seed: int = 1) -> HouseSpec:
    """Sobrado verde com garagem: tábuas verde-sálvia, empena frontal, varanda com guarda-corpo, garagem lateral."""
    win = WindowStyle(w=1.45, h=1.45, sill=0.8, mullions=(2, 2), casing=True, lit_prob=0.0)
    main = WingSpec("main", 6.2, 6.6, 2, 2.8, -1.6, 0, foundation=0.15, pad=0.15, wall="wall", roof="gable", ridge="z", pitch=32, overhang=0.6, rake=0.5,
                    bay=3.0, window=win, door_side="front", door_w=1.05, door_h=2.2, corner_posts=True, gable_window=False)
    gar = WingSpec("garage", 3.8, 5.6, 1, 2.8, 3.4, 0.5, foundation=0.15, pad=0.15, wall="wall", roof="gable", ridge="x", pitch=26, overhang=0.55,
                   window=win, door_side="front", garage=True, corner_posts=True, sides=("front", "back", "right"), hide_end="a", gable_window=False)
    pal = _pal(wall="#9DAD8E", trim="#EEE4CE", base="#BDB5A5", roof="#3A3D43", timber="#EEE4CE", door=DOOR, frame="#2A2D32", shutter="#2A2D32",
               brick="#A05A43", deck="#B98C55", metal="#2A2D32", accent=DOOR, flower="#F0E6C8")
    feats = [Feature("porch", "main", "front", x=-1.6, w=5.6, depth=2.0, style="shed", pitch=12, height=2.55, rail=True, mode="trim"),
             Feature("shrubs", "main", "front", x=-4.0, w=1.2, depth=2.5), Feature("shrubs", "garage", "front", x=-1.2, w=1.2, depth=0.7)]
    return HouseSpec("Sobrado Verde com Garagem", "ref06", seed, 0.05, "clapboard", "shingles", "plaster", pal, [main, gar], feats, ground=True)


def archetype_ref_tower(seed: int = 1) -> HouseSpec:
    """Residential tower (user reference): beige facade, olive-framed balcony column, central glass strip, olive pilasters, storefront
    ground floor with an entrance canopy, rooftop penthouse and equipment screen."""
    upper = WindowStyle(w=1.35, h=1.75, sill=0.65, mullions=(2, 1), casing=False, lit_prob=0.0, lite=True)
    shop = WindowStyle(w=3.0, h=3.1, sill=0.35, mullions=(3, 1), casing=False, lit_prob=0.0, lite=True)
    floors, gfh, fh, fnd = 19, 4.6, 3.1, 0.3
    top = fnd + gfh + (floors - 1) * fh
    main = WingSpec("main", 22.0, 16.0, floors, fh, 0, 0, foundation=fnd, pad=0.0, wall="wall", roof="flat", overhang=0.15, bay=2.2, window=upper,
                    ground_fh=gfh, ground_window=shop, door_side="front", door_w=2.6, door_h=3.3, door_x=-1.0, corner_posts=False, belt=False,
                    skip={"front": [(-10.2, -3.6)]})
    balc_windows = WingSpec("balc", 6.2, 0.2, floors, fh, -6.9, 8.0 - 0.1, foundation=fnd, wall="wall", roof="none", window=WindowStyle(
        w=1.4, h=2.3, sill=0.15, mullions=(3, 1), casing=False, lit_prob=0.0, lite=True), bay=1.9, ground_fh=gfh, ground_window=shop, sides=("front",),
        corner_posts=False, no_windows=())
    pent = WingSpec("pent", 6.0, 6.0, 1, 3.4, -6.5, -1.5, y0=top + 0.22, foundation=0.0, wall="wall", roof="flat", overhang=0.25,
                    window=WindowStyle(w=1.6, h=1.9, sill=0.6, mullions=(3, 1), casing=False, lit_prob=0.0, lite=True), bay=1.9, corner_posts=False)
    pal = _pal(wall="#E8D1AC", trim="#EFE1C6", base="#D5BE98", roof="#8A8A86", accent="#878B55", door="#3A3E44", frame="#3A3E44", shutter="#3A3E44",
               metal="#44484E", glass="#566069", timber="#878B55", brick="#A05A43", deck="#B98C55", flower="#F0E6C8")
    feats = [Feature("balcony_stack", "main", "front", x=-6.9, w=5.8, depth=1.25, floor=1),
             Feature("pilaster", "main", "front", x=-10.0, w=0.55, depth=0.35, floor=1), Feature("pilaster", "main", "front", x=-3.8, w=0.55, depth=0.35, floor=1),
             Feature("glass_strip", "main", "front", x=-0.9, w=4.6, floor=1),
             Feature("pilaster", "main", "front", x=4.1, w=0.45, depth=0.18, floor=1), Feature("pilaster", "main", "front", x=6.3, w=0.45, depth=0.18, floor=1),
             Feature("pilaster", "main", "right", x=-2.6, w=0.45, depth=0.18, floor=1), Feature("pilaster", "main", "right", x=2.6, w=0.45, depth=0.18, floor=1),
             Feature("canopy", "main", "front", x=-0.9, w=5.6, depth=2.3, height=3.9),
             Feature("roof_screen", "main", "front", x=4.5, w=10.0, depth=6.0, y=1.0, height=1.5)]
    spec = HouseSpec("Torre residencial", "ref_tower", seed, 0.03, "stucco", "plaster", "plaster", pal, [main, pent], feats)
    _ = balc_windows  # kept as a documented alternative; the balcony column uses the main wing's windows
    return spec


ARCHETYPES = {
    "tudor_cottage": archetype_tudor_cottage,
    "colonial": archetype_colonial,
    "mediterranean": archetype_mediterranean,
    "nordic_cabin": archetype_nordic,
    "modern": archetype_modern,
    "bungalow": archetype_bungalow,
    "ref01": archetype_ref01,
    "ref02": archetype_ref02,
    "ref03": archetype_ref03,
    "ref04": archetype_ref04,
    "ref05": archetype_ref05,
    "ref06": archetype_ref06,
    "ref_tower": archetype_ref_tower,
}


def generate_house(spec: HouseSpec | dict[str, Any], stage: int = 6) -> GeneratedBuilding:
    """Build the house at a construction stage: 1 terrain, 2 slab, 3 framing, 4 walls + half roof, 5 finished, 6 landscaped."""
    if isinstance(spec, dict):
        spec = HouseSpec.from_dict(spec)
    return HouseBuilder(spec, stage).build()
