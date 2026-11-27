#!/usr/bin/env python3
"""Non-destructive orientation fix for reconstructions that come out in the input camera's frame (pixal3d single-view: pitched by the photo's elevation).

Estimates the tilt of the model's dominant vertical axis, then writes a NEW glb where only a parent node (rotation + translation: upright, pivot at the
bottom centre, resting on y=0) is added to the glTF JSON. Vertex/texture data are byte-identical to the input, so the original master is preserved.

    python level_glb.py in.glb out.glb [--mode auto|tallest|none] [--max-tilt 40]
Report (stdout, JSON): estimated tilt, rotation applied, extents before/after.
"""
import argparse
import json
import struct
import sys

import numpy as np
import trimesh


def read_glb(path):
    d = open(path, "rb").read()
    assert d[:4] == b"glTF"
    jl = struct.unpack("<I", d[12:16])[0]
    return json.loads(d[20:20 + jl]), d[20 + jl:], d


def rot_from_to(a, b):
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if np.linalg.norm(v) < 1e-9:
        return np.eye(3) if c > 0 else np.diag([1, -1, -1])
    k = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + k + k @ k * ((1 - c) / (v @ v))


def quat(R):
    """rotation matrix -> glTF quaternion [x, y, z, w]"""
    t = np.trace(R)
    if t > 0:
        sc = np.sqrt(t + 1.0) * 2
        q = [(R[2, 1] - R[1, 2]) / sc, (R[0, 2] - R[2, 0]) / sc, (R[1, 0] - R[0, 1]) / sc, 0.25 * sc]
    else:
        i = int(np.argmax(np.diag(R)))
        j, k = (i + 1) % 3, (i + 2) % 3
        sc = np.sqrt(1.0 + R[i, i] - R[j, j] - R[k, k]) * 2
        q = [0.0] * 4
        q[i], q[3] = 0.25 * sc, (R[k, j] - R[j, k]) / sc
        q[j], q[k] = (R[j, i] + R[i, j]) / sc, (R[k, i] + R[i, k]) / sc
    n = np.linalg.norm(q)
    return [float(x / n) for x in q]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--mode", choices=["auto", "tallest", "none"], default="auto")
    ap.add_argument("--max-tilt", type=float, default=40.0, help="refuse to correct more than this many degrees (probably a wrong estimate)")
    a = ap.parse_args()
    scene = trimesh.load(a.src)
    v = np.vstack([g.vertices for g in scene.geometry.values()])
    sub = v[np.random.default_rng(0).choice(len(v), min(len(v), 400_000), replace=False)]
    c = sub.mean(0)
    w, e = np.linalg.eigh(np.cov((sub - c).T))
    axis = e[:, np.argmax(w)]  # axis of largest variance
    if axis[1] < 0:
        axis = -axis
    up = np.array([0.0, 1.0, 0.0])
    tilt = float(np.degrees(np.arccos(np.clip(axis @ up, -1, 1))))
    ext = sub.max(0) - sub.min(0)
    tall = ext[1] >= max(ext[0], ext[2]) * 0.9 or tilt < a.max_tilt and w.max() > 1.8 * np.sort(w)[1]  # clearly elongated vertically
    R = np.eye(3)
    applied = False
    if a.mode != "none" and tilt <= a.max_tilt and (a.mode == "tallest" or tall) and tilt > 0.5:
        R, applied = rot_from_to(axis, up), True
    vr = (sub - c) @ R.T
    t = np.array([-(vr[:, 0].min() + vr[:, 0].max()) / 2, -vr[:, 1].min(), -(vr[:, 2].min() + vr[:, 2].max()) / 2])  # bottom centre on the origin
    # node transform: x' = R (x - c) + t = R x + (t - R c)
    trans = t - R @ c
    j, binchunk, raw = read_glb(a.src)
    roots = j["scenes"][j.get("scene", 0)]["nodes"]
    j["nodes"].append({"name": "AssetForge_upright", "children": roots, "rotation": quat(R), "translation": [float(x) for x in trans]})
    j["scenes"][j.get("scene", 0)]["nodes"] = [len(j["nodes"]) - 1]
    jb = json.dumps(j, separators=(",", ":")).encode()
    jb += b" " * (-len(jb) % 4)
    out = b"glTF" + struct.pack("<II", 2, 12 + 8 + len(jb) + len(binchunk)) + struct.pack("<I", len(jb)) + b"JSON" + jb + binchunk
    open(a.dst, "wb").write(out)
    after = vr + t
    print(json.dumps({"tilt_deg_estimated": round(tilt, 2), "applied": applied, "extent_before": [round(float(x), 3) for x in ext],
                      "extent_after": [round(float(x), 3) for x in (after.max(0) - after.min(0))], "mode": a.mode}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
