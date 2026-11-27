"""Run and package an experimental engine without rewriting its GLB master."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
import trimesh
from assetforge_contract import AssetManifest, LodInfo
from assetforge_contract.engines import ENGINES, RECONSTRUCT, ReconstructionParams
from assetforge_export.pipeline import PipelineError, _file_entry
from assetforge_validation import validate_glb
from PIL import Image, ImageDraw

from .nvidia import CPP_WEIGHTS, sample


def prepare_views(work: Path, params: ReconstructionParams) -> Path:
    poses = {"front": 0, "right": 90, "back": 180, "three_quarter": params.three_quarter_angle}
    names = ENGINES[params.engine]["views"]
    directory = work / "views"
    directory.mkdir()
    images = []
    for view in names:
        with Image.open(work / f"{view}.png") as source:
            rgba = source.convert("RGBA")
        alpha = rgba.getchannel("A")
        box = alpha.point(lambda a: 255 if a >= 128 else 0).getbbox()
        if alpha.getextrema() == (255, 255) or not box:
            raise PipelineError(f"{view}: envie uma PNG recortada com fundo transparente")
        images.append((rgba, box))
    size = 1024
    span = max(max(box[2] - box[0], box[3] - box[1]) for _, box in images)
    scale = 0.85 * size / span
    frames = []
    for index, (view, (image, box)) in enumerate(zip(names, images, strict=True)):
        width, height = box[2] - box[0], box[3] - box[1]
        r = image.crop(box).resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (size, size))
        offset = ((size - r.width) // 2, (size - r.height) // 2)
        canvas.alpha_composite(r, dest=offset)
        filename = f"view{index}.png"
        canvas.save(directory / filename)
        angle = math.radians(poses[view])
        c, s = math.cos(angle), math.sin(angle)
        frames.append({"file_path": filename, "name": view,
                       "transform_matrix": [[c, 0, s, 3.119 * s], [s, 0, -c, -3.119 * c], [0, 1, 0, 0], [0, 0, 0, 1]]})
    (directory / "transforms.json").write_text(json.dumps(
        {"camera_angle_x": math.radians(20), "mesh_scale": params.mesh_scale, "frames": frames}), encoding="utf-8")
    return directory


def cpp_command(work: Path, out: Path, params: ReconstructionParams, views: Path | None, threads: int) -> list[str]:
    if params.engine == "trellis2-gguf":
        inputs = ["--image", str(work / "front.png")]
        options = ["--birefnet", "--dump-bg"]
    elif params.engine == "pixal3d-sv":
        inputs = ["--sv-image", str(views / "view0.png")]
        options = ["--pixal3d-weights", "sv"]
    else:
        inputs = ["--views", str(views)]
        options = ["--pixal3d-weights", "mv"]
    if params.skip_decimation:
        options += ["--decim", "0"]
    models = Path(os.environ.get("ASSETFORGE_ENGINE_MODELS", "/models")) / CPP_WEIGHTS[params.engine]
    return ["trellis-cli", *inputs, "--models", str(models), "--require-gpu",
            "--res", str(params.resolution), "--max-tokens", str(params.max_tokens), "--seed", str(params.seed),
            "--atlas", str(params.texture_size), "--gss", str(params.structure_guidance), "--gsh", str(params.shape_guidance),
            "--threads", str(max(1, threads)), *options, "-o", str(out)]


def execute(work: Path, params: ReconstructionParams, views: Path | None, model: Path, threads: int) -> dict:
    start = time.monotonic()
    baseline = sample()
    lowest = baseline.copy()
    log_path = work / "engine.log"
    broker = params.engine == "pixal3d-python"
    proc = None
    request = work / "python.request.json"
    response = work / "python.response.json"
    log = None
    try:
        if broker:
            tmp = request.with_suffix(".tmp")
            tmp.write_text(params.model_dump_json(), encoding="utf-8")
            tmp.replace(request)
        else:
            log = log_path.open("w", encoding="utf-8")
            proc = subprocess.Popen(cpp_command(work, model, params, views, threads), stdout=log, stderr=subprocess.STDOUT)
        while not (response.exists() if broker else proc.poll() is not None):
            if broker and time.time() - (work.parent / ".pixal3d-python-heartbeat").stat().st_mtime > 20:
                raise RuntimeError("Pixal3D Python runner stopped responding")
            status = sample()
            for key in ("ram_available_mb", "vram_free_mb"):
                if status.get(key) is not None and lowest.get(key) is not None:
                    lowest[key] = min(status[key], lowest[key])
            if (status.get("temperature_c") or 0) >= 86 or status["ram_available_mb"] < 8192 or (
                status.get("vram_free_mb") is not None and status["vram_free_mb"] < 2048
            ):
                raise RuntimeError("a margem térmica ou de memória do host foi atingida")
            time.sleep(1)
        if broker:
            code = json.loads(response.read_text(encoding="utf-8"))["exit_code"]
        else:
            code = proc.returncode
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        if code or not model.is_file():
            raise RuntimeError(f"{params.engine} terminou com código {code}: {log_text[-500:]}")
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()
        if log is not None:
            log.close()
        if broker:
            (work / "python.cancel").touch()
    if broker:
        details = json.loads(model.with_suffix(".json").read_text(encoding="utf-8"))
        model.with_suffix(".json").unlink()
    else:
        matches = re.findall(r"quantized @res(\d+) \(grid [^)]*\) = (\d+) tokens", log_text)
        details = {"effective_resolution": int(matches[-1][0]), "tokens": int(matches[-1][1])} if matches else {"effective_resolution": None}
    return {**details, "wall_seconds": round(time.monotonic() - start, 2),
            "host_ram_delta_mb": baseline["ram_available_mb"] - lowest["ram_available_mb"],
            "gpu_delta_mb": baseline["vram_free_mb"] - lowest["vram_free_mb"] if baseline.get("vram_free_mb") is not None else None}


def preview(scene: trimesh.Scene, dest: Path) -> None:
    """Small sampled geometry preview. The dashboard loads the full textured master."""
    mesh = scene.to_geometry()
    count = min(32000, len(mesh.faces))
    faces = mesh.faces[np.linspace(0, len(mesh.faces) - 1, count, dtype=int)]
    vertices = mesh.vertices[faces]
    basis = np.array([[0.87, 0, -0.5], [-0.17, 0.94, -0.30], [0.47, 0.34, 0.81]])
    v = vertices @ basis.T
    lo, hi = v.reshape(-1, 3).min(0), v.reshape(-1, 3).max(0)
    xy = (v[..., :2] - (lo[:2] + hi[:2]) / 2) / max((hi - lo)[:2].max(), 1e-8) * [420, -420] + 256
    depths = v[..., 2].mean(1)
    normals = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    shade = (normals @ [0.2, 0.4, 0.8]) / np.maximum(np.linalg.norm(normals, axis=1), 1e-12)
    im = Image.new("RGB", (512, 512), (232, 236, 239))
    draw = ImageDraw.Draw(im)
    for i in np.argsort(depths):
        value = int(102 + abs(shade[i]) * 115)
        draw.polygon([tuple(p) for p in xy[i]], fill=(value - 14, value, min(255, value + 18)))
    im.save(dest)


def run_reconstruction(job: dict, work: Path, emit, threads: int) -> dict:
    params = ReconstructionParams.model_validate(job["params"])
    out = work / "out"
    out.mkdir()
    model = out / "model.glb"

    def stage(name, status):
        emit({"type": "stage", "name": name, "status": status})

    stage("prepare", "start")
    views = None if params.engine == "trellis2-gguf" else prepare_views(work, params)
    stage("prepare", "done")
    stage("inference", "start")
    runtime = execute(work, params, views, model, threads)
    stage("inference", "done")
    stage("validate_outputs", "start")
    validation = validate_glb(model, require_bottom_center=False)
    if not validation.passed:
        raise PipelineError("GLB do motor não passou pela validação estrutural")
    scene = trimesh.load_scene(model, process=False)
    lo, hi = scene.bounds
    dims = tuple(float(x) for x in hi - lo)
    triangles = int(validation.metrics["glb_triangles"])
    preview(scene, out / "thumbnail.png")
    (out / "validation.json").write_text(validation.model_dump_json(), encoding="utf-8")
    stage("validate_outputs", "done")
    stage("package", "start")
    files = [_file_entry(out / filename, out, role, fmt) for filename, role, fmt in (
        ("model.glb", "model", "glb"), ("thumbnail.png", "preview", "png"), ("validation.json", "report", "json"))]
    manifest = AssetManifest(asset_id=job["asset_id"], name=job["name"], version=job["version"], category=params.category,
                             art_profile="experimental", seed=params.seed, generator_id=RECONSTRUCT, generator_version="0.1.0",
                             ai_model=params.engine, quality_profile="experimental", dimensions_m=dims, footprint_m=(dims[0], dims[2]),
                             bounding_box=(tuple(lo.tolist()), tuple(hi.tolist())), pivot="engine_original", triangle_count=triangles,
                             triangle_budget=None, lods=[LodInfo(level=0, triangles=triangles, file="model.glb")],
                             license="Experimental. Revisão de licenças para uso comercial pendente.",
                             engine=params.engine, generation_params={**params.model_dump(), "runtime": runtime},
                             files=files, created_at=datetime.now(UTC))
    manifest_path = out / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(), encoding="utf-8")
    package = out / "asset.zip"
    with ZipFile(package, "w", ZIP_DEFLATED) as archive:
        for name in [f.name for f in files] + ["manifest.json"]:
            archive.write(out / name, name)
    files += [_file_entry(manifest_path, out, "metadata", "json"), _file_entry(package, out, "package", "zip")]
    stage("package", "done")
    return {"engine": params.engine, "files": [f.model_dump() for f in files], "validation": validation.model_dump()}
