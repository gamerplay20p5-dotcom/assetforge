"""Export a new game-ready derivative from the leased source version."""

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

import trimesh
from assetforge_contract import AssetManifest, LodInfo
from assetforge_contract.models import PreparationParams
from assetforge_export.pipeline import PipelineError, _file_entry
from assetforge_validation import validate_glb

from .engine_job import preview


def run_preparation(job: dict, work: Path, emit, threads: int) -> dict:
    params = PreparationParams.model_validate(job["params"])
    out = work / "out"
    script = "/app/scripts/engines/prepare_game.py"
    blender = os.environ.get("BLENDER_BIN")
    if not blender:
        raise PipelineError("Blender indisponível neste worker")
    cmd = [blender, "-b", "-t", str(threads), "--python-exit-code", "1", "-P", script, "--",
           str(work / "master.glb"), str(out), "--category", params.category, "--height-m", str(params.height_m)]
    for flag, values in (("rotation-deg", params.rotation_deg), ("lod-ratios", params.lod_ratios),
                         ("lod-heights", params.lod_heights)):
        cmd.append(f"--{flag}=" + ",".join(map(str, values)))
    emit({"type": "stage", "name": "prepare", "status": "start"})
    subprocess.run(cmd, check=True, timeout=float(os.environ.get("ASSETFORGE_BLENDER_TIMEOUT", "900")))
    emit({"type": "stage", "name": "prepare", "status": "done"})
    report = json.loads((out / "assetforge-import.json").read_text(encoding="utf-8"))
    model = out / "model.glb"
    (out / "lod0.glb").rename(model)
    report["lods"][0]["file"] = "model.glb"
    (out / "assetforge-import.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    validation = validate_glb(model)
    if not validation.passed:
        raise PipelineError("O GLB preparado não passou pela validação estrutural")
    scene = trimesh.load_scene(model, process=False)
    preview(scene, out / "thumbnail.png")
    (out / "validation.json").write_text(validation.model_dump_json(), encoding="utf-8")
    lods = [LodInfo(level=lod["index"], file=lod["file"], triangles=lod["triangles"],
                    screen_height_percent=lod["relativeHeight"] * 100) for lod in report["lods"]]
    paths = [("model.glb", "model"), ("model.blend", "editable"), ("model.fbx", "interchange"),
             ("thumbnail.png", "preview"), ("validation.json", "report"), ("assetforge-import.json", "metadata")]
    paths += [(item.file, "model") for item in lods[1:]]
    paths += [(item.relative_to(out).as_posix(), "texture") for item in sorted((out / "textures").glob("*.png"))]
    files = [_file_entry(out / name, out, role, Path(name).suffix[1:]) for name, role in paths]
    dimensions = tuple(report["dimensions"])
    manifest = AssetManifest(
        asset_id=job["asset_id"], version=job["version"], name=job["name"], category=params.category,
        art_profile="game", seed=0, generator_id="asset.prepare", generator_version="0.1.0", engine="blender",
        quality_profile="explicit", dimensions_m=dimensions, footprint_m=(dimensions[0], dimensions[2]),
        bounding_box=tuple(tuple(axis.tolist()) for axis in scene.bounds),
        triangle_count=lods[0].triangles, triangle_budget=None, lods=lods, files=files,
        textures=[file.name for file in files if file.role == "texture"],
        generation_params=params.model_dump(mode="json"),
        provenance={"master_sha256": report["sourceSha256"], "source_version": str(params.source_version)},
        license="Derivado. Sujeito às licenças e à revisão do master original.",
        created_at=datetime.now(UTC),
    )
    manifest_path = out / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(), encoding="utf-8")
    files.append(_file_entry(manifest_path, out, "metadata", "json"))
    with ZipFile(out / "asset.zip", "w", ZIP_STORED) as archive:
        for item in files:
            archive.write(out / item.name, item.name)
    files.append(_file_entry(out / "asset.zip", out, "package", "zip"))
    return {"engine": "blender", "files": [file.model_dump() for file in files], "validation": validation.model_dump()}
