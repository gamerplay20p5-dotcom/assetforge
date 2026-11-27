#!/usr/bin/env python3
"""Pilot: reference image -> BiRefNet cutout -> TRELLIS.2 -> master GLB, with timing and memory measured.

Runs INSIDE the AssetPipeline's `clonez-mesh:1` Docker image on the DGX Spark (see run_pilot.sh). Only reads the Hank pipeline's code
(mounted read-only at /hank) and weights (/models, read-only); everything it writes goes to --out. It reuses his `Generator.cutout` logic
(BiRefNet crop at full resolution) and `meshpost.drop_inner_shells`, and calls TRELLIS.2 and o_voxel's `to_glb` exactly as `Generator.mesh` does,
minus Z-Image, Ollama and the game-specific fit.

    python pilot_reconstruct.py --image in/tower.png --out out/tower --res 1024_cascade 1536_cascade --seed 1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

sys.dont_write_bytecode = True
sys.path[:0] = ["/hank/Tools/AssetPipeline/mesh", "/hank/Tools/AssetPipeline"]

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

MODELS = Path(os.environ.get("CLONEZ_MODELS", "/models"))


def mem_gb() -> tuple[float, float]:
    """(used, total) of the Spark's unified memory, from /proc/meminfo."""
    d = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        k, v = line.split(":", 1)
        d[k] = int(v.split()[0])
    return (d["MemTotal"] - d["MemAvailable"]) / 1048576, d["MemTotal"] / 1048576


class PeakMemory:
    def __init__(self) -> None:
        self.peak = 0.0
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(0.5):
            self.peak = max(self.peak, mem_gb()[0])

    def __enter__(self) -> "PeakMemory":
        self.peak = mem_gb()[0]
        self._t.start()
        return self

    def __exit__(self, *a) -> None:
        self._stop.set()
        self._t.join()


def cutout(pipe, photo: Image.Image, cond_size: int) -> Image.Image | None:
    """BiRefNet cutout cropped to the item at full resolution (same logic as Hank's Generator.cutout)."""
    rgba = pipe.rembg_model(photo.convert("RGB"))
    ys, xs = np.nonzero(np.asarray(rgba)[:, :, 3] > 127)
    if len(xs) < 256:
        return None
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
    pad = int(0.04 * max(x1 - x0, y1 - y0))
    crop = rgba.crop((max(0, x0 - pad), max(0, y0 - pad), min(rgba.width, x1 + pad), min(rgba.height, y1 + pad)))
    s = cond_size / max(crop.size)
    if s < 1.0:
        crop = crop.resize((max(1, round(crop.width * s)), max(1, round(crop.height * s))), Image.LANCZOS)
    return crop


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--res", nargs="+", default=["1024_cascade"], choices=["512", "1024", "1024_cascade", "1536_cascade"])
    ap.add_argument("--max-tokens", type=int, default=49152)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--cond-size", type=int, default=1024)
    ap.add_argument("--master-verts", type=int, default=500_000)
    ap.add_argument("--master-tex", type=int, default=4096)
    ap.add_argument("--min-free-gb", type=float, default=40.0, help="refuse to start when less unified memory than this is available")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    used, total = mem_gb()
    if total - used < a.min_free_gb:
        print(f"refusing: only {total - used:.0f} GB free (< {a.min_free_gb:.0f}); another job seems to be running", flush=True)
        return 3

    import torch
    import o_voxel
    from trellis2.pipelines import Trellis2ImageTo3DPipeline

    import meshpost

    report: dict = {"image": str(a.image), "seed": a.seed, "max_tokens": a.max_tokens, "cond_size": a.cond_size, "runs": []}
    t = time.time()
    with PeakMemory() as pm_load:
        pipe = Trellis2ImageTo3DPipeline.from_pretrained(str(MODELS / "TRELLIS.2-4B"), config_file="pipeline.clonez.json")
        pipe.low_vram = False
        pipe.cuda()
    report["load"] = {"seconds": round(time.time() - t, 1), "peak_mem_gb": round(pm_load.peak, 1)}
    print("models loaded", report["load"], flush=True)

    photo = Image.open(a.image)
    t = time.time()
    cut = cutout(pipe, photo, a.cond_size)
    report["cutout_seconds"] = round(time.time() - t, 1)
    if cut is None:
        report["error"] = "BiRefNet found no object"
        (a.out / "metrics.json").write_text(json.dumps(report, indent=2))
        return 2
    cut.save(a.out / "cutout.png")

    for res in a.res:
        run: dict = {"res": res}
        report["runs"].append(run)
        torch.cuda.reset_peak_memory_stats()
        t0 = time.time()
        try:
            with PeakMemory() as pm:
                t = time.time()
                m = pipe.run(cut, seed=a.seed, pipeline_type=res, max_num_tokens=a.max_tokens)[0]
                m.simplify(16777216)
                torch.cuda.empty_cache()
                run["trellis_seconds"] = round(time.time() - t, 1)
                t = time.time()
                glb = o_voxel.postprocess.to_glb(
                    vertices=m.vertices.clone(), faces=m.faces.clone(), attr_volume=m.attrs, coords=m.coords, attr_layout=m.layout,
                    voxel_size=m.voxel_size, aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]], decimation_target=a.master_verts,
                    texture_size=a.master_tex, remesh=True, remesh_band=1, remesh_project=0, verbose=False)
                torch.cuda.empty_cache()
                run["to_glb_seconds"] = round(time.time() - t, 1)
                path = a.out / f"master_{res}.glb"
                run["master_triangles"] = meshpost.export_master(glb, path)
                run["master_mb"] = round(path.stat().st_size / 1048576, 1)
            run["peak_mem_gb"] = round(pm.peak, 1)
            run["torch_peak_allocated_gb"] = round(torch.cuda.max_memory_allocated() / 1073741824, 1)
            run["status"] = "ok"
        except Exception as e:  # noqa: BLE001 - recorded, never hidden
            run["status"] = "failed"
            run["error"] = f"{type(e).__name__}: {e}"[:500]
            traceback.print_exc()
            torch.cuda.empty_cache()
        run["total_seconds"] = round(time.time() - t0, 1)
        print(json.dumps(run), flush=True)
        (a.out / "metrics.json").write_text(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
