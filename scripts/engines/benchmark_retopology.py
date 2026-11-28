"""Compare archived GLBs in Docker. Force no conclusions about artistic approval."""

import argparse
import csv
import hashlib
import json
import os
import struct
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import mean, median

import numpy as np
from PIL import Image, ImageDraw

from optimize_master import inspect_glb

VIEWS = ("front", "rear", "top")
METHODS = ("baseline", "instant", "quadri", "lod-permissive", "hybrid", "lod-voxel")
DEFAULT_BUDGETS = {"building": [8000, 2400, 600], "vehicle": [6000, 1800, 450], "npc": [4000, 1200, 300]}
CREASES = {"building": 24, "vehicle": 32, "npc": 50}
VOXELS = {"building": 0.012, "vehicle": 0.014, "npc": 0.018}
PLANAR_ANGLES = {"building": 1, "vehicle": 0.25, "npc": 0}


def category(name):
    return "npc" if name.startswith("npc_") else "vehicle" if name.startswith("veh_") else "building"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(task, args, budgets):
    path, method = task
    name = path.parent.name
    kind = category(name)
    folder = args.output / name / method
    record = folder / "metrics.json"
    if record.is_file():
        return json.loads(record.read_text())
    folder.parent.mkdir(parents=True, exist_ok=True)
    if folder.exists():
        folder.rename(folder.with_name(f"{method}.interrupted-{time.time_ns()}"))
    start = time.monotonic()
    master_sha = sha(path)
    raw = inspect_glb(path)
    logfile = folder.parent / f"{method}.log"
    with logfile.open("w") as log:
        try:
            subprocess.run([
                os.environ["BLENDER_BIN"], "-b", "-t", str(args.threads), "--python-exit-code", "1",
                "-P", str(Path(__file__).with_name("city_retopology.py")), "--", str(path), str(folder),
                "--method", method, "--threads", str(args.threads), "--pixels", str(args.pixels),
                "--crease", str(CREASES[kind]), "--voxel", str(VOXELS[kind]),
                "--planar-angle", str(PLANAR_ANGLES[kind]),
                "--bake-size", str(args.bake_size), "--budgets",
                *map(str, budgets[kind]),
            ], stdout=log, stderr=subprocess.STDOUT, check=True, timeout=args.timeout)
            error = None
        except (subprocess.SubprocessError, OSError) as exc:
            error = str(exc)
    folder.mkdir(exist_ok=True)
    with logfile.open(errors="replace") as log:
        measured = [float(line.split()[1]) for line in log if line.startswith("BENCH_SECONDS ")]
    results = []
    for level, goal in enumerate(budgets[kind]):
        output = folder / f"lod{level}.glb"
        if output.is_file():
            try:
                results.append({"level": level, "target": goal, **inspect_glb(output)})
            except (ValueError, KeyError, OSError, struct.error) as exc:
                error = f"Invalid LOD{level}: {exc}"
    unchanged = sha(path) == master_sha
    if not unchanged:
        raise RuntimeError(f"Master changed: {name}")
    report = {"asset": name, "category": kind, "method": method, "master_sha256": master_sha,
              "master": raw, "lods": results, "mesh_bake_seconds": measured[-1] if measured else None,
              "total_seconds": round(time.monotonic() - start, 3), "error": error}
    temporary = record.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2))
    temporary.replace(record)
    print(name, method, "error" if error else "ok", [lod["triangles"] for lod in results], flush=True)
    return report


def compare(reference, other):
    ref, image = [np.asarray(Image.open(p).convert("RGBA")) for p in (reference, other)]
    a, b = ref[:, :, 3] > 127, image[:, :, 3] > 127
    both = a & b
    union = int((a | b).sum())
    return {"iou": float(both.sum() / union) if union else None,
            "rgb_mae": float(np.abs(ref[:, :, :3][both].astype(float) - image[:, :, :3][both]).mean()) if both.any() else None}


