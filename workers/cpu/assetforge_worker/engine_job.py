"""Run and package an experimental engine without rewriting its GLB master."""

from __future__ import annotations

import json
import hashlib
import math
import os
import re
import shutil
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


def matte_view(raw: Path, output: Path) -> None:
    models = Path(os.environ.get("ASSETFORGE_ENGINE_MODELS", "/models")) / CPP_WEIGHTS["trellis2-gguf"]
    log = output.with_suffix(".log")
    with log.open("wb") as stream:
        status = subprocess.run(
            ["trellis-cli", "--image", str(raw), "--models", str(models), "--birefnet",
             "--require-gpu", "--bg-only", "-o", str(output)],
            stdout=stream, stderr=subprocess.STDOUT, timeout=180, check=False,
        )
    cutout = output.with_name(f"{output.stem}_cutout.png")
    if status.returncode or not cutout.is_file():
        raise PipelineError(f"Falha no recorte da vista {raw.stem}: {log.read_text(errors='replace')[-400:]}")
    cutout.replace(output)


def camera_pose(azimuth: float) -> list[list[float]]:
    angle = math.radians(azimuth)
    c, s = math.cos(angle), math.sin(angle)
    return [[c, 0, s, 3.119 * s], [s, 0, -c, -3.119 * c], [0, 1, 0, 0], [0, 0, 0, 1]]


def prepare_views(work: Path, params: ReconstructionParams, emit) -> tuple[Path, dict]:
    poses = {"front": 0, "right": 90, "back": 180, "three_quarter": params.three_quarter_angle}
    names = ENGINES[params.engine]["views"]
    directory = work / "views"
    directory.mkdir()
    if params.prepared_inputs:
        frames = []
        projection = params.archived_projection
        for index, view in enumerate(names):
            filename = f"view{index}.png"
            shutil.copyfile(work / f"{view}.png", directory / filename)
            if projection:
                matrix = projection.transforms[view]
                if view == "three_quarter" and params.archive_azimuth_override is not None:
                    matrix = camera_pose(params.archive_azimuth_override)
                frames.append({"file_path": filename, "name": view,
                               "transform_matrix": matrix})
        if projection:
            (directory / "transforms.json").write_text(json.dumps(
                {"camera_angle_x": projection.camera_angle_x, "mesh_scale": params.mesh_scale, "frames": frames}),
                encoding="utf-8")
        emit({"type": "log", "message": "Referências arquivadas reutilizadas sem recorte ou reenquadramento."})
        return directory, {"archived_inputs": True}
    images, report, hashes = [], {}, set()
    masks = work / "masks"
    masks.mkdir()
    for view in names:
        raw = work / f"{view}.png"
        signature = hashlib.sha256(raw.read_bytes()).hexdigest()
        if signature in hashes:
            raise PipelineError(f"A vista {view} repete uma referência do mesmo asset.")
        hashes.add(signature)
        with Image.open(raw) as source:
            rgba = source.convert("RGBA")
        removed_background = rgba.getchannel("A").getextrema() == (255, 255)
        if removed_background:
            masked = masks / raw.name
            matte_view(raw, masked)
            with Image.open(masked) as source:
                rgba = source.convert("RGBA")
        foreground = rgba.getchannel("A").point(lambda a: 255 if a >= 128 else 0)
        box = foreground.getbbox()
        if not box or foreground.getextrema() == (255, 255) or foreground.histogram()[255] < 256:
            raise PipelineError(f"A vista {view} não tem um primeiro plano suficiente após o recorte.")
        report[view] = {"background_removed": removed_background,
                        "bbox_px": list(box), "image_size": list(rgba.size)}
        images.append((rgba, box))
        emit({"type": "log", "message": f"Vista {view}: {'fundo removido' if removed_background else 'máscara original preservada'}"})
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
        frames.append({"file_path": filename, "name": view, "transform_matrix": camera_pose(poses[view])})
    (directory / "transforms.json").write_text(json.dumps(
        {"camera_angle_x": math.radians(20), "mesh_scale": params.mesh_scale, "frames": frames}), encoding="utf-8")
    heights = [(box[3] - box[1]) / image.height for image, box in images]
    warnings = []
    if max(heights) > 1.7 * min(heights):
        warning = "As vistas têm enquadramentos muito diferentes. Confira escala e câmera nas referências."
        warnings.append(warning)
        emit({"type": "log", "level": "warning", "message": warning})
    return directory, {"views": report, "warnings": warnings}


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
    if not params.use_native_threads:
        options += ["--threads", str(max(1, threads))]
    for flag, value in (("--gss", params.structure_guidance), ("--gsh", params.shape_guidance)):
        if value is not None:
            options += [flag, str(value)]
    models = Path(os.environ.get("ASSETFORGE_ENGINE_MODELS", "/models")) / CPP_WEIGHTS[params.engine]
    return ["trellis-cli", *inputs, "--models", str(models), "--require-gpu",
            "--res", str(params.resolution), "--max-tokens", str(params.max_tokens), "--seed", str(params.seed),
            "--atlas", str(params.texture_size),
            *options, "-o", str(out)]


