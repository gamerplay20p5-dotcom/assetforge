#!/usr/bin/env python3
"""Pilot: reference image -> BiRefNet cutout -> TRELLIS.2 -> master GLB, with timing, memory and the effective resolution measured.

Runs INSIDE the AssetPipeline's `clonez-mesh:1` Docker image on the DGX Spark (see run_pilot.sh). It only reads the Hank pipeline's code (mounted
read-only at /hank) and weights (/models, read-only); everything it writes goes to --out. It reuses his `Generator.cutout` logic (BiRefNet crop at
full resolution) and `meshpost.drop_inner_shells`, and calls TRELLIS.2 like `Generator.mesh` does, minus Z-Image, Ollama and the game-specific fit.

Bake modes (the texture bake inside ``to_glb``):
  --bake nvdiffrast  original o_voxel.to_glb (nvdiffrast: research/evaluation use only)        -> out/<name>/experimental/
  --bake torch       assetforge_trellis2.to_glb_commercial (pure PyTorch rasteriser, MIT)      -> out/<name>/commercial_candidate/
  --bake both        both on the same TRELLIS.2 result, with a texture/geometry comparison     -> experimental/ and commercial_candidate/
  --commercial       also blocks nvdiffrast/nvdiffrec (they raise on use) so a finished run PROVES they were not needed; implies --bake torch

Exit codes: 0 all runs ok; 1 at least one run failed or the models did not load; 2 BiRefNet found no object; 3 refused (memory / another job);
75 aborted by the memory watchdog. Repeated resolutions (--res 1024_cascade 1024_cascade) give a warm second measurement.

    python pilot_reconstruct.py --image in/tower.png --out out/tower --res 1024_cascade 1024_cascade 1536_cascade 1536_cascade --bake both
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
import threading
import time
import traceback
from pathlib import Path

sys.dont_write_bytecode = True
sys.path[:0] = ["/pilot/code", "/hank/Tools/AssetPipeline/mesh", "/hank/Tools/AssetPipeline"]

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

MODELS = Path(os.environ.get("CLONEZ_MODELS", "/models"))
EXIT_ABORTED = 75


def mem_gb() -> tuple[float, float, float]:
    """(used, available, total) of the Spark's unified memory, from /proc/meminfo."""
    d = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        k, v = line.split(":", 1)
        d[k] = int(v.split()[0])
    gb = 1048576
    return (d["MemTotal"] - d["MemAvailable"]) / gb, d["MemAvailable"] / gb, d["MemTotal"] / gb


class Watch:
    """Samples memory twice a second: keeps the peak and ABORTS the whole process if the system runs short (so the kernel's OOM killer never has to pick
    a victim among other people's processes)."""

    def __init__(self, min_available_gb: float, report_path: Path | None = None) -> None:
        self.peak = 0.0
        self.min_available = min_available_gb
        self.report_path = report_path
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(0.5):
            used, avail, _ = mem_gb()
            self.peak = max(self.peak, used)
            if avail < self.min_available:
                msg = f"memory watchdog: only {avail:.1f} GB available (< {self.min_available:.0f}); aborting this job"
                print(msg, flush=True)
                if self.report_path:
                    try:
                        self.report_path.write_text(json.dumps({"aborted": msg}))
                    except OSError:
                        pass
                os._exit(EXIT_ABORTED)

    def __enter__(self) -> "Watch":
        self.peak = mem_gb()[0]
        self._t.start()
        return self

    def __exit__(self, *a) -> None:
        self._stop.set()
        self._t.join()


class Tee:
    """stdout wrapper that notices TRELLIS.2's 'resolution is reduced to N' message (the token budget lowering the cascade resolution)."""

    def __init__(self, inner) -> None:  # noqa: ANN001
        self.inner, self.reduced_to = inner, None

    def write(self, s: str) -> int:
        m = re.search(r"resolution is reduced to (\d+)", s)
        if m:
            self.reduced_to = int(m.group(1))
        return self.inner.write(s)

    def flush(self) -> None:
        self.inner.flush()

    def __getattr__(self, n: str):  # noqa: ANN204
        return getattr(self.inner, n)


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


