#!/usr/bin/env python3
"""Builds the inputs of every engine from the 4 matted views of an asset (front, right, back, 34).

For each asset  <out>/<asset>/ :
  front.png        original gray-background front view          -> TRELLIS.2 (it mattes by itself)
  sv_rgba.png      matted front view (RGBA)                     -> Pixal3D single-view (--sv-image)
  mv4/             front,right,back + 3/4 view with transforms.json (azimuth 0/90/180/45)  -> Pixal3D multi-view (--views); the 3/4 azimuth is an ASSUMPTION
  mv3/             front,right,back (0/90/180)                  -> Pixal3D multi-view with 3 views
Framing rules of pixal3d.cpp: real alpha, NO re-crop, same scale in every view, object ~85 % of the frame, centred. Cameras: canonical Pixal3D rig
(distance 3.119, FOV 20 deg, elevation 0, z-up, azimuth 0 = front, 90 = right) copied from the upstream example's transforms.json convention.
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

N = 1024
FILL = 0.85
DIST = 3.119


def bbox(im):
    a = np.asarray(im)[..., 3] > 127
    ys, xs = np.nonzero(a)
    return xs.min(), xs.max() + 1, ys.min(), ys.max() + 1


def pose(az_deg):
    t = math.radians(az_deg)
    c0, c1, c2 = (math.cos(t), math.sin(t), 0.0), (0.0, 0.0, 1.0), (math.sin(t), -math.cos(t), 0.0)
    return [[c0[0], c1[0], c2[0], DIST * c2[0]], [c0[1], c1[1], c2[1], DIST * c2[1]], [c0[2], c1[2], c2[2], 0.0], [0.0, 0.0, 0.0, 1.0]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rgba", type=Path, required=True, help="matted views, any depth")
    ap.add_argument("--orig", type=Path, required=True, help="original (gray background) views, any depth")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    rgba = {p.stem: p for p in a.rgba.rglob("*.png")}
    orig = {p.stem: p for p in a.orig.rglob("*.png")}
    assets = sorted({s.rsplit("_", 1)[0] for s in rgba})
    report = {}
    for asset in assets:
        views = {v: Image.open(rgba[f"{asset}_{v}"]).convert("RGBA") for v in ("front", "right", "back", "34")}
        boxes = {v: bbox(im) for v, im in views.items()}
        side = max(max(b[1] - b[0], b[3] - b[2]) for b in boxes.values())  # largest object extent over all views
        s = FILL * N / side  # ONE scale for every view

        def frame(v):
            im, (x0, x1, y0, y1) = views[v], boxes[v]
            r = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
            cx, cy = (x0 + x1) / 2 * s, (y0 + y1) / 2 * s
            canvas = Image.new("RGBA", (N, N), (0, 0, 0, 0))
            canvas.paste(r, (round(N / 2 - cx), round(N / 2 - cy)), r)
            return canvas

        d = a.out / asset
        for sub in ("mv4", "mv3"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        Image.open(orig[f"{asset}_front"]).convert("RGB").save(d / "front.png")
        views["front"].save(d / "sv_rgba.png")
        sets = {"mv4": [("front", 0), ("right", 90), ("back", 180), ("34", 45)], "mv3": [("front", 0), ("right", 90), ("back", 180)]}
        for name, lst in sets.items():
            frames = []
            for i, (v, az) in enumerate(lst):
                fn = f"view{i:02d}_{v}_azim{az:03d}.png"
                frame(v).save(d / name / fn)
                frames.append({"file_path": fn, "transform_matrix": pose(az)})
            (d / name / "transforms.json").write_text(json.dumps({"camera_angle_x": 0.3490658503988659, "mesh_scale": 1.0, "frames": frames}, indent=1))
        report[asset] = {"scale": round(s, 3), "extent_px_in_1254_frame": int(side), "fill": FILL}
    (a.out / "prep_report.json").write_text(json.dumps(report, indent=1))
    print(len(assets), "assets prepared")


if __name__ == "__main__":
    main()
