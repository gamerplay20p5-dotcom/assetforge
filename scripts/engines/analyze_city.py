#!/usr/bin/env python3
"""Analyses engine results of the city pilot, locally (Windows, Blender in .tools). Safe to re-run: finished models are cached in <out>/<name>/analysis.json.

Per model dir  <results>/<asset>_<engine>_<res>_<machine>/model.glb  (+ summary.json from run_cpp.sh):
  * triangles, disconnected components (welded vertices), extents, file size
  * orientation: scripts/engines/level_glb.py -> model_level.glb (NON-destructive: only a parent node is added)
  * 4 renders with the SAME cameras/light for every model (scripts/review/blender_views.py, plain backdrop)
Per asset: <out>/sheets/<asset>.jpg  = reference views (front,right,back,34) + one row per engine run (+ speed/memory caption from summary.json).

    python scripts/engines/analyze_city.py --results reports_out/engines/results --refs reports_out/engines/city_inputs --out reports_out/engines/analysis
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
ENGINES = ("t2q8", "sv", "mv4", "mv3")
VIEWS = ["front_left", "front_right", "back", "aerial"]


def blender() -> str:
    return str(next((ROOT / ".tools" / "blender").rglob("blender.exe")))


def components(faces: np.ndarray, verts: np.ndarray) -> tuple[int, int]:
    """(number of disconnected components, faces outside the largest one), vertices welded at 1e-5 first (UV seams duplicate vertices)."""
    key = np.round(verts / 1e-5).astype(np.int64)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    f = inv.ravel()[faces]
    label = np.arange(inv.max() + 1)
    e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    for _ in range(400):  # vectorised min-label propagation
        m = np.minimum(label[e[:, 0]], label[e[:, 1]])
        new = label.copy()
        np.minimum.at(new, e[:, 0], m)
        np.minimum.at(new, e[:, 1], m)
        new = new[new]  # pointer jumping
        if (new == label).all():
            break
        label = new
    fl = label[f[:, 0]]
    counts = np.bincount(np.unique(fl, return_inverse=True)[1])
    return int(len(counts)), int(len(faces) - counts.max())


def parse(name: str):
    for eng in ENGINES:
        tag = f"_{eng}_"
        if tag in name:
            asset, rest = name.split(tag, 1)
            res, _, machine = rest.partition("_")
            return asset, eng, res, machine
    return None


def analyse(d: Path, out: Path) -> dict:
    cache = out / d.name / "analysis.json"
    if cache.is_file():
        return json.loads(cache.read_text())
    (out / d.name).mkdir(parents=True, exist_ok=True)
    scene = trimesh.load(str(d / "model.glb"))
    v = np.vstack([g.vertices for g in scene.geometry.values()])
    f = np.vstack([g.faces + off for g, off in zip(scene.geometry.values(), np.cumsum([0] + [len(g.vertices) for g in scene.geometry.values()])[:-1])])
    nc, loose = components(f, v)
    lvl = out / d.name / "model_level.glb"
    rep = json.loads(subprocess.run([sys.executable, str(ROOT / "scripts/engines/level_glb.py"), str(d / "model.glb"), str(lvl)], capture_output=True, text=True, check=True).stdout)
    ext = np.array(rep["extent_after"])
    portrait = ext[1] > 1.3 * max(ext[0], ext[2])
    args = [blender(), "-b", "-P", str(ROOT / "scripts/review/blender_views.py"), "--", str(lvl), str(out / d.name / "r"), "40", "700", ",".join(VIEWS), "plain",
            f"{ext[1] * 65:.3f}"] + (["portrait"] if portrait else ["landscape"]) + ["65"]
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    res = {"name": d.name, "triangles": int(len(f)), "components": nc, "faces_outside_largest_component": loose, "orientation": rep,
           "glb_mb": round((d / "model.glb").stat().st_size / 1048576, 1), "summary": json.loads((d / "summary.json").read_text()) if (d / "summary.json").is_file() else None}
    cache.write_text(json.dumps(res, indent=1))
    return res


def sheet(asset: str, runs: list[dict], refs: Path, out: Path) -> None:
    S = 300
    img = Image.new("RGB", (S * 5, (S + 24) * (1 + len(runs))), (30, 32, 36))
    d = ImageDraw.Draw(img)
    d.text((6, 6), f"{asset}: referencia (front, right, back, 3/4)", fill=(240, 240, 240))
    for c, fn in enumerate(sorted((refs / asset / "mv4").glob("view*.png"))):
        im = Image.open(fn).convert("RGBA")
        bg = Image.new("RGBA", im.size, (200, 200, 200, 255))
        bg.alpha_composite(im)
        im = bg.convert("RGB")
        im.thumbnail((S, S))
        img.paste(im, (c * S, 24))
    for r, run in enumerate(runs, 1):
        y = r * (S + 24)
        s = run["summary"] or {}
        cap = f'{run["name"].replace(asset + "_", "")}  {run["triangles"]:,} tri  comp {run["components"]}  tilt {run["orientation"]["tilt_deg_estimated"]}deg  ' \
              f'{s.get("wall_seconds", "?")}s  RAM+{(s.get("peak_ram_delta_mb") or 0) // 1024}GB  VRAM {s.get("peak_gpu_mb", "NA")}MB'
        d.text((6, y + 6), cap, fill=(240, 240, 240))
        for c, v in enumerate(VIEWS):
            p = out / run["name"] / f"r_{v}.png"
            if p.is_file():
                im = Image.open(p).convert("RGB")
                im.thumbnail((S, S))
                img.paste(im, (c * S, y + 24))
    (out / "sheets").mkdir(exist_ok=True)
    img.save(out / "sheets" / f"{asset}.jpg", quality=88)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, required=True)
    ap.add_argument("--refs", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    a.results, a.refs, a.out = a.results.resolve(), a.refs.resolve(), a.out.resolve()  # Blender resolves relative paths against ITS own folder
    a.out.mkdir(parents=True, exist_ok=True)
    by_asset: dict[str, list[dict]] = {}
    for d in sorted(a.results.iterdir()):
        p = parse(d.name)
        if p and (d / "model.glb").is_file():
            r = analyse(d, a.out)
            by_asset.setdefault(p[0], []).append(r)
            print(json.dumps({k: r[k] for k in ("name", "triangles", "components", "glb_mb")}), flush=True)
    for asset, runs in by_asset.items():
        sheet(asset, runs, a.refs, a.out)
    (a.out / "all.json").write_text(json.dumps([r for rs in by_asset.values() for r in rs], indent=1))


if __name__ == "__main__":
    main()