def compare_glb(a, b) -> dict:
    """Original (nvdiffrast) vs commercial (PyTorch) bake of the SAME TRELLIS.2 result: same geometry? how different are the textures?"""
    out: dict = {"same_vertices": bool(a.vertices.shape == b.vertices.shape and np.allclose(a.vertices, b.vertices, atol=1e-6)),
                 "same_faces": bool(a.faces.shape == b.faces.shape and (a.faces == b.faces).all()),
                 "same_uv": bool(a.visual.uv.shape == b.visual.uv.shape and np.allclose(a.visual.uv, b.visual.uv, atol=1e-6))}
    for name in ("baseColorTexture", "metallicRoughnessTexture"):
        ta, tb = getattr(a.visual.material, name), getattr(b.visual.material, name)
        x, y = np.asarray(ta, dtype=np.int16), np.asarray(tb, dtype=np.int16)
        if x.shape != y.shape:
            out[name] = {"error": f"shape {x.shape} vs {y.shape}"}
            continue
        d = np.abs(x - y)
        out[name] = {"mean_abs_diff_0_255": round(float(d.mean()), 3), "p99_abs_diff": int(np.percentile(d, 99)), "max_abs_diff": int(d.max()),
                     "pixels_differing_by_more_than_8": round(float((d.max(axis=-1) > 8).mean()), 5)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--res", nargs="+", default=["1024_cascade"], choices=["512", "1024", "1024_cascade", "1536_cascade"])
    ap.add_argument("--bake", choices=["nvdiffrast", "torch", "both"], default="nvdiffrast")
    ap.add_argument("--commercial", action="store_true", help="block nvdiffrast/nvdiffrec and use only the PyTorch bake")
    ap.add_argument("--lods", default="", help="comma list of to_glb vertex targets: also bake LOD meshes (commercial to_glb), e.g. 8000,4000,1400,300")
    ap.add_argument("--lod-tex", default="2048,2048,1024,512", help="texture size per LOD")
    ap.add_argument("--max-tokens", type=int, default=49152)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--cond-size", type=int, default=1024)
    ap.add_argument("--master-verts", type=int, default=500_000)
    ap.add_argument("--master-tex", type=int, default=4096)
    ap.add_argument("--min-free-gb", type=float, default=60.0, help="refuse to start with less unified memory available than this")
    ap.add_argument("--abort-available-gb", type=float, default=12.0, help="abort the job if available memory drops below this while running")
    a = ap.parse_args()
    if a.commercial:
        a.bake = "torch"
    a.out.mkdir(parents=True, exist_ok=True)

    lock = open("/pilot/.lock", "w")  # exclusivity: one AssetForge job at a time on the Spark (the lock lives on the host-mounted folder)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("refusing: another AssetForge job holds the Spark lock", flush=True)
        return 3
    used, avail, total = mem_gb()
    if avail < a.min_free_gb:
        print(f"refusing: only {avail:.0f} GB available (< {a.min_free_gb:.0f}); another job seems to be running", flush=True)
        return 3

    if a.commercial:
        from assetforge_trellis2.license_guard import block_noncommercial

        block_noncommercial()

    import torch
    from trellis2.pipelines import Trellis2ImageTo3DPipeline

    import meshpost

    tee = Tee(sys.stdout)
    sys.stdout = tee
    report: dict = {"image": str(a.image), "seed": a.seed, "max_tokens": a.max_tokens, "cond_size": a.cond_size, "bake": a.bake, "commercial_guard": a.commercial,
                    "runs": [], "failed": False}
    metrics_path = a.out / "metrics.json"
    status = 0
    try:
        with Watch(a.abort_available_gb, a.out / "aborted.json") as w:
            t = time.time()
            pipe = Trellis2ImageTo3DPipeline.from_pretrained(str(MODELS / "TRELLIS.2-4B"), config_file="pipeline.clonez.json")
            pipe.low_vram = False
            pipe.cuda()
        report["load"] = {"seconds": round(time.time() - t, 1), "peak_mem_gb": round(w.peak, 1)}
        print("models loaded", report["load"], flush=True)

        t = time.time()
        with Watch(a.abort_available_gb, a.out / "aborted.json"):
            cut = cutout(pipe, Image.open(a.image), a.cond_size)
        report["cutout_seconds"] = round(time.time() - t, 1)
        if cut is None:
            report["error"] = "BiRefNet found no object"
            metrics_path.write_text(json.dumps(report, indent=2))
            return 2
        cut.save(a.out / "cutout.png")

        import o_voxel  # original to_glb: needs nvdiffrast, only touched in --bake nvdiffrast/both
        from assetforge_trellis2.to_glb import to_glb_commercial

        seen: dict[str, int] = {}
        for res in a.res:
            seen[res] = seen.get(res, 0) + 1
            run: dict = {"res": res, "repeat": seen[res], "warm": seen[res] > 1}
            report["runs"].append(run)
            torch.cuda.reset_peak_memory_stats()
            tee.reduced_to = None
            t0 = time.time()
            try:
                with Watch(a.abort_available_gb, a.out / "aborted.json") as w:
                    t = time.time()
                    m = pipe.run(cut, seed=a.seed, pipeline_type=res, max_num_tokens=a.max_tokens)[0]
                    m.simplify(16777216)
                    torch.cuda.empty_cache()
                    run["trellis_seconds"] = round(time.time() - t, 1)
                    req = int(res.split("_")[0])
                    run["requested_resolution"] = req
                    run["effective_resolution"] = tee.reduced_to or req  # the token budget can lower the cascade's resolution
                    run["resolution_reduced_by_token_limit"] = tee.reduced_to is not None
                    run["tokens"] = int(m.coords.shape[0]) if hasattr(m, "coords") else None

                    def bake(kind: str):  # noqa: ANN202
                        t1 = time.time()
                        fn = o_voxel.postprocess.to_glb if kind == "nvdiffrast" else to_glb_commercial
                        glb = fn(vertices=m.vertices.clone(), faces=m.faces.clone(), attr_volume=m.attrs, coords=m.coords, attr_layout=m.layout,
                                 voxel_size=m.voxel_size, aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]], decimation_target=a.master_verts,
                                 texture_size=a.master_tex, remesh=True, remesh_band=1, remesh_project=0, verbose=False)
                        torch.cuda.empty_cache()
                        return glb, round(time.time() - t1, 1)

                    glbs = {}
                    for kind in (["nvdiffrast", "torch"] if a.bake == "both" else [a.bake]):
                        glb, secs = bake(kind)
                        folder = "experimental" if kind == "nvdiffrast" else "commercial_candidate"
                        (a.out / folder).mkdir(exist_ok=True)
                        path = a.out / folder / f"master_{res}_r{seen[res]}.glb"
                        tris = meshpost.export_master(glb, path)
                        run[f"bake_{kind}"] = {"seconds": secs, "master_triangles": tris, "master_mb": round(path.stat().st_size / 1048576, 1), "file": str(path.relative_to(a.out))}
                        glbs[kind] = glb
                    if a.bake == "both":
                        run["bake_comparison"] = compare_glb(glbs["nvdiffrast"], glbs["torch"])
                    if a.lods and seen[res] == 1:  # LODs straight from TRELLIS.2's own structured remesh (collapse-decimating the master shreds it)
                        run["lods"] = []
                        lod_dir = a.out / "lods"
                        lod_dir.mkdir(exist_ok=True)
                        for li, (tv, tx) in enumerate(zip([int(x) for x in a.lods.split(",")], [int(x) for x in a.lod_tex.split(",")])):
                            t1 = time.time()
                            g = to_glb_commercial(vertices=m.vertices.clone(), faces=m.faces.clone(), attr_volume=m.attrs, coords=m.coords, attr_layout=m.layout,
                                                  voxel_size=m.voxel_size, aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]], decimation_target=tv, texture_size=tx,
                                                  remesh=True, remesh_band=1, remesh_project=0, verbose=False)
                            torch.cuda.empty_cache()
                            lp = lod_dir / f"lod{li}_{res}_v{tv}.glb"
                            ltris = meshpost.export_master(g, lp)
                            run["lods"].append({"lod": li, "target_vertices": tv, "texture_px": tx, "triangles": ltris, "seconds": round(time.time() - t1, 1),
                                                "file": str(lp.relative_to(a.out))})
                            print(json.dumps(run["lods"][-1]), flush=True)
                run["peak_mem_gb"] = round(w.peak, 1)
                run["torch_peak_allocated_gb"] = round(torch.cuda.max_memory_allocated() / 1073741824, 1)
                run["status"] = "ok"
            except Exception as e:  # noqa: BLE001 - recorded, never hidden
                run["status"] = "failed"
                run["error"] = f"{type(e).__name__}: {e}"[:500]
                report["failed"] = True
                traceback.print_exc()
                torch.cuda.empty_cache()
            run["total_seconds"] = round(time.time() - t0, 1)
            print(json.dumps(run), flush=True)
            metrics_path.write_text(json.dumps(report, indent=2))
    except Exception as e:  # noqa: BLE001
        report["failed"] = True
        report["error"] = f"{type(e).__name__}: {e}"[:500]
        traceback.print_exc()
        status = 1
    if a.commercial:
        from assetforge_trellis2.license_guard import violations

        report["licence_guard_violations"] = violations()
        if violations():
            report["failed"] = True
    report["provenance"] = {
        "experimental": "uses nvdiffrast (research/evaluation only): NOT for commercial assets" if a.bake in ("nvdiffrast", "both") else None,
        "commercial_candidate": ("candidate only: nvdiffrast/nvdiffrec not used" + (" (guard proved it)" if a.commercial else " (guard NOT enabled in this run)")
                                 if a.bake in ("torch", "both") else None),
        "commercial_ready": False,
        "open_items": ["legal review of DINOv3 terms (export controls, weapons/military end-use)", "BiRefNet training-data terms", "GPL/LGPL packages in the image (plyfile, easydict) if the image is ever redistributed"],
    }
    metrics_path.write_text(json.dumps(report, indent=2))
    if status == 0 and report["failed"]:
        status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
