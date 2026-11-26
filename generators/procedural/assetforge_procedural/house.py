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
            if isinstance(w.get("window"), dict):
                wd = dict(w["window"])
                if "mullions" in wd:
                    wd["mullions"] = tuple(wd["mullions"])
                w["window"] = build(WindowStyle, wd)
            if "sides" in w:
                w["sides"] = tuple(w["sides"])
            if "skip" in w:
                w["skip"] = {k: [tuple(p) for p in v] for k, v in w["skip"].items()}
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
            if not (2.5 <= w.w <= 40 and 2.5 <= w.d <= 40):
                raise ValueError(f"wing {w.name}: width/depth must be 2.5..40 m")
            if not 1 <= w.floors <= 6 or not 2.2 <= w.fh <= 5:
                raise ValueError(f"wing {w.name}: floors 1..6 and floor height 2.2..5 m")
            if w.roof not in ROOFS or w.ridge not in ("x", "z") or not 8 <= w.pitch <= 65:
                raise ValueError(f"wing {w.name}: invalid roof")
            if any(s not in SIDES for s in w.sides):
                raise ValueError(f"wing {w.name}: invalid side")
        for f in self.features:
            if f.wing not in names:
                raise ValueError(f"feature {f.type}: unknown wing {f.wing!r}")
            if f.type not in ("porch", "portico", "chimney", "dormer", "balcony", "panel", "shrubs"):
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

    def _top(self, w: WingSpec) -> float:
        return w.y0 + w.foundation + w.floors * w.fh

    # ------------------------------------------------------------------ layout
    def _layout(self, w: WingSpec, side: str, length: float) -> list[Opening]:
        st = w.window
        ops: list[Opening] = []
        fnd = w.y0 + w.foundation
        margin = max(1.0, st.w * 0.9)
        has_door = w.door_side == side
        span = length - 2 * margin
        n = max(1, round(span / w.bay))
        if has_door and not w.garage and n % 2 == 0:
            n = n + 1 if span / (n + 1) >= st.w + 0.45 else max(1, n - 1)
        while n > 1 and span / n < st.w + 0.45:
            n -= 1
        centres = [-length / 2 + margin + span * (i + 0.5) / n for i in range(n)] if n > 1 or span > 0 else [0.0]
        skip = w.skip.get(side, [])
        ww = min(st.w, (span / n) * 0.62 if n else st.w)
        for f in range(w.floors):
            y_fl = fnd + f * w.fh
            for i, cx in enumerate(centres):
                if any(a - ww / 2 - 0.2 <= cx <= b + ww / 2 + 0.2 for a, b in skip):
                    continue
                is_door = has_door and f == 0 and (i == n // 2)
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
                rise = st.arch * ww / 2
                y0 = y_fl + st.sill
                ops.append(Opening(cx, ww, y0, y0 + st.h + rise, "window", arch=st.arch, shutters=st.shutters,
                                   flower_box=st.flower_boxes and f == 0 and not (has_door and abs(cx) < 1.0),
                                   mullions=st.mullions, lit=bool(self.rng.random() < st.lit_prob), casing=st.casing))
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
            for f in self.s.features:
                if f.type != "shrubs" or st >= 6:
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
            C.wall_with_openings(mb, w.wall, -L / 2, L / 2, fnd - 0.02, top, ops, reveal, w.wall)
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
                    C.belt_course(mb, "trim", -L / 2 - 0.04, L / 2 + 0.04, fnd + f * w.fh)
            if w.corner_posts:
                for x in (-L / 2, L / 2):
                    C.corner_post(mb, "trim" if not w.timber else "timber", x, fnd, top - 0.12, 0.24 if w.timber else 0.2)
            if w.timber:
                C.timber_frame(mb, "timber", -L / 2 + 0.1, L / 2 - 0.1, fnd, top - 0.12, ops, [fnd + f * w.fh for f in range(1, w.floors)])

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
                self.ridge_y[w.name] = C.shed_roof(mb, m, -w.w / 2, w.w / 2, -w.d / 2, w.d / 2, top, w.pitch, w.overhang, high_side=w.shed_high)
            elif w.roof == "flat":
                C.flat_roof(mb, m, -w.w / 2, w.w / 2, -w.d / 2, w.d / 2, top, w.overhang, parapet=1, slab=w.slab)
                self.ridge_y[w.name] = top + 0.3

    def _roof_stage(self, w: WingSpec) -> None:
        """Stage 3: bare rafters. Stage 4: one slope shingled, the other still showing rafters and battens. Gable roofs only."""
        mb, m = self.mb, self.m
        if w.roof != "gable":
            return
        top = self._top(w)
        stage3 = self.stage == 3
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

    # ------------------------------------------------------------------ ground / pads / landscaping
    def _extent(self) -> tuple[float, float, float, float]:
        xs0 = min(w.cx - w.w / 2 for w in self.s.wings)
        xs1 = max(w.cx + w.w / 2 for w in self.s.wings)
        zs0 = min(w.cz - w.d / 2 for w in self.s.wings)
        zs1 = max(w.cz + w.d / 2 for w in self.s.wings)
        return xs0, xs1, zs0, zs1

    def _ground(self) -> None:
        x0, x1, z0, z1 = self._extent()
        mg = self.s.ground_margin
        C.bbox(self.mb, "soil", (x0 - mg, -0.4, z0 - mg), (x1 + mg, 0.0, z1 + mg), 0.04, faces=("+x", "-x", "+z", "-z", "+y", "-y"))
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
        x0, x1, z0, z1 = self._extent()
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
            posts = [x0 + 0.13, x1 - 0.13]
            if f.w > 4.6:
                posts.insert(1, f.x)
            for px in posts if f.posts else []:
                if f.columns:
                    C.column(mb, m, px, f.depth - 0.18, fnd, fnd + ph, 0.12)
                else:
                    C.post(mb, "timber", px, f.depth - 0.13, fnd, fnd + ph, 0.17)
            if f.rail:
                gap = min(f.w * 0.42, 1.7) if f.style != "open" else f.w
                for a, b in ((x0 + 0.1, f.x - gap / 2), (f.x + gap / 2, x1 - 0.1)):
                    if b - a > 0.3:
                        C.railing(mb, m, a, b, f.depth - 0.13, fnd, 0.9, 0.2, iron=False)
                for sx in (x0 + 0.13, x1 - 0.13):
                    pass
            y_roof = fnd + ph
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
        y = w.y0 + w.foundation + f.floor * w.fh
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
        y1 = y0 + (f.height or w.floors * w.fh - 0.14)  # stop just under the eave so it never pokes through the roof slab
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


ARCHETYPES = {
    "tudor_cottage": archetype_tudor_cottage,
    "colonial": archetype_colonial,
    "mediterranean": archetype_mediterranean,
    "nordic_cabin": archetype_nordic,
    "modern": archetype_modern,
    "bungalow": archetype_bungalow,
}


def generate_house(spec: HouseSpec | dict[str, Any], stage: int = 6) -> GeneratedBuilding:
    """Build the house at a construction stage: 1 terrain, 2 slab, 3 framing, 4 walls + half roof, 5 finished, 6 landscaped."""
    if isinstance(spec, dict):
        spec = HouseSpec.from_dict(spec)
    return HouseBuilder(spec, stage).build()
