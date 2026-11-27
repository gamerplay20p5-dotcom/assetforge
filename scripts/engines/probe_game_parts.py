"""Probe game-specific structure on derivatives of a static master in Blender."""

import argparse
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from derive_master import components, measurements
from prepare_game import digest, normalize, select


def wheels(objects, dimensions):
    results = []
    for obj in objects:
        bm = bmesh.new()
        try:
            bm.from_mesh(obj.data)
            for faces in components(bm):
                lo, hi, area = measurements(obj, faces)
                d = [high - low for low, high in zip(lo, hi)]
                x, y, z = [(low + high) / 2 for low, high in zip(lo, hi)]
                if z < dimensions.z * 0.34 and hi[2] < dimensions.z * 0.6 and (
                    abs(x) > dimensions.x * 0.28 and abs(y) > dimensions.y * 0.12
                ) and d[2] > dimensions.z * 0.10 and 0.65 < d[1] / d[2] < 1.5:
                    results.append({"center": [x, z, -y], "faces": len(faces), "area_m2": area,
                                    "quadrant": f"{'right' if x > 0 else 'left'}_{'rear' if y > 0 else 'front'}"})
        finally:
            bm.free()
    return results


def rig(objects, dimensions, output):
    if len(objects) != 1:
        raise ValueError("Rig probe expects one retopologized mesh")
    obj = objects[0]
    data = bpy.data.armatures.new("Humanoid probe")
    armature = bpy.data.objects.new("Humanoid probe", data)
    bpy.context.collection.objects.link(armature)
    select([armature])
    bpy.ops.object.mode_set(mode="EDIT")
    width, height = dimensions.x, dimensions.z
    def bone(name, head, tail, parent=None):
        item = data.edit_bones.new(name)
        item.head = (head[0] * width, head[1] * width, head[2] * height)
        item.tail = (tail[0] * width, tail[1] * width, tail[2] * height)
        if parent:
            item.parent = data.edit_bones[parent]
    bone("hips", (0, 0, .48), (0, 0, .56))
    bone("spine", (0, 0, .56), (0, 0, .78), "hips")
    bone("head", (0, 0, .78), (0, 0, .97), "spine")
    for sign, tag in ((-1, "L"), (1, "R")):
        bone(f"arm.{tag}", (sign*.20, 0, .76), (sign*.32, 0, .60), "spine")
        bone(f"forearm.{tag}", (sign*.32, 0, .60), (sign*.37, -.02, .49), f"arm.{tag}")
        bone(f"thigh.{tag}", (sign*.12, 0, .48), (sign*.14, -.02, .27), "hips")
        bone(f"shin.{tag}", (sign*.14, -.02, .27), (sign*.15, 0, .07), f"thigh.{tag}")
        bone(f"foot.{tag}", (sign*.15, 0, .07), (sign*.15, -.12, .035), f"shin.{tag}")
    bpy.ops.object.mode_set(mode="OBJECT")
    select([armature, obj])
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    weights = [sum(g.weight for g in vertex.groups) for vertex in obj.data.vertices]
    weighted = sum(weight > 1e-5 for weight in weights)
    report = {"vertices": len(weights), "weighted_vertices": weighted, "bones": len(data.bones)}
    if weighted == len(weights):
        bpy.ops.file.pack_all()
        bpy.ops.wm.save_as_mainfile(filepath=str(output / "rig-probe.blend"))
    return report


def section(objects, height, fraction, output):
    actual = height * fraction
    for obj in objects:
        bm = bmesh.new()
        try:
            bm.from_mesh(obj.data)
            bmesh.ops.bisect_plane(bm, geom=[*bm.verts, *bm.edges, *bm.faces], dist=1e-6,
                                  plane_co=(0, 0, actual), plane_no=(0, 0, 1), clear_outer=True)
            bm.to_mesh(obj.data)
        finally:
            bm.free()
    triangles = sum(len(p.vertices) - 2 for o in objects for p in o.data.polygons)
    if triangles == 0:
        raise ValueError("The section has no surface")
    select(objects)
    bpy.ops.export_scene.gltf(filepath=str(output / "section.glb"), export_format="GLB", use_selection=True)
    return {"height_m": actual, "triangles": triangles, "open_section": True}


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("kind", choices=("rig", "wheels", "building-section"))
    args.add_argument("master", type=Path)
    args.add_argument("out", type=Path)
    args.add_argument("--height-m", required=True, type=float)
    args.add_argument("--fraction", type=float, default=.5)
    options = args.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if options.out.resolve().exists() or not math.isfinite(options.height_m) or options.height_m <= 0 or not 0 < options.fraction < 1:
        args.error("Provide a new output directory and valid physical dimensions")
    before = digest(options.master)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(options.master.resolve()), merge_vertices=True)
    objects = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    dimensions = normalize(objects, (0, 0, 0), options.height_m)
    options.out.mkdir(parents=True)
    if options.kind == "rig":
        report = rig(objects, dimensions, options.out)
    elif options.kind == "wheels":
        report = {"wheel_candidates": wheels(objects, dimensions)}
    else:
        report = section(objects, dimensions.z, options.fraction, options.out)
    if digest(options.master) != before:
        raise RuntimeError("Source hash changed")
    report["source_sha256"] = before
    (options.out / "metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
