"""Modular architectural component library (Premium Stylized, low/mid poly).

Every function draws one real building component into a :class:`MeshBuilder` using *facade-local* coordinates unless noted:
``x`` runs along the wall, ``y`` is up, ``z`` points OUT of the wall (the outer wall plane is ``z = 0``, the building interior is ``z < 0``).
Components are independent of each other so a spec (JSON) can add, remove or tweak each one individually.

Material keys used (see :func:`house_materials`): wall, wall2, trim, base, roof, roof_cap, timber, door, frame, glass, glass_lit,
metal, brick, shutter, accent, deck, plant, flower, dark.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from .materials import MaterialDef, weather
from .mesh import ALL_FACES, MeshBuilder, Vec

AX = {"x": 0, "y": 1, "z": 2}
FACE_AXES = {"+x": (0, 1), "-x": (0, -1), "+y": (1, 1), "-y": (1, -1), "+z": (2, 1), "-z": (2, -1)}


# ------------------------------------------------------------------------------------------------ primitives
def _pt(**k: float) -> Vec:
    return (k.get("x", 0.0), k.get("y", 0.0), k.get("z", 0.0))


def face_to(mb: MeshBuilder, mat: str, a: Vec, b: Vec, c: Vec, d: Vec, toward: Vec, tile: float | None = None,
            uv: Sequence[tuple[float, float]] | None = None) -> None:
    """Quad whose normal points TOWARD ``toward``."""
    ctr = (np.asarray(a) + np.asarray(b) + np.asarray(c) + np.asarray(d)) / 4.0
    away = tuple(2 * ctr - np.asarray(toward))
    mb.quad(mat, a, b, c, d, outward=away, tile=tile, uv=uv)  # type: ignore[arg-type]


def bbox(mb: MeshBuilder, mat: str, lo: Vec, hi: Vec, bevel: float = 0.0, faces: Sequence[str] = ALL_FACES,
         tile: float | None = None) -> None:
    """Axis-aligned box with optional chamfered edges. Faces not listed are omitted and do NOT get chamfered on that side."""
    if bevel <= 0:
        mb.box(mat, lo, hi, faces, tile)
        return
    lo_a, hi_a = np.asarray(lo, dtype=float), np.asarray(hi, dtype=float)
    b = float(min(bevel, (hi_a - lo_a).min() / 2.5))
    present = {FACE_AXES[f] for f in faces}
    ctr = tuple((lo_a + hi_a) / 2)

    def ins(axis: int, sign: int) -> float:
        return b if (axis, sign) in present else 0.0

    def rng(axis: int) -> tuple[float, float]:
        return lo_a[axis] + ins(axis, -1), hi_a[axis] - ins(axis, +1)

    def make(vals: dict[int, float]) -> Vec:
        return (vals[0], vals[1], vals[2])

    for (a, s) in present:
        u, v = [i for i in range(3) if i != a]
        plane = hi_a[a] if s > 0 else lo_a[a]
        (u0, u1), (v0, v1) = rng(u), rng(v)
        mb.quad(mat, make({a: plane, u: u0, v: v0}), make({a: plane, u: u1, v: v0}), make({a: plane, u: u1, v: v1}),
                make({a: plane, u: u0, v: v1}), outward=ctr, tile=tile)
    for (a, sa) in present:
        for (u, su) in present:
            if u <= a:
                continue
            w = 3 - a - u
            wlo, whi = rng(w)
            pa = (hi_a[a] - b) if sa > 0 else (lo_a[a] + b)
            pu = (hi_a[u] - b) if su > 0 else (lo_a[u] + b)
            fa = hi_a[a] if sa > 0 else lo_a[a]
            fu = hi_a[u] if su > 0 else lo_a[u]
            mb.quad(mat, make({a: fa, u: pu, w: wlo}), make({a: fa, u: pu, w: whi}), make({a: pa, u: fu, w: whi}),
                    make({a: pa, u: fu, w: wlo}), outward=ctr, tile=tile)
    for (a, sa) in present:
        for (u, su) in present:
            for (w, sw) in present:
                if not (a < u < w):
                    continue
                pa = (hi_a[a] - b) if sa > 0 else (lo_a[a] + b)
                pu = (hi_a[u] - b) if su > 0 else (lo_a[u] + b)
                pw = (hi_a[w] - b) if sw > 0 else (lo_a[w] + b)
                fa = hi_a[a] if sa > 0 else lo_a[a]
                fu = hi_a[u] if su > 0 else lo_a[u]
                fw = hi_a[w] if sw > 0 else lo_a[w]
                mb.tri_out(mat, make({a: fa, u: pu, w: pw}), make({a: pa, u: fu, w: pw}), make({a: pa, u: pu, w: fw}), ctr, tile=tile)


def facing_quad(mb: MeshBuilder, mat: str, x0: float, x1: float, y0: float, y1: float, z: float, tile: float | None = None) -> None:
    """A wall-parallel quad at depth ``z`` facing OUT (+z)."""
    mb.quad(mat, (x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z), outward=(0.5 * (x0 + x1), 0.5 * (y0 + y1), z - 10.0), tile=tile)


def arc_points(cx: float, spring: float, w: float, rise: float, n: int) -> list[tuple[float, float]]:
    """Points (x, y) of an elliptical arch from the left jamb to the right jamb."""
    return [(cx + (w / 2) * math.cos(math.pi - math.pi * i / n), spring + rise * math.sin(math.pi * i / n)) for i in range(n + 1)]


# ------------------------------------------------------------------------------------------------ openings
@dataclass
class Opening:
    cx: float
    w: float
    y0: float  # sill (windows) / floor (doors)
    y1: float  # head, INCLUDING the arch rise
    kind: str = "window"  # window | door | garage
    arch: float = 0.0  # arch rise as a fraction of half the width (0 = flat head)
    shutters: bool = False
    flower_box: bool = False
    mullions: tuple[int, int] = (2, 2)  # columns x rows of glass panes
    lit: bool = False
    sill: bool = True
    casing: bool = True

    @property
    def rise(self) -> float:
        return self.arch * self.w / 2

    @property
    def x0(self) -> float:
        return self.cx - self.w / 2

    @property
    def x1(self) -> float:
        return self.cx + self.w / 2


def wall_with_openings(mb: MeshBuilder, mat: str, x0: float, x1: float, y0: float, y1: float, ops: list[Opening], reveal: float,
                       reveal_mat: str, tile: float | None = None, arch_n: int = 6) -> None:
    """Outer wall plane at z=0 with real holes, plus reveal (jamb) surfaces going back by ``reveal``."""
    xs = sorted({x0, x1, *[o.x0 for o in ops], *[o.x1 for o in ops]})
    for xa, xb in zip(xs, xs[1:], strict=False):
        if xb - xa < 1e-4:
            continue
        mid = (xa + xb) / 2
        cover = sorted((o for o in ops if o.x0 - 1e-6 <= mid <= o.x1 + 1e-6), key=lambda o: o.y0)
        cur = y0
        for o in cover:
            if o.y0 > cur + 1e-4:
                facing_quad(mb, mat, xa, xb, cur, o.y0, 0.0, tile)
            cur = max(cur, o.y1)
        if y1 > cur + 1e-4:
            facing_quad(mb, mat, xa, xb, cur, y1, 0.0, tile)
    for o in ops:
        spring = o.y1 - o.rise
        if o.arch > 0:  # fill the two spandrels between the rectangle and the arc
            pts = arc_points(o.cx, spring, o.w, o.rise, arch_n)
            for (xa, ya), (xb, yb) in zip(pts, pts[1:], strict=False):
                mb.quad(mat, (xa, ya, 0), (xb, yb, 0), (xb, o.y1, 0), (xa, o.y1, 0), outward=(o.cx, ya, -10.0), tile=tile)
        r = reveal
        cy = (o.y0 + spring) / 2
        face_to(mb, reveal_mat, (o.x0, o.y0, 0), (o.x0, o.y0, -r), (o.x0, spring, -r), (o.x0, spring, 0), (o.cx, cy, -r / 2), tile=1.0)
        face_to(mb, reveal_mat, (o.x1, o.y0, 0), (o.x1, o.y0, -r), (o.x1, spring, -r), (o.x1, spring, 0), (o.cx, cy, -r / 2), tile=1.0)
        if o.kind == "window":
            face_to(mb, reveal_mat, (o.x0, o.y0, 0), (o.x1, o.y0, 0), (o.x1, o.y0, -r), (o.x0, o.y0, -r), (o.cx, o.y0 + 1, -r / 2), tile=1.0)
        if o.arch > 0:
            pts = arc_points(o.cx, spring, o.w, o.rise, arch_n)
            for (xa, ya), (xb, yb) in zip(pts, pts[1:], strict=False):
                face_to(mb, reveal_mat, (xa, ya, 0), (xb, yb, 0), (xb, yb, -r), (xa, ya, -r), (o.cx, spring - 0.2, -r / 2), tile=1.0)
        else:
            face_to(mb, reveal_mat, (o.x0, o.y1, 0), (o.x1, o.y1, 0), (o.x1, o.y1, -r), (o.x0, o.y1, -r), (o.cx, o.y1 - 1, -r / 2), tile=1.0)


def window_dressing(mb: MeshBuilder, m: dict[str, str], o: Opening, reveal: float, arch_n: int = 6) -> None:
    """Frame, mullions, glass, casing, sill, shutters and flower box for one window opening (z=0 is the wall plane)."""
    r = reveal
    f = 0.075  # frame bar width
    zf = -r * 0.62
    spring = o.y1 - o.rise
    glass = m["glass_lit"] if o.lit else m["glass"]
    # glass pane at the back of the frame
    if o.arch > 0:
        pts = arc_points(o.cx, spring, o.w - 2 * f, max(o.rise - f, 0.05), arch_n)
        facing_quad(mb, glass, o.x0 + f, o.x1 - f, o.y0 + f, spring, zf + 0.01, tile=1.0)
        for (xa, ya), (xb, yb) in zip(pts, pts[1:], strict=False):
            mb.tri_out(glass, (xa, ya, zf + 0.01), (xb, yb, zf + 0.01), (o.cx, spring, zf + 0.01), (o.cx, spring, zf - 5), tile=1.0)
    else:
        facing_quad(mb, glass, o.x0 + f, o.x1 - f, o.y0 + f, o.y1 - f, zf + 0.01, tile=1.0)
    # frame (recessed): outer ring + mullions
    d = 0.06
    fr = m["frame"]
    bbox(mb, fr, (o.x0, o.y0, zf), (o.x0 + f, spring, zf + d), faces=("+x", "+z", "-x"))
    bbox(mb, fr, (o.x1 - f, o.y0, zf), (o.x1, spring, zf + d), faces=("-x", "+z", "+x"))
    bbox(mb, fr, (o.x0 + f, o.y0, zf), (o.x1 - f, o.y0 + f, zf + d), faces=("+y", "+z"))
    if o.arch > 0:
        pts = arc_points(o.cx, spring, o.w, o.rise, arch_n)
        inner = arc_points(o.cx, spring, o.w - 2 * f, max(o.rise - f, 0.05), arch_n)
        for i in range(arch_n):
            mb.quad(fr, (*pts[i], zf + d), (*pts[i + 1], zf + d), (*inner[i + 1], zf + d), (*inner[i], zf + d), outward=(o.cx, spring, zf - 5))
    else:
        bbox(mb, fr, (o.x0 + f, o.y1 - f, zf), (o.x1 - f, o.y1, zf + d), faces=("-y", "+z"))
    cols, rows = o.mullions
    mw = 0.035
    for i in range(1, cols):
        x = o.x0 + f + (o.w - 2 * f) * i / cols
        bbox(mb, fr, (x - mw / 2, o.y0 + f, zf), (x + mw / 2, spring if o.arch > 0 else o.y1 - f, zf + d + 0.012), faces=("+z", "+x", "-x"))
    for j in range(1, rows):
        y = o.y0 + f + ((spring if o.arch > 0 else o.y1 - f) - o.y0 - f) * j / rows
        bbox(mb, fr, (o.x0 + f, y - mw / 2, zf), (o.x1 - f, y + mw / 2, zf + d + 0.012), faces=("+z", "+y", "-y"))
    # casing (architrave) around the opening, proud of the wall
    if o.casing:
        c, p = 0.11, 0.045
        t = m["trim"]
        bbox(mb, t, (o.x0 - c, o.y0 - 0.02, 0), (o.x0, spring, p), 0.012, faces=("-x", "+z", "+x"))
        bbox(mb, t, (o.x1, o.y0 - 0.02, 0), (o.x1 + c, spring, p), 0.012, faces=("+x", "+z", "-x"))
        if o.arch > 0:
            pts = arc_points(o.cx, spring, o.w, o.rise, arch_n)
            out = arc_points(o.cx, spring, o.w + 2 * c, o.rise + c, arch_n)
            for i in range(arch_n):
                mb.quad(t, (*pts[i], p), (*pts[i + 1], p), (*out[i + 1], p), (*out[i], p), outward=(o.cx, spring, -5))
        else:
            bbox(mb, t, (o.x0 - c - 0.03, o.y1, 0), (o.x1 + c + 0.03, o.y1 + 0.13, p + 0.03), 0.015, faces=("+x", "-x", "+y", "+z", "-y"))
    if o.sill and o.kind == "window":
        bbox(mb, m["trim"], (o.x0 - 0.1, o.y0 - 0.1, 0), (o.x1 + 0.1, o.y0 + 0.02, 0.15), 0.02, faces=("+x", "-x", "+y", "+z", "-y"))
    if o.shutters:
        sw = o.w / 2 - 0.02
        for side in (-1, 1):
            xa = o.x0 - 0.13 - sw if side < 0 else o.x1 + 0.13
            bbox(mb, m["shutter"], (xa, o.y0 - 0.05, 0), (xa + sw, o.y1 + 0.05, 0.05), 0.01, faces=("+z", "+x", "-x", "+y", "-y"))
            n = 3
            for k in range(1, n):
                yy = o.y0 - 0.05 + (o.y1 - o.y0 + 0.1) * k / n
                bbox(mb, m["shutter"], (xa + 0.04, yy - 0.012, 0.05), (xa + sw - 0.04, yy + 0.012, 0.075), faces=("+z", "+y"))
    if o.flower_box:
        y = o.y0 - 0.32
        bbox(mb, m["timber"], (o.x0 - 0.05, y, 0), (o.x1 + 0.05, y + 0.22, 0.26), 0.012, faces=("+x", "-x", "+z", "-y", "+y"))
        n = max(2, int(o.w / 0.28))
        for i in range(n):
            xx = o.x0 + (i + 0.5) * o.w / n
            mb.cone(m["plant"], (xx, y + 0.22, 0.13), 0.13, 0.2, 5)
            if i % 2 == 0:
                bbox(mb, m["flower"], (xx - 0.03, y + 0.36, 0.1), (xx + 0.03, y + 0.42, 0.16), faces=("+y", "+z"))


def door_dressing(mb: MeshBuilder, m: dict[str, str], o: Opening, reveal: float, arch_n: int = 6) -> None:
    """Door leaf (recessed, with raised panels and a small window), frame, casing, handle and threshold."""
    r = reveal
    zf = -r * 0.5
    spring = o.y1 - o.rise
    w = o.w
    leaf_mat = m["door"]
    bbox(mb, leaf_mat, (o.x0 + 0.05, o.y0, zf - 0.04), (o.x1 - 0.05, spring, zf + 0.04), 0.012, faces=("+z", "+x", "-x"))
    if o.arch > 0:
        pts = arc_points(o.cx, spring, w - 0.1, o.rise - 0.04, arch_n)
        for (xa, ya), (xb, yb) in zip(pts, pts[1:], strict=False):
            mb.tri_out(leaf_mat, (xa, ya, zf + 0.04), (xb, yb, zf + 0.04), (o.cx, spring, zf + 0.04), (o.cx, spring, zf - 5))
    else:
        bbox(mb, leaf_mat, (o.x0 + 0.05, spring - 0.01, zf - 0.04), (o.x1 - 0.05, o.y1, zf + 0.04), 0.012, faces=("+z", "+x", "-x", "+y"))
    # raised panels (lower) + glazed upper light
    pw = (w - 0.34) / 2
    for i in range(2):
        px = o.x0 + 0.14 + i * (pw + 0.06)
        bbox(mb, leaf_mat, (px, o.y0 + 0.14, zf + 0.04), (px + pw, o.y0 + 0.14 + (spring - o.y0) * 0.38, zf + 0.085), 0.015, faces=("+z", "+x", "-x", "+y", "-y"))
    gy0 = o.y0 + (spring - o.y0) * 0.58
    gy1 = spring - 0.12
    bbox(mb, m["frame"], (o.x0 + 0.16, gy0 - 0.04, zf + 0.04), (o.x1 - 0.16, gy1 + 0.04, zf + 0.07), faces=("+z",))
    facing_quad(mb, m["glass_lit"] if o.lit else m["glass"], o.x0 + 0.2, o.x1 - 0.2, gy0, gy1, zf + 0.075, tile=1.0)
    bbox(mb, m["frame"], (o.cx - 0.015, gy0, zf + 0.075), (o.cx + 0.015, gy1, zf + 0.09), faces=("+z",))
    bbox(mb, m["metal"], (o.x1 - 0.2, o.y0 + (spring - o.y0) * 0.5, zf + 0.04), (o.x1 - 0.14, o.y0 + (spring - o.y0) * 0.5 + 0.06, zf + 0.13), faces=("+z", "+y", "-x", "+x"))
    # casing
    c, p = 0.13, 0.06
    t = m["trim"]
    bbox(mb, t, (o.x0 - c, o.y0, 0), (o.x0, spring, p), 0.012, faces=("-x", "+z", "+x"))
    bbox(mb, t, (o.x1, o.y0, 0), (o.x1 + c, spring, p), 0.012, faces=("+x", "+z", "-x"))
    if o.arch > 0:
        pts = arc_points(o.cx, spring, w, o.rise, arch_n)
        out = arc_points(o.cx, spring, w + 2 * c, o.rise + c, arch_n)
        for i in range(arch_n):
            mb.quad(t, (*pts[i], p), (*pts[i + 1], p), (*out[i + 1], p), (*out[i], p), outward=(o.cx, spring, -5))
    else:
        bbox(mb, t, (o.x0 - c - 0.04, o.y1, 0), (o.x1 + c + 0.04, o.y1 + 0.16, p + 0.05), 0.015, faces=("+x", "-x", "+y", "+z", "-y"))


def steps(mb: MeshBuilder, mat: str, cx: float, w: float, rise: float, n: int, run: float = 0.32, z0: float = 0.0) -> None:
    for i in range(n):
        h = rise * (n - i) / n
        bbox(mb, mat, (cx - w / 2 - i * 0.02, 0, z0), (cx + w / 2 + i * 0.02, h, z0 + run * (i + 1)), 0.02, faces=("+x", "-x", "+y", "+z"))


# ------------------------------------------------------------------------------------------------ wall dressing
def belt_course(mb: MeshBuilder, mat: str, x0: float, x1: float, y: float, h: float = 0.14, p: float = 0.07) -> None:
    bbox(mb, mat, (x0, y - h / 2, 0), (x1, y + h / 2, p), 0.02, faces=("+z", "+y", "-y", "+x", "-x"))


def corner_post(mb: MeshBuilder, mat: str, x: float, y0: float, y1: float, w: float = 0.2, p: float = 0.06) -> None:
    bbox(mb, mat, (x - w / 2, y0, 0), (x + w / 2, y1, p), 0.015, faces=("+z", "+x", "-x", "+y"))


def foundation(mb: MeshBuilder, mat: str, cap: str, x0: float, x1: float, h: float, p: float = 0.1) -> None:
    """Stone plinth along one facade, slightly proud of the wall, with a capping course."""
    bbox(mb, mat, (x0 - p, 0, 0), (x1 + p, h, p), 0.03, faces=("+z", "+x", "-x"))
    bbox(mb, cap, (x0 - p - 0.03, h - 0.1, 0), (x1 + p + 0.03, h + 0.04, p + 0.05), 0.02, faces=("+z", "+x", "-x", "+y"))


def timber_frame(mb: MeshBuilder, mat: str, x0: float, x1: float, y0: float, y1: float, ops: list[Opening], floor_ys: list[float],
                 post_every: float = 1.8, p: float = 0.07, t: float = 0.13, braces: bool = True) -> None:
    """Half-timbering: vertical posts, floor rails and diagonal braces laid over the plaster infill."""
    def clear(xa: float, xb: float, ya: float, yb: float) -> bool:
        return not any(o.x1 + 0.12 > xa and o.x0 - 0.12 < xb and o.y1 + 0.2 > ya and o.y0 - 0.2 < yb for o in ops)

    rails = [y0, *floor_ys, y1]
    for y in rails:
        bbox(mb, mat, (x0, y - t / 2, 0), (x1, y + t / 2, p), faces=("+z", "+y", "-y"))
    for ya, yb in zip(rails, rails[1:], strict=False):
        n = max(1, round((x1 - x0) / post_every))
        xs = [x0 + (x1 - x0) * i / n for i in range(n + 1)]
        for x in xs:
            lo, hi = max(x0, x - t / 2), min(x1, x + t / 2)
            bbox(mb, mat, (lo, ya, 0), (hi, yb, p), faces=("+z", "+x", "-x"))
        for o in ops:  # posts flanking openings
            if o.y0 < yb and o.y1 > ya:
                for xx in (o.x0 - 0.11 - t / 2, o.x1 + 0.11 + t / 2):
                    if x0 < xx < x1:
                        bbox(mb, mat, (xx - t / 2, ya, 0), (xx + t / 2, yb, p), faces=("+z", "+x", "-x"))
        if braces:
            for xa, xb in zip(xs, xs[1:], strict=False):
                if clear(xa + t, xb - t, ya + t, yb - t) and xb - xa > 1.0:
                    # diagonal brace as a flat slanted quad band
                    k = 0.07
                    a = (xa + t / 2, ya + t / 2)
                    b = (xb - t / 2, yb - t / 2)
                    mb.quad(mat, (a[0], a[1] + k, p), (a[0] + k, a[1], p), (b[0], b[1] - k, p), (b[0] - k, b[1], p), outward=(a[0], a[1], -10))


# ------------------------------------------------------------------------------------------------ roofs
def _slab(mb: MeshBuilder, mat_top: str, mat_edge: str, mat_under: str, top: list[Vec], th: float, uv_top: Sequence[tuple[float, float]],
          edges: Sequence[bool], inside: Vec) -> None:
    """Thick roof plane given 4 top corners (counter-clockwise). Adds top (UV mapped), underside and fascia on flagged edges."""
    n = len(top)
    mb.quad(mat_top, *top, outward=inside, uv=uv_top) if n == 4 else mb.tri_out(mat_top, *top, inside)  # type: ignore[arg-type]
    bot = [(x, y - th, z) for (x, y, z) in top]
    if n == 4:
        mb.quad(mat_under, *bot, outward=tuple(np.asarray(inside) + np.array([0, 20, 0])), tile=2.0)
    else:
        mb.tri_out(mat_under, *bot, tuple(np.asarray(inside) + np.array([0, 20, 0])))
    for i in range(n):
        if edges[i]:
            a, b = top[i], top[(i + 1) % n]
            mb.quad(mat_edge, a, b, bot[(i + 1) % n], bot[i], outward=inside, tile=1.0)


def gable_roof(mb: MeshBuilder, mats: dict[str, str], x0: float, x1: float, z0: float, z1: float, y_eave: float, pitch_deg: float,
               ov_eave: float = 0.5, ov_rake: float = 0.35, th: float = 0.14, ridge_cap: bool = True, tile: float = 1.6,
               back_overhang: bool = True, gable_wall: str = "wall", end_a: bool = True, end_b: bool = True,
               slopes: Sequence[str] = ("front", "back")) -> float:
    """Gable roof with the ridge along X over the footprint [x0,x1] x [z0,z1] (world/local frame of the caller).
    Returns the ridge height. Gable-end triangles are drawn at x=x0 and x=x1."""
    zc = (z0 + z1) / 2
    hz = (z1 - z0) / 2
    t = math.tan(math.radians(pitch_deg))
    ze_f = hz + ov_eave
    ze_b = hz + (ov_eave if back_overhang else 0.0)
    y_r = y_eave + hz * t
    xa, xb = x0 - (ov_rake if end_a else 0.0), x1 + (ov_rake if end_b else 0.0)
    ye_f = y_r - ze_f * t
    ye_b = y_r - ze_b * t
    slope_f = math.hypot(ze_f, y_r - ye_f)
    slope_b = math.hypot(ze_b, y_r - ye_b)
    inside = (zc * 0 + (x0 + x1) / 2, y_eave - 2.0, zc)
    # front slope (z > zc)
    top = [(xa, ye_f, zc + ze_f), (xb, ye_f, zc + ze_f), (xb, y_r, zc), (xa, y_r, zc)]
    if "front" in slopes:
      _slab(mb, mats["roof"], mats["trim"], mats["trim"], top, th, [(xa / tile, 0), (xb / tile, 0), (xb / tile, slope_f / tile), (xa / tile, slope_f / tile)],
          [True, False, False, False], inside)
    # back slope (z < zc)
    top = [(xb, ye_b, zc - ze_b), (xa, ye_b, zc - ze_b), (xa, y_r, zc), (xb, y_r, zc)]
    if "back" in slopes:
      _slab(mb, mats["roof"], mats["trim"], mats["trim"], top, th, [(-xb / tile, 0), (-xa / tile, 0), (-xa / tile, slope_b / tile), (-xb / tile, slope_b / tile)],
          [True, False, False, False], inside)
    # rake boards (verge) on both gable ends
    for xe, sgn in ((xa, -1), (xb, 1)):
        if (sgn < 0 and not end_a) or (sgn > 0 and not end_b):
            continue
        for zs, ye, ze in ((1, ye_f, ze_f), (-1, ye_b, ze_b)):
            a = (xe, ye, zc + zs * ze)
            b = (xe, y_r, zc)
            mb.quad(mats["trim"], a, b, (xe, y_r - th, zc), (xe, ye - th, zc + zs * ze), outward=(xe - sgn * 10, y_eave, zc), tile=1.0)
    # gable triangles on the wall planes
    for xe, sgn in ((x0, -1), (x1, 1)):
        if (sgn < 0 and not end_a) or (sgn > 0 and not end_b):
            continue
        a, b, c = (xe, y_eave, z0), (xe, y_eave, z1), (xe, y_r, zc)
        mb.tri_out(mats[gable_wall], a, b, c, (xe - sgn * 10, y_eave, zc), tile=2.0)
    if ridge_cap:
        bbox(mb, mats["roof_cap"], (xa - 0.04, y_r - 0.07, zc - 0.17), (xb + 0.04, y_r + 0.1, zc + 0.17), 0.03, faces=("+x", "-x", "+y", "+z", "-z"))
    return y_r


def hip_roof(mb: MeshBuilder, mats: dict[str, str], x0: float, x1: float, z0: float, z1: float, y_eave: float, pitch_deg: float,
             ov: float = 0.5, th: float = 0.14, tile: float = 1.6, skip: Sequence[str] = ()) -> float:
    """Hip roof (ridge along the longer side). Returns ridge height."""
    t = math.tan(math.radians(pitch_deg))
    cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
    hx, hz = (x1 - x0) / 2 + ov, (z1 - z0) / 2 + ov
    short = min(hx, hz)
    rl = max(hx, hz) - short  # half ridge length
    along_x = hx >= hz
    y_r = y_eave + short * t
    slope = math.hypot(short, short * t)
    inside = (cx, y_eave - 2.0, cz)

    def P(a: float, b: float, y: float) -> Vec:  # (along, across) -> world
        return (cx + a, y, cz + b) if along_x else (cx + b, y, cz + a)

    A, Bh = (hx, hz) if along_x else (hz, hx)
    # long sides
    for s in (1, -1):
        if ("front" if s > 0 else "back") in skip:
            continue
        top = [P(-A, s * Bh, y_eave), P(A, s * Bh, y_eave), P(rl, 0, y_r), P(-rl, 0, y_r)]
        if s < 0:
            top = [P(A, s * Bh, y_eave), P(-A, s * Bh, y_eave), P(-rl, 0, y_r), P(rl, 0, y_r)]
        uv = [(-A / tile, 0), (A / tile, 0), (rl / tile, slope / tile), (-rl / tile, slope / tile)]
        _slab(mb, mats["roof"], mats["trim"], mats["trim"], top, th, uv, [True, False, False, False], inside)
    # hip ends (triangles)
    for s in (1, -1):
        if ("endp" if s > 0 else "endn") in skip:
            continue
        a, b = P(s * A, -Bh, y_eave), P(s * A, Bh, y_eave)
        c = P(s * rl, 0, y_r)
        tri = [a, b, c] if s > 0 else [b, a, c]
        if not along_x:
            tri = [b, a, c] if s > 0 else [a, b, c]
        uv = [(-Bh / tile, 0), (Bh / tile, 0), (0, slope / tile)]
        _slab(mb, mats["roof"], mats["trim"], mats["trim"], tri, th, uv, [True, False, False], inside)
    if rl > 0.05:
        if along_x:
            bbox(mb, mats["roof_cap"], (cx - rl - 0.1, y_r - 0.07, cz - 0.15), (cx + rl + 0.1, y_r + 0.1, cz + 0.15), 0.03, faces=("+x", "-x", "+y", "+z", "-z"))
        else:
            bbox(mb, mats["roof_cap"], (cx - 0.15, y_r - 0.07, cz - rl - 0.1), (cx + 0.15, y_r + 0.1, cz + rl + 0.1), 0.03, faces=("+x", "-x", "+y", "+z", "-z"))
    else:
        mb.cone(mats["roof_cap"], (cx, y_r - 0.02, cz), 0.16, 0.22, 6)
    return y_r


def shed_roof(mb: MeshBuilder, mats: dict[str, str], x0: float, x1: float, z0: float, z1: float, y_low: float, pitch_deg: float,
              ov: float = 0.4, th: float = 0.14, tile: float = 1.6, high_side: str = "-z") -> float:
    """Single-slope roof rising toward ``high_side`` (default back). Returns the high edge height."""
    t = math.tan(math.radians(pitch_deg))
    depth = (z1 - z0) + 2 * ov
    y_hi = y_low + depth * t
    xa, xb = x0 - ov, x1 + ov
    za, zb = z0 - ov, z1 + ov
    inside = ((x0 + x1) / 2, y_low - 2, (z0 + z1) / 2)
    slope = math.hypot(depth, y_hi - y_low)
    if high_side == "-z":
        top = [(xa, y_low, zb), (xb, y_low, zb), (xb, y_hi, za), (xa, y_hi, za)]
    else:
        top = [(xb, y_low, za), (xa, y_low, za), (xa, y_hi, zb), (xb, y_hi, zb)]
    _slab(mb, mats["roof"], mats["trim"], mats["trim"], top, th, [(xa / tile, 0), (xb / tile, 0), (xb / tile, slope / tile), (xa / tile, slope / tile)],
          [True, True, True, True], inside)
    return y_hi


def flat_roof(mb: MeshBuilder, mats: dict[str, str], x0: float, x1: float, z0: float, z1: float, y: float, ov: float = 0.3, parapet: float = 0.0,
              slab: str = "trim") -> None:
    th = 0.22
    bbox(mb, mats[slab], (x0 - ov, y, z0 - ov), (x1 + ov, y + th, z1 + ov), 0.03, faces=("+x", "-x", "+z", "-z", "+y", "-y"))
    if parapet > 0:  # real parapet walls around the edge + a coping stone, roof membrane inside
        ph, pt = 0.42, 0.2
        bbox(mb, mats["roof_cap"], (x0 - ov + pt, y + th, z0 - ov + pt), (x1 + ov - pt, y + th + 0.02, z1 + ov - pt), faces=("+y",))
        for (a, b) in (((x0 - ov, z1 + ov - pt), (x1 + ov, z1 + ov)), ((x0 - ov, z0 - ov), (x1 + ov, z0 - ov + pt)),
                       ((x0 - ov, z0 - ov + pt), (x0 - ov + pt, z1 + ov - pt)), ((x1 + ov - pt, z0 - ov + pt), (x1 + ov, z1 + ov - pt))):
            bbox(mb, mats["wall"], (a[0], y + th, a[1]), (b[0], y + th + ph, b[1]), 0.0, faces=("+x", "-x", "+z", "-z"))
        bbox(mb, mats["trim"], (x0 - ov - 0.03, y + th + ph, z0 - ov - 0.03), (x1 + ov + 0.03, y + th + ph + 0.06, z1 + ov + 0.03), 0.02, faces=("+y", "+x", "-x", "+z", "-z"))


# ------------------------------------------------------------------------------------------------ features
def chimney(mb: MeshBuilder, m: dict[str, str], cx: float, cz: float, w: float, d: float, y0: float, y1: float, base_mat: str | None = None) -> None:
    """Chimney stack (shaft, corbelled cap, two flues). World/volume frame."""
    bm = base_mat or m["brick"]
    bbox(mb, bm, (cx - w / 2, y0, cz - d / 2), (cx + w / 2, y1, cz + d / 2), 0.03, faces=("+x", "-x", "+z", "-z"))
    bbox(mb, m["trim"], (cx - w / 2 - 0.07, y1 - 0.18, cz - d / 2 - 0.07), (cx + w / 2 + 0.07, y1 + 0.06, cz + d / 2 + 0.07), 0.02, faces=("+x", "-x", "+z", "-z", "+y"))
    for s in (-1, 1):
        mb.prism(m["dark"], (cx + s * w * 0.22, y1 + 0.06, cz), 0.1, 0.3, 6)


def column(mb: MeshBuilder, m: dict[str, str], x: float, z: float, y0: float, y1: float, r: float = 0.14, sides: int = 10) -> None:
    mb.prism(m["trim"], (x, y0 + 0.12, z), r, y1 - y0 - 0.3, sides, cap_top=False)
    bbox(mb, m["trim"], (x - r * 1.4, y0, z - r * 1.4), (x + r * 1.4, y0 + 0.14, z + r * 1.4), 0.02, faces=("+x", "-x", "+z", "-z", "+y"))
    bbox(mb, m["trim"], (x - r * 1.5, y1 - 0.2, z - r * 1.5), (x + r * 1.5, y1, z + r * 1.5), 0.025, faces=("+x", "-x", "+z", "-z", "+y", "-y"))


def post(mb: MeshBuilder, mat: str, x: float, z: float, y0: float, y1: float, w: float = 0.16) -> None:
    bbox(mb, mat, (x - w / 2, y0, z - w / 2), (x + w / 2, y1, z + w / 2), 0.015, faces=("+x", "-x", "+z", "-z", "+y"))


def railing(mb: MeshBuilder, m: dict[str, str], x0: float, x1: float, z: float, y: float, h: float = 0.95, spacing: float = 0.2, iron: bool = False) -> None:
    """Straight railing (rails + balusters) along X at depth z, base at height y."""
    mat = m["metal"] if iron else m["trim"]
    bbox(mb, mat, (x0, y + h - 0.07, z - 0.05), (x1, y + h, z + 0.05), 0.012, faces=("+y", "+x", "-x", "+z", "-z"))
    bbox(mb, mat, (x0, y + 0.08, z - 0.035), (x1, y + 0.14, z + 0.035), faces=("+y", "+z", "-z"))
    n = max(2, int((x1 - x0) / spacing))
    bw = 0.03 if iron else 0.045
    for i in range(n + 1):
        x = x0 + 0.04 + (x1 - x0 - 0.08) * i / n
        bbox(mb, mat, (x - bw / 2, y + 0.14, z - bw / 2), (x + bw / 2, y + h - 0.07, z + bw / 2), faces=("+x", "+z"))


def deck(mb: MeshBuilder, m: dict[str, str], x0: float, x1: float, z0: float, z1: float, y: float, th: float = 0.16) -> None:
    """Wooden deck / porch floor between facade-frame coords (z grows outward)."""
    bbox(mb, m["deck"], (x0, y - th, z0), (x1, y, z1), 0.02, faces=("+y", "+x", "-x", "+z"), tile=1.2)


def bracket(mb: MeshBuilder, mat: str, x: float, y: float, size: float = 0.4) -> None:
    mb.tri_out(mat, (x - 0.03, y, 0.0), (x - 0.03, y, size), (x - 0.03, y - size, 0.0), (x - 10, y, 0))
    mb.tri_out(mat, (x + 0.03, y, 0.0), (x + 0.03, y, size), (x + 0.03, y - size, 0.0), (x + 10, y, 0))


def awning(mb: MeshBuilder, mat: str, x0: float, x1: float, y: float, depth: float = 0.7, drop: float = 0.35) -> None:
    mb.quad(mat, (x0, y, 0.0), (x1, y, 0.0), (x1, y - drop, depth), (x0, y - drop, depth), outward=(0.5 * (x0 + x1), y - 5, 0.0), tile=1.0)
    for x in (x0, x1):
        mb.tri_out(mat, (x, y, 0.0), (x, y - drop, depth), (x, y - drop, 0.0), (x + (-5 if x == x0 else 5), y, 0.0))


def house_materials(palette: dict[str, str], wear: float, wall_kind: str = "stucco", roof_kind: str = "shingles",
                    base_kind: str = "cobble", wall2_kind: str | None = None) -> dict[str, MaterialDef]:
    """Material set for the house kit; every colour comes from the palette dict and is weathered consistently."""
    w = lambda k, d="#888888": weather(palette.get(k, d), wear)  # noqa: E731
    return {
        "wall": MaterialDef("wall", w("wall"), wall_kind, 0.92, 0.0, 2.4),
        "wall2": MaterialDef("wall2", w("wall2", palette.get("wall", "#cccccc")), wall2_kind or wall_kind, 0.85, 0.0, 1.6),
        "trim": MaterialDef("trim", w("trim"), "plaster", 0.8, 0.0, 2.0),
        "base": MaterialDef("base", w("base"), base_kind, 0.95, 0.0, 2.2),
        "roof": MaterialDef("roof", w("roof"), roof_kind, 0.8, 0.0, 1.6),
        "roof_cap": MaterialDef("roof_cap", weather(palette.get("roof", "#554433"), wear + 0.2), "plaster", 0.8, 0.0, 1.0),
        "timber": MaterialDef("timber", w("timber", "#4A3526"), "timber", 0.75, 0.0, 1.5),
        "door": MaterialDef("door", w("door"), "wood", 0.6, 0.0, 1.5),
        "frame": MaterialDef("frame", w("frame"), None, 0.55, 0.0),
        "shutter": MaterialDef("shutter", w("shutter", palette.get("accent", "#335544")), "timber", 0.7, 0.0, 1.5),
        "brick": MaterialDef("brick", w("brick", "#9A5B45"), "brick", 0.9, 0.0, 1.6),
        "deck": MaterialDef("deck", w("deck", "#8A6A4A"), "planks", 0.8, 0.0, 1.6),
        "metal": MaterialDef("metal", w("metal", "#2E3236"), None, 0.5, 0.6),
        "glass": MaterialDef("glass", "#6F9DB3", "glass", 0.08, 0.0, 1.0),
        "glass_lit": MaterialDef("glass_lit", "#F2D08A", "glass", 0.25, 0.0, 1.0),
        "plant": MaterialDef("plant", "#4C8A3E", None, 0.95, 0.0),
        "plant2": MaterialDef("plant2", "#6FA84B", None, 0.95, 0.0),
        "flower": MaterialDef("flower", w("flower", "#D8574A"), None, 0.9, 0.0),
        "accent": MaterialDef("accent", w("accent"), "plaster", 0.7, 0.0, 2.0),
        "dark": MaterialDef("dark", "#3A2F2A", "timber", 0.9, 0.0, 1.5),
        "framing": MaterialDef("framing", "#D9A25A", "timber", 0.75, 0.0, 1.5),
        "soil": MaterialDef("soil", "#A06C3E", "concrete", 0.98, 0.0, 1.6),
        "concrete": MaterialDef("concrete", "#B8B5AE", "concrete", 0.95, 0.0, 2.0),
        "grass": MaterialDef("grass", "#5C8F3A", "stucco", 0.98, 0.0, 1.8),
    }


def overlay_window(mb: MeshBuilder, m: dict[str, str], cx: float, y0: float, w: float, h: float, round_top: bool = False, lit: bool = False) -> None:
    """Window applied on top of a plain wall (attic / dormer): frame ring, glass, cross bars and a small sill."""
    f, p = 0.08, 0.07
    bbox(mb, m["trim"], (cx - w / 2 - f, y0 - f, 0), (cx + w / 2 + f, y0, p), 0.015, faces=("+z", "-y", "+x", "-x", "+y"))
    bbox(mb, m["trim"], (cx - w / 2 - f, y0 + h, 0), (cx + w / 2 + f, y0 + h + f, p), 0.015, faces=("+z", "+y", "+x", "-x", "-y"))
    bbox(mb, m["trim"], (cx - w / 2 - f, y0, 0), (cx - w / 2, y0 + h, p), 0.015, faces=("+z", "-x", "+x"))
    bbox(mb, m["trim"], (cx + w / 2, y0, 0), (cx + w / 2 + f, y0 + h, p), 0.015, faces=("+z", "-x", "+x"))
    facing_quad(mb, m["glass_lit"] if lit else m["glass"], cx - w / 2, cx + w / 2, y0, y0 + h, p * 0.5, tile=1.0)
    bbox(mb, m["frame"], (cx - 0.018, y0, p * 0.5), (cx + 0.018, y0 + h, p), faces=("+z",))
    bbox(mb, m["frame"], (cx - w / 2, y0 + h / 2 - 0.018, p * 0.5), (cx + w / 2, y0 + h / 2 + 0.018, p), faces=("+z",))
    bbox(mb, m["trim"], (cx - w / 2 - f - 0.05, y0 - f - 0.05, 0), (cx + w / 2 + f + 0.05, y0 - f + 0.02, p + 0.06), 0.015, faces=("+z", "+y", "-y", "+x", "-x"))


def garage_dressing(mb: MeshBuilder, m: dict[str, str], o: Opening, reveal: float) -> None:
    """Sectional garage door: recessed leaf in horizontal panels with a row of small windows, plus a heavy casing."""
    zf = -reveal * 0.5
    n = 4
    h = o.y1 - o.y0
    for i in range(n):
        ya = o.y0 + h * i / n
        yb = o.y0 + h * (i + 1) / n
        bbox(mb, m["door"], (o.x0 + 0.03, ya + 0.012, zf - 0.04), (o.x1 - 0.03, yb - 0.012, zf + 0.04), 0.01, faces=("+z",))
    ya = o.y0 + h * (n - 1) / n + 0.1
    yb = o.y1 - 0.1
    k = 4
    gw = (o.w - 0.4) / k
    for i in range(k):
        x = o.x0 + 0.2 + i * gw
        facing_quad(mb, m["glass"], x + 0.05, x + gw - 0.05, ya, yb, zf + 0.045, tile=1.0)
    c, p = 0.16, 0.07
    bbox(mb, m["trim"], (o.x0 - c, o.y0, 0), (o.x0, o.y1 + 0.02, p), 0.012, faces=("-x", "+z", "+x"))
    bbox(mb, m["trim"], (o.x1, o.y0, 0), (o.x1 + c, o.y1 + 0.02, p), 0.012, faces=("+x", "+z", "-x"))
    bbox(mb, m["trim"], (o.x0 - c, o.y1, 0), (o.x1 + c, o.y1 + 0.2, p + 0.04), 0.015, faces=("+x", "-x", "+y", "+z", "-y"))


def shrub(mb: MeshBuilder, m: dict[str, str], x: float, z: float, r: float = 0.45, light: bool = False) -> None:
    """Low-poly rounded bush (three faceted rings + cap): ~35 triangles. Frame-local coordinates, base at y=0."""
    mat = m["plant2"] if light else m["plant"]
    n = 7
    rings = [(0.0, r * 0.62), (r * 0.55, r), (r * 1.0, r * 0.72)]
    top = (x, r * 1.28, z)
    pts = [[(x + rr * math.cos(2 * math.pi * i / n + 0.4 * k), y, z + rr * math.sin(2 * math.pi * i / n + 0.4 * k)) for i in range(n)]
           for k, (y, rr) in enumerate(rings)]
    ctr = (x, r * 0.6, z)
    for k in range(len(rings) - 1):
        for i in range(n):
            a, b = pts[k][i], pts[k][(i + 1) % n]
            c, d = pts[k + 1][(i + 1) % n], pts[k + 1][i]
            mb.quad(mat, a, b, c, d, outward=ctr)
    for i in range(n):
        mb.tri_out(mat, pts[-1][i], pts[-1][(i + 1) % n], top, ctr)


# ------------------------------------------------------------------------------------------------ construction stages
def beam(mb: MeshBuilder, mat: str, p0: Vec, p1: Vec, w: float = 0.08, h: float = 0.14, up: Vec = (0, 1, 0)) -> None:
    """Rectangular beam between two points (``w`` across, ``h`` along the ``up`` direction)."""
    a, b = np.asarray(p0, dtype=float), np.asarray(p1, dtype=float)
    d = b - a
    ln = float(np.linalg.norm(d))
    if ln < 1e-6:
        return
    d /= ln
    side = np.cross(d, np.asarray(up, dtype=float))
    if np.linalg.norm(side) < 1e-6:
        side = np.cross(d, np.array([1.0, 0, 0]))
    side /= np.linalg.norm(side)
    nrm = np.cross(side, d)
    ring = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    pa = [a + sx * side * w / 2 + sy * nrm * h / 2 for sx, sy in ring]
    pb = [b + sx * side * w / 2 + sy * nrm * h / 2 for sx, sy in ring]
    ctr = tuple((a + b) / 2)
    for i in range(4):
        j = (i + 1) % 4
        mb.quad(mat, tuple(pa[i]), tuple(pa[j]), tuple(pb[j]), tuple(pb[i]), outward=ctr)  # type: ignore[arg-type]
    mb.quad(mat, *(tuple(p) for p in pa), outward=ctr)  # type: ignore[arg-type]
    mb.quad(mat, *(tuple(p) for p in pb), outward=ctr)  # type: ignore[arg-type]


def framing_wall(mb: MeshBuilder, mat: str, x0: float, x1: float, y0: float, y1: float, ops: Sequence[Opening], stud: float = 0.6,
                 t: float = 0.09, d: float = 0.14) -> None:
    """Timber wall frame (plates, studs, king/jack studs, headers, sills) in the facade frame, inside the wall plane."""
    faces = ("+z", "+x", "-x", "+y", "-y")
    bbox(mb, mat, (x0, y0, -d), (x1, y0 + t, 0), faces=faces)
    bbox(mb, mat, (x0, y1 - 2 * t, -d), (x1, y1, 0), faces=faces)
    lo, hi = y0 + t, y1 - 2 * t
    n = max(1, int((x1 - x0) / stud))
    xs = [x0 + (x1 - x0) * i / n for i in range(n + 1)]
    for x in xs:
        if any(o.x0 - 0.1 < x < o.x1 + 0.1 for o in ops):
            continue
        a, b = max(x0, x - t / 2), min(x1, x + t / 2)
        bbox(mb, mat, (a, lo, -d), (b, hi, 0), faces=("+z", "+x", "-x"))
    for o in ops:
        top = o.y1
        for x in (o.x0 - t, o.x1 + t):
            if x0 <= x <= x1:
                bbox(mb, mat, (x - t / 2, lo, -d), (x + t / 2, hi, 0), faces=("+z", "+x", "-x"))
        bbox(mb, mat, (o.x0 - t, top, -d), (o.x1 + t, top + 0.16, 0), faces=faces)
        if o.kind == "window":
            bbox(mb, mat, (o.x0 - t, o.y0 - 0.07, -d), (o.x1 + t, o.y0, 0), faces=faces)
            for x in xs:
                if o.x0 < x < o.x1:
                    bbox(mb, mat, (x - t / 2, lo, -d), (x + t / 2, o.y0 - 0.07, 0), faces=("+z", "+x", "-x"))
        for x in xs:
            if o.x0 < x < o.x1 and top + 0.16 < hi:
                bbox(mb, mat, (x - t / 2, top + 0.16, -d), (x + t / 2, hi, 0), faces=("+z", "+x", "-x"))


def gable_framing(mb: MeshBuilder, mat: str, x0: float, x1: float, z0: float, z1: float, y_eave: float, pitch_deg: float, ov_eave: float = 0.5,
                  ov_rake: float = 0.35, spacing: float = 0.6, slopes: Sequence[str] = ("front", "back"), battens: bool = False) -> float:
    """Rafters, ridge beam and ceiling ties of a gable roof (ridge along X), matching :func:`gable_roof`. Returns the ridge height."""
    zc, hz = (z0 + z1) / 2, (z1 - z0) / 2
    t = math.tan(math.radians(pitch_deg))
    y_r = y_eave + hz * t
    ze = hz + ov_eave
    ye = y_r - ze * t
    xa, xb = x0 - ov_rake, x1 + ov_rake
    n = max(1, int((xb - xa) / spacing))
    xs = [xa + (xb - xa) * i / n for i in range(n + 1)]
    bbox(mb, mat, (xa, y_r - 0.12, zc - 0.05), (xb, y_r + 0.1, zc + 0.05), faces=("+x", "-x", "+y", "+z", "-z"))
    for x in xs:
        if "front" in slopes:
            beam(mb, mat, (x, ye, zc + ze), (x, y_r, zc), 0.06, 0.16)
        if "back" in slopes:
            beam(mb, mat, (x, ye, zc - ze), (x, y_r, zc), 0.06, 0.16)
        if x0 <= x <= x1:
            beam(mb, mat, (x, y_eave - 0.04, z0), (x, y_eave - 0.04, z1), 0.06, 0.14)
            beam(mb, mat, (x, y_eave + hz * t * 0.5, zc - hz * 0.5), (x, y_eave + hz * t * 0.5, zc + hz * 0.5), 0.05, 0.1)
    if battens:
        for sgn, name in ((1, "front"), (-1, "back")):
            if name in slopes:
                for k in range(1, 7):
                    f = k / 7
                    beam(mb, mat, (xa, ye + (y_r - ye) * f, zc + sgn * ze * (1 - f)), (xb, ye + (y_r - ye) * f, zc + sgn * ze * (1 - f)), 0.04, 0.05)
    return y_r


def bare_opening(mb: MeshBuilder, mat: str, o: Opening, reveal: float) -> None:
    """Unglazed opening: just the wooden frame set in the reveal (construction stage)."""
    t, z0 = 0.07, -reveal * 0.7
    bbox(mb, mat, (o.x0, o.y0, z0), (o.x0 + t, o.y1, z0 + 0.1), faces=("+z", "+x", "-x"))
    bbox(mb, mat, (o.x1 - t, o.y0, z0), (o.x1, o.y1, z0 + 0.1), faces=("+z", "+x", "-x"))
    bbox(mb, mat, (o.x0, o.y1 - t, z0), (o.x1, o.y1, z0 + 0.1), faces=("+z", "-y", "+y"))
    if o.kind == "window":
        bbox(mb, mat, (o.x0, o.y0, z0), (o.x1, o.y0 + t, z0 + 0.1), faces=("+z", "+y"))


def hip_framing(mb: MeshBuilder, mat: str, x0: float, x1: float, z0: float, z1: float, y_eave: float, pitch_deg: float, ov: float = 0.5,
                spacing: float = 0.6, skip: Sequence[str] = ()) -> float:
    """Ridge, common rafters, hip rafters and jack rafters of a hip roof matching :func:`hip_roof`. Returns the ridge height."""
    t = math.tan(math.radians(pitch_deg))
    cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
    hx, hz = (x1 - x0) / 2 + ov, (z1 - z0) / 2 + ov
    short = min(hx, hz)
    rl = max(hx, hz) - short
    along_x = hx >= hz
    y_r = y_eave + short * t
    A, Bh = (hx, hz) if along_x else (hz, hx)

    def P(a: float, b: float, y: float) -> Vec:
        return (cx + a, y, cz + b) if along_x else (cx + b, y, cz + a)

    if rl > 0.05:
        beam(mb, mat, P(-rl, 0, y_r), P(rl, 0, y_r), 0.07, 0.18)
    n = max(1, int(2 * rl / spacing)) if rl > 0.05 else 0
    for i in range(n + 1 if n else 0):
        a = -rl + 2 * rl * i / n
        for s in (1, -1):
            if ("front" if s > 0 else "back") not in skip:
                beam(mb, mat, P(a, s * Bh, y_eave), P(a, 0, y_r), 0.06, 0.16)
        beam(mb, mat, P(a, -(Bh - ov), y_eave - 0.05), P(a, Bh - ov, y_eave - 0.05), 0.06, 0.14)
    for sa in (1, -1):
        for sb in (1, -1):
            beam(mb, mat, P(sa * A, sb * Bh, y_eave), P(sa * rl, 0, y_r), 0.07, 0.17)
        k = max(1, int(Bh / spacing))
        for j in range(1, k):
            b = Bh * j / k
            for sb in (1, -1):
                tt = 1 - b / Bh
                beam(mb, mat, P(sa * A, sb * b, y_eave), P(sa * (A + tt * (rl - A)), sb * Bh * (1 - tt), y_eave + tt * (y_r - y_eave)), 0.05, 0.14)
    return y_r


def shed_framing(mb: MeshBuilder, mat: str, x0: float, x1: float, z0: float, z1: float, y_low: float, pitch_deg: float, ov: float = 0.4,
                 spacing: float = 0.6, high_side: str = "-z") -> float:
    t = math.tan(math.radians(pitch_deg))
    depth = (z1 - z0) + 2 * ov
    y_hi = y_low + depth * t
    xa, xb = x0 - ov, x1 + ov
    za, zb = z0 - ov, z1 + ov
    n = max(1, int((xb - xa) / spacing))
    for i in range(n + 1):
        x = xa + (xb - xa) * i / n
        if high_side == "-z":
            beam(mb, mat, (x, y_low, zb), (x, y_hi, za), 0.06, 0.16)
        else:
            beam(mb, mat, (x, y_low, za), (x, y_hi, zb), 0.06, 0.16)
    return y_hi
