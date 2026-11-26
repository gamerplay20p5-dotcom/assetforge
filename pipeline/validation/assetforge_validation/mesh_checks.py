"""Validation of generated geometry before export."""

from __future__ import annotations

import numpy as np
from assetforge_contract import QualityProfile, ValidationCheck, ValidationReport, triangle_budget
from assetforge_procedural import MeshSpec

MAX_MATERIALS_WARN = 16


def check_mesh_spec(spec: MeshSpec, category: str, profile: QualityProfile | str,
                    triangle_limit: int | None = None) -> ValidationReport:
    checks: list[ValidationCheck] = []
    metrics: dict[str, float | int | str] = {}

    def add(name: str, status: str, detail: str = "") -> None:
        checks.append(ValidationCheck(name=name, status=status, detail=detail))  # type: ignore[arg-type]

    if not spec.parts:
        add("geometry_present", "fail", "mesh has no geometry")
        return ValidationReport(passed=False, checks=checks)
    add("geometry_present", "pass")

    verts = np.concatenate([p.vertices for p in spec.parts.values()])
    finite = bool(np.isfinite(verts).all())
    add("finite_vertices", "pass" if finite else "fail", "" if finite else "NaN/Inf in vertex positions")

    tris = spec.triangle_count
    metrics["triangles"] = tris
    metrics["vertices"] = spec.vertex_count
    metrics["materials"] = len(spec.parts)

    degenerate = 0
    inverted = 0
    uv_missing = 0
    uv_extreme = 0
    for p in spec.parts.values():
        t = p.vertices[p.faces].astype(np.float64)
        cr = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        ar = np.linalg.norm(cr, axis=1)
        degenerate += int((ar < 1e-10).sum())
        fn = cr / np.maximum(ar[:, None], 1e-30)
        sn = p.normals[p.faces[:, 0]]
        inverted += int((np.einsum("ij,ij->i", fn, sn) < 0.0).sum())
        if p.uvs.shape[0] != p.vertices.shape[0]:
            uv_missing += 1
        elif not np.isfinite(p.uvs).all() or np.abs(p.uvs).max() > 1000:
            uv_extreme += 1
    add("degenerate_triangles", "pass" if degenerate == 0 else "fail", f"{degenerate} degenerate triangles")
    add("normals_match_winding", "pass" if inverted == 0 else "fail", f"{inverted} faces disagree with their normals")
    add("uv_present", "pass" if uv_missing == 0 else "fail", f"{uv_missing} parts without UVs")
    add("uv_range", "pass" if uv_extreme == 0 else "warn", f"{uv_extreme} parts with extreme UVs")

    lo, hi = spec.bounds()
    dims = hi - lo
    metrics.update(width=round(float(dims[0]), 3), height=round(float(dims[1]), 3), depth=round(float(dims[2]), 3))
    sane = bool((dims > 0.05).all() and (dims < 500).all())
    add("scale_sane", "pass" if sane else "fail", f"bounding box {dims.round(2).tolist()} m (expected 1 unit = 1 m)")
    pivot_ok = abs(lo[1]) < 1e-3 and abs((lo[0] + hi[0]) / 2) < 1e-3 and abs((lo[2] + hi[2]) / 2) < 1e-3
    add("pivot_bottom_center", "pass" if pivot_ok else "fail",
        "" if pivot_ok else f"bounds {lo.round(3).tolist()}..{hi.round(3).tolist()}")

    b_lo, b_hi = triangle_budget(category, profile, triangle_limit)
    metrics["triangle_budget_min"], metrics["triangle_budget_max"] = b_lo, b_hi
    if tris > b_hi:
        add("triangle_budget", "warn",
            f"{tris} triangles exceed the budget of {b_hi} ({category}, {QualityProfile(profile).value})")
    elif tris < b_lo:
        add("triangle_budget", "pass", f"{tris} triangles (below the target range {b_lo}-{b_hi}; simple asset)")
    else:
        add("triangle_budget", "pass", f"{tris} within {b_lo}-{b_hi}")
    add("material_count", "pass" if len(spec.parts) <= MAX_MATERIALS_WARN else "warn",
        f"{len(spec.parts)} materials (draw calls per LOD)")
    return ValidationReport(passed=not any(c.status == "fail" for c in checks), checks=checks, metrics=metrics)
