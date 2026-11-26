#!/usr/bin/env python3
"""Measured CPU benchmark of the procedural pipeline on THIS machine (no numbers are pre-baked).

    python scripts/benchmark.py --count 20 [--engine trimesh|blender] [--blender PATH] [--json out.json]

Generates real assets in a temp dir, validates every output and reports wall time per asset and per stage.
Run it on each node (outside peak hours) to size limits and queue expectations.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for d in ("workers/cpu", "generators/procedural", "pipeline/export", "pipeline/validation", "pipeline/optimization", "packages/asset-contract"):
    sys.path.insert(0, str(ROOT / d))

import psutil  # noqa: E402
from assetforge_export.pipeline import find_blender, run_building_job  # noqa: E402

CATEGORIES = ["house", "apartment", "commercial", "hospital", "school", "industrial", "skyscraper"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=14)
    ap.add_argument("--engine", choices=["trimesh", "blender"], default="trimesh")
    ap.add_argument("--blender", default=None)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    blender = args.blender or find_blender()
    if args.engine == "blender" and not blender:
        print("Blender not found: pass --blender or set BLENDER_BIN", file=sys.stderr)
        return 2
    rows = []
    t_all = time.perf_counter()
    for i in range(args.count):
        cat = CATEGORIES[i % len(CATEGORIES)]
        stage_t: dict[str, float] = {}
        marks: dict[str, float] = {}

        def emit(e: dict) -> None:
            if e["type"] == "stage":
                if e["status"] == "start":
                    marks[e["name"]] = time.perf_counter()
                else:
                    stage_t[e["name"]] = time.perf_counter() - marks[e["name"]]

        with tempfile.TemporaryDirectory(prefix="afbench-") as tmp:
            job = dict(asset_id=f"ast_bench{i}", name=f"bench {i}", version=1, job_id=f"b{i}", formats=["glb"],
                       params=dict(category=cat, style="classic", seed=i + 1, detail=1, texture_resolution=512),
                       thumbnail_samples=16)
            t0 = time.perf_counter()
            res = run_building_job(job, Path(tmp), emit, engine=args.engine, blender_bin=blender, threads=args.threads)
            dt = time.perf_counter() - t0
        rows.append({"category": cat, "seconds": round(dt, 2), "triangles": res["triangle_count"],
                     "validation_passed": res["validation"]["passed"], "stages": {k: round(v, 2) for k, v in stage_t.items()}})
        print(f"[{i + 1}/{args.count}] {cat:12s} {dt:6.2f}s {res['triangle_count']:6d} tris")
    total = time.perf_counter() - t_all
    secs = [r["seconds"] for r in rows]
    summary = {
        "machine": {"cpu": platform.processor(), "threads": psutil.cpu_count(), "ram_mb": int(psutil.virtual_memory().total / 2**20),
                    "os": platform.platform()},
        "engine": args.engine, "assets": len(rows), "total_seconds": round(total, 1),
        "assets_per_minute": round(len(rows) / total * 60, 2), "median_seconds": round(statistics.median(secs), 2),
        "p95_seconds": round(sorted(secs)[max(0, int(len(secs) * 0.95) - 1)], 2), "all_valid": all(r["validation_passed"] for r in rows),
        "rows": rows,
    }
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=2))
    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0 if summary["all_valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