def execute(work: Path, params: ReconstructionParams, views: Path | None, model: Path, threads: int, emit) -> dict:
    start = time.monotonic()
    baseline = sample()
    lowest = baseline.copy()
    log_path = work / "engine.log"
    broker = params.engine == "pixal3d-python"
    proc = None
    request = work / "python.request.json"
    response = work / "python.response.json"
    log = None
    progress = set()
    log_offset = 0
    phase = "conditioning"

    def advance(next_phase):
        nonlocal phase
        if phase != next_phase:
            emit({"type": "stage", "name": phase, "status": "done"})
            phase = next_phase
            emit({"type": "stage", "name": phase, "status": "start"})

    try:
        if broker:
            tmp = request.with_suffix(".tmp")
            tmp.write_text(params.model_dump_json(), encoding="utf-8")
            tmp.replace(request)
        else:
            log = log_path.open("w", encoding="utf-8")
            proc = subprocess.Popen(cpp_command(work, model, params, views, threads), stdout=log, stderr=subprocess.STDOUT)
        while not (response.exists() if broker else proc.poll() is not None):
            if log_path.is_file():
                with log_path.open(encoding="utf-8", errors="replace") as reader:
                    reader.seek(log_offset)
                    while line := reader.readline():
                        if not line.endswith("\n"):
                            break
                        log_offset = reader.tell()
                        message = line.strip()
                        native_stage = re.match(r"^\[(\d+)/([67])\]", message)
                        if (native_stage or re.match(r"^\[(?:Pipeline|Rembg|Baking|Export)\]", message)) and message not in progress:
                            progress.add(message)
                            emit({"type": "log", "message": message[:500]})
                        if (native_stage and native_stage[1] == "3") or (broker and "Starting generation" in message):
                            advance("inference")
                        if (native_stage and native_stage[1] == native_stage[2]) or (broker and message.startswith(("[Baking]", "[Export]"))):
                            if phase == "conditioning":
                                advance("inference")
                            advance("surface")
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


def generate_reference(work: Path, params: ReconstructionParams) -> None:
    request = work / "python.request.json"
    response = work / "python.response.json"
    temporary = request.with_suffix(".tmp")
    temporary.write_text(json.dumps({"task": "text_reference", "prompt": params.prompt, "seed": params.seed}), encoding="utf-8")
    temporary.replace(request)
    try:
        while not response.is_file():
            marker = work.parent / ".zimage-heartbeat"
            if not marker.is_file() or time.time() - marker.stat().st_mtime > 20:
                raise RuntimeError("O worker de texto deixou de responder.")
            status = sample()
            if (status.get("temperature_c") or 0) >= 86 or status["ram_available_mb"] < 8192:
                raise RuntimeError("A margem térmica ou de memória foi atingida ao gerar a referência.")
            time.sleep(1)
        if json.loads(response.read_text())["exit_code"] or not (work / "front.png").is_file():
            log = work / "text-reference.log"
            detail = log.read_text(errors="replace")[-500:] if log.is_file() else ""
            raise RuntimeError(f"Z-Image não produziu uma referência. {detail}")
    finally:
        (work / "python.cancel").touch()


def run_reconstruction(job: dict, work: Path, emit, threads: int) -> dict:
    params = ReconstructionParams.model_validate(job["params"])
    out = work / "out"
    out.mkdir()
    model = out / "model.glb"

    def stage(name, status):
        emit({"type": "stage", "name": name, "status": status})

    if params.prompt:
        stage("text_to_image", "start")
        generate_reference(work, params)
        stage("text_to_image", "done")
    stage("prepare", "start")
    views, preparation = (None, {}) if params.engine == "trellis2-gguf" else prepare_views(work, params, emit)
    stage("prepare", "done")
    stage("conditioning", "start")
    runtime = execute(work, params, views, model, threads, emit)
    for finished in ("conditioning", "inference", "surface"):
        stage(finished, "done")
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
    source_info = {}
    if params.prompt:
        shutil.copyfile(work / "front.png", out / "reference.png")
        files.append(_file_entry(out / "reference.png", out, "report", "png"))
        source_info = {"generated_reference_file": "reference.png", "reference_model": "Tongyi-MAI/Z-Image-Turbo"}
    manifest = AssetManifest(asset_id=job["asset_id"], name=job["name"], version=job["version"], category=params.category,
                             art_profile="experimental", seed=params.seed, generator_id=RECONSTRUCT, generator_version="0.1.0",
                             ai_model=params.engine, quality_profile="experimental", dimensions_m=dims, footprint_m=(dims[0], dims[2]),
                             bounding_box=(tuple(lo.tolist()), tuple(hi.tolist())), pivot="engine_original", triangle_count=triangles,
                             triangle_budget=None, lods=[LodInfo(level=0, triangles=triangles, file="model.glb")],
                             license="Experimental. Revisão de licenças para uso comercial pendente.",
                             engine=params.engine, generation_params={**params.model_dump(), **source_info, "runtime": runtime,
                                                                      "reference_preparation": preparation},
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
