#!/usr/bin/env python3
"""Write an optional GLB derivative with gltfpack and retain the original master."""

import argparse
import hashlib
import json
import struct
import subprocess
import tempfile
from pathlib import Path


def inspect_glb(path: Path) -> dict:
    with path.open("rb") as file:
        magic, version, size = struct.unpack("<4sII", file.read(12))
        if (magic, version, size) != (b"glTF", 2, path.stat().st_size):
            raise ValueError(f"Invalid GLB header: {path}")
        length, kind = struct.unpack("<I4s", file.read(8))
        if kind != b"JSON":
            raise ValueError(f"Missing GLB JSON chunk: {path}")
        doc = json.loads(file.read(length))
        length, kind = struct.unpack("<I4s", file.read(8))
        if kind != b"BIN\0":
            raise ValueError(f"Missing GLB binary chunk: {path}")
        binary_offset = file.tell()
        image_hashes = set()
        for image in doc.get("images", []):
            view = doc["bufferViews"][image["bufferView"]]
            offset, size = view.get("byteOffset", 0), view["byteLength"]
            if view["buffer"] != 0 or offset < 0 or size < 1 or offset + size > length:
                raise ValueError(f"Invalid embedded image in {path}")
            file.seek(binary_offset + offset)
            image_hashes.add(hashlib.sha256(file.read(size)).hexdigest())
    counts = []
    for mesh in doc["meshes"]:
        for primitive in mesh["primitives"]:
            if primitive.get("mode", 4) != 4:
                raise ValueError(f"Only triangle primitives are supported: {path}")
            accessor = primitive.get("indices", primitive["attributes"]["POSITION"])
            counts.append(doc["accessors"][accessor]["count"] // 3)
    return {"bytes": path.stat().st_size, "triangles": sum(counts), "image_sha256": sorted(image_hashes)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("master", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--ratio", type=float, required=True, help="Target fraction of source triangles")
    args = parser.parse_args()
    master, output = args.master.resolve(), args.output.resolve()
    if master == output or output.exists() or output.suffix.lower() != ".glb":
        parser.error("Output must be a new GLB path distinct from the master")
    if not 0 < args.ratio <= 1:
        parser.error("--ratio must be in (0, 1]")
    original = inspect_glb(master)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".optimize-", dir=output.parent) as temp:
        candidate = Path(temp) / output.name
        subprocess.run([
            "gltfpack", "-i", str(master), "-o", str(candidate),
            "-si", str(args.ratio), "-noq", "-kn", "-km", "-ke",
        ], check=True)
        optimized = inspect_glb(candidate)
        if optimized["image_sha256"] != original["image_sha256"]:
            raise RuntimeError("Optimization changed or dropped embedded textures")
        candidate.replace(output)
    print(json.dumps({"target_ratio": args.ratio, "master": original, "derivative": optimized}, indent=2))


if __name__ == "__main__":
    main()
