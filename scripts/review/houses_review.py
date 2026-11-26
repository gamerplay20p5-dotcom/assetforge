#!/usr/bin/env python3
"""Generate the review houses (GLB) and render them from several perspectives for visual approval.

    python scripts/review/houses_review.py --out reports_out/houses_v1 [--only modern] [--samples 64] [--size 960]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for d in ("generators/procedural", "pipeline/export", "pipeline/validation", "pipeline/optimization", "packages/asset-contract"):
    sys.path.insert(0, str(ROOT / d))

from assetforge_export.glb import render_textures, write_glb  # noqa: E402
from assetforge_export.pipeline import find_blender  # noqa: E402
from assetforge_optimization import clean_mesh  # noqa: E402
from assetforge_procedural.house import ARCHETYPES, generate_house  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "reports_out" / "houses_v1")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--samples", type=int, default=64)
    ap.add_argument("--size", type=int, default=960)
    ap.add_argument("--views", default="front_left,front_right,side,back,aerial,front_low")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--texres", type=int, default=1024)
    args = ap.parse_args()
    blender = find_blender() or str(next((ROOT / ".tools" / "blender").rglob("blender.exe"), "")) or None
    print("blender:", blender, flush=True)
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    report = []
    for name, factory in ARCHETYPES.items():
        if args.only and name not in args.only:
            continue
        gen = generate_house(factory(1))
        spec, _ = clean_mesh(gen.mesh)
        d = args.out / name
        d.mkdir(exist_ok=True)
        textures = render_textures(gen.materials, args.texres, d / "textures")
        write_glb(d / "model.glb", spec, gen.materials, textures, name, {})
        (d / "spec.json").write_text(json.dumps(gen.summary["spec"], indent=2, ensure_ascii=False), encoding="utf-8")
        info = {"archetype": name, "triangles": spec.triangle_count, "materials": len(gen.materials), "dims_m": [round(x, 2) for x in gen.dimensions]}
        print(info, flush=True)
        report.append(info)
        if not args.no_render and blender:
            subprocess.run([blender, "-b", "-P", str(Path(__file__).with_name("blender_views.py")), "--", str(d / "model.glb"), str(d / "view"),
                            str(args.samples), str(args.size), args.views], check=True)
            views = [p for p in sorted(d.glob("view_*.png"))]
            if views:
                w, h = Image.open(views[0]).size
                cols = 3
                rows = (len(views) + cols - 1) // cols
                sheet = Image.new("RGB", (w * cols, h * rows), "white")
                for i, p in enumerate(views):
                    sheet.paste(Image.open(p).convert("RGB"), ((i % cols) * w, (i // cols) * h))
                sheet.save(d / "sheet.jpg", quality=90)
    (args.out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
