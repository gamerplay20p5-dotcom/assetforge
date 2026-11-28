"""Build a separate game import package from an immutable master with Blender."""

import argparse
import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path

import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from optimize_master import inspect_glb


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def select(objects):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]


def normalize(objects, rotation, height, reference=None):
    axes = Euler(tuple(math.radians(a) for a in rotation), "XYZ").to_matrix().to_4x4()
    positions = [axes @ obj.matrix_world for obj in objects]
    fit = objects if reference is None else reference
    fit_positions = positions if reference is None else [axes @ obj.matrix_world for obj in fit]
    bounds = [position @ v.co for obj, position in zip(fit, fit_positions) for v in obj.data.vertices]
    lo = Vector(min(p[i] for p in bounds) for i in range(3))
    hi = Vector(max(p[i] for p in bounds) for i in range(3))
    del bounds
    size = hi - lo
    if min(size) <= 1e-8:
        raise ValueError("A game asset needs nonzero bounds in all three axes")
    scale = height / size.z
    offset = (hi + lo) / 2
    offset.z = lo.z
    for obj, position in zip(objects, positions):
        obj.data = obj.data.copy()
        obj.data.transform(Matrix.Scale(scale, 4) @ Matrix.Translation(-offset) @ position)
        obj.parent = None
        obj.matrix_world = Matrix.Identity(4)
        obj.data.update()
    return size * scale


def collider(category, size):
    # Metadata uses Unity axes. Keep render meshes separate from collision primitives.
    width, height, depth = size.x, size.z, size.y
    if category == "npc":
        radius = min(width * 0.30, depth * 0.50, height * 0.45)
        return {"kind": "capsule", "center": [0, height / 2, 0], "height": height, "radius": radius}
    if category == "vehicle":
        return {"kind": "box", "center": [0, height * 0.52, 0], "size": [width * 0.94, height * 0.78, depth * 0.94]}
    return {"kind": "box", "center": [0, height / 2, 0], "size": [width, height, depth]}


def lod(objects, index, ratio):
    if index or ratio < 1:
        result = []
        for original in objects:
            obj = original.copy()
            obj.data = original.data.copy()
            bpy.context.collection.objects.link(obj)
            select([obj])
            modifier = obj.modifiers.new("Requested LOD ratio", "DECIMATE")
            modifier.ratio = ratio
            modifier.use_collapse_triangulate = True
            bpy.ops.object.modifier_apply(modifier=modifier.name)
            result.append(obj)
    else:
        result = objects
    for i, obj in enumerate(result):
        obj.name = f"Part_{i:02d}_LOD{index}"
    return result


def input_image(socket):
    if not socket.is_linked:
        return None, 0
    link = socket.links[0]
    node = link.from_node
    channel = 0
    if node.type in ("SEPARATE_COLOR", "SEPRGB"):
        channel = {"Red": 0, "Green": 1, "Blue": 2, "R": 0, "G": 1, "B": 2}.get(link.from_socket.name, 0)
        if not node.inputs[0].is_linked:
            return None, 0
        node = node.inputs[0].links[0].from_node
    if node.type == "NORMAL_MAP" and node.inputs["Color"].is_linked:
        node = node.inputs["Color"].links[0].from_node
    return (node.image, channel) if node.type == "TEX_IMAGE" else (None, 0)


def png(image, dest):
    original, fmt = image.filepath_raw, image.file_format
    try:
        image.filepath_raw, image.file_format = str(dest), "PNG"
        image.save()
    finally:
        image.filepath_raw, image.file_format = original, fmt


