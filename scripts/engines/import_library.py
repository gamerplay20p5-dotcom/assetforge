"""Import the CITY experiment archive into the library without running inference."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo

import trimesh
from sqlalchemy import select
from assetforge_api.config import get_settings
from assetforge_api.db import Database
from assetforge_api.models import Asset, AssetVersion
from assetforge_api.services import emit_event
from assetforge_api.storage import Storage
from assetforge_contract import AssetManifest, LodInfo
from assetforge_contract.engines import ENGINES, RECONSTRUCT, ReconstructionParams
from assetforge_export.pipeline import _file_entry
from assetforge_validation import validate_glb

from optimize_master import inspect_glb


PATTERN = re.compile(r"(.+)_(t2q8|sv_q8|sv|mv4|mvpy)_(\d+)_(4090|spark)(_gridfix)?")
CPP_COMMIT = "d1b4926452f9e09702b891db5f05acc845e153ed"
PY_COMMIT = "f7cf38429b0bd264f1995f0f8743a88b1c728b94"
WEIGHTS = {
    "trellis2-gguf": ("ilintar/trellis2-gguf:q8", "a57397bd3d351599d9729fc144b3f87c3f87d65b"),
    "pixal3d-sv": ("raven38/pixal3d-sv-q8_0-v1", "46d399ac986f45a0d7f5b1ca5058614d8729a131"),
    "pixal3d-mv": ("raven38/pixal3d-q8_0-v1", "1c4f4bdddb5fef1dc5efa512d4b88e899b10bd91"),
    "pixal3d-python": ("TencentARC/Pixal3D", "b0cb2e1b794cab9aa0ac38a95d794a4d9337437f"),
}
ENGINE_ID = {"t2q8": "trellis2-gguf", "sv_q8": "pixal3d-sv", "sv": "pixal3d-sv",
             "mv4": "pixal3d-mv", "mvpy": "pixal3d-python"}
VIEW_SUFFIX = {"front": "front", "right": "right", "back": "back", "three_quarter": "34"}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def archive_zip(path: Path, files: dict[str, Path]) -> None:
    with ZipFile(path, "w", ZIP_STORED) as archive:
        for name, source in sorted(files.items()):
            with source.open("rb") as incoming, archive.open(ZipInfo(name), "w", force_zip64=True) as member:
                shutil.copyfileobj(incoming, member, 1024 * 1024)


def recipe_for(root: Path, report: dict):
    run = report["name"]
    match = PATTERN.fullmatch(run)
    if not match:
        raise ValueError(f"Unknown experiment {run}")
    subject, variant, resolution, worker, patch = match.groups()
    engine = ENGINE_ID[variant]
    is_python = variant == "mvpy"
    category = "npc" if subject.startswith("npc_") else "vehicle" if subject.startswith("veh_") else "building"
    inputs = root / "city_inputs" / subject
    if subject == "tower":
        originals = {"front": root / "refs/tower.png"}
    else:
        originals = {}
        for view, suffix in VIEW_SUFFIX.items():
            paths = sorted((root / "refs_city").rglob(f"{subject}_{suffix}.png"))
            if not paths or len({digest(path) for path in paths}) != 1:
                raise ValueError(f"Missing or ambiguous original {subject} {view}")
            originals[view] = paths[0]
    projection_path = inputs / "mv4/transforms.json"
    projection = None
    engine_inputs = {"front": originals["front"] if subject == "tower" else inputs / "front.png"}
    if engine == "pixal3d-sv":
        engine_inputs = {"front": root / "refs/tower_rgba.png" if subject == "tower" else inputs / "sv_rgba.png"}
    elif len(ENGINES[engine]["views"]) > 1:
        poses = read_json(projection_path)
        frames = dict(zip(ENGINES[engine]["views"], poses["frames"], strict=True))
        engine_inputs = {view: projection_path.parent / value["file_path"] for view, value in frames.items()}
        projection = {"camera_angle_x": poses["camera_angle_x"],
                      "transforms": {view: value["transform_matrix"] for view, value in frames.items()}}
    all_references = {path: digest(path) for path in set(originals.values()) | set(engine_inputs.values())}
    reference_id = {path: f"ref_{sha[:12]}" for path, sha in all_references.items()}
    summary = report["summary"]
    params = ReconstructionParams(
        engine=engine, category=category, references={view: reference_id[path] for view, path in engine_inputs.items()},
        resolution=int(resolution), seed=summary.get("seed", 1),
        max_tokens=summary.get("max_tokens", 49152), texture_size=4096,
        structure_guidance=7.5 if is_python else None, shape_guidance=7.5 if is_python else None,
        skip_decimation=False, prepared_inputs=engine != "trellis2-gguf", archived_projection=projection,
        use_native_threads=not is_python,
    ).model_dump(mode="json")
    params.update(original_references={view: reference_id[path] for view, path in originals.items()},
                  archive={"run": run, "worker": worker, "requested_resolution": int(resolution),
                           "effective_resolution": report["effective_resolution"], "wall_seconds": summary["wall_seconds"],
                           "tokens": report.get("tokens"), "grid_fix": bool(patch),
                           "decimation": "engine_default", "references_sha256": {reference_id[p]: h for p, h in all_references.items()}})
    return params, originals, engine_inputs, projection_path if projection else None, all_references


def unity_packages(path: Path | None) -> dict[str, list[Path]]:
    indexed: dict[str, list[Path]] = {}
    if path:
        for entry in sorted(path.rglob("assetforge-import.json")):
            indexed.setdefault(read_json(entry)["sourceSha256"], []).append(entry.parent)
    return indexed


def phase_derivatives(root: Path | None, city: Path | None) -> dict[str, dict[str, dict[str, Path]]]:
    result: dict[str, dict[str, dict[str, Path]]] = {}
    if root:
        for category in ("building", "npc", "vehicle"):
            folder = root / "out"
            report = folder / f"{category}.log"
            with report.open(encoding="utf-8") as handle:
                metadata = next(json.loads(line) for line in handle if line.startswith('{"category"'))
            extras = {p.relative_to(folder).as_posix(): p for p in folder.glob(f"{category}*") if p.is_file()}
            if category == "vehicle":
                extras.update({p.relative_to(folder).as_posix(): p for p in (folder / "vehicle-impostor").glob("*") if p.is_file()})
            result.setdefault(metadata["master_sha256"], {})[f"{category}-pilotos"] = extras
    if city:
        master = city / "verified-results/bldg_skyscraper_commercial_001_mv4_1536_spark/model.glb"
        result.setdefault(digest(master), {})["gltfpack-pilotos"] = {
            file.name: file for file in sorted((city / "optimization").iterdir()) if file.is_file()
        }
    return result


def copy_reference(path: Path, sha: str, directory: Path) -> None:
    target = directory / f"ref_{sha[:12]}.png"
    if target.exists():
        if digest(target) != sha:
            raise RuntimeError(f"Reference hash collision at {target.name}")
        return
    with tempfile.TemporaryDirectory(dir=directory) as scratch:
        candidate = Path(scratch) / target.name
        shutil.copyfile(path, candidate)
        if digest(candidate) != sha:
            raise RuntimeError(f"Reference copy mismatch at {target.name}")
        candidate.replace(target)


def import_run(db, storage: Storage, root: Path, report: dict, options, packs: dict, derivatives: dict) -> dict:
    run = report["name"]
    source = root / "results" / run
    master = source / "model.glb"
    sha = digest(master)
    metrics = inspect_glb(master)
    if report["triangles"] != metrics["triangles"]:
        raise ValueError(f"{run}: triangle count differs from the evidence")
    params, originals, inputs, poses, hashes = recipe_for(root, report)
    aid = f"ast_{hashlib.sha256(run.encode()).hexdigest()[:16]}"
    result = {"id": aid, "run": run, "master_sha256": sha, "triangles": metrics["triangles"]}
    if options.dry_run:
        return {**result, "status": "verified"}
    out = storage.asset_dir(aid, 1)
    with db.session() as session:
        if session.get(Asset, aid):
            version = session.scalar(select(AssetVersion).where(
                AssetVersion.asset_id == aid, AssetVersion.version == 1))
            if version is None or digest(out / "model.glb") != sha:
                raise ValueError(f"{run}: existing master has a different hash")
            return {**result, "status": "existing"}
        refs_dir = storage.root / "references"
        refs_dir.mkdir(exist_ok=True)
        for path, reference_hash in hashes.items():
            copy_reference(path, reference_hash, refs_dir)
        engine, category = params["engine"], params["category"]
        is_python = engine == "pixal3d-python"
        weights, revision = WEIGHTS[engine]
        timestamp = datetime.fromtimestamp((source / ("model.json" if is_python else "summary.json")).stat().st_mtime, UTC)
        with tempfile.TemporaryDirectory(prefix="archive-", dir=storage.staging) as temporary:
            stage = Path(temporary) / "v1"
            stage.mkdir()
            files = []

            def register(name, role):
                files.append(_file_entry(stage / name, stage, role, Path(name).suffix[1:]))

            def copy(path, name, role):
                dest = stage / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, dest)
                register(name, role)

            copy(master, "model.glb", "model")
            if files[0].sha256 != sha:
                raise RuntimeError(f"{run}: master changed during copy")
            renders = root / "analysis" / run
            if (renders / "r_front_left.png").is_file():
                copy(renders / "r_front_left.png", "thumbnail.png", "preview")
            if (renders / "model_level.glb").is_file():
                copy(renders / "model_level.glb", "derived/model_level.glb", "interchange")
            for view, path in originals.items():
                copy(path, f"original/{view}.png", "report")
            for view, path in inputs.items():
                copy(path, f"inputs/{view}.png", "report")
            if poses:
                copy(poses, "inputs/transforms.json", "report")
            (stage / "reports").mkdir()
            (stage / "reports/analysis.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            register("reports/analysis.json", "report")
            subject = PATTERN.fullmatch(run).group(1)
            sheet = root / "analysis/sheets" / f"{subject}.jpg"
            if sheet.is_file():
                copy(sheet, "reports/comparativo.jpg", "report")
            for name in ("summary.json", "model.json"):
                if (source / name).is_file():
                    copy(source / name, f"reports/{name}", "report")
            evidence = {item.name: item for item in source.iterdir()
                        if item.is_file() and item.name not in {"model.glb", "summary.json", "model.json"}}
            if evidence:
                archive_zip(stage / "reports/engine-evidence.zip", evidence)
                register("reports/engine-evidence.zip", "report")
            if options.gemini and (evaluation := options.gemini / f"{run}.json").is_file():
                copy(evaluation, "reports/gemini.json", "report")
            for number, folder in enumerate(packs.get(sha, []), 1):
                name = f"derived/unity-{number}.zip"
                target = stage / name
                target.parent.mkdir(exist_ok=True)
                archive_zip(target, {p.relative_to(folder).as_posix(): p for p in folder.rglob("*") if p.is_file()})
                register(name, "interchange")
            for label, artifacts in derivatives.get(sha, {}).items():
                name = f"derived/{label}.zip"
                target = stage / name
                target.parent.mkdir(exist_ok=True)
                archive_zip(target, artifacts)
                register(name, "interchange")
            lower, upper = trimesh.load_scene(master, process=False).bounds
            extent = tuple((upper - lower).tolist())
            validation = validate_glb(stage / "model.glb", expected_triangles=metrics["triangles"], require_bottom_center=False)
            if not validation.passed:
                raise ValueError(f"{run}: master GLB failed structural validation")
            (stage / "validation.json").write_text(validation.model_dump_json(), encoding="utf-8")
            register("validation.json", "report")
            version = PY_COMMIT if is_python else CPP_COMMIT
            manifest = AssetManifest(
                asset_id=aid, name=run, version=1, seed=params["seed"], category=category,
                art_profile="experimental", generator_id=RECONSTRUCT, generator_version=version,
                ai_model=weights, engine=engine, quality_profile="experimental", dimensions_m=extent,
                footprint_m=(extent[0], extent[2]), bounding_box=(tuple(lower.tolist()), tuple(upper.tolist())), pivot="engine_original",
                triangle_count=metrics["triangles"], triangle_budget=None,
                lods=[LodInfo(level=0, triangles=metrics["triangles"], file="model.glb")],
                license="Experimental. Revisão de licenças para uso comercial pendente.",
                provenance={"weights": weights, "weights_revision": revision, "source_run": run,
                            "master_sha256": sha, "dimensions": "original engine units"},
                generation_params=params, files=files, created_at=timestamp,
            ).model_dump(mode="json")
            if options.gemini and (stage / "reports/gemini.json").is_file():
                manifest["gemini_evaluation"] = read_json(stage / "reports/gemini.json")
            (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            register("manifest.json", "metadata")
            archive_zip(stage / "asset.zip", {item.name: stage / item.name for item in files})
            register("asset.zip", "package")
            index = [item.model_dump() for item in files]
            out.parent.mkdir(exist_ok=True)
            created = not out.exists()
            if created:
                stage.rename(out)
            elif any(not (out / item.name).is_file() or digest(out / item.name) != item.sha256 for item in files):
                raise ValueError(f"{run}: unregistered contents differ from the archive at {out}")
            try:
                session.add(Asset(id=aid, name=run, category=category, generator_id=RECONSTRUCT, current_version=1,
                                  art_profile="experimental", tags=["city-experimentos"], created_at=timestamp))
                session.flush()
                session.add(AssetVersion(asset_id=aid, version=1, files=index, manifest=manifest,
                                         validation=validation.model_dump(mode="json"),
                                         triangle_count=metrics["triangles"], engine=engine, created_at=timestamp,
                                         note="Master original importado do experimento CITY+++"))
                emit_event(session, "asset.created", aid, name=run)
                session.commit()
            except Exception:
                if created:
                    shutil.rmtree(out)
                raise
    return {**result, "status": "imported"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--gemini", type=Path)
    parser.add_argument("--unity-packs", type=Path)
    parser.add_argument("--phase-derivatives", type=Path)
    parser.add_argument("--city-review", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    reports = read_json(args.archive / "analysis/all.json")
    names = {item["name"] for item in reports}
    if len(names) != 40 or len(reports) != len(names):
        parser.error("The experiment archive must contain 40 distinct runs")
    settings = get_settings()
    db = None if args.dry_run else Database(settings.database_url)
    storage = None if args.dry_run else Storage(settings.storage_root)
    packs = unity_packages(args.unity_packs)
    derivatives = phase_derivatives(args.phase_derivatives, args.city_review)
    for report in reports:
        print(json.dumps(import_run(db, storage, args.archive, report, args, packs, derivatives)), flush=True)


if __name__ == "__main__":
    main()
