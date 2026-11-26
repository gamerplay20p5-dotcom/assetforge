#!/usr/bin/env python3
"""End-to-end check of the vision flow: benchmark JSON -> description -> kit house -> Blender render (stage 6), one image per house.

    python scripts/vlm/render_predictions.py --json reports_out/vlm/Qwen2.5-VL-7B-Instruct.json --out reports_out/vlm/render_7b
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for d in ("generators/procedural", "generators/vision", "pipeline/export", "pipeline/validation", "pipeline/optimization", "packages/asset-contract"):
    sys.path.insert(0, str(ROOT / d))

from assetforge_export.glb import render_textures, write_glb  # noqa: E402
from assetforge_optimization import clean_mesh  # noqa: E402
from assetforge_procedural.house import generate_house  # noqa: E402
from assetforge_vision.mapper import description_to_spec  # noqa: E402
from assetforge_vision.schema import parse_description  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--samples", type=int, default=40)
    args = ap.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    blender = next((ROOT / ".tools" / "blender").rglob("blender.exe"))
    data = json.loads(args.json.read_text(encoding="utf-8"))
    for row in data["rows"]:
        if not row.get("valid"):
            continue
        spec = description_to_spec(parse_description(row["parsed"]))
        gen = generate_house(spec, 6)
        mesh, _ = clean_mesh(gen.mesh, normalize_pivot=False)
        d = out / row["house"]
        d.mkdir(exist_ok=True)
        tex = render_textures(gen.materials, 1024, d / "textures")
        write_glb(d / "model.glb", mesh, gen.materials, tex, row["house"], {})
        (d / "description.json").write_text(json.dumps(row["parsed"], indent=2, ensure_ascii=False), encoding="utf-8")
        subprocess.run([str(blender), "-b", "-P", str(ROOT / "scripts/review/blender_views.py"), "--", str(d / "model.glb"), str(d / "view"),
                        str(args.samples), "800", "front_right", "plain", f"{gen.dimensions[1]:.3f}"], check=True, stdout=subprocess.DEVNULL)
        print(row["house"], spec.archetype, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