def maps(objects, root):
    result = []
    materials = {m for obj in objects for m in obj.data.materials if m and m.use_nodes}
    for index, material in enumerate(sorted(materials, key=lambda m: m.name)):
        shader = next((n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if shader is None:
            continue
        inputs = shader.inputs
        meta = {"name": material.name, "baseColor": list(inputs["Base Color"].default_value),
                "normalScale": 1.0, "metallic": inputs["Metallic"].default_value,
                "smoothness": 1 - inputs["Roughness"].default_value}
        for key, socket in (("albedo", "Base Color"), ("normal", "Normal")):
            image, _ = input_image(inputs[socket])
            if image:
                filename = f"textures/{index:02d}-{key}.png"
                png(image, root / filename)
                meta[key] = filename
                if key == "albedo":
                    # A direct image connection replaces the socket default.
                    meta["baseColor"] = [1, 1, 1, 1]
                elif inputs[socket].links[0].from_node.type == "NORMAL_MAP":
                    meta["normalScale"] = inputs[socket].links[0].from_node.inputs["Strength"].default_value
        metal, metal_channel = input_image(inputs["Metallic"])
        rough, rough_channel = input_image(inputs["Roughness"])
        source = metal or rough
        if source:
            width, height = source.size
            rgba = np.zeros(width * height * 4, dtype=np.float32)
            for image, channel, dest, scalar in (
                (metal, metal_channel, 0, meta["metallic"]), (rough, rough_channel, 3, 1 - meta["smoothness"]),
            ):
                if image and tuple(image.size) != (width, height):
                    raise ValueError("Metallic and roughness maps must have the same dimensions")
                if image:
                    pixels = np.empty(width * height * 4, dtype=np.float32)
                    image.pixels.foreach_get(pixels)
                    rgba[dest::4] = pixels[channel::4] if dest == 0 else 1 - pixels[channel::4]
                else:
                    rgba[dest::4] = scalar if dest == 0 else 1 - scalar
            output = bpy.data.images.new(f"URP MetallicSmoothness {index}", width, height, alpha=True)
            output.colorspace_settings.name = "Non-Color"
            output.alpha_mode = "CHANNEL_PACKED"
            output.pixels.foreach_set(rgba)
            filename = f"textures/{index:02d}-metallic-smoothness.png"
            png(output, root / filename)
            meta["metallicSmoothness"] = filename
            bpy.data.images.remove(output)
        result.append(meta)
    return result


def numbers(text):
    return [float(part) for part in text.split(",")]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("master", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--category", choices=("building", "vehicle", "npc", "prop"), required=True)
    parser.add_argument("--height-m", type=float, required=True)
    parser.add_argument("--rotation-deg", type=numbers, default=[0, 0, 0], help="Blender X,Y,Z, after GLB import")
    parser.add_argument("--lod-ratios", type=numbers, default=[1])
    parser.add_argument("--lod-heights", type=numbers, default=[0], help="Descending screen-relative heights")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    master, output = args.master.resolve(), args.output_dir.resolve()
    ratios, thresholds = args.lod_ratios, args.lod_heights
    if output.exists() or master.is_relative_to(output):
        parser.error("Choose a new package directory outside the master")
    if not math.isfinite(args.height_m) or args.height_m <= 0 or len(args.rotation_deg) != 3 or not all(map(math.isfinite, args.rotation_deg)):
        parser.error("Specify an actual height and three finite orientation angles")
    if not 0 < ratios[0] <= 1 or not all(0 < lower < upper for upper, lower in zip(ratios, ratios[1:])):
        parser.error("LOD ratios must be in (0, 1] and decrease")
    if len(thresholds) != len(ratios) or not all(0 <= value < 1 for value in thresholds) or any(a <= b for a, b in zip(thresholds, thresholds[1:])):
        parser.error("Provide one descending screen-relative height per LOD, with optional 0 for no culling")
    source_hash = digest(master)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(master), merge_vertices=False)
    objects = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not objects or any(o.type == "ARMATURE" or o.animation_data for o in bpy.context.scene.objects):
        raise ValueError("This import path expects a static master")
    bpy.context.scene.unit_settings.system = "METRIC"
    dimensions = normalize(objects, args.rotation_deg, args.height_m)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".game-", dir=output.parent) as temporary:
        root = Path(temporary)
        (root / "textures").mkdir()
        material_maps = maps(objects, root)
        levels = [lod(objects, index, ratio) for index, ratio in enumerate(ratios)]
        if ratios[0] < 1:
            parts = [part for level in levels for part in level]
            dimensions = normalize(parts, (0, 0, 0), args.height_m, reference=levels[0])
            for obj in objects:
                bpy.data.objects.remove(obj, do_unlink=True)
        hierarchy = bpy.data.objects.new("AssetForge", None)
        bpy.context.collection.objects.link(hierarchy)
        report = {"schema": 1, "sourceSha256": source_hash, "category": args.category,
                  "units": "meters", "pivot": "ground_center", "rotationBlenderDegrees": args.rotation_deg,
                  "dimensions": [dimensions.x, dimensions.z, dimensions.y],
                  "collider": collider(args.category, dimensions), "materials": material_maps, "lods": []}
        for index, (ratio, threshold, parts) in enumerate(zip(ratios, thresholds, levels)):
            for part in parts:
                part.parent = hierarchy
            select(parts)
            name = f"lod{index}.glb"
            bpy.ops.export_scene.gltf(filepath=str(root / name), export_format="GLB", use_selection=True)
            metrics = inspect_glb(root / name)
            if not metrics["triangles"]:
                raise RuntimeError(f"LOD {index} produced no triangles")
            report["lods"].append({"index": index, "ratio": ratio, "relativeHeight": threshold,
                                   "file": name, "triangles": metrics["triangles"]})
        select([hierarchy, *hierarchy.children])
        bpy.ops.export_scene.fbx(filepath=str(root / "model.fbx"), use_selection=True, apply_unit_scale=True,
                                 apply_scale_options="FBX_SCALE_UNITS", axis_forward="-Z", axis_up="Y",
                                 path_mode="COPY", embed_textures=True)
        bpy.ops.file.pack_all()
        bpy.ops.wm.save_as_mainfile(filepath=str(root / "model.blend"))
        if digest(master) != source_hash:
            raise RuntimeError("Master changed during package construction")
        (root / "assetforge-import.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        output.mkdir()
        for file in root.iterdir():
            file.replace(output / file.name)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
