"""Mesh construction primitives shared by every procedural generator.

Conventions: meters, Y-up, right-handed, counter-clockwise front faces, flat-shaded (hard edges).
UVs are planar and expressed in meters / tile size, so tiling textures keep a consistent texel density.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field

import numpy as np

Vec = tuple[float, float, float]
ALL_FACES = ("+x", "-x", "+y", "-y", "+z", "-z")


@dataclass
class MeshPart:
    """Geometry that shares a single material."""

    vertices: np.ndarray  # (n,3) float32
    normals: np.ndarray  # (n,3) float32
    uvs: np.ndarray  # (n,2) float32
    faces: np.ndarray  # (m,3) int32


@dataclass
class MeshSpec:
    """Finished geometry grouped by material name."""

    parts: dict[str, MeshPart] = field(default_factory=dict)

    @property
    def triangle_count(self) -> int:
        return int(sum(len(p.faces) for p in self.parts.values()))

    @property
    def vertex_count(self) -> int:
        return int(sum(len(p.vertices) for p in self.parts.values()))

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        verts = np.concatenate([p.vertices for p in self.parts.values()])
        return verts.min(axis=0), verts.max(axis=0)

    def save_npz(self, path: str) -> None:
        arrays: dict[str, np.ndarray] = {}
        for name, p in self.parts.items():
            arrays[f"{name}__v"] = p.vertices
            arrays[f"{name}__n"] = p.normals
            arrays[f"{name}__uv"] = p.uvs
            arrays[f"{name}__f"] = p.faces
        np.savez_compressed(path, **arrays)

    @staticmethod
    def load_npz(path: str) -> MeshSpec:
        spec = MeshSpec()
        with np.load(path) as data:
            names = sorted({k.rsplit("__", 1)[0] for k in data.files})
            for n in names:
                spec.parts[n] = MeshPart(data[f"{n}__v"], data[f"{n}__n"], data[f"{n}__uv"], data[f"{n}__f"])
        return spec


def _sub(a: Sequence[float], b: Sequence[float]) -> np.ndarray:
    return np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64)


class MeshBuilder:
    """Accumulates quads/triangles per material, with a yaw+translate transform stack."""

    def __init__(self, tile_m: float = 2.0) -> None:
        self.tile_m = tile_m
        self._tris: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {}  # mat -> [(3x3 verts, 3x2 uv)]
        self._rot = np.eye(3)
        self._off = np.zeros(3)

    # ---------------------------------------------------------------- transforms
    @contextmanager
    def transform(self, yaw_deg: float = 0.0, offset: Vec = (0, 0, 0)) -> Iterator[None]:
        """Compose a rotation about +Y (degrees, CCW seen from above) and a translation."""
        saved = (self._rot, self._off)
        a = math.radians(yaw_deg)
        c, s = math.cos(a), math.sin(a)
        r = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
        self._off = self._rot @ np.asarray(offset, dtype=np.float64) + self._off
        self._rot = self._rot @ r
        try:
            yield
        finally:
            self._rot, self._off = saved

    def _w(self, p: Sequence[float]) -> np.ndarray:
        return self._rot @ np.asarray(p, dtype=np.float64) + self._off

    # ---------------------------------------------------------------- primitives
    def _uv_planar(self, pts: list[np.ndarray], normal: np.ndarray, tile: float) -> list[tuple[float, float]]:
        ax = int(np.argmax(np.abs(normal)))
        out = []
        for p in pts:
            if ax == 0:
                u, v = p[2], p[1]
            elif ax == 1:
                u, v = p[0], p[2]
            else:
                u, v = p[0], p[1]
            out.append((u / tile, v / tile))
        return out

    def tri(self, mat: str, a: Vec, b: Vec, c: Vec, uv: Sequence[tuple[float, float]] | None = None,
            tile: float | None = None) -> None:
        pts = [np.asarray(p, dtype=np.float64) for p in (a, b, c)]
        n = np.cross(pts[1] - pts[0], pts[2] - pts[0])
        if np.linalg.norm(n) < 1e-9:
            return
        n = n / np.linalg.norm(n)
        uvs = list(uv) if uv is not None else self._uv_planar(pts, n, tile or self.tile_m)
        w = np.array([self._w(p) for p in pts])
        self._tris.setdefault(mat, []).append((w, np.asarray(uvs, dtype=np.float64)))

    def quad(self, mat: str, a: Vec, b: Vec, c: Vec, d: Vec, outward: Vec | None = None,
             uv: Sequence[tuple[float, float]] | None = None, tile: float | None = None) -> None:
        """Add a quad. Vertex order a,b,c,d. If ``outward`` (a point the face must look away from)
        is given, the winding is flipped when needed so the normal points away from that point."""
        pts = [np.asarray(p, dtype=np.float64) for p in (a, b, c, d)]
        if outward is not None:
            n = np.cross(pts[1] - pts[0], pts[3] - pts[0])
            centre = sum(pts) / 4.0
            if np.dot(n, centre - np.asarray(outward, dtype=np.float64)) < 0:
                pts = [pts[0], pts[3], pts[2], pts[1]]
                if uv is not None:
                    uv = [uv[0], uv[3], uv[2], uv[1]]
        n = np.cross(pts[1] - pts[0], pts[3] - pts[0])
        if np.linalg.norm(n) < 1e-12:
            n = np.cross(pts[2] - pts[1], pts[3] - pts[1])
        n = n / (np.linalg.norm(n) or 1.0)
        uvs = list(uv) if uv is not None else self._uv_planar(pts, n, tile or self.tile_m)
        self._add_tri(mat, pts[0], pts[1], pts[2], uvs[0], uvs[1], uvs[2])
        self._add_tri(mat, pts[0], pts[2], pts[3], uvs[0], uvs[2], uvs[3])

    def _add_tri(self, mat: str, p0, p1, p2, u0, u1, u2) -> None:
        if np.linalg.norm(np.cross(p1 - p0, p2 - p0)) < 1e-10:
            return
        w = np.array([self._w(p) for p in (p0, p1, p2)])
        self._tris.setdefault(mat, []).append((w, np.asarray([u0, u1, u2], dtype=np.float64)))

    def box(self, mat: str, lo: Vec, hi: Vec, faces: Sequence[str] = ALL_FACES,
            tile: float | None = None) -> None:
        """Axis-aligned box in local space; ``faces`` selects visible faces (e.g. ``("+z", "+y")``)."""
        x0, y0, z0 = lo
        x1, y1, z1 = hi
        c = ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
        quads = {
            "+x": ((x1, y0, z1), (x1, y0, z0), (x1, y1, z0), (x1, y1, z1)),
            "-x": ((x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)),
            "+y": ((x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0)),
            "-y": ((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)),
            "+z": ((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)),
            "-z": ((x1, y0, z0), (x0, y0, z0), (x0, y1, z0), (x1, y1, z0)),
        }
        for f in faces:
            self.quad(mat, *quads[f], outward=c, tile=tile)

    def prism(self, mat: str, base_center: Vec, radius: float, height: float, sides: int = 8,
              cap_mat: str | None = None, cap_top: bool = True, tile: float | None = None) -> None:
        """Vertical n-gon prism (columns, tanks, chimneys)."""
        cx, cy, cz = base_center
        ang = [2 * math.pi * i / sides for i in range(sides)]
        ring = [(cx + radius * math.cos(a), cz + radius * math.sin(a)) for a in ang]
        ctr = (cx, cy + height / 2, cz)
        for i in range(sides):
            (x0, z0), (x1, z1) = ring[i], ring[(i + 1) % sides]
            u0, u1 = i / sides * (2 * math.pi * radius / (tile or self.tile_m)), (i + 1) / sides * (
                2 * math.pi * radius / (tile or self.tile_m))
            v1 = height / (tile or self.tile_m)
            self.quad(mat, (x0, cy, z0), (x1, cy, z1), (x1, cy + height, z1), (x0, cy + height, z0),
                      outward=ctr, uv=[(u0, 0), (u1, 0), (u1, v1), (u0, v1)])
        if cap_top:
            top = (cx, cy + height, cz)
            for i in range(sides):
                (x0, z0), (x1, z1) = ring[i], ring[(i + 1) % sides]
                # (top, p[i+1], p[i]) has a +Y normal: cross(a, b).y = sin(theta[i+1] - theta[i]) > 0
                self.tri(cap_mat or mat, top, (x1, cy + height, z1), (x0, cy + height, z0))

    def cone(self, mat: str, base_center: Vec, radius: float, height: float, sides: int = 8) -> None:
        cx, cy, cz = base_center
        apex = (cx, cy + height, cz)
        ctr = (cx, cy + height / 3, cz)
        for i in range(sides):
            a0, a1 = 2 * math.pi * i / sides, 2 * math.pi * (i + 1) / sides
            p0 = (cx + radius * math.cos(a0), cy, cz + radius * math.sin(a0))
            p1 = (cx + radius * math.cos(a1), cy, cz + radius * math.sin(a1))
            n = np.cross(_sub(p1, p0), _sub(apex, p0))
            mid = ((np.asarray(p0) + np.asarray(p1) + np.asarray(apex)) / 3) - np.asarray(ctr)
            if np.dot(n, mid) >= 0:
                self.tri(mat, p0, p1, apex)
            else:
                self.tri(mat, p1, p0, apex)

    def tri_out(self, mat: str, a: Vec, b: Vec, c: Vec, outward: Vec, tile: float | None = None) -> None:
        pts = [np.asarray(p, dtype=np.float64) for p in (a, b, c)]
        n = np.cross(pts[1] - pts[0], pts[2] - pts[0])
        if np.dot(n, sum(pts) / 3 - np.asarray(outward, dtype=np.float64)) < 0:
            a, b, c = a, c, b
        self.tri(mat, a, b, c, tile=tile)

    # ---------------------------------------------------------------- finalize
    def build(self) -> MeshSpec:
        """Weld identical vertices (same position, normal and UV), drop degenerate triangles."""
        spec = MeshSpec()
        for mat, tris in self._tris.items():
            index: dict[tuple, int] = {}
            verts: list[np.ndarray] = []
            norms: list[np.ndarray] = []
            uvs: list[np.ndarray] = []
            faces: list[tuple[int, int, int]] = []
            for w, uv in tris:
                n = np.cross(w[1] - w[0], w[2] - w[0])
                ln = np.linalg.norm(n)
                if ln < 1e-10:
                    continue
                n = n / ln
                ids = []
                for p, t in zip(w, uv, strict=True):
                    key = (*np.round(p, 5), *np.round(n, 3), *np.round(t, 5))
                    i = index.get(key)
                    if i is None:
                        i = len(verts)
                        index[key] = i
                        verts.append(p)
                        norms.append(n)
                        uvs.append(t)
                    ids.append(i)
                faces.append((ids[0], ids[1], ids[2]))
            if faces:
                spec.parts[mat] = MeshPart(
                    np.asarray(verts, dtype=np.float32), np.asarray(norms, dtype=np.float32),
                    np.asarray(uvs, dtype=np.float32), np.asarray(faces, dtype=np.int32))
        return spec
