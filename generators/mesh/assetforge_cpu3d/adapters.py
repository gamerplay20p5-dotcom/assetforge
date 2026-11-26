"""Adapters that run the OFFICIAL CLIs of Stable Fast 3D and TripoSR on CPU (nothing is re-implemented here).

Only whitelisted, range-checked numeric/enum parameters ever reach a command line.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import sys
from pathlib import Path

SF3D_DIR = Path(os.environ.get("SF3D_DIR", "/opt/sf3d"))
TRIPOSR_DIR = Path(os.environ.get("TRIPOSR_DIR", "/opt/TripoSR"))
REMESH = ("none", "triangle", "quad")


def _int(params: dict, key: str, lo: int, hi: int, default: int) -> int:
    try:
        v = int(params.get(key, default))
    except (TypeError, ValueError):
        raise ValueError(f"parameter {key!r} must be an integer") from None
    if not lo <= v <= hi:
        raise ValueError(f"parameter {key!r} must be in [{lo}, {hi}]")
    return v


def _float(params: dict, key: str, lo: float, hi: float, default: float) -> float:
    try:
        v = float(params.get(key, default))
    except (TypeError, ValueError):
        raise ValueError(f"parameter {key!r} must be a number") from None
    if not lo <= v <= hi:
        raise ValueError(f"parameter {key!r} must be in [{lo}, {hi}]")
    return v


def validate_params(provider: str, params: dict) -> dict:
    """Return a clean copy of the parameters or raise ValueError."""
    out = {"foreground_ratio": _float(params, "foreground_ratio", 0.5, 1.0, 0.85),
           "texture_resolution": _int(params, "texture_resolution", 256, 4096, 1024)}
    if provider == "sf3d":
        remesh = str(params.get("remesh", "none"))
        if remesh not in REMESH:
            raise ValueError(f"remesh must be one of {REMESH}")
        out["remesh"] = remesh
        out["target_vertex_count"] = _int(params, "target_vertex_count", -1, 200000, -1)
    elif provider == "triposr":
        out["mc_resolution"] = _int(params, "mc_resolution", 64, 512, 256)
        out["bake_texture"] = bool(params.get("bake_texture", True))
    else:
        raise ValueError(f"unknown provider {provider!r}")
    return out


def provider_device() -> str:
    """``cpu`` (default) or ``cuda:0`` etc. from PROVIDER_DEVICE; a GPU box sets it so the same server code runs on its card."""
    d = os.environ.get("PROVIDER_DEVICE", "cpu").strip() or "cpu"
    if d != "cpu" and not re.fullmatch(r"cuda(:\d)?", d):
        raise ValueError(f"PROVIDER_DEVICE must be cpu or cuda[:N], got {d!r}")
    return d


def build_command(provider: str, image: Path, out_dir: Path, params: dict, *, bake: bool | None = None) -> tuple[list[str], dict[str, str]]:
    p = validate_params(provider, params)
    py = sys.executable
    dev = provider_device()
    if provider == "sf3d":
        cmd = [py, str(SF3D_DIR / "run.py"), str(image), "--output-dir", str(out_dir), "--device", dev,
               "--texture-resolution", str(p["texture_resolution"]), "--remesh_option", p["remesh"],
               "--foreground-ratio", str(p["foreground_ratio"])]
        if p["remesh"] != "none" and p["target_vertex_count"] > 0:
            cmd += ["--target_vertex_count", str(p["target_vertex_count"])]
        return cmd, ({"SF3D_USE_CPU": "1"} if dev == "cpu" else {})
    do_bake = p["bake_texture"] if bake is None else bake
    cmd = [py, str(TRIPOSR_DIR / "run.py"), str(image), "--device", dev, "--output-dir", str(out_dir), "--mc-resolution", str(p["mc_resolution"]),
           "--chunk-size", "8192", "--foreground-ratio", str(p["foreground_ratio"])]
    if do_bake:
        # moderngl needs a display/GL context: run under a virtual X server (Mesa llvmpipe, software GL) when available (container)
        if shutil.which("xvfb-run"):
            cmd = ["xvfb-run", "-a", "-s", "-screen 0 1024x768x24", *cmd]
        cmd += ["--bake-texture", "--texture-resolution", str(p["texture_resolution"]), "--model-save-format", "obj"]
    else:
        cmd += ["--model-save-format", "glb"]
    return cmd, {}


def can_fallback(provider: str, params: dict) -> bool:
    """TripoSR texture baking needs an OpenGL context; if it fails we retry once with vertex colors."""
    return provider == "triposr" and bool(validate_params(provider, params)["bake_texture"])


def to_gradio_3d_orientation(mesh) -> None:
    """Same two rotations as tsr.utils.to_gradio_3d_orientation (TripoSR's own app applies them before export): the raw
    mesh has +Z up, this makes it +Y up (glTF)."""
    import numpy as np
    import trimesh

    mesh.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))
    mesh.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    # Measured on the real node (chair, 2026-11-26): after the two rotations above the object's FRONT points to -Z (its backrest
    # sat on the +Z side). AssetForge convention is front = +Z, so turn it 180 degrees about Y.
    mesh.apply_transform(trimesh.transformations.rotation_matrix(np.pi, [0, 1, 0]))


def collect_result(provider: str, out_dir: Path, dest: Path) -> dict:
    """Place the final textured GLB at ``dest`` and describe how the colour is stored."""
    d = out_dir / "0"
    if provider == "sf3d":
        src = d / "mesh.glb"
        if not src.is_file():
            raise FileNotFoundError("Stable Fast 3D produced no mesh.glb")
        shutil.copyfile(src, dest)
        return {"color": "pbr_texture"}
    glb, obj, tex = d / "mesh.glb", d / "mesh.obj", d / "texture.png"
    if obj.is_file() and tex.is_file():
        import trimesh
        from PIL import Image

        mesh = trimesh.load(str(obj), process=False, maintain_order=True)
        uv = getattr(mesh.visual, "uv", None)
        if uv is None:
            raise RuntimeError("baked OBJ has no UV coordinates")
        mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=trimesh.visual.material.PBRMaterial(baseColorTexture=Image.open(tex).convert("RGB")))
        to_gradio_3d_orientation(mesh)
        mesh.export(str(dest))
        return {"color": "baked_texture"}
    if glb.is_file():
        import trimesh

        scene = trimesh.load(str(glb), force="mesh", process=False)
        to_gradio_3d_orientation(scene)
        scene.export(str(dest))
        return {"color": "vertex_color"}
    raise FileNotFoundError("TripoSR produced no mesh output")


def weights_ready(provider: str, hf_home: Path) -> tuple[bool, str]:
    pattern = {"sf3d": "models--stabilityai--stable-fast-3d/snapshots/*/model.safetensors",
               "triposr": "models--stabilityai--TripoSR/snapshots/*/model.ckpt"}[provider]
    hit = glob.glob(str(hf_home / "hub" / pattern))
    return (True, "weights cached") if hit else (False, f"weights not downloaded in {hf_home} (run the download task)")
