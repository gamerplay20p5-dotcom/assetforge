"""Minimal, dependency-light glTF 2.0 binary (GLB) writer.

Writing GLB directly (instead of going through a generic library) gives exact control over linear
color factors, texture samplers (REPEAT + mipmaps), flat normals and node naming, which are all part of
the Unity import contract. Output is independently re-read by the validation pipeline (trimesh).
"""

from __future__ import annotations

import io
import json
import struct
from pathlib import Path

import numpy as np
from assetforge_procedural import MaterialDef, MeshSpec, hex_to_linear
from assetforge_procedural.textures import generate as generate_texture

GLB_MAGIC = 0x46546C67
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942


def render_textures(materials: dict[str, MaterialDef], resolution: int, out_dir: Path) -> dict[str, Path]:
    """Write one PNG per used texture kind into ``out_dir`` and return {kind: path}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    wear_contrast = 0.15
    for kind in sorted({m.texture for m in materials.values() if m.texture}):
        path = out_dir / f"tex_{kind}_{resolution}.png"
        generate_texture(kind, resolution, wear_contrast).save(path, optimize=True)
        paths[kind] = path
    return paths


def _pad(data: bytes, pad: bytes) -> bytes:
    rem = (-len(data)) % 4
    return data + pad * rem


def write_glb(path: Path, spec: MeshSpec, materials: dict[str, MaterialDef], textures: dict[str, Path],
              asset_name: str, extras: dict | None = None) -> None:
    bin_buf = io.BytesIO()
    views: list[dict] = []
    accessors: list[dict] = []

    def add_view(data: bytes, target: int | None = None) -> int:
        offset = bin_buf.tell()
        bin_buf.write(data)
        bin_buf.write(b"\x00" * ((-len(data)) % 4))
        v: dict = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target:
            v["target"] = target
        views.append(v)
        return len(views) - 1

    def add_accessor(arr: np.ndarray, ctype: int, atype: str, target: int, minmax: bool = False) -> int:
        view = add_view(np.ascontiguousarray(arr).tobytes(), target)
        acc: dict = {"bufferView": view, "componentType": ctype, "count": int(len(arr)), "type": atype}
        if minmax:
            acc["min"] = [float(x) for x in arr.min(axis=0)]
            acc["max"] = [float(x) for x in arr.max(axis=0)]
        accessors.append(acc)
        return len(accessors) - 1

    images, gltf_textures = [], []
    tex_index: dict[str, int] = {}
    for kind, p in sorted(textures.items()):
        view = add_view(p.read_bytes())
        images.append({"bufferView": view, "mimeType": "image/png", "name": p.stem})
        gltf_textures.append({"sampler": 0, "source": len(images) - 1, "name": p.stem})
        tex_index[kind] = len(gltf_textures) - 1

    gltf_materials, mat_index = [], {}
    for name in spec.parts:
        m = materials[name]
        r, g, b = hex_to_linear(m.color)
        pbr: dict = {"baseColorFactor": [r, g, b, 1.0], "metallicFactor": m.metallic, "roughnessFactor": m.roughness}
        if m.texture:
            pbr["baseColorTexture"] = {"index": tex_index[m.texture]}
        gltf_materials.append({"name": name, "pbrMetallicRoughness": pbr, "doubleSided": False})
        mat_index[name] = len(gltf_materials) - 1

    meshes, nodes = [], []
    for name, part in spec.parts.items():
        pos = add_accessor(part.vertices.astype("<f4"), 5126, "VEC3", 34962, minmax=True)
        nor = add_accessor(part.normals.astype("<f4"), 5126, "VEC3", 34962)
        uv = add_accessor(part.uvs.astype("<f4"), 5126, "VEC2", 34962)
        if len(part.vertices) < 65536:
            idx = add_accessor(part.faces.astype("<u2").reshape(-1), 5123, "SCALAR", 34963)
        else:
            idx = add_accessor(part.faces.astype("<u4").reshape(-1), 5125, "SCALAR", 34963)
        meshes.append({"name": name, "primitives": [{
            "attributes": {"POSITION": pos, "NORMAL": nor, "TEXCOORD_0": uv},
            "indices": idx, "material": mat_index[name], "mode": 4}]})
        nodes.append({"name": name, "mesh": len(meshes) - 1})

    root = {"name": asset_name, "children": list(range(len(nodes)))}
    nodes.append(root)
    doc = {
        "asset": {"version": "2.0", "generator": "AssetForge glb writer", "extras": extras or {}},
        "scene": 0,
        "scenes": [{"name": asset_name, "nodes": [len(nodes) - 1]}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": gltf_materials,
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": bin_buf.tell()}],
    }
    if images:
        doc["images"] = images
        doc["textures"] = gltf_textures
        doc["samplers"] = [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}]
    json_chunk = _pad(json.dumps(doc, separators=(",", ":")).encode("utf-8"), b" ")
    bin_chunk = _pad(bin_buf.getvalue(), b"\x00")
    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    with path.open("wb") as fh:
        fh.write(struct.pack("<III", GLB_MAGIC, 2, total))
        fh.write(struct.pack("<II", len(json_chunk), CHUNK_JSON) + json_chunk)
        fh.write(struct.pack("<II", len(bin_chunk), CHUNK_BIN) + bin_chunk)
