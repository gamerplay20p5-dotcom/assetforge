#!/usr/bin/env python3
"""Pinned Pixal3D multi-view pilot for the DGX Spark Docker image."""

import argparse
import json
import tempfile
import time
from pathlib import Path

MODEL_REPO = "TencentARC/Pixal3D"
MODEL_REVISION = "b0cb2e1b794cab9aa0ac38a95d794a4d9337437f"
CONFIG = "pipeline_mv.json"


def download_models(models: Path) -> None:
    from huggingface_hub import hf_hub_download, snapshot_download

    config = hf_hub_download(MODEL_REPO, CONFIG, revision=MODEL_REVISION, local_dir=models)
    checkpoints = json.loads(Path(config).read_text())["args"]["models"].values()
    include = [checkpoint + ext for checkpoint in checkpoints for ext in (".json", ".safetensors")]
    snapshot_download(MODEL_REPO, revision=MODEL_REVISION, allow_patterns=include, local_dir=models, max_workers=4)


def generate(args: argparse.Namespace) -> None:
    if args.output.exists() or args.output.with_suffix(".json").exists():
        raise FileExistsError(f"Choose a new output path: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    from assetforge_trellis2.license_guard import block_noncommercial, violations

    block_noncommercial()
    from assetforge_trellis2.to_glb import to_glb_commercial
    import inference_mv
    import torch
    from pixal3d.pipelines import rembg
    from pixal3d.trainers.flow_matching.mixins.image_conditioned_proj import DinoV3ProjMultiViewFeatureExtractor

    class PreMattedViews:
        def to(self, device):
            return self

        def __call__(self, image):
            raise ValueError("Pixal3D pilot views must already have an alpha mask")

    def load_naf(extractor) -> None:
        if extractor.naf_model is None:
            device = next(extractor.model.parameters()).device
            extractor.naf_model = torch.hub.load("/opt/NAF", "naf", pretrained=True, device=device, source="local")
            extractor.naf_model.eval().requires_grad_(False)

    details = {"requested_resolution": args.resolution, "max_tokens": args.max_tokens, "seed": args.seed,
               "cpu_offload": args.cpu_offload}

    def bake(**kwargs):
        details["effective_resolution"] = int(kwargs["grid_size"])
        details["decoded_faces_before_export"] = len(kwargs["faces"])
        print(json.dumps(details), flush=True)
        kwargs["texture_size"] = args.texture_size
        return to_glb_commercial(**kwargs)

    rembg.AssetForgePreMattedViews = PreMattedViews
    DinoV3ProjMultiViewFeatureExtractor._load_naf = load_naf
    inference_mv.o_voxel.postprocess.to_glb = bake
    for config in inference_mv.IMAGE_COND_CONFIGS.values():
        config["model_name"] = str(args.dinov3.resolve())

    model_config = json.loads((args.models / CONFIG).read_text())
    model_config["args"]["rembg_model"] = {"name": "AssetForgePreMattedViews", "args": {}}
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=".pixal3d-", dir=args.output.parent) as workdir:
        model_dir = Path(workdir).resolve()
        (model_dir / "ckpts").symlink_to((args.models / "ckpts").resolve(), target_is_directory=True)
        (model_dir / CONFIG).write_text(json.dumps(model_config))
        candidate = model_dir / "model.glb"
        inference_mv.run_inference(
            views_dir=str(args.views),
            output_path=str(candidate),
            seed=args.seed,
            model_path=str(model_dir),
            max_num_tokens=args.max_tokens,
            low_vram=args.cpu_offload,
            resolution=args.resolution,
            ss_guidance_strength=args.structure_guidance,
            shape_slat_guidance_strength=args.shape_guidance,
        )
        details["wall_seconds"] = round(time.monotonic() - started, 2)
        details["restricted_library_calls"] = violations()
        report = model_dir / "model.json"
        report.write_text(json.dumps(details, indent=2))
        args.output.hardlink_to(candidate)
        args.output.with_suffix(".json").hardlink_to(report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_subparsers(dest="mode", required=True)
    download = mode.add_parser("download")
    download.add_argument("--models", type=Path, required=True)
    run = mode.add_parser("generate")
    run.add_argument("--views", type=Path, required=True)
    run.add_argument("--models", type=Path, required=True)
    run.add_argument("--dinov3", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--resolution", type=int, choices=(1024, 1536), required=True)
    run.add_argument("--max-tokens", type=int, required=True)
    run.add_argument("--seed", type=int, default=1)
    run.add_argument("--texture-size", type=int, default=4096)
    run.add_argument("--structure-guidance", type=float, default=7.5)
    run.add_argument("--shape-guidance", type=float, default=7.5)
    run.add_argument("--cpu-offload", action="store_true")
    args = parser.parse_args()
    if args.mode == "download":
        download_models(args.models)
    else:
        if args.max_tokens < 1 or args.output.suffix.lower() != ".glb":
            run.error("--max-tokens must be positive and --output must be a GLB")
        generate(args)


if __name__ == "__main__":
    main()
