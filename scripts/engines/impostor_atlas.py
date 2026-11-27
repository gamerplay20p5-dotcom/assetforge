"""Render transparent, orthographic impostor views from a static GLB in Blender."""

import argparse
import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("master", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--views", type=int, default=8)
    parser.add_argument("--tile", type=int, default=512)
    parser.add_argument("--elevation", type=float, default=12)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if args.views < 3 or args.tile < 64 or not -89 <= args.elevation <= 89:
        parser.error("Choose at least three views, tiles of at least 64 px and elevation within ±89°")
    master, output = args.master.resolve(), args.output_dir.resolve()
    if output.exists():
        parser.error("Output directory must be new")
    columns = math.ceil(math.sqrt(args.views))
    rows = math.ceil(args.views / columns)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(master))
    pts = [o.matrix_world @ Vector(c) for o in bpy.context.scene.objects if o.type == "MESH" for c in o.bound_box]
    if not pts:
        raise ValueError("Model has no mesh")
    lo = Vector(min(p[i] for p in pts) for i in range(3))
    hi = Vector(max(p[i] for p in pts) for i in range(3))
    center, diameter = (lo + hi) / 2, (hi - lo).length
    if diameter <= 0:
        raise ValueError("Model has empty bounds")
    scene = bpy.context.scene
    scene.world = bpy.data.worlds.new("Neutral lighting")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes.get("Background").inputs[0].default_value = (0.55, 0.55, 0.55, 1)
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 8
    scene.cycles.use_denoising = True
    scene.render.film_transparent = True
    scene.render.resolution_x = scene.render.resolution_y = args.tile
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    data = bpy.data.cameras.new("Impostor")
    data.type, data.ortho_scale = "ORTHO", diameter * 1.06
    data.clip_start, data.clip_end = diameter * 0.01, diameter * 10
    scene.camera = camera = bpy.data.objects.new("Impostor", data)
    scene.collection.objects.link(camera)
    image = np.zeros((rows * args.tile, columns * args.tile, 4), dtype=np.float32)
    frames = []
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".impostor-", dir=output.parent) as temp:
        root = Path(temp)
        for i in range(args.views):
            az, el = math.tau * i / args.views, math.radians(args.elevation)
            direction = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
            camera.location = center + direction * diameter * 2
            camera.rotation_euler = (-direction).to_track_quat("-Z", "Y").to_euler()
            scene.render.filepath = str(root / "tile.png")
            bpy.ops.render.render(write_still=True)
            tile = bpy.data.images.load(scene.render.filepath, check_existing=False)
            # PNG tiles are already display-referred. Keep their values through the atlas save.
            tile.colorspace_settings.name = "Non-Color"
            rgba = np.empty(args.tile * args.tile * 4, dtype=np.float32)
            tile.pixels.foreach_get(rgba)
            bpy.data.images.remove(tile)
            if not np.any(rgba[3::4] > 0.1) or not np.any(rgba[3::4] < 0.1):
                raise RuntimeError(f"Invalid alpha coverage at view {i}")
            x, y = (i % columns) * args.tile, (rows - 1 - i // columns) * args.tile
            image[y:y + args.tile, x:x + args.tile] = rgba.reshape(args.tile, args.tile, 4)
            frames.append({"azimuth_degrees": math.degrees(az), "x": x, "y": y})
        atlas = bpy.data.images.new("Atlas", columns * args.tile, rows * args.tile, alpha=True)
        atlas.colorspace_settings.name = "Non-Color"
        atlas.pixels.foreach_set(image.ravel())
        atlas.filepath_raw, atlas.file_format = str(root / "atlas.png"), "PNG"
        atlas.save()
        with master.open("rb") as stream:
            sha = hashlib.file_digest(stream, "sha256").hexdigest()
        metadata = {"master_sha256": sha, "tile_size": args.tile, "columns": columns, "rows": rows,
                    "elevation_degrees": args.elevation, "world_extent": data.ortho_scale,
                    "center_gltf": [center.x, center.z, -center.y], "origin": "bottom_left", "frames": frames}
        (root / "atlas.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        output.mkdir()
        for name in ("atlas.png", "atlas.json"):
            (root / name).replace(output / name)


if __name__ == "__main__":
    main()
