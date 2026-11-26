"""Independent validation of an exported GLB file.

Structure is parsed with a tiny reader (no third-party glTF library) and the geometry is re-loaded with
trimesh, an unrelated implementation, to cross-check triangle counts and bounds.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np
from assetforge_contract import ValidationCheck, ValidationReport


def read_glb_json(path: Path) -> tuple[dict, int]:
    """Return (gltf json, bin chunk length). Raises ValueError on malformed containers."""
    raw = path.read_bytes()
    if len(raw) < 20:
        raise ValueError("file too small to be a GLB")
    magic, version, length = struct.unpack_from("<III", raw, 0)
    if magic != 0x46546C67:
        raise ValueError("bad GLB magic")
    if version != 2:
        raise ValueError(f"unsupported GLB version {version}")
    if length != len(raw):
        raise ValueError(f"declared length {length} != file size {len(raw)}")
    off, doc, bin_len = 12, None, 0
    while off + 8 <= len(raw):
        clen, ctype = struct.unpack_from("<II", raw, off)
        body = raw[off + 8: off + 8 + clen]
        if len(body) != clen:
            raise ValueError("truncated chunk")
        if ctype == 0x4E4F534A:
            doc = json.loads(body.decode("utf-8"))
        elif ctype == 0x004E4942:
            bin_len = clen
        off += 8 + clen
    if doc is None:
        raise ValueError("missing JSON chunk")
    return doc, bin_len


def validate_glb(path: Path, expected_triangles: int | None = None,
                 expected_dims: tuple[float, float, float] | None = None, tol: float = 0.02) -> ValidationReport:
    checks: list[ValidationCheck] = []
    metrics: dict[str, float | int | str] = {}

    def add(name: str, status: str, detail: str = "") -> None:
        checks.append(ValidationCheck(name=name, status=status, detail=detail))  # type: ignore[arg-type]

    if not path.is_file():
        add("file_exists", "fail", f"{path.name} does not exist")
        return ValidationReport(passed=False, checks=checks)
    metrics["glb_bytes"] = path.stat().st_size
    try:
        doc, bin_len = read_glb_json(path)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError, struct.error) as exc:
        add("glb_container", "fail", str(exc))
        return ValidationReport(passed=False, checks=checks)
    add("glb_container", "pass")

    bad = []
    views = doc.get("bufferViews", [])
    for i, v in enumerate(views):
        if v.get("byteOffset", 0) + v["byteLength"] > bin_len:
            bad.append(f"bufferView {i} exceeds BIN chunk")
    for i, a in enumerate(doc.get("accessors", [])):
        if a.get("bufferView") is not None and a["bufferView"] >= len(views):
            bad.append(f"accessor {i} references missing bufferView")
    n_mat = len(doc.get("materials", []))
    for m in doc.get("meshes", []):
        for prim in m.get("primitives", []):
            if n_mat and prim.get("material", 0) >= n_mat:
                bad.append(f"mesh {m.get('name')} uses unknown material")
            if "POSITION" not in prim.get("attributes", {}):
                bad.append(f"mesh {m.get('name')} has no POSITION")
    add("gltf_references", "pass" if not bad else "fail", "; ".join(bad))
    metrics["gltf_materials"] = n_mat
    metrics["gltf_images"] = len(doc.get("images", []))
    metrics["gltf_meshes"] = len(doc.get("meshes", []))

    try:
        import trimesh

        scene = trimesh.load(str(path), force="scene", process=False)  # raw faces: do not let trimesh silently drop/merge any
        tri_count = int(sum(len(g.faces) for g in scene.geometry.values()))
        bounds = scene.bounds
        dims = (bounds[1] - bounds[0]).tolist()
        metrics["glb_triangles"] = tri_count
        finite = bool(np.isfinite(bounds).all())
        add("reload_trimesh", "pass" if finite and tri_count > 0 else "fail",
            f"{tri_count} triangles, size {np.round(dims, 2).tolist()} m")
        if expected_triangles is not None:
            ok = abs(tri_count - expected_triangles) <= max(2, int(expected_triangles * 0.001))
            add("triangle_count_matches", "pass" if ok else "fail",
                f"exported {tri_count}, expected {expected_triangles}")
        if expected_dims is not None:
            ok = all(abs(a - b) <= max(tol, 0.005 * b) for a, b in zip(dims, expected_dims, strict=True))
            add("dimensions_match", "pass" if ok else "fail",
                f"exported {np.round(dims, 3).tolist()} vs expected {np.round(expected_dims, 3).tolist()}")
        pivot_ok = (abs(bounds[0][1]) < 0.01 and abs((bounds[0][0] + bounds[1][0]) / 2) < 0.05
                    and abs((bounds[0][2] + bounds[1][2]) / 2) < 0.05)
        add("pivot_bottom_center", "pass" if pivot_ok else "fail", f"bounds {np.round(bounds, 3).tolist()}")
    except Exception as exc:  # noqa: BLE001 - the validator must report, never crash the job
        add("reload_trimesh", "fail", f"trimesh could not load the file: {exc}")
    return ValidationReport(passed=not any(c.status == "fail" for c in checks), checks=checks, metrics=metrics)
