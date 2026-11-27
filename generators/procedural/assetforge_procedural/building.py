"""Parametric modular building generator (houses, towers, civic and industrial buildings).

Geometry is composed from modular pieces: wall panels with real openings (reveals, frames, sills,
lintels), balconies, awnings, plinths, cornices, roofs and category features. Everything is deterministic
for a given (params, seed). Output is a MeshSpec in meters, Y-up, pivot bottom-center, front = +Z.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from assetforge_contract import BuildingParams

from .materials import (
    ART_PROFILE_ID,
    CURTAIN_COLORS,
    MaterialDef,
    build_materials,
    pick_palette,
)
from .mesh import MeshBuilder, MeshSpec

GENERATOR_ID = "procedural.building"
GENERATOR_VERSION = "0.1.0"

PLINTH = 0.35  # height of the base plinth = first floor level
REVEAL = 0.12  # depth of window/door reveals


@dataclass(frozen=True)
class Preset:
    width: tuple[float, float]
    depth: tuple[float, float]
    floors: tuple[int, int]
    floor_height: float
    roofs: tuple[str, ...]
    bay: tuple[float, float]
    ground: str  # door | storefront | lobby | garage_bays | columns | docks
    facade: str  # punched | curtain | clad
    balconies: bool = False
    bands: bool = False
    features: frozenset[str] = frozenset()


PRESETS: dict[str, Preset] = {
    "house": Preset((8, 12), (8, 11), (1, 2), 2.9, ("gable", "hip"), (2.8, 3.4), "door", "punched",
                    features=frozenset({"chimney", "porch"})),
    "apartment": Preset((16, 26), (11, 16), (4, 7), 3.0, ("flat",), (3.0, 3.8), "door", "punched",
                        balconies=True, bands=True, features=frozenset({"rooftop", "canopy"})),
    "commercial": Preset((14, 24), (12, 18), (3, 6), 3.5, ("flat",), (3.4, 4.4), "storefront", "punched",
                         bands=True, features=frozenset({"rooftop", "sign"})),
    "skyscraper": Preset((22, 34), (22, 34), (24, 40), 3.6, ("flat",), (3.0, 3.6), "lobby", "curtain",
                         features=frozenset({"podium", "crown", "antenna"})),
    "industrial": Preset((26, 40), (18, 26), (1, 1), 7.5, ("sawtooth",), (6.0, 8.0), "docks", "clad",
                         features=frozenset({"stack", "tanks"})),
    "hospital": Preset((30, 44), (14, 20), (4, 5), 3.6, ("flat",), (3.4, 4.0), "lobby", "punched",
                       bands=True, features=frozenset({"cross", "helipad", "canopy", "rooftop"})),
    "school": Preset((28, 40), (12, 16), (2, 3), 3.5, ("hip", "flat"), (3.2, 4.0), "door", "punched",
                     bands=True, features=frozenset({"pediment", "flagpole", "clock", "canopy"})),
    "university": Preset((34, 50), (16, 22), (3, 4), 3.8, ("flat", "hip"), (3.4, 4.2), "columns", "punched",
                         bands=True, features=frozenset({"pediment", "clock_tower", "flagpole"})),
    "police": Preset((16, 22), (12, 16), (2, 3), 3.5, ("flat",), (3.2, 4.0), "door", "punched",
                     bands=True, features=frozenset({"police_sign", "canopy", "antenna"})),
    "fire_station": Preset((20, 28), (14, 18), (2, 2), 3.8, ("flat", "hip"), (4.0, 5.0), "garage_bays", "punched",
                           features=frozenset({"tower", "rooftop"})),
    "transport_station": Preset((30, 50), (12, 16), (2, 2), 4.0, ("flat",), (3.6, 4.6), "lobby", "punched",
                                bands=True, features=frozenset({"platform"})),
    "warehouse": Preset((30, 50), (20, 30), (1, 1), 8.0, ("gable",), (6.0, 9.0), "docks", "clad",
                        features=frozenset({"tanks"})),
    "government": Preset((26, 38), (16, 22), (3, 3), 4.0, ("flat", "hip"), (3.6, 4.4), "columns", "punched",
                         bands=True, features=frozenset({"pediment", "flagpole", "stairs"})),
}


@dataclass
class Volume:
    """A rectangular block of the building. ``cx``/``cz`` are center offsets in the building frame."""

    width: float
    depth: float
    y0: float
    floors: int
    floor_height: float
    cx: float = 0.0
    cz: float = 0.0
    facade: str = "punched"
    sides: tuple[str, ...] = ("front", "back", "right", "left")
    ground: str | None = None  # ground-floor treatment on the front side
    roof: str | None = None
    wall_mat: str = "wall"

    @property
    def height(self) -> float:
        return self.floors * self.floor_height

    @property
    def top(self) -> float:
        return self.y0 + self.height


@dataclass
class GeneratedBuilding:
    mesh: MeshSpec
    materials: dict[str, MaterialDef]
    dimensions: tuple[float, float, float]
    connection_points: list[dict]
    summary: dict = field(default_factory=dict)


class BuildingGenerator:
    def __init__(self, params: BuildingParams) -> None:
        self.p = params
        self.rng = np.random.default_rng(params.seed)
        self.preset = PRESETS[params.category]
        self.mb = MeshBuilder()
        self.points: list[dict] = []
        self.palette_name, palette = pick_palette(params.style, params.palette, self.rng)
        curtain = CURTAIN_COLORS[int(self.rng.integers(len(CURTAIN_COLORS)))]
        self.mats = build_materials(palette, params.wear, curtain)
        self._resolve()

    # ------------------------------------------------------------------ planning
    def _uni(self, lo: float, hi: float, step: float = 0.5) -> float:
        return float(round(self.rng.uniform(lo, hi) / step) * step)

    def _resolve(self) -> None:
        pr, p = self.preset, self.p
        self.W = p.width or self._uni(*pr.width)
        self.D = p.depth or self._uni(*pr.depth)
        self.floors = p.floors or int(self.rng.integers(pr.floors[0], pr.floors[1] + 1))
        self.fh = p.floor_height or pr.floor_height
        self.roof = p.roof or str(self.rng.choice(pr.roofs))
        if p.category == "house" and p.style == "modern" and p.roof is None:
            self.roof = "flat"
        if p.category == "house" and p.style == "nordic" and p.roof is None:
            self.roof = "gable"
        bay = p.bay_width or self._uni(*pr.bay, 0.1)
        self.bay_w = bay
        self.balconies = pr.balconies if p.balconies is None else p.balconies
        self.garage = (p.category == "house" and bool(self.rng.random() < 0.5)) if p.garage is None else p.garage
        self.pitch = {"mediterranean": 24.0, "nordic": 38.0}.get(p.style, 32.0) + float(self.rng.uniform(-3, 3))
        brick_palette = self.palette_name.startswith("brick")
        if pr.facade == "clad":
            self.wall_mat = "cladding"
        elif brick_palette and p.category in ("house", "apartment", "school", "commercial", "police", "university"):
            self.wall_mat = "brick"
        else:
            self.wall_mat = "wall"

    # ------------------------------------------------------------------ public
    def generate(self) -> GeneratedBuilding:
        p = self.p
        vols = self._volumes()
        for v in vols:
            self._volume(v)
        self._features(vols)
        spec = self.mb.build()
        # Normalise pivot: bottom center of the bounding box footprint.
        lo, hi = spec.bounds()
        shift = np.array([-(lo[0] + hi[0]) / 2, -lo[1], -(lo[2] + hi[2]) / 2], dtype=np.float32)
        for part in spec.parts.values():
            part.vertices = (part.vertices + shift).astype(np.float32)
        for cp in self.points:
            cp["position"] = tuple(float(c) for c in (np.asarray(cp["position"]) + shift))
        lo, hi = spec.bounds()
        used = {m: self.mats[m] for m in spec.parts}
        dims = tuple(float(x) for x in (hi - lo))
        return GeneratedBuilding(
            mesh=spec, materials=used, dimensions=dims,  # type: ignore[arg-type]
            connection_points=self.points,
            summary=dict(category=p.category, style=p.style, palette=self.palette_name, floors=self.floors,
                         roof=self.roof, width=self.W, depth=self.D, floor_height=self.fh,
                         art_profile=ART_PROFILE_ID, seed=p.seed, balconies=self.balconies, garage=self.garage),
        )

    # ------------------------------------------------------------------ volumes
    def _volumes(self) -> list[Volume]:
        pr, W, D = self.preset, self.W, self.D
        cat = self.p.category
        facade = pr.facade
        if cat == "skyscraper":
            pod_floors = 3
            ph = pod_floors * 3.8
            inset = 0.1
            tw, td = W * (1 - inset), D * (1 - inset)
            vols = [
                Volume(W, D, PLINTH, pod_floors, 3.8, facade="punched", ground="lobby", roof="flat",
                       wall_mat="wall"),
                Volume(tw, td, PLINTH + ph, self.floors, self.fh, facade="curtain", roof="flat"),
            ]
            return vols
        main = Volume(W, D, PLINTH, self.floors, self.fh, facade=facade, ground=pr.ground, roof=self.roof,
                      wall_mat=self.wall_mat)
        vols = [main]
        if cat == "house" and self.garage:
            gw = 3.4
            vols.append(Volume(gw, D * 0.7, PLINTH, 1, 2.8, cx=-(W / 2 + gw / 2), cz=D / 2 - D * 0.35,
                               facade="punched", ground="garage", roof="flat", wall_mat=self.wall_mat,
                               sides=("front", "back", "left")))
        if cat == "fire_station" and "tower" in pr.features:
            tw = 6.0
            vols.append(Volume(tw, tw, PLINTH, 5, 3.6, cx=W / 2 - tw / 2 - 1.0, cz=-D / 2 + tw / 2 - 0.0 + 0.001,
                               facade="punched", roof="hip", wall_mat=self.wall_mat))
        if cat == "university":
            tw = 7.0
            vols.append(Volume(tw, tw, PLINTH + self.floors * self.fh, 2, 3.4, cx=0, cz=-D / 4,
                               facade="punched", roof="hip", wall_mat=self.wall_mat))
        return vols

    # ------------------------------------------------------------------ one volume
    def _volume(self, v: Volume) -> None:
        mb = self.mb
        # plinth
        if v.y0 <= PLINTH + 1e-6:
            mb.box("base", (v.cx - v.width / 2 - 0.06, 0, v.cz - v.depth / 2 - 0.06),
                   (v.cx + v.width / 2 + 0.06, v.y0, v.cz + v.depth / 2 + 0.06),
                   faces=tuple(f for f in ("+x", "-x", "+z", "-z", "+y") if self._side_on(v, f)))
        side_defs = {
            "front": (0, (v.cx, 0, v.cz + v.depth / 2), v.width),
            "back": (180, (v.cx, 0, v.cz - v.depth / 2), v.width),
            "right": (90, (v.cx + v.width / 2, 0, v.cz), v.depth),
            "left": (270, (v.cx - v.width / 2, 0, v.cz), v.depth),
        }
        for side in v.sides:
            yaw, off, length = side_defs[side]
            with mb.transform(yaw, off):
                self._facade(v, side, length)
        self._ornament(v)
        self._roof(v)

    @staticmethod
    def _side_on(v: Volume, face: str) -> bool:
        m = {"+z": "front", "-z": "back", "+x": "right", "-x": "left"}
        return face == "+y" or m[face] in v.sides

    def _ornament(self, v: Volume) -> None:
        mb, p = self.mb, self.p
        hx, hz = v.width / 2, v.depth / 2
        top = v.top
        # floor separator bands
        if self.preset.bands and v.facade == "punched" and v.floors > 1:
            for i in range(1, v.floors):
                y = v.y0 + i * v.floor_height
                mb.box("trim", (v.cx - hx - 0.05, y - 0.09, v.cz - hz - 0.05),
                       (v.cx + hx + 0.05, y + 0.09, v.cz + hz + 0.05),
                       faces=tuple(f for f in ("+x", "-x", "+z", "-z") if self._side_on(v, f)) + ("+y", "-y"))
        # cornice (flat/hip/classic) on punched volumes
        if v.roof in ("flat", "hip") and v.facade != "clad":
            o = 0.28 if p.style == "classic" or self.preset.bands else 0.15
            mb.box("trim", (v.cx - hx - o, top - 0.28, v.cz - hz - o), (v.cx + hx + o, top, v.cz + hz + o),
                   faces=("+x", "-x", "+z", "-z", "-y"))
            if v.roof == "flat":
                mb.box("trim", (v.cx - hx - o + 0.06, top, v.cz - hz - o + 0.06),
                       (v.cx + hx + o - 0.06, top + 0.06, v.cz + hz + o - 0.06), faces=("+y",))
        # corner quoins (classic)
        if p.style == "classic" and v.facade == "punched" and v.floors <= 8:
            q = 0.55
            for sx in (-1, 1):
                for sz in (-1, 1):
                    xs = v.cx + sx * hx
                    zs = v.cz + sz * hz
                    lo = (min(xs, xs - sx * q) - (0.04 if sx < 0 else 0), v.y0, min(zs, zs - sz * q) - (0.04 if sz < 0 else 0))
                    hi = (max(xs, xs - sx * q) + (0.04 if sx > 0 else 0), top - 0.28, max(zs, zs - sz * q) + (0.04 if sz > 0 else 0))
                    faces = []
                    faces.append("+x" if sx > 0 else "-x")
                    faces.append("+z" if sz > 0 else "-z")
                    mb.box("trim", lo, hi, faces=tuple(f for f in faces if self._side_on(v, f)))

    # ------------------------------------------------------------------ facades
    def _bay_layout(self, length: float, odd: bool) -> tuple[int, float]:
        n = max(1, round(length / self.bay_w))
        if odd and n % 2 == 0:
            n += 1
        return n, length / n

    def _facade(self, v: Volume, side: str, length: float) -> None:
        """Draw one facade in local frame: x along the wall, wall plane z=0, interior at z<0."""
        if v.facade == "curtain":
            self._curtain(v, length)
            return
        if v.facade == "clad":
            self._clad(v, side, length)
            return
        front = side == "front"
        n, bw = self._bay_layout(length, odd=front)
        centre_bay = n // 2
        for fl in range(v.floors):
            y0 = v.y0 + fl * v.floor_height
            y1 = y0 + v.floor_height
            ops: list[tuple[float, float, float, float, str] | None] = []  # (ox0, ox1, oy0, oy1, kind)
            for i in range(n):
                cx = -length / 2 + bw * (i + 0.5)
                ops.append(self._opening(v, side, fl, i, n, centre_bay, cx, bw, y0, y1))
            self._wall_row(v, -length / 2, length / 2, y0, y1, bw, ops)
            for i, op in enumerate(ops):
                if op is not None:
                    self._dress_opening(v, side, fl, i, n, op, y0, y1)
        if front and v.ground:
            self._front_features(v, length, n, bw)

    def _opening(self, v: Volume, side: str, fl: int, i: int, n: int, centre: int, cx: float, bw: float,
                 y0: float, y1: float) -> tuple[float, float, float, float, str] | None:
        fh = v.floor_height
        style = self.p.style
        ww = bw * {"modern": 0.62, "classic": 0.42, "mediterranean": 0.4, "nordic": 0.44, "industrial": 0.5}[style]
        ww = min(ww, 2.6 if style != "modern" else 3.2)
        wh = fh * (0.55 if style == "modern" else 0.5)
        sill = y0 + fh * 0.3
        if side == "front" and fl == 0 and v.ground:
            g = v.ground
            if g == "door" and i == centre:
                return cx - 0.55, cx + 0.55, y0, y0 + 2.2, "door"
            if g == "lobby" and i == centre:
                w = min(bw * 0.9, 3.6)
                return cx - w / 2, cx + w / 2, y0, y0 + min(fh - 0.6, 3.0), "lobby"
            if g == "columns" and i == centre:
                return cx - 0.9, cx + 0.9, y0, y0 + 2.7, "door"
            if g == "garage":
                return cx - 1.25, cx + 1.25, y0, y0 + 2.2, "garage"
            if g == "garage_bays":
                w = min(bw * 0.72, 3.8)
                return cx - w / 2, cx + w / 2, y0, y0 + 3.2, "bay"
            if g == "storefront":
                if i == centre:
                    return cx - 0.9, cx + 0.9, y0, y0 + 2.4, "shopdoor"
                w = bw * 0.84
                return cx - w / 2, cx + w / 2, y0 + 0.45, y0 + min(fh - 0.9, 2.8), "shopwin"
        if side == "back" and fl == 0 and i == n // 2 and self.p.category in ("house", "apartment", "school"):
            return cx - 0.5, cx + 0.5, y0, y0 + 2.1, "backdoor"
        if side != "front" and self.p.category == "fire_station" and fl == 0:
            return None if i % 2 else (cx - ww / 2, cx + ww / 2, sill, sill + wh, "window")
        # balcony door on upper floors (front only for apartments; side for others rarely)
        if self.balconies and fl >= 1 and side in ("front", "back") and i % 2 == 0 and ww < bw - 0.6:
            w = min(bw * 0.55, 2.0)
            return cx - w / 2, cx + w / 2, y0 + 0.03, y0 + 2.2, "balcony"
        return cx - ww / 2, cx + ww / 2, sill, sill + wh, "window"

    def _wall_row(self, v: Volume, xa: float, xb: float, y0: float, y1: float, bw: float,
                  ops: list) -> None:
        """Emit the wall surface of one floor as large quads with holes for the openings."""
        mb = self.mb
        mat = v.wall_mat
        # group consecutive bays by their vertical extents to merge strips
        i = 0
        n = len(ops)
        while i < n:
            key = None if ops[i] is None else (ops[i][2], ops[i][3])
            j = i
            while j + 1 < n and ((None if ops[j + 1] is None else (ops[j + 1][2], ops[j + 1][3])) == key):
                j += 1
            gx0, gx1 = xa + bw * i, xa + bw * (j + 1)
            if key is None:
                mb.quad(mat, (gx0, y0, 0), (gx1, y0, 0), (gx1, y1, 0), (gx0, y1, 0))
            else:
                oy0, oy1 = key
                if oy0 > y0 + 1e-6:
                    mb.quad(mat, (gx0, y0, 0), (gx1, y0, 0), (gx1, oy0, 0), (gx0, oy0, 0))
                if oy1 < y1 - 1e-6:
                    mb.quad(mat, (gx0, oy1, 0), (gx1, oy1, 0), (gx1, y1, 0), (gx0, y1, 0))
                edge = gx0
                for k in range(i, j + 1):
                    ox0, ox1 = ops[k][0], ops[k][1]
                    if ox0 > edge + 1e-6:
                        mb.quad(mat, (edge, oy0, 0), (ox0, oy0, 0), (ox0, oy1, 0), (edge, oy1, 0))
                    edge = ox1
                if gx1 > edge + 1e-6:
                    mb.quad(mat, (edge, oy0, 0), (gx1, oy0, 0), (gx1, oy1, 0), (edge, oy1, 0))
            i = j + 1

    def _reveals(self, ox0: float, ox1: float, oy0: float, oy1: float, floor: bool = True, depth: float = REVEAL,
                 mat: str | None = None) -> None:
        mb = self.mb
        m = mat or "trim"
        c = ((ox0 + ox1) / 2, (oy0 + oy1) / 2, 0.0)
        # quads facing into the opening
        if floor:
            mb.quad(m, (ox0, oy0, -depth), (ox1, oy0, -depth), (ox1, oy0, 0), (ox0, oy0, 0), outward=(c[0], oy0 - 1, c[2]))
        mb.quad(m, (ox0, oy1, -depth), (ox1, oy1, -depth), (ox1, oy1, 0), (ox0, oy1, 0), outward=(c[0], oy1 + 1, c[2]))
        mb.quad(m, (ox0, oy0, -depth), (ox0, oy1, -depth), (ox0, oy1, 0), (ox0, oy0, 0), outward=(ox0 - 1, c[1], c[2]))
        mb.quad(m, (ox1, oy0, -depth), (ox1, oy1, -depth), (ox1, oy1, 0), (ox1, oy0, 0), outward=(ox1 + 1, c[1], c[2]))

    def _glass(self, x0: float, x1: float, y0: float, y1: float, z: float, lit_p: float = 0.22,
               curtain_p: float = 0.18, force: str | None = None) -> None:
        r = self.rng.random()
        mat = force or ("glass_lit" if r < lit_p else "curtain" if r < lit_p + curtain_p else "glass")
        self.mb.quad(mat, (x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z),
                     uv=[(0, 0), (1, 0), (1, 1), (0, 1)])

    def _dress_opening(self, v: Volume, side: str, fl: int, i: int, n: int, op, y0: float, y1: float) -> None:
        ox0, ox1, oy0, oy1, kind = op
        mb, style, detail = self.mb, self.p.style, self.p.detail
        fw = 0.07
        zf = -REVEAL
        cx = (ox0 + ox1) / 2
        if kind in ("window", "balcony", "shopwin"):
            self._reveals(ox0, ox1, oy0, oy1, floor=kind != "balcony")
            if detail >= 1:
                zb = zf - 0.07
                mb.box("frame", (ox0, oy1 - fw, zb), (ox1, oy1, zf), faces=("+z", "-y"))
                if kind != "balcony":
                    mb.box("frame", (ox0, oy0, zb), (ox1, oy0 + fw, zf), faces=("+z", "+y"))
                mb.box("frame", (ox0, oy0 + (fw if kind != "balcony" else 0), zb), (ox0 + fw, oy1 - fw, zf),
                       faces=("+z", "+x"))
                mb.box("frame", (ox1 - fw, oy0 + (fw if kind != "balcony" else 0), zb), (ox1, oy1 - fw, zf),
                       faces=("+z", "-x"))
                self._glass(ox0 + fw, ox1 - fw, oy0 + (fw if kind != "balcony" else 0), oy1 - fw, zb + 0.02,
                            force="glass" if kind == "shopwin" else None)
                if detail >= 2 or style in ("classic", "nordic", "industrial"):
                    # mullions
                    mb.box("frame", (cx - 0.025, oy0 + fw, zb + 0.01), (cx + 0.025, oy1 - fw, zf + 0.01), faces=("+z",))
                    if style != "modern" and kind == "window":
                        ym = (oy0 + oy1) / 2
                        mb.box("frame", (ox0 + fw, ym - 0.025, zb + 0.01), (ox1 - fw, ym + 0.025, zf + 0.01), faces=("+z",))
            else:
                self._glass(ox0, ox1, oy0, oy1, zf)
            if kind == "window":
                if detail >= 1:  # sill
                    mb.box("trim", (ox0 - 0.08, oy0 - 0.09, 0), (ox1 + 0.08, oy0, 0.1), faces=("+z", "+y", "-y", "+x", "-x"))
                if detail >= 2 and style in ("classic", "mediterranean"):
                    mb.box("trim", (ox0 - 0.12, oy1, 0), (ox1 + 0.12, oy1 + 0.16, 0.1), faces=("+z", "+y", "-y", "+x", "-x"))
                if detail >= 2 and style in ("mediterranean", "nordic") and fl < 3:
                    sw = (ox1 - ox0) * 0.38
                    for sx0 in (ox0 - sw - 0.06, ox1 + 0.06):
                        mb.box("accent", (sx0, oy0, 0), (sx0 + sw, oy1, 0.04), faces=("+z", "+x", "-x"))
            if kind == "balcony":
                self._balcony(ox0, ox1, y0)
            if kind == "shopwin":
                # stall riser below the glass
                mb.box("base", (ox0, y0, 0), (ox1, oy0, 0.04), faces=("+z", "+x", "-x", "+y"))
        elif kind in ("door", "backdoor", "shopdoor", "lobby"):
            self._door(ox0, ox1, oy0, oy1, kind, side)
        elif kind == "garage":
            self._reveals(ox0, ox1, oy0, oy1, floor=False)
            z = -REVEAL
            mb.quad("metal", (ox0, oy0, z), (ox1, oy0, z), (ox1, oy1, z), (ox0, oy1, z))
            for k in range(1, 5):
                y = oy0 + (oy1 - oy0) * k / 5
                mb.box("frame", (ox0, y - 0.015, z), (ox1, y + 0.015, z + 0.03), faces=("+z",))
        elif kind == "bay":
            self._reveals(ox0, ox1, oy0, oy1, floor=False, depth=0.3)
            z = -0.3
            mb.quad("metal", (ox0, oy0, z), (ox1, oy0, z), (ox1, oy1, z), (ox0, oy1, z))
            for k in range(1, 8):
                y = oy0 + (oy1 - oy0) * k / 8
                mb.box("frame", (ox0, y - 0.02, z), (ox1, y + 0.02, z + 0.04), faces=("+z",))
            mb.box("accent", (ox0 - 0.12, oy0, 0), (ox0, oy1 + 0.12, 0.06), faces=("+z", "-x"))
            mb.box("accent", (ox1, oy0, 0), (ox1 + 0.12, oy1 + 0.12, 0.06), faces=("+z", "+x"))
            mb.box("accent", (ox0 - 0.12, oy1, 0), (ox1 + 0.12, oy1 + 0.12, 0.06), faces=("+z", "-y", "+y"))
        if kind == "door" and fl == 0 and side == "front" and not any(c["name"] == "entrance" for c in self.points):
            self._add_point("entrance", v, cx, v.y0, 0.8, side)

    def _add_point(self, name: str, v: Volume, x_local: float, y: float, z_out: float, side: str) -> None:
        # translate local facade coords to building frame (front side only is used for entrances)
        self.points.append({"name": name, "position": (v.cx + x_local, y, v.cz + v.depth / 2 + z_out),
                            "direction": (0.0, 0.0, 1.0)})

    def _door(self, ox0: float, ox1: float, oy0: float, oy1: float, kind: str, side: str) -> None:
        mb, detail = self.mb, self.p.detail
        self._reveals(ox0, ox1, oy0, oy1, floor=False, depth=0.14)
        z = -0.14
        mat = "door"
        if kind in ("lobby", "shopdoor"):
            # glazed double door with frame and mullions
            mb.box("frame", (ox0, oy0, z - 0.05), (ox1, oy1, z), faces=("+z",))
            iw = 0.07
            self._glass(ox0 + iw, (ox0 + ox1) / 2 - 0.03, oy0 + 0.1, oy1 - iw, z + 0.005, force="glass")
            self._glass((ox0 + ox1) / 2 + 0.03, ox1 - iw, oy0 + 0.1, oy1 - iw, z + 0.005, force="glass")
            mb.box("metal", ((ox0 + ox1) / 2 - 0.2, oy0 + 0.9, z), ((ox0 + ox1) / 2 - 0.15, oy0 + 1.2, z + 0.05), faces=("+z",))
            mb.box("metal", ((ox0 + ox1) / 2 + 0.15, oy0 + 0.9, z), ((ox0 + ox1) / 2 + 0.2, oy0 + 1.2, z + 0.05), faces=("+z",))
        else:
            mb.quad(mat, (ox0, oy0, z), (ox1, oy0, z), (ox1, oy1, z), (ox0, oy1, z))
            if detail >= 1:
                mb.box("frame", (ox0, oy1 - 0.08, z - 0.04), (ox1, oy1, z + 0.04), faces=("+z", "-y"))
                mb.box("frame", (ox0, oy0, z - 0.04), (ox0 + 0.08, oy1 - 0.08, z + 0.04), faces=("+z", "+x"))
                mb.box("frame", (ox1 - 0.08, oy0, z - 0.04), (ox1, oy1 - 0.08, z + 0.04), faces=("+z", "-x"))
                w = ox1 - ox0
                for px0 in (ox0 + 0.14, (ox0 + ox1) / 2 + 0.04):
                    mb.box("trim", (px0, oy0 + 0.2, z), (px0 + w / 2 - 0.18, oy0 + 0.85, z + 0.025), faces=("+z",))
                self._glass(ox0 + 0.16, ox1 - 0.16, oy0 + 1.1, oy1 - 0.2, z + 0.01, force="glass")
                mb.box("metal", (ox1 - 0.22, oy0 + 1.0, z), (ox1 - 0.14, oy0 + 1.08, z + 0.08), faces=("+z", "+y"))
        if side == "front" and kind in ("door", "lobby", "shopdoor") and oy0 <= PLINTH + 0.01:
            cx = (ox0 + ox1) / 2
            w = (ox1 - ox0) + 0.8
            mb.box("base", (cx - w / 2, 0, 0), (cx + w / 2, 0.17, 0.9), faces=("+z", "+x", "-x", "+y"))

    def _balcony(self, ox0: float, ox1: float, y0: float) -> None:
        mb, detail = self.mb, self.p.detail
        cx = (ox0 + ox1) / 2
        hw = max((ox1 - ox0) / 2 + 0.45, 1.1)
        depth = 1.25
        mb.box("trim", (cx - hw, y0 - 0.16, 0), (cx + hw, y0 + 0.03, depth), faces=("+z", "+y", "-y", "+x", "-x"))
        top = y0 + 1.0
        # top rail
        mb.box("frame", (cx - hw, top - 0.05, depth - 0.06), (cx + hw, top, depth), faces=("+z", "+y", "-z"))
        mb.box("frame", (cx - hw, top - 0.05, 0), (cx - hw + 0.05, top, depth), faces=("+y", "-x"))
        mb.box("frame", (cx + hw - 0.05, top - 0.05, 0), (cx + hw, top, depth), faces=("+y", "+x"))
        if detail >= 1:
            n = max(4, int((2 * hw) / 0.35))
            for k in range(n + 1):
                x = cx - hw + 0.025 + (2 * hw - 0.05) * k / n
                mb.box("frame", (x - 0.02, y0 + 0.03, depth - 0.05), (x + 0.02, top - 0.05, depth - 0.01), faces=("+z", "+x"))
        else:
            mb.quad("glass", (cx - hw, y0 + 0.1, depth - 0.03), (cx + hw, y0 + 0.1, depth - 0.03),
                    (cx + hw, top - 0.05, depth - 0.03), (cx - hw, top - 0.05, depth - 0.03),
                    uv=[(0, 0), (1, 0), (1, 1), (0, 1)])

    # ------------------------------------------------------------------ front-only dressing
    def _front_features(self, v: Volume, length: float, n: int, bw: float) -> None:
        mb = self.mb
        g = v.ground
        y0 = v.y0
        if g == "storefront":
            band_y0 = y0 + min(v.floor_height - 0.85, 2.8) + 0.05
            mb.box("accent", (-length / 2, band_y0, 0), (length / 2, y0 + v.floor_height - 0.05, 0.12),
                   faces=("+z", "+x", "-x", "-y", "+y"))
            # striped awnings per bay
            for i in range(n):
                if i == n // 2:
                    continue
                cx = -length / 2 + bw * (i + 0.5)
                w = bw * 0.84
                strips = 6
                top_y, low_y, out = band_y0 - 0.05, band_y0 - 0.55, 1.0
                for s in range(strips):
                    xa = cx - w / 2 + w * s / strips
                    xb = cx - w / 2 + w * (s + 1) / strips
                    mat = "awning" if s % 2 == 0 else "awning_b"
                    mb.quad(mat, (xa, top_y, 0), (xb, top_y, 0), (xb, low_y, out), (xa, low_y, out),
                            outward=((xa + xb) / 2, top_y - 1, -1), uv=[(0, 0), (1, 0), (1, 1), (0, 1)])
                    mb.quad(mat, (xa, low_y, out), (xb, low_y, out), (xb, low_y - 0.18, out), (xa, low_y - 0.18, out),
                            outward=((xa + xb) / 2, low_y, -1), uv=[(0, 0), (1, 0), (1, 1), (0, 1)])
        elif g in ("lobby", "door") and "canopy" in self.preset.features and v.floors >= 1:
            cx = 0.0
            w = 5.0 if g == "lobby" else 3.0
            y = y0 + min(3.2, v.floor_height - 0.3)
            mb.box("trim", (cx - w / 2, y, 0), (cx + w / 2, y + 0.18, 2.6), faces=("+z", "+y", "-y", "+x", "-x"))
            for sx in (-1, 1):
                mb.box("metal", (cx + sx * (w / 2 - 0.2) - 0.06, 0, 2.4), (cx + sx * (w / 2 - 0.2) + 0.06, y, 2.52),
                       faces=("+z", "+x", "-x", "-z"))
        elif g == "columns":
            self._portico(v, length)

    def _portico(self, v: Volume, length: float) -> None:
        mb = self.mb
        w = min(length * 0.45, 16.0)
        depth = 3.2
        y0 = v.y0
        h = min(v.floor_height * 2 - 0.4, v.floor_height * v.floors - 0.5)
        mb.box("base", (-w / 2 - 0.4, 0, 0), (w / 2 + 0.4, y0 + 0.01, depth + 1.8), faces=("+z", "+x", "-x", "+y"))
        for s in range(1, 4):  # steps
            mb.box("base", (-w / 2 - 0.4, 0, depth + 1.8 - s * 0.6), (w / 2 + 0.4, y0 * s / 3 + 0.01, depth + 1.8 - (s - 1) * 0.6),
                   faces=("+z", "+y"))
        ncol = max(4, int(w / 2.6))
        for k in range(ncol + 1):
            x = -w / 2 + w * k / ncol
            mb.prism("trim", (x, y0, depth), 0.32, h, 12, tile=2)
            mb.box("trim", (x - 0.42, y0, depth - 0.42), (x + 0.42, y0 + 0.28, depth + 0.42), faces=("+x", "-x", "+z", "-z", "+y"))
            mb.box("trim", (x - 0.42, y0 + h - 0.25, depth - 0.42), (x + 0.42, y0 + h, depth + 0.42), faces=("+x", "-x", "+z", "-z", "-y"))
        mb.box("trim", (-w / 2 - 0.6, y0 + h, -0.0), (w / 2 + 0.6, y0 + h + 0.7, depth + 0.6),
               faces=("+z", "+y", "-y", "+x", "-x"))
        # pediment
        ph = 1.8
        mb.tri_out("trim", (-w / 2 - 0.6, y0 + h + 0.7, depth + 0.6), (w / 2 + 0.6, y0 + h + 0.7, depth + 0.6),
                   (0, y0 + h + 0.7 + ph, depth + 0.6), outward=(0, y0 + h, -5))
        mb.quad("trim", (-w / 2 - 0.6, y0 + h + 0.7, depth + 0.6), (0, y0 + h + 0.7 + ph, depth + 0.6),
                (0, y0 + h + 0.7 + ph, 0), (-w / 2 - 0.6, y0 + h + 0.7, 0), outward=(0, y0 + h, depth / 2))
        mb.quad("trim", (w / 2 + 0.6, y0 + h + 0.7, depth + 0.6), (w / 2 + 0.6, y0 + h + 0.7, 0),
                (0, y0 + h + 0.7 + ph, 0), (0, y0 + h + 0.7 + ph, depth + 0.6), outward=(0, y0 + h, depth / 2))
        if not any(c["name"] == "entrance" for c in self.points):
            self._add_point("entrance", v, 0.0, v.y0, depth + 2.5, "front")

    # ------------------------------------------------------------------ curtain wall
    def _curtain(self, v: Volume, length: float) -> None:
        mb = self.mb
        n = max(2, round(length / self.bay_w))
        bw = length / n
        for fl in range(v.floors):
            y0 = v.y0 + fl * v.floor_height
            y1 = y0 + v.floor_height
            sp = 0.9
            mb.quad("metal", (-length / 2, y0, 0), (length / 2, y0, 0), (length / 2, y0 + sp, 0), (-length / 2, y0 + sp, 0))
            for i in range(n):
                x0 = -length / 2 + bw * i
                self._glass(x0 + 0.04, x0 + bw - 0.04, y0 + sp, y1, -0.04, lit_p=0.2, curtain_p=0.0)
        fin_h = v.height
        for i in range(n + 1):
            x = -length / 2 + bw * i
            mb.box("frame", (x - 0.06, v.y0, -0.04), (x + 0.06, v.y0 + fin_h, 0.14),
                   faces=("+z", "+x", "-x"))

    # ------------------------------------------------------------------ clad (industrial)
    def _clad(self, v: Volume, side: str, length: float) -> None:
        mb = self.mb
        h = v.height
        y0 = v.y0
        mb.quad(v.wall_mat, (-length / 2, y0, 0), (length / 2, y0, 0), (length / 2, y0 + h, 0), (-length / 2, y0 + h, 0))
        # clerestory ribbon
        wy0, wy1 = y0 + h - 2.6, y0 + h - 1.2
        n = max(2, int(length // 4))
        bw = length / n
        for i in range(n):
            x0 = -length / 2 + bw * i + 0.5
            x1 = -length / 2 + bw * (i + 1) - 0.5
            self._reveals(x0, x1, wy0, wy1, depth=0.1)
            self._glass(x0, x1, wy0, wy1, -0.1, force="glass")
            mb.box("trim", (x0 - 0.06, wy0 - 0.08, 0), (x1 + 0.06, wy0, 0.08), faces=("+z", "+y", "-y"))
        if side == "front" or (side != "back" and length > 25):
            nd = max(1, int(length // 9)) if side == "front" else 0
            for i in range(nd):
                cx = -length / 2 + length * (i + 0.5) / nd
                ox0, ox1, oy1 = cx - 1.8, cx + 1.8, y0 + 3.6
                self._reveals(ox0, ox1, y0, oy1, floor=False, depth=0.25)
                mb.quad("metal", (ox0, y0, -0.25), (ox1, y0, -0.25), (ox1, oy1, -0.25), (ox0, oy1, -0.25))
                for k in range(1, 9):
                    y = y0 + (oy1 - y0) * k / 9
                    mb.box("frame", (ox0, y - 0.02, -0.25), (ox1, y + 0.02, -0.21), faces=("+z",))
                mb.box("accent", (ox0 - 0.15, y0, 0), (ox0, oy1 + 0.15, 0.1), faces=("+z", "-x"))
                mb.box("accent", (ox1, y0, 0), (ox1 + 0.15, oy1 + 0.15, 0.1), faces=("+z", "+x"))
                mb.box("accent", (ox0 - 0.15, oy1, 0), (ox1 + 0.15, oy1 + 0.15, 0.1), faces=("+z", "-y", "+y"))
                mb.box("base", (cx - 2.2, 0, 0), (cx + 2.2, y0 * 1.0 + 0.001, 4.0), faces=("+z", "+y", "+x", "-x"))
            if nd and not any(c["name"] == "entrance" for c in self.points):
                self._add_point("entrance", v, -length / 2 + length * 0.5 / nd, v.y0, 2.0, side)

    # ------------------------------------------------------------------ roofs
    def _roof(self, v: Volume) -> None:
        kind = v.roof or "flat"
        if kind == "flat":
            self._roof_flat(v)
        elif kind in ("gable", "hip"):
            self._roof_pitched(v, kind)
        elif kind == "sawtooth":
            self._roof_sawtooth(v)
        elif kind == "shed":
            self._roof_shed(v)

    def _roof_flat(self, v: Volume) -> None:
        mb = self.mb
        hx, hz = v.width / 2, v.depth / 2
        y = v.top
        ph = 0.75 if self.preset.facade != "clad" else 0.5
        o = 0.15
        mb.quad("roof_flat", (v.cx - hx, y + 0.02, v.cz + hz), (v.cx + hx, y + 0.02, v.cz + hz),
                (v.cx + hx, y + 0.02, v.cz - hz), (v.cx - hx, y + 0.02, v.cz - hz), outward=(0, y - 5, 0),
                tile=3)
        t = 0.25
        if v.sides:
            mat = v.wall_mat
            zi = v.cz + hz - t
            mb.box(mat, (v.cx - hx, y, zi), (v.cx + hx, y + ph, v.cz + hz), faces=("+z", "-z", "+y"))
            mb.box(mat, (v.cx - hx, y, v.cz - hz), (v.cx + hx, y + ph, v.cz - hz + t), faces=("-z", "+z", "+y"))
            mb.box(mat, (v.cx + hx - t, y, v.cz - hz + t), (v.cx + hx, y + ph, v.cz + hz - t), faces=("+x", "-x", "+y"))
            mb.box(mat, (v.cx - hx, y, v.cz - hz + t), (v.cx - hx + t, y + ph, v.cz + hz - t), faces=("-x", "+x", "+y"))

    def _roof_pitched(self, v: Volume, kind: str) -> None:
        mb = self.mb
        along_x = v.width >= v.depth
        lx, lz = (v.width, v.depth) if along_x else (v.depth, v.width)
        yaw = 0 if along_x else 90
        slope = math.tan(math.radians(self.pitch))
        hs = lz / 2
        o, ov = 0.55, 0.4
        H = v.top
        yE = H - slope * o
        rise = slope * hs
        ridgeY = H + rise
        eave_z = hs + o
        with mb.transform(yaw, (v.cx if along_x else v.cx, 0, v.cz)):
            ref_low = (0, H - 3, 0)
            if kind == "gable":
                ex = lx / 2 + ov
                for s in (1, -1):
                    mb.quad("roof", (-ex, yE, s * eave_z), (ex, yE, s * eave_z), (ex, ridgeY, 0), (-ex, ridgeY, 0),
                            outward=ref_low, tile=2.0)
                    mb.box("trim", (-ex, yE - 0.16, s * eave_z - (0.02 if s > 0 else 0.03)),
                           (ex, yE + 0.03, s * eave_z + (0.03 if s > 0 else 0.02)), faces=("+z" if s > 0 else "-z", "-y"))
                for sx in (1, -1):  # gable ends
                    x = sx * lx / 2
                    mb.tri_out(v.wall_mat, (x, H, hs), (x, H, -hs), (x, ridgeY, 0), outward=(0, H, 0))
                    # verge board following the roof edge
                    mb.quad("trim", (sx * ex, yE, eave_z), (sx * ex, ridgeY, 0), (sx * ex, ridgeY - 0.14, 0), (sx * ex, yE - 0.14, eave_z),
                            outward=(0, H, 0))
                    mb.quad("trim", (sx * ex, yE, -eave_z), (sx * ex, ridgeY, 0), (sx * ex, ridgeY - 0.14, 0), (sx * ex, yE - 0.14, -eave_z),
                            outward=(0, H, 0))
                mb.quad("trim", (-ex, yE - 0.12, -eave_z), (ex, yE - 0.12, -eave_z), (ex, yE - 0.12, eave_z), (-ex, yE - 0.12, eave_z),
                        outward=(0, H + 5, 0))
                mb.box("trim", (-ex, ridgeY - 0.02, -0.14), (ex, ridgeY + 0.12, 0.14), faces=("+y", "+z", "-z", "+x", "-x"))
                if "chimney" in self.preset.features and self.p.category == "house":
                    cx, cz = lx * 0.25, -hs * 0.35
                    top = ridgeY + 0.9
                    mb.box("brick", (cx - 0.4, H + 0.2, cz - 0.4), (cx + 0.4, top, cz + 0.4), faces=("+x", "-x", "+z", "-z"))
                    mb.box("trim", (cx - 0.5, top, cz - 0.5), (cx + 0.5, top + 0.12, cz + 0.5), faces=("+x", "-x", "+z", "-z", "+y"))
                    mb.box("dark", (cx - 0.3, top + 0.1, cz - 0.3), (cx + 0.3, top + 0.12, cz + 0.3), faces=("+y",))
            else:  # hip
                ex = lx / 2 + o
                lr = max(lx / 2 - hs, 0.0)
                e = [(-ex, yE, eave_z), (ex, yE, eave_z), (ex, yE, -eave_z), (-ex, yE, -eave_z)]
                r1, r2 = (-lr, ridgeY, 0), (lr, ridgeY, 0)
                mb.quad("roof", e[0], e[1], r2, r1, outward=ref_low, tile=2.0)
                mb.quad("roof", e[2], e[3], r1, r2, outward=ref_low, tile=2.0)
                # end slopes are triangles; for a pyramid (lr ~ 0) the quads above degenerate and are dropped
                mb.tri_out("roof", e[1], e[2], r2, outward=ref_low)
                mb.tri_out("roof", e[3], e[0], r1, outward=ref_low)
                mb.quad("trim", e[3], e[2], e[1], e[0], outward=(0, H + 5, 0), uv=[(0, 0), (1, 0), (1, 1), (0, 1)])
                for (a, b) in zip(e, e[1:] + e[:1], strict=True):
                    mb.quad("trim", a, b, (b[0], b[1] - 0.15, b[2]), (a[0], a[1] - 0.15, a[2]), outward=(0, H, 0))

    def _roof_sawtooth(self, v: Volume) -> None:
        mb = self.mb
        hx, hz = v.width / 2, v.depth / 2
        H = v.top
        n = max(2, round(v.depth / 6.5))
        tw = v.depth / n
        rise = 2.0
        for i in range(n):
            z0 = v.cz - hz + tw * i
            z1 = z0 + tw
            # gentle slope facing -z (back), glazed vertical facing +z
            mb.quad("roof_flat", (v.cx - hx, H, z0), (v.cx + hx, H, z0), (v.cx + hx, H + rise, z1), (v.cx - hx, H + rise, z1),
                    outward=(0, H - 3, 0), tile=3)
            mb.quad("glass", (v.cx - hx, H, z1), (v.cx + hx, H, z1), (v.cx + hx, H + rise, z1), (v.cx - hx, H + rise, z1),
                    outward=(0, H, z1 - 3), uv=[(0, 0), (4, 0), (4, 1), (0, 1)])
            for sx in (-1, 1):
                mb.tri_out(v.wall_mat, (v.cx + sx * hx, H, z0), (v.cx + sx * hx, H, z1), (v.cx + sx * hx, H + rise, z1),
                           outward=(v.cx, H, v.cz))
        # parapet around the perimeter
        mb.box(v.wall_mat, (v.cx - hx, H, v.cz + hz - 0.2), (v.cx + hx, H + 0.6, v.cz + hz), faces=("+z", "+y", "-z"))

    def _roof_shed(self, v: Volume) -> None:
        mb = self.mb
        hx, hz = v.width / 2, v.depth / 2
        H = v.top
        rb = 1.6
        mb.quad("roof_flat", (v.cx - hx, H + 0.3, v.cz + hz), (v.cx + hx, H + 0.3, v.cz + hz), (v.cx + hx, H + rb, v.cz - hz),
                (v.cx - hx, H + rb, v.cz - hz), outward=(0, H - 3, 0))
        for sx in (-1, 1):
            x = v.cx + sx * hx
            mb.quad(v.wall_mat, (x, H, v.cz + hz), (x, H, v.cz - hz), (x, H + rb, v.cz - hz), (x, H + 0.3, v.cz + hz),
                    outward=(v.cx, H, v.cz))
        mb.quad(v.wall_mat, (v.cx - hx, H, v.cz - hz), (v.cx + hx, H, v.cz - hz), (v.cx + hx, H + rb, v.cz - hz),
                (v.cx - hx, H + rb, v.cz - hz), outward=(v.cx, H, v.cz))

    # ------------------------------------------------------------------ category features
    def _features(self, vols: list[Volume]) -> None:
        f, mb, cat = self.preset.features, self.mb, self.p.category
        main = vols[-1] if cat == "skyscraper" else vols[0]
        W, D = main.width, main.depth
        top = main.top
        rng = self.rng
        roof_flat = main.roof == "flat"
        if cat == "skyscraper":
            pod = vols[0]
            # setback terrace on podium roof
            if "crown" in f:
                cw, cd = W * 0.7, D * 0.7
                mb.box("trim", (-cw / 2, top, -cd / 2), (cw / 2, top + 2.4, cd / 2), faces=("+x", "-x", "+z", "-z", "+y"))
                for sx in (-1, 1):
                    for sz in (-1, 1):
                        px, pz = sx * (cw / 2 - 0.4), sz * (cd / 2 - 0.4)
                        mb.box("metal", (px - 0.4, top, pz - 0.4), (px + 0.4, top + 3.6, pz + 0.4),
                               faces=("+x", "-x", "+z", "-z", "+y"))
                mb.box("metal", (-cw / 2 + 0.5, top + 2.4, -cd / 2 + 0.5), (cw / 2 - 0.5, top + 3.0, cd / 2 - 0.5), faces=("+y", "+x", "-x", "+z", "-z"))
            if "antenna" in f:
                h = 14 + float(rng.uniform(0, 6))
                mb.box("metal", (-0.2, top + 2.4, -0.2), (0.2, top + 2.4 + h, 0.2), faces=("+x", "-x", "+z", "-z", "+y"))
                for k, w in enumerate((2.4, 1.6, 1.0)):
                    y = top + 2.4 + h * (0.45 + 0.17 * k)
                    mb.box("metal", (-w / 2, y, -0.06), (w / 2, y + 0.1, 0.06), faces=("+z", "-z", "+y", "-y", "+x", "-x"))
                mb.box("sign_red", (-0.28, top + 2.4 + h, -0.28), (0.28, top + 2.4 + h + 0.5, 0.28), faces=("+x", "-x", "+z", "-z", "+y"))
            self._add_roof_point(top + 3.0)
            return
        if "rooftop" in f and roof_flat:
            self._rooftop(main)
        if "cross" in f:
            self._hospital_cross(main)
        if "helipad" in f and roof_flat:
            hx = main.width * 0.28
            mb.prism("roof_flat", (-hx, top + 0.02, 0), 5.0, 0.14, 20, cap_mat="base")
            for dx in (-0.9, 0.9):
                mb.box("sign_white", (-hx + dx - 0.15, top + 0.17, -1.5), (-hx + dx + 0.15, top + 0.18, 1.5), faces=("+y",))
            mb.box("sign_white", (-hx - 0.9, top + 0.17, -0.15), (-hx + 0.9, top + 0.18, 0.15), faces=("+y",))
        if "pediment" in f and cat in ("school",):
            self._school_pediment(main)
        if "flagpole" in f:
            fx = -main.width / 2 - 3.0 if cat != "government" else main.width * 0.32 + 2
            self._flagpole(fx, main.depth / 2 + 2.5, 9.0)
        if "clock" in f and cat == "school" and main.facade == "punched":
            y = top - 1.0
            mb.box("sign_white", (-0.7, y - 0.7, main.depth / 2), (0.7, y + 0.7, main.depth / 2 + 0.12), faces=("+z", "+x", "-x", "+y", "-y"))
            mb.box("dark", (-0.04, y, main.depth / 2 + 0.12), (0.04, y + 0.5, main.depth / 2 + 0.16), faces=("+z",))
            mb.box("dark", (0, y - 0.04, main.depth / 2 + 0.12), (0.4, y + 0.04, main.depth / 2 + 0.16), faces=("+z",))
        if "police_sign" in f:
            y = main.y0 + main.floor_height - 0.1
            mb.box("sign_blue", (-3.0, y, main.depth / 2), (3.0, y + 0.9, main.depth / 2 + 0.2), faces=("+z", "+x", "-x", "+y", "-y"))
            mb.box("sign_white", (-2.6, y + 0.2, main.depth / 2 + 0.2), (2.6, y + 0.7, main.depth / 2 + 0.23), faces=("+z",))
        if "antenna" in f and cat == "police" and roof_flat:
            mb.box("metal", (main.width * 0.3 - 0.12, top, 0), (main.width * 0.3 + 0.12, top + 7, 0.24), faces=("+x", "-x", "+z", "-z", "+y"))
        if "stack" in f:
            h = 20 + float(rng.uniform(0, 8))
            sx = main.width / 2 + 3.0
            mb.prism("brick", (sx, 0, -main.depth * 0.25), 1.3, h, 12)
            mb.prism("dark", (sx, h - 0.8, -main.depth * 0.25), 1.45, 0.8, 12)
            mb.prism("metal", (sx, 0, main.depth * 0.1), 0.8, h * 0.55, 10)
        if "tanks" in f:
            for k in range(2 if cat == "industrial" else 1):
                tx = -main.width / 2 - 4.0 - k * 6.4
                mb.prism("metal", (tx, 0, main.depth * 0.2), 2.8, 6.5, 14)
                mb.cone("metal", (tx, 6.5, main.depth * 0.2), 2.8, 1.2, 14)
                mb.box("frame", (tx - 0.1, 0, main.depth * 0.2 + 2.8), (tx + 0.1, 6.5, main.depth * 0.2 + 2.95), faces=("+z", "+x", "-x"))
        if "platform" in f:
            self._platform(main)
        self._add_roof_point(top)

    def _add_roof_point(self, y: float) -> None:
        self.points.append({"name": "roof_access", "position": (0.0, y, 0.0), "direction": (0.0, 1.0, 0.0)})

    def _rooftop(self, v: Volume) -> None:
        mb, rng = self.mb, self.rng
        top = v.top
        n = 2 + int(rng.integers(0, 3))
        for _ in range(n):
            w, d, h = rng.uniform(1.2, 2.6), rng.uniform(1.0, 2.0), rng.uniform(0.8, 1.6)
            x = rng.uniform(-v.width / 2 + 2, v.width / 2 - 2)
            z = rng.uniform(-v.depth / 2 + 2, v.depth / 2 - 2)
            mb.box("metal", (x - w / 2, top, z - d / 2), (x + w / 2, top + h, z + d / 2), faces=("+x", "-x", "+z", "-z", "+y"))
            mb.prism("dark", (x, top + h, z), 0.35, 0.12, 8)
        if v.floors >= 3 and rng.random() < 0.6:
            x, z = rng.uniform(-v.width / 3, v.width / 3), rng.uniform(-v.depth / 3, v.depth / 3)
            for sx in (-0.6, 0.6):
                for sz in (-0.6, 0.6):
                    mb.box("frame", (x + sx - 0.05, top, z + sz - 0.05), (x + sx + 0.05, top + 1.4, z + sz + 0.05), faces=("+x", "-x", "+z", "-z"))
            mb.prism("door", (x, top + 1.4, z), 1.1, 1.8, 10)
            mb.cone("roof", (x, top + 3.2, z), 1.25, 0.7, 10)

    def _hospital_cross(self, v: Volume) -> None:
        mb = self.mb
        y = v.y0 + v.floor_height * (v.floors - 0.5)
        z = v.depth / 2
        mb.box("sign_white", (-2.0, y - 2.0, z), (2.0, y + 2.0, z + 0.14), faces=("+z", "+x", "-x", "+y", "-y"))
        mb.box("sign_red", (-1.4, y - 0.4, z + 0.14), (1.4, y + 0.4, z + 0.2), faces=("+z", "+y", "-y"))
        mb.box("sign_red", (-0.4, y - 1.4, z + 0.14), (0.4, y + 1.4, z + 0.2), faces=("+z", "+x", "-x"))

    def _school_pediment(self, v: Volume) -> None:
        mb = self.mb
        top = v.top
        w = 9.0
        z = v.depth / 2
        h = 2.4
        mb.tri_out("trim", (-w / 2, top, z + 0.15), (w / 2, top, z + 0.15), (0, top + h, z + 0.15), outward=(0, top, -3))
        mb.box("trim", (-w / 2, top - 0.05, 0), (w / 2, top + 0.12, z + 0.15), faces=("+z", "+y"))
        mb.quad("trim", (-w / 2, top, z + 0.15), (0, top + h, z + 0.15), (0, top + h, 0), (-w / 2, top, 0), outward=(0, top, z / 2))
        mb.quad("trim", (w / 2, top, z + 0.15), (w / 2, top, 0), (0, top + h, 0), (0, top + h, z + 0.15), outward=(0, top, z / 2))

    def _flagpole(self, x: float, z: float, h: float) -> None:
        mb = self.mb
        mb.prism("metal", (x, 0, z), 0.07, h, 6)
        mb.box("sign_blue", (x + 0.05, h - 1.2, z - 0.01), (x + 1.6, h - 0.15, z + 0.01), faces=("+z", "-z"))
        mb.box("sign_red", (x + 0.05, h - 0.9, z - 0.011), (x + 1.6, h - 0.6, z + 0.011), faces=("+z", "-z"))
        mb.box("base", (x - 0.3, 0, z - 0.3), (x + 0.3, 0.3, z + 0.3), faces=("+x", "-x", "+z", "-z", "+y"))

    def _platform(self, v: Volume) -> None:
        mb = self.mb
        w, d = v.width * 0.9, 6.0
        z0 = v.depth / 2
        mb.box("base", (-w / 2, 0, z0), (w / 2, 0.5, z0 + d), faces=("+z", "+x", "-x", "+y"))
        mb.box("sign_white", (-w / 2, 0.5, z0 + d - 0.5), (w / 2, 0.52, z0 + d - 0.35), faces=("+y",))
        y = 4.6
        n = max(3, int(w / 7))
        for k in range(n + 1):
            x = -w / 2 + 0.5 + (w - 1.0) * k / n
            mb.box("metal", (x - 0.12, 0.5, z0 + d - 1.2), (x + 0.12, y, z0 + d - 0.96), faces=("+x", "-x", "+z", "-z"))
        mb.box("trim", (-w / 2 - 0.4, y, z0 - 0.1), (w / 2 + 0.4, y + 0.22, z0 + d + 0.4), faces=("+z", "+y", "-y", "+x", "-x"))
        mb.box("accent", (-w / 2 - 0.4, y + 0.22, z0 + d + 0.3), (w / 2 + 0.4, y + 0.5, z0 + d + 0.4), faces=("+z", "+y"))
        for k in range(n):
            x = -w / 2 + w * (k + 0.5) / n
            mb.box("base", (x - 0.9, 0.5, z0 + 1.0), (x + 0.9, 0.95, z0 + 1.5), faces=("+z", "+y", "+x", "-x"))
        self.points.append({"name": "platform_edge", "position": (0.0, 0.5, z0 + d), "direction": (0.0, 0.0, 1.0)})


def generate_building(params: BuildingParams) -> GeneratedBuilding:
    if params.category == "house" and params.house_description and not params.house_spec:
        from assetforge_vision.mapper import description_to_spec  # local import: the vision package builds on the house kit
        from assetforge_vision.schema import parse_description

        from .house import generate_house as _gh

        spec = description_to_spec(parse_description(params.house_description), params.seed)
        spec.wear = params.wear
        return _gh(spec, params.construction_stage or 6)
    if params.house_spec or (params.category == "house" and params.archetype):
        from .house import ARCHETYPES, HouseSpec, generate_house  # local import: house.py builds on this module

        if params.house_spec:
            spec = HouseSpec.from_dict(params.house_spec)
        else:
            if params.archetype not in ARCHETYPES:
                raise ValueError(f"unknown archetype {params.archetype!r}; available: {sorted(ARCHETYPES)}")
            spec = ARCHETYPES[params.archetype](params.seed)
            spec.wear = params.wear
        return generate_house(spec, params.construction_stage or 6)
    return BuildingGenerator(params).generate()
