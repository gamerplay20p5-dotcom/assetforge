#!/usr/bin/env python3
"""Equivalence test: nvdiffrast's UV-space rasterisation vs assetforge_trellis2.uvraster (pure PyTorch, MIT) on the SAME mesh and UV layout.

Runs inside the clonez-mesh image (needs a GPU and, for the reference side, nvdiffrast: research/evaluation use). The texel coverage and the 3D position found
under every covered texel must agree; those are the only two things to_glb takes from the rasteriser.

    PILOT_SCRIPT=test_uvraster.py bash run_pilot.sh --glb /pilot/out/<run>/commercial_candidate/master_1024_cascade_r1.glb --size 2048 --json /pilot/out/uvraster_test.json
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path[:0] = ["/pilot/code"]
import numpy as np  # noqa: E402
import torch  # noqa: E402
import trimesh  # noqa: E402
import nvdiffrast.torch as dr  # noqa: E402
from assetforge_trellis2.uvraster import rasterize_uv  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--glb", type=Path, required=True)
ap.add_argument("--size", type=int, default=2048)
ap.add_argument("--json", type=Path, required=True)
a = ap.parse_args()

g = list(trimesh.load(str(a.glb)).geometry.values())[0]
uv = np.asarray(g.visual.uv, dtype=np.float32).copy()
uv[:, 1] = 1 - uv[:, 1]  # undo the exporter's V flip: to_glb rasterises the un-flipped layout
uvs = torch.tensor(uv, device="cuda")
faces = torch.tensor(np.asarray(g.faces), dtype=torch.int32, device="cuda")
verts = torch.tensor(np.asarray(g.vertices), dtype=torch.float32, device="cuda")
size = a.size
res: dict = {"glb": str(a.glb), "faces": int(faces.shape[0]), "size": size}

# --- reference: the original nvdiffrast block of o_voxel.postprocess.to_glb ---
torch.cuda.synchronize(); torch.cuda.reset_peak_memory_stats(); t = time.time()
ctx = dr.RasterizeCudaContext()
uvs_rast = torch.cat([uvs * 2 - 1, torch.zeros_like(uvs[:, :1]), torch.ones_like(uvs[:, :1])], dim=-1).unsqueeze(0)
rast = torch.zeros((1, size, size, 4), device="cuda", dtype=torch.float32)
for i in range(0, faces.shape[0], 100000):
    rc, _ = dr.rasterize(ctx, uvs_rast, faces[i:i + 100000], resolution=[size, size])
    mc = rc[..., 3:4] > 0
    rc[..., 3:4] += i
    rast = torch.where(mc, rc, rast)
mask_a = rast[0, ..., 3] > 0
pos_a = dr.interpolate(verts.unsqueeze(0), rast, faces)[0][0]
torch.cuda.synchronize()
res["nvdiffrast"] = {"seconds": round(time.time() - t, 2), "peak_alloc_gb": round(torch.cuda.max_memory_allocated() / 1073741824, 2)}
del rast, uvs_rast

# --- ours ---
torch.cuda.synchronize(); torch.cuda.reset_peak_memory_stats(); t = time.time()
mask_b, tri, bary = rasterize_uv(uvs, faces, size)
pos_b = torch.zeros((size, size, 3), device="cuda")
pos_b[mask_b] = (verts[faces[tri[mask_b].long()].long()] * bary[mask_b].unsqueeze(-1)).sum(1)
torch.cuda.synchronize()
res["uvraster_torch"] = {"seconds": round(time.time() - t, 2), "peak_alloc_gb": round(torch.cuda.max_memory_allocated() / 1073741824, 2)}

inter = mask_a & mask_b
union = mask_a | mask_b
extent = float((verts.max(0).values - verts.min(0).values).max())
d = (pos_a[inter] - pos_b[inter]).norm(dim=-1) / extent
res["coverage"] = {"texels_nvdiffrast": int(mask_a.sum()), "texels_torch": int(mask_b.sum()), "iou": round(float(inter.sum() / union.sum()), 5),
                   "only_nvdiffrast": int((mask_a & ~mask_b).sum()), "only_torch": int((mask_b & ~mask_a).sum())}
res["position_error_fraction_of_model_size"] = {"mean": float(d.mean()), "p99": float(torch.quantile(d.float()[:16_000_000], 0.99)), "max": float(d.max()),
                                                "texel_world_size_at_this_res": 1.0 / size}
a.json.write_text(json.dumps(res, indent=2))
print(json.dumps(res))
