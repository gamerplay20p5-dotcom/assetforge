"""Validate the integrated preparation on archived masters, with resumable per-asset reports."""

import argparse
import csv
import json
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from benchmark_retopology import category as archived_category

TARGETS = {"building": "8000,2400,600", "vehicle": "6000,1800,450", "npc": "4000,1200,300", "prop": "4000,1200,300"}


def run(source, args):
    name = source.parent.name
    folder = args.output / name
    result = folder / "quality.json"
    if result.is_file():
        return name, json.loads(result.read_text(encoding="utf-8"))
    folder.mkdir(exist_ok=True)
    package = folder / "package"
    category = archived_category(name)
    command = [
        os.environ["BLENDER_BIN"], "-b", "-t", str(args.threads), "--python-exit-code", "1",
        "-P", str(Path(__file__).with_name("prepare_optimized.py")), "--", str(source), str(package),
        "--category", category, "--height-m", "1", "--lod-heights=0.50,0.16,0.04",
        "--triangle-targets", TARGETS[category], "--method", "auto", "--threads", str(args.threads),
        "--bake-size", str(args.bake_size), "--pixels", str(args.pixels),
    ]
    if args.impostor:
        command.append("--impostor")
    try:
        if not package.is_dir():
            with (folder / "blender.log").open("w", encoding="utf-8") as log:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=args.timeout, check=True)
        shutil.copyfile(package / "quality.json", result)
        report = json.loads(result.read_text(encoding="utf-8"))
        if args.metrics_only:
            shutil.rmtree(package)
        print(name, [item["triangles"] for item in report["levels"]], flush=True)
        return name, report
    except (OSError, subprocess.SubprocessError) as error:
        print(name, error, flush=True)
        return name, {"error": str(error)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("masters", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--pixels", type=int, default=144)
    parser.add_argument("--bake-size", type=int, default=512)
    parser.add_argument("--impostor", action="store_true")
    parser.add_argument("--metrics-only", action="store_true")
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(args.masters.resolve()):
        parser.error("Choose an output outside the archive")
    sources = sorted(args.masters.glob("*/model.glb"))
    if not sources:
        parser.error("No archived master found")
    args.output.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = dict(pool.map(lambda path: run(path, args), sources))
    (args.output / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    with (args.output / "lods.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("asset", "level", "master_sha256", "master_triangles", "master_bytes",
                         "method", "target", "triangles", "bytes", "target_met", "package_seconds",
                         "worst_iou", "worst_color_mae", "worst_interior_missing", "worst_dark_patches"))
        for name, report in results.items():
            for entry in report.get("levels", []):
                views = list(entry["accepted"]["views"].values())
                writer.writerow((name, entry["index"], report["master_sha256"], report["master_triangles"],
                                 report["master_bytes"], entry["accepted"]["method"], entry["target"],
                                 entry["triangles"], entry["bytes"], entry["target_met"], report["seconds"],
                                 min(v["silhouette_iou"] for v in views), max(v["color_mae"] for v in views),
                                 max(v["interior_missing"] for v in views), max(v["dark_patches"] for v in views)))
    return int(any("error" in report for report in results.values()))


if __name__ == "__main__":
    raise SystemExit(main())
