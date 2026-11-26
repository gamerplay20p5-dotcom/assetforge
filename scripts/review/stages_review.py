#!/usr/bin/env python3
"""Render the six construction stages of one house archetype with identical framing and compose a 3x2 sheet.

    python scripts/review/stages_review.py --archetype bungalow --out reports_out/stages_bungalow
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
from assetforge_optimization import clean_mesh  # noqa: E402
from assetforge_procedural.house import ARCHETYPES, generate_house  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archetype", default="bungalow")
    ap.add_argument("--out", type=Path, default=ROOT / "reports_out" / "stages")
    ap.add_argument("--samples", type=int, default=48)
    ap.add_argument("--size", type=int, default=800)
    ap.add_argument("--view", default="front_right")
    ap.add_argument("--no-render", action="store_true")
    args = ap.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    blender = next((ROOT / ".tools" / "blender").rglob("blender.exe"), None)
    info = []
    for st in range(1, 7):
        gen = generate_house(ARCHETYPES[args.archetype](1), st)
        spec, _ = clean_mesh(gen.mesh, normalize_pivot=False)
        d = out / f"stage{st}"
        d.mkdir(exist_ok=True)
        tex = render_textures(gen.materials, 1024, d / "textures")
        write_glb(d / "model.glb", spec, gen.materials, tex, f"{args.archetype}_stage{st}", {})
        lo, hi = spec.bounds()
        info.append({"stage": st, "triangles": spec.triangle_count, "footprint": [round(float(hi[0] - lo[0]), 2), round(float(hi[2] - lo[2]), 2)]})
        print(info[-1], flush=True)
        if not args.no_render and blender:
            subprocess.run([str(blender), "-b", "-P", str(Path(__file__).with_name("blender_views.py")), "--", str(d / "model.glb"), str(d / "view"),
                            str(args.samples), str(args.size), args.view, "plain"], check=True, stdout=subprocess.DEVNULL)
    (out / "report.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    imgs = [out / f"stage{st}" / f"view_{args.view}.png" for st in range(1, 7)]
    if all(p.is_file() for p in imgs):
        w, h = Image.open(imgs[0]).size
        sheet = Image.new("RGB", (w * 3, h * 2), (204, 204, 201))
        for i, p in enumerate(imgs):
            sheet.paste(Image.open(p).convert("RGB"), ((i % 3) * w, (i // 3) * h))
        sheet.save(out / "sheet.jpg", quality=90)
    return 0


if __name__ == "__main__":
    sys.exit(main())
