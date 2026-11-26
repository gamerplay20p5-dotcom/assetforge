"""End-to-end building pipeline: generate -> optimize -> validate -> export -> thumbnail -> verify -> package.

The pipeline runs inside a worker subprocess. Progress is reported through ``emit`` only when a stage
has really started/finished; nothing here fabricates progress.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from assetforge_contract import (
    AssetManifest,
    BuildingParams,
    ColliderInfo,
    ConnectionPoint,
    FileEntry,
    LodInfo,
    MaterialInfo,
    QualityProfile,
    ValidationCheck,
    ValidationReport,
    triangle_budget,
)
from assetforge_optimization import clean_mesh
from assetforge_procedural import GENERATOR_ID, GENERATOR_VERSION, generate_building
from assetforge_validation import check_mesh_spec, validate_glb

from .blender_runner_path import RUNNER_PATH
from .glb import render_textures, write_glb
from .proc import JobCancelled, run_supervised
from .thumbnail import render_thumbnail

# (stage, relative weight). The worker sends this plan to the server; progress only advances when a
# stage has actually finished.
STAGE_PLAN: list[tuple[str, float]] = [
    ("generate_geometry", 8), ("optimize", 4), ("validate_geometry", 4), ("textures", 10), ("export", 40),
    ("thumbnail", 16), ("validate_outputs", 8), ("package", 10),
]
STAGES = [n for n, _ in STAGE_PLAN]

Emit = Callable[[dict], None]


class PipelineError(Exception):
    """A deliberate, user-explainable failure (validation failed, Blender missing, ...)."""


def find_blender() -> str | None:
    cand = os.environ.get("BLENDER_BIN")
    if cand and Path(cand).is_file():
        return cand
    return shutil.which("blender")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_entry(path: Path, root: Path, role: str, fmt: str) -> FileEntry:
    return FileEntry(name=path.relative_to(root).as_posix(), role=role, format=fmt, size=path.stat().st_size,
                     sha256=sha256_file(path))  # type: ignore[arg-type]


def run_building_job(job: dict, workdir: Path, emit: Emit, *, engine: str = "auto", blender_bin: str | None = None,
                     threads: int = 2, blender_timeout: float = 600.0,
                     should_cancel: Callable[[], bool] | None = None) -> dict:
    """Execute a ``procedural.building`` job. ``job`` carries asset_id, name, version, params, formats..."""
    cancel = should_cancel or (lambda: False)

    def stage(name: str, status: str, **extra) -> None:
        emit({"type": "stage", "name": name, "status": status, **extra})
        if status == "start" and cancel():
            raise JobCancelled()

    def log(msg: str, level: str = "info") -> None:
        emit({"type": "log", "level": level, "message": msg})

    params = BuildingParams.model_validate(job["params"])
    profile = QualityProfile(job.get("quality_profile", "stylized_standard"))
    formats = list(job.get("formats") or ["glb"])
    out = workdir / "out"
    out.mkdir(parents=True, exist_ok=True)
    blender = blender_bin or find_blender()
    use_blender = engine == "blender" or (engine == "auto" and blender is not None)
    if ("blend" in formats or "fbx" in formats) and not use_blender:
        raise PipelineError("formats 'blend'/'fbx' need a Blender engine, but no Blender executable is available on this worker")
    if use_blender and not blender:
        raise PipelineError("engine 'blender' requested but BLENDER_BIN is not set / blender not found")
    engine_used = "blender" if use_blender else "trimesh"
    log(f"engine={engine_used} seed={params.seed} category={params.category} style={params.style}")

    # 1. geometry --------------------------------------------------------------------------
    stage("generate_geometry", "start")
    gen = generate_building(params)
    log(f"generated {gen.mesh.triangle_count} triangles, {len(gen.materials)} materials, "
        f"summary={json.dumps(gen.summary)}")
    stage("generate_geometry", "done", detail=f"{gen.mesh.triangle_count} triangles")

    # 2. optimize --------------------------------------------------------------------------
    stage("optimize", "start")
    spec, stats = clean_mesh(gen.mesh)
    log(f"clean: degenerate={stats.degenerate_removed} welded={stats.duplicate_vertices_merged} "
        f"normals_fixed={stats.normals_fixed} {'; '.join(stats.notes)}")
    stage("optimize", "done")

    # 3. validate geometry ------------------------------------------------------------------
    stage("validate_geometry", "start")
    geo_report = check_mesh_spec(spec, params.category, profile, job.get("triangle_limit"))
    for c in geo_report.checks:
        if c.status in ("warn", "fail"):
            log(f"validation {c.status}: {c.name} - {c.detail}", "warning" if c.status == "warn" else "error")
    if not geo_report.passed:
        raise PipelineError("geometry validation failed: " + "; ".join(f"{c.name}: {c.detail}" for c in geo_report.errors))
    stage("validate_geometry", "done")

    # 4. textures ---------------------------------------------------------------------------
    stage("textures", "start")
    tex_dir = out / "textures"
    textures = render_textures(gen.materials, params.texture_resolution, tex_dir)
    log(f"textures: {', '.join(p.name for p in textures.values())}")
    stage("textures", "done")

    # 5/6. export + thumbnail ------------------------------------------------------------------
    glb_path = out / "model.glb"
    thumb_path = out / "thumbnail.png"
    extras = {"assetId": job["asset_id"], "generator": GENERATOR_ID, "seed": params.seed}
    if use_blender:
        spec_npz = workdir / "spec.npz"
        spec.save_npz(str(spec_npz))
        cfg = {
            "spec_npz": str(spec_npz), "out_dir": str(out), "asset_name": job["name"], "formats": formats,
            "thumbnail_size": job.get("thumbnail_size", 512), "thumbnail_samples": job.get("thumbnail_samples", 24),
            "materials": {n: {"color": m.color, "texture": m.texture, "roughness": m.roughness, "metallic": m.metallic}
                          for n, m in gen.materials.items()},
            "textures": {k: str(v) for k, v in textures.items()},
        }
        cfg_path = workdir / "blender_config.json"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        stage("export", "start")
        state = {"thumb": False}

        def on_line(line: str) -> None:
            if line.startswith("@@EVENT "):
                ev = json.loads(line[8:])
                log(f"blender: {ev['stage']} {ev['status']}")
                if ev["stage"] == "thumbnail" and ev["status"] == "start":
                    stage("export", "done")
                    stage("thumbnail", "start")
                    state["thumb"] = True
            elif line.strip() and not line.startswith(("Fra:", "Saved:", "Time:")):
                log("blender: " + line.strip()[:300])

        assert blender is not None
        cmd = [blender, "-b", "--factory-startup", "--threads", str(max(1, threads)), "--python", str(RUNNER_PATH), "--", str(cfg_path)]
        run_supervised(cmd, timeout=blender_timeout, on_line=on_line, should_cancel=cancel)
        if not state["thumb"]:
            stage("export", "done")
            stage("thumbnail", "start")
        stage("thumbnail", "done")
    else:
        stage("export", "start")
        write_glb(glb_path, spec, gen.materials, textures, job["name"], extras)
        stage("export", "done")
        stage("thumbnail", "start")
        render_thumbnail(spec, gen.materials, thumb_path, size=int(job.get("thumbnail_size", 512)))
        stage("thumbnail", "done")

    # 7. validate outputs ---------------------------------------------------------------------
    stage("validate_outputs", "start")
    lo, hi = spec.bounds()
    dims = tuple(float(x) for x in (hi - lo))
    glb_report = validate_glb(glb_path, expected_triangles=spec.triangle_count, expected_dims=dims)  # type: ignore[arg-type]
    expected_files = [thumb_path] + [out / f"model.{f}" for f in formats]
    missing = [p.name for p in expected_files if not p.is_file() or p.stat().st_size == 0]
    file_checks = [ValidationCheck(name="files_exist", status="fail" if missing else "pass",
                                   detail=f"missing or empty: {missing}" if missing else "all requested outputs exist")]
    report = ValidationReport(
        passed=geo_report.passed and glb_report.passed and not missing,
        checks=[*geo_report.checks, *glb_report.checks, *file_checks],
        metrics={**geo_report.metrics, **glb_report.metrics, "engine": engine_used},
    )
    for c in glb_report.checks + file_checks:
        log(f"output check {c.name}: {c.status} {c.detail}", "info" if c.status == "pass" else "error")
    if not report.passed:
        raise PipelineError("output validation failed: " + "; ".join(f"{c.name}: {c.detail}" for c in report.errors))
    stage("validate_outputs", "done")

    # 8. manifest + package -----------------------------------------------------------------------
    stage("package", "start")
    files: list[FileEntry] = [_file_entry(glb_path, out, "interchange", "glb"),
                              _file_entry(thumb_path, out, "preview", "png")]
    if "blend" in formats:
        files.append(_file_entry(out / "model.blend", out, "editable", "blend"))
    if "fbx" in formats:
        files.append(_file_entry(out / "model.fbx", out, "model", "fbx"))
    for p in sorted(tex_dir.glob("*.png")):
        files.append(_file_entry(p, out, "texture", "png"))
    (out / "validation.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    files.append(_file_entry(out / "validation.json", out, "report", "json"))

    b_lo, b_hi = triangle_budget(params.category, profile, job.get("triangle_limit"))
    centre = (lo + hi) / 2
    manifest = AssetManifest(
        asset_id=job["asset_id"], name=job["name"], category=params.category, version=int(job.get("version", 1)),
        art_profile=gen.summary["art_profile"], seed=params.seed, generator_id=GENERATOR_ID,
        generator_version=GENERATOR_VERSION, quality_profile=profile.value,
        dimensions_m=(round(dims[0], 4), round(dims[1], 4), round(dims[2], 4)),
        footprint_m=(round(dims[0], 4), round(dims[2], 4)),
        bounding_box=((float(lo[0]), float(lo[1]), float(lo[2])), (float(hi[0]), float(hi[1]), float(hi[2]))),
        connection_points=[ConnectionPoint(**cp) for cp in gen.connection_points],
        materials=[MaterialInfo(name=n, base_color=m.color, texture=f"textures/tex_{m.texture}_{params.texture_resolution}.png"
                                if m.texture else None, roughness=m.roughness, metallic=m.metallic,
                                tile_meters=m.tile_m if m.texture else None) for n, m in gen.materials.items()],
        textures=[f.name for f in files if f.role == "texture"],
        lods=[LodInfo(level=0, triangles=spec.triangle_count, file="model.glb")],
        colliders=[ColliderInfo(type="box", center=(0.0, round(dims[1] / 2, 4), 0.0),
                                size=(round(dims[0], 4), round(dims[1], 4), round(dims[2], 4)))],
        triangle_count=spec.triangle_count, triangle_budget=(b_lo, b_hi),
        provenance={"generator": f"{GENERATOR_ID}@{GENERATOR_VERSION}", "engine": engine_used,
                    "job_id": str(job.get("job_id", "")), "inputs": "parameters only (no third-party assets)"},
        engine=engine_used, generation_params=params.model_dump(mode="json") | {"summary": gen.summary},
        files=files, created_at=datetime.now(UTC),
    )
    manifest_path = out / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    pkg = out / f"{job['asset_id']}_v{manifest.version}.zip"
    with zipfile.ZipFile(pkg, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(out / f.name, f.name)
        zf.write(manifest_path, "manifest.json")
    files.append(_file_entry(manifest_path, out, "metadata", "json"))
    files.append(_file_entry(pkg, out, "package", "zip"))
    stage("package", "done")
    return {
        "files": [f.model_dump() for f in files],
        "manifest": json.loads(manifest_path.read_text(encoding="utf-8")),
        "validation": json.loads(report.model_dump_json()),
        "engine": engine_used,
        "triangle_count": spec.triangle_count,
    }
