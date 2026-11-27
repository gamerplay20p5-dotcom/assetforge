#!/usr/bin/env python3
"""Full-frame BiRefNet matting (no re-crop) of every PNG under --src, mirrored into --dst as RGBA. Runs INSIDE the Hank's clonez-mesh:1 image
(read-only weights at /models/BiRefNet). Multi-view input must keep its framing, so unlike `trellis-cli --bg-only` nothing is cropped.

    python matte_birefnet.py --src /in/city --dst /out/city_rgba
"""
import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path[:0] = ["/opt/TRELLIS.2"]
from PIL import Image  # noqa: E402
from trellis2.pipelines.rembg import BiRefNet  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--src", type=Path, required=True)
ap.add_argument("--dst", type=Path, required=True)
ap.add_argument("--model", default="/models/BiRefNet")
a = ap.parse_args()
m = BiRefNet(model_name=a.model)
m.cuda()
files = sorted(p for p in a.src.rglob("*.png"))
for i, p in enumerate(files, 1):
    out = a.dst / p.relative_to(a.src)
    out.parent.mkdir(parents=True, exist_ok=True)
    m(Image.open(p).convert("RGB")).save(out)
    print(f"[{i}/{len(files)}] {p.name}", flush=True)
print("MATTE_DONE")