def summarize(output, rows, pixels):
    assets = {row["asset"] for row in rows}
    for row in rows:
        root = output / row["asset"]
        for lod in row["lods"]:
            views = {}
            for view in VIEWS:
                ref = root / "baseline" / f"master-{view}.png"
                method = row["method"]
                if lod["level"] == 0:
                    method = {"lod-permissive": "instant", "lod-voxel": "hybrid"}.get(method, method)
                candidate = root / method / f"lod{lod['level']}-{view}.png"
                if ref.is_file() and candidate.is_file():
                    views[view] = compare(ref, candidate)
            lod["views"] = views
    fields = ("asset", "category", "method", "level", "target", "triangles", "bytes", "master_triangles",
              "master_bytes", "mesh_bake_seconds", "total_seconds", "silhouette_min", "rgb_mae_mean", "error")
    with (output / "metrics.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            for lod in row["lods"] or [{}]:
                measures = lod.get("views", {}).values()
                iou = [view["iou"] for view in measures if view["iou"] is not None]
                rgb = [view["rgb_mae"] for view in measures if view["rgb_mae"] is not None]
                data = {key: lod[key] for key in ("level", "target", "triangles", "bytes") if key in lod}
                writer.writerow({**{key: row[key] for key in ("asset", "category", "method", "mesh_bake_seconds",
                                                               "total_seconds", "error")},
                                 **data, "master_triangles": row["master"]["triangles"],
                                 "master_bytes": row["master"]["bytes"], "silhouette_min": min(iou) if iou else "",
                                 "rgb_mae_mean": mean(rgb) if rgb else ""})
    sheets = output / "sheets"
    sheets.mkdir(exist_ok=True)
    for asset in sorted(assets):
        root = output / asset
        columns = (("baseline", "master", "Master"), ("baseline", "lod0", "gltfpack"),
                   ("instant", "lod0", "Instant + bake"), ("quadri", "lod0", "QuadriFlow + bake"),
                   ("hybrid", "lod0", "Hibrido LOD0"), ("lod-voxel", "lod1", "Voxel LOD1"),
                   ("lod-voxel", "lod2", "Voxel LOD2"))
        image = Image.new("RGB", (len(columns) * pixels, 38 + 3 * pixels), "#e2e7ed")
        draw = ImageDraw.Draw(image)
        draw.text((8, 4), asset, fill="#151e2a")
        for i, (method, level, label) in enumerate(columns):
            draw.text((i * pixels + 8, 22), label, fill="#151e2a")
            for j, view in enumerate(VIEWS):
                path = root / method / f"{level}-{view}.png"
                if path.is_file():
                    frame = Image.open(path).convert("RGBA")
                    image.paste(frame, (i * pixels, 38 + j * pixels), frame)
        image.save(sheets / f"{asset}.jpg", quality=89)
    (output / "metrics.json").write_text(json.dumps(rows, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("masters", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--jobs", type=int, default=5)
    parser.add_argument("--threads", type=int, default=3)
    parser.add_argument("--pixels", type=int, default=144)
    parser.add_argument("--bake-size", type=int, default=512)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--methods", choices=METHODS, nargs="+", default=METHODS[:3])
    parser.add_argument("--budget-file", type=Path)
    parser.add_argument("--match", default="*")
    args = parser.parse_args()
    budgets = json.loads(args.budget_file.read_text()) if args.budget_file else DEFAULT_BUDGETS
    for kind in DEFAULT_BUDGETS:
        a, b, c = budgets[kind]
        if not (a > b > c >= 4):
            parser.error(f"{kind}: triangle budgets must decrease")
    masters = sorted(args.masters.glob(f"{args.match}/model.glb"))
    if not masters:
        parser.error("No model.glb files matched")
    args.output.mkdir(parents=True, exist_ok=True)
    budget_path = args.output / "budgets.json"
    settings_path = args.output / "settings.json"
    settings = {"pixels": args.pixels, "bake_size": args.bake_size}
    for path, data in ((budget_path, budgets), (settings_path, settings)):
        if path.is_file() and json.loads(path.read_text()) != data:
            parser.error("Use another output directory for changed budgets or render settings")
        path.write_text(json.dumps(data, indent=2))
    tasks = [(path, method) for path in masters for method in args.methods]
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(lambda task: run(task, args, budgets), tasks))
    rows = [json.loads(path.read_text()) for master in masters
            for method in METHODS if (path := args.output / master.parent.name / method / "metrics.json").is_file()]
    summarize(args.output, rows, args.pixels)
    for method in args.methods:
        successful = [row for row in rows if row["method"] == method and not row["error"]]
        if successful:
            print(method, len(successful), "of", len(masters), "median seconds",
                  median(row["mesh_bake_seconds"] for row in successful))


if __name__ == "__main__":
    main()
