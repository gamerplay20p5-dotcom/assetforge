"""Mesh clean-up and normalisation passes (applied before validation and export)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from assetforge_procedural import MeshPart, MeshSpec


@dataclass
class CleanStats:
    degenerate_removed: int = 0
    duplicate_vertices_merged: int = 0
    duplicate_faces_removed: int = 0
    normals_fixed: int = 0
    pivot_shift: tuple[float, float, float] = (0.0, 0.0, 0.0)
    notes: list[str] = field(default_factory=list)


def clean_mesh(spec: MeshSpec, normalize_pivot: bool = True, area_eps: float = 1e-10) -> tuple[MeshSpec, CleanStats]:
    """Drop degenerate triangles, weld identical vertices, recompute normals from winding and move the
    pivot to the bottom center of the bounding box. Never decimates geometry (details are preserved)."""
    stats = CleanStats()
    out = MeshSpec()
    for name, part in spec.parts.items():
        v, n, uv, f = part.vertices.astype(np.float64), part.normals, part.uvs, part.faces
        tri = v[f]
        cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        area = np.linalg.norm(cross, axis=1)
        ok = area > area_eps
        stats.degenerate_removed += int((~ok).sum())
        f = f[ok]
        cross = cross[ok]
        if len(f) == 0:
            continue
        # weld vertices with identical (position, normal, uv)
        key = np.round(np.concatenate([v, n, uv], axis=1), 5)
        _, first, inverse = np.unique(key, axis=0, return_index=True, return_inverse=True)
        inverse = inverse.reshape(-1)
        stats.duplicate_vertices_merged += int(len(v) - len(first))
        used = np.unique(inverse[f])
        remap = -np.ones(len(first), dtype=np.int64)
        remap[used] = np.arange(len(used))
        vi = first[used]
        nf = remap[inverse[f]]
        # identical triangles (same three vertices, e.g. two overlapping beams sharing a face) are redundant: exporters/Blender drop them silently,
        # so drop them here and the reported count always matches the exported file
        _, keep = np.unique(np.sort(nf, axis=1), axis=0, return_index=True)
        if len(keep) < len(nf):
            keep.sort()
            stats.duplicate_faces_removed += int(len(nf) - len(keep))
            nf, cross = nf[keep], cross[keep]
        nv, nn, nuv = part.vertices[vi], n[vi], uv[vi]
        # make stored normals agree with face winding
        fn = cross / np.linalg.norm(cross, axis=1, keepdims=True)
        vn_ref = np.zeros((len(nv), 3))
        np.add.at(vn_ref, nf[:, 0], fn)
        flip = np.einsum("ij,ij->i", vn_ref, nn) < 0
        stats.normals_fixed += int(flip.sum())
        nn = np.where(flip[:, None], -nn, nn)
        out.parts[name] = MeshPart(nv.astype(np.float32), nn.astype(np.float32), nuv.astype(np.float32),
                                   nf.astype(np.int32))
    if normalize_pivot and out.parts:
        lo, hi = out.bounds()
        shift = np.array([-(lo[0] + hi[0]) / 2, -lo[1], -(lo[2] + hi[2]) / 2], dtype=np.float32)
        if np.abs(shift).max() > 1e-4:
            for p in out.parts.values():
                p.vertices = (p.vertices + shift).astype(np.float32)
            stats.pivot_shift = tuple(float(x) for x in shift)  # type: ignore[assignment]
            stats.notes.append("pivot moved to bottom center")
    return out, stats
