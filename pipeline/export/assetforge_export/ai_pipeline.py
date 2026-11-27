"""Generative pipeline: [text -> image] -> image -> 3D (ComfyUI/Intel workflows) -> Blender post-processing -> validate -> package.

Complements the procedural generators; it reuses the same validation, manifest and queue contracts.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from assetforge_contract import (
    AiParams,
    AssetManifest,
    ColliderInfo,
    ConnectionPoint,
    LodInfo,
    MaterialInfo,
    QualityProfile,
    ValidationCheck,
    ValidationReport,
    triangle_budget,
)
from assetforge_intel_ai import ModelSpec, required_specs, target_faces
from assetforge_validation import read_glb_json, validate_glb
from PIL import Image

from .blender_runner_path import RUNNER_PATH
from .cpu3d_profiles import CPU_PROFILES
from .pipeline import STAGE_PLAN, PipelineError, _file_entry, find_blender
from .proc import run_supervised

AI_RUNNER_PATH = RUNNER_PATH.with_name("ai_runner.py")
AI_PLANS: dict[str, list[tuple[str, float]]] = {
    "ai.text_to_3d": [("text_to_image", 14), ("image_to_3d", 46), ("postprocess", 20), ("validate_outputs", 8), ("package", 12)],
    "ai.image_to_3d": [("image_to_3d", 55), ("postprocess", 23), ("validate_outputs", 9), ("package", 13)],
}
Emit = Callable[[dict], None]


def plan_for(job_type: str) -> list[tuple[str, float]]:
    if job_type == "experimental.reconstruct":
        return [("prepare", 1), ("conditioning", 2), ("inference", 8), ("surface", 4),
                ("validate_outputs", 1), ("package", 1)]
    if job_type == "agent.building":
        from .agent_pipeline import AGENT_PLAN

        return AGENT_PLAN
    return AI_PLANS.get(job_type, STAGE_PLAN)


def _hex(rgb: list[float]) -> str:
    def to_srgb(c: float) -> float:
        return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055

    return "#" + "".join(f"{round(max(0, min(1, to_srgb(c))) * 255):02X}" for c in rgb[:3])


def run_ai_job(job: dict, workdir: Path, emit: Emit, provider, *, blender_bin: str | None = None,
               threads: int = 2, blender_timeout: float = 900.0, should_cancel: Callable[[], bool] | None = None) -> dict:
    cancel = should_cancel or (lambda: False)

    def stage(name: str, status: str, **extra) -> None:
        emit({"type": "stage", "name": name, "status": status, **extra})

    def log(msg: str, level: str = "info") -> None:
        emit({"type": "log", "level": level, "message": msg})

    params = AiParams.model_validate(job["params"])
    profile = QualityProfile(job.get("quality_profile", "stylized_standard"))
    formats = list(job.get("formats") or ["glb"])
    blender = blender_bin or find_blender()
    if not blender:
        raise PipelineError("AI jobs need Blender for post-processing (set BLENDER_BIN)")
    out = workdir / "out"
    out.mkdir(parents=True, exist_ok=True)
    ai_meta: dict = {"stages": {}}
    is_cpu = params.provider in ("sf3d", "triposr")
    limit_override = params.max_triangles or job.get("triangle_limit")
    used_models: list[ModelSpec] = []

    # 1. concept image -------------------------------------------------------------------------------
    if job["job_type"] == "ai.text_to_3d":
        stage("text_to_image", "start")
        concept = out / "concept.png"
        g = provider.text_to_image(params.prompt or "", concept, negative=params.negative_prompt, size=params.image_size,
                                   seed=params.seed, art_style=params.art_style == "premium_stylized", should_cancel=cancel)
        ai_meta["stages"]["text_to_image"] = {"seconds": round(g.seconds, 1), "peak_vram_mb": g.peak_vram_mb, "workflow_sha": g.workflow_sha}
        log(f"text-to-image ok in {g.seconds:.0f}s (peak VRAM {g.peak_vram_mb} MB)")
        image = concept
        used_models += required_specs(("text_to_image",))
        stage("text_to_image", "done")
    else:
        image = Path(job["reference_path"])
        try:
            with Image.open(image) as im:
                im.verify()
            with Image.open(image) as im:
                if max(im.size) > 4096 or min(im.size) < 64:
                    raise PipelineError(f"reference image size {im.size} outside 64..4096 px")
        except OSError as exc:
            raise PipelineError(f"reference image is not a valid image: {exc}") from exc

    # 2. image -> 3D ----------------------------------------------------------------------------------
    stage("image_to_3d", "start")
    faces = target_faces(params.category, profile, limit_override)
    raw_glb = workdir / "raw" / "ai_raw.glb"
    if is_cpu:
        prof = CPU_PROFILES[profile]
        cp = {"texture_resolution": params.texture_resolution or prof["texture"], "mc_resolution": params.mc_resolution or prof["mc"],
              "remesh": params.remesh, "target_vertex_count": faces // 2 if params.remesh != "none" else -1}
        g3 = provider.image_to_3d(image, raw_glb, params=cp, tag=str(job.get("job_id", "")), should_cancel=cancel)
        ai_meta["stages"]["image_to_3d"] = {"seconds": round(g3.seconds, 1), "provider": params.provider, "peak_ram_mb": g3.peak_ram_mb,
                                            "peak_cpu_percent": g3.peak_cpu_percent, "color": g3.info.get("color"), "provider_params": cp,
                                            "target_faces": faces, "bake_fallback": g3.info.get("bake_fallback", False)}
        log(f"{params.provider} ok in {g3.seconds:.0f}s (peak RAM {g3.peak_ram_mb} MB, peak CPU {g3.peak_cpu_percent:.0f}%, color={g3.info.get('color')})")
    else:
        g3 = provider.image_to_3d(image, raw_glb, profile=profile, target_faces=faces, seed=params.seed,
                                  use_trellis2=params.use_trellis2, remove_background=params.remove_background, should_cancel=cancel)
        ai_meta["stages"]["image_to_3d"] = {"seconds": round(g3.seconds, 1), "peak_vram_mb": g3.peak_vram_mb, "vram_total_mb": g3.vram_total_mb,
                                            "workflow_sha": g3.workflow_sha, "target_faces": faces, "use_trellis2": params.use_trellis2}
        log(f"image-to-3D ok in {g3.seconds:.0f}s (peak VRAM {g3.peak_vram_mb}/{g3.vram_total_mb} MB, target {faces} faces)")
        used_models += required_specs(("image_to_3d",))
    stage("image_to_3d", "done", detail=f"{g3.seconds:.0f}s")

    # 3. Blender post-processing: normalise, cap to budget, LODs, exports, thumbnail -------------------------
    stage("postprocess", "start")
    b_lo, b_hi = triangle_budget(params.category, profile, limit_override)
    cfg = {"glb_in": str(raw_glb), "out_dir": str(out), "asset_name": job["name"], "formats": formats, "target_size_m": params.target_size_m,
           "size_axis": params.size_axis, "triangle_limit": b_hi, "lod_ratios": params.lod_ratios, "thumbnail_size": job.get("thumbnail_size", 512),
           "thumbnail_samples": job.get("thumbnail_samples", 24), "compare_preview": is_cpu, "reduction": "bake",
           "bake_resolution": (params.texture_resolution or CPU_PROFILES[profile]["texture"]) if is_cpu else 1024}
    cfg_path = workdir / "ai_blender_config.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    def on_line(line: str) -> None:
        if line.startswith("@@EVENT "):
            ev = json.loads(line[8:])
            log(f"blender: {ev['stage']} {ev['status']}")
        elif line.strip() and not line.startswith(("Fra:", "Saved:", "Time:")):
            log("blender: " + line.strip()[:300])

    run_supervised([blender, "-b", "--factory-startup", "--threads", str(max(1, threads)), "--python", str(AI_RUNNER_PATH), "--", str(cfg_path)],
                   timeout=blender_timeout, on_line=on_line, should_cancel=cancel)
    report = json.loads((out / "ai_report.json").read_text(encoding="utf-8"))
    (out / "ai_report.json").unlink()
    if "blend" not in formats:
        (out / "model.blend").unlink(missing_ok=True)
    stage("postprocess", "done")

    # 4. validation -------------------------------------------------------------------------------------
    stage("validate_outputs", "start")
    lod0 = report["lods"][0]["triangles"]
    dims = tuple(report["dimensions_m"])
    glb_report = validate_glb(out / "model.glb", expected_triangles=lod0, expected_dims=dims, tol=0.05)  # type: ignore[arg-type]
    checks = list(glb_report.checks)
    lod_files = [out / ("model.glb" if i == 0 else f"model_lod{i}.glb") for i in range(len(report["lods"]))]
    missing = [p.name for p in lod_files + [out / "thumbnail.png"] + [out / f"model.{f}" for f in formats] if not p.is_file() or p.stat().st_size == 0]
    checks.append(ValidationCheck(name="files_exist", status="fail" if missing else "pass", detail=f"missing: {missing}" if missing else "all outputs present"))
    over = lod0 > b_hi
    checks.append(ValidationCheck(name="triangle_budget", status="warn" if over else "pass", detail=f"{lod0} triangles (budget {b_lo}-{b_hi})"))
    gdoc, _ = read_glb_json(out / "model.glb")
    has_tex = any("baseColorTexture" in m.get("pbrMetallicRoughness", {}) for m in gdoc.get("materials", []))
    has_vc = any("COLOR_0" in pr.get("attributes", {}) for me in gdoc.get("meshes", []) for pr in me.get("primitives", []))
    checks.append(ValidationCheck(name="material_preserved", status="pass" if (has_tex or has_vc) else "warn",
                                  detail="textured material" if has_tex else "vertex colors" if has_vc else "LOD0 has neither a base-color texture nor vertex colors"))
    mono = all(report["lods"][i]["triangles"] >= report["lods"][i + 1]["triangles"] for i in range(len(report["lods"]) - 1))
    checks.append(ValidationCheck(name="lods_monotonic", status="pass" if mono else "fail", detail=str([x["triangles"] for x in report["lods"]])))
    for lv in report["lods"][1:]:
        want = lod0 * lv["target_ratio"]
        if lv["triangles"] > want * 1.25 + 20:
            checks.append(ValidationCheck(name=f"lod{lv['level']}_ratio_reached", status="warn",
                                          detail=f"LOD{lv['level']} has {lv['triangles']} triangles, requested ~{int(want)} (mesh could not be reduced further)"))
    thin = lod0 < max(200, int(b_lo * 0.2))
    checks.append(ValidationCheck(name="not_prototype_like", status="warn" if thin else "pass",
                                  detail=f"LOD0 has {lod0} triangles; below 20% of the category minimum ({b_lo})" if thin else "geometric density ok"))
    vr = ValidationReport(passed=not any(c.status == "fail" for c in checks), checks=checks,
                          metrics={**glb_report.metrics, "triangles": lod0, "engine": "blender+" + ("cpu3d" if is_cpu else "comfyui"), "raw_triangles": report["raw_triangles"]})
    for c in checks:
        if c.status != "pass":
            log(f"validation {c.status}: {c.name} - {c.detail}", "warning" if c.status == "warn" else "error")
    if not vr.passed:
        raise PipelineError("output validation failed: " + "; ".join(f"{c.name}: {c.detail}" for c in vr.errors))
    stage("validate_outputs", "done")

    # 5. manifest + package -------------------------------------------------------------------------------
    stage("package", "start")
    doc, _ = read_glb_json(out / "model.glb")
    materials = []
    for m in doc.get("materials", []):
        pbr = m.get("pbrMetallicRoughness", {})
        materials.append(MaterialInfo(name=m.get("name", "material"), base_color=_hex(pbr.get("baseColorFactor", [0.8, 0.8, 0.8, 1])),
                                      texture="embedded in GLB" if "baseColorTexture" in pbr else None,
                                      roughness=float(pbr.get("roughnessFactor", 1.0)), metallic=float(pbr.get("metallicFactor", 0.0))))
    files = [_file_entry(out / "model.glb", out, "interchange", "glb"), _file_entry(out / "thumbnail.png", out, "preview", "png")]
    if (out / "concept.png").is_file():
        files.append(_file_entry(out / "concept.png", out, "preview", "png"))
    if (out / "preview_raw.png").is_file():
        files.append(_file_entry(out / "preview_raw.png", out, "preview", "png"))  # before optimisation
    files += [_file_entry(p, out, "interchange", "glb") for p in lod_files[1:]]
    if "blend" in formats:
        files.append(_file_entry(out / "model.blend", out, "editable", "blend"))
    if "fbx" in formats:
        files.append(_file_entry(out / "model.fbx", out, "model", "fbx"))
    (out / "validation.json").write_text(vr.model_dump_json(indent=2), encoding="utf-8")
    files.append(_file_entry(out / "validation.json", out, "report", "json"))
    uniq = {s.key: s for s in used_models}.values()
    if is_cpu:
        licenses = provider.license_summary()
        ai_name = provider.model_name()
        engine_name = f"blender+{params.provider}-cpu"
    else:
        licenses = "; ".join(sorted({f"{s.repo}: {s.license_info['license']}" for s in uniq}))
        ai_name = ("trellis2" if params.use_trellis2 else "pixal3d") + ("+z-image-turbo" if job["job_type"] == "ai.text_to_3d" else "")
        engine_name = "blender+comfyui"
    size = tuple(round(x, 4) for x in dims)
    manifest = AssetManifest(
        asset_id=job["asset_id"], name=job["name"], category=params.category, version=int(job.get("version", 1)),
        art_profile=f"generative-{params.art_style}", seed=params.seed, generator_id=job["job_type"], generator_version="0.1.0",
        ai_model=ai_name, quality_profile=profile.value, dimensions_m=size, footprint_m=(size[0], size[2]),  # type: ignore[arg-type]
        bounding_box=((-size[0] / 2, 0.0, -size[2] / 2), (size[0] / 2, size[1], size[2] / 2)),
        connection_points=[ConnectionPoint(name="origin", position=(0.0, 0.0, 0.0))], materials=materials, textures=[],
        lods=[LodInfo(level=x["level"], triangles=x["triangles"], file=lod_files[x["level"]].name) for x in report["lods"]],
        colliders=[ColliderInfo(type="box", center=(0.0, round(size[1] / 2, 4), 0.0), size=size)],  # type: ignore[arg-type]
        triangle_count=lod0, triangle_budget=(b_lo, b_hi),
        license=f"Saída de modelos de IA (sem assets de terceiros no input). Licenças dos modelos — {licenses}",
        provenance={**provider.provenance(), "job_id": str(job.get("job_id", "")), "inputs": "text prompt" if job["job_type"] == "ai.text_to_3d" else "reference image",
                    "models": ", ".join(sorted(s.key for s in uniq))[:1500]},
        engine=engine_name, generation_params={**params.model_dump(mode="json"), "ai": ai_meta, "raw_triangles": report["raw_triangles"], "reduction": report.get("reduction")},
        files=files, created_at=datetime.now(UTC))
    manifest_path = out / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    import zipfile

    pkg = out / f"{job['asset_id']}_v{manifest.version}.zip"
    with zipfile.ZipFile(pkg, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(out / f.name, f.name)
        zf.write(manifest_path, "manifest.json")
    files.append(_file_entry(manifest_path, out, "metadata", "json"))
    files.append(_file_entry(pkg, out, "package", "zip"))
    stage("package", "done")
    return {"files": [f.model_dump() for f in files], "manifest": json.loads(manifest_path.read_text(encoding="utf-8")),
            "validation": json.loads(vr.model_dump_json()), "engine": engine_name, "triangle_count": lod0}
