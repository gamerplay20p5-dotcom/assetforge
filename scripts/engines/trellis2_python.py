"""Run a pinned TRELLIS.2 Python pipeline with local weights and optional CPU offload."""

import argparse
import json
import tempfile
import time
from pathlib import Path

from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--dinov3", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resolution", type=int, choices=(512, 1024, 1536), default=1024)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--texture-size", type=int, default=4096)
    parser.add_argument("--max-tokens", type=int, default=49152)
    parser.add_argument("--cpu-offload", action="store_true")
    args = parser.parse_args()
    if args.output.exists() or args.output.with_suffix(".json").exists():
        parser.error("Use a new output path for the master")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(args.image) as raw:
        image = raw.convert("RGBA")
    if image.getchannel("A").getextrema() == (255, 255):
        parser.error("This direct pilot takes a matte from the AssetForge reference preparation stage")

    from assetforge_trellis2.license_guard import block_noncommercial, violations

    block_noncommercial()
    import torch
    from assetforge_trellis2.to_glb import to_glb_commercial
    from trellis2.pipelines import Trellis2ImageTo3DPipeline, rembg

    class PreMatted:
        def to(self, device):
            return self

    rembg.AssetForgePreMatted = PreMatted
    config = json.loads((args.models / "pipeline.json").read_text(encoding="utf-8"))
    config["args"]["image_cond_model"]["args"]["model_name"] = str(args.dinov3.resolve())
    config["args"]["rembg_model"] = {"name": "AssetForgePreMatted", "args": {}}
    config["args"]["low_vram"] = args.cpu_offload
    mode = str(args.resolution) if args.resolution == 512 else f"{args.resolution}_cascade"
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=".trellis-", dir=args.output.parent) as temporary:
        work = Path(temporary)
        (work / "ckpts").symlink_to((args.models / "ckpts").resolve(), target_is_directory=True)
        (work / "pipeline.json").write_text(json.dumps(config), encoding="utf-8")
        pipe = Trellis2ImageTo3DPipeline.from_pretrained(str(work))
        pipe.cuda()
        print("[Pipeline] Weights loaded", flush=True)
        meshes, _ = pipe.run(image, seed=args.seed, pipeline_type=mode, return_latent=True, max_num_tokens=args.max_tokens)
        mesh = meshes[0]
        effective = round(1 / float(mesh.voxel_size))
        del pipe
        torch.cuda.empty_cache()
        print("[Baking] Texturing mesh", flush=True)
        glb = to_glb_commercial(vertices=mesh.vertices, faces=mesh.faces, attr_volume=mesh.attrs,
                                coords=mesh.coords, attr_layout=mesh.layout, voxel_size=mesh.voxel_size,
                                aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]], texture_size=args.texture_size,
                                decimation_target=len(mesh.vertices), remesh=False)
        candidate = work / "model.glb"
        glb.export(candidate)
        report = {"engine": "trellis2-python", "cpu_offload": args.cpu_offload,
                  "requested_resolution": args.resolution, "effective_resolution": effective,
                  "seconds": round(time.monotonic() - started, 2), "triangles": len(glb.faces),
                  "cuda_peak_allocated_mb": torch.cuda.max_memory_allocated() // 2**20,
                  "restricted_library_calls": violations()}
        args.output.hardlink_to(candidate)
        args.output.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
