"""Prepare Unity derivatives with measured quality gates and an immutable source."""

import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import bpy
import numpy as np
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from city_quality import compare, concerns
from city_retopology import (bake, decimate, finalize_mesh, framing_from, quadriflow,
                             remesh, render, scaffold_mesh, select_only, simplify, tri_count)
from prepare_game import collider, digest, inspect_glb, maps, normalize, numbers, select


VIEWS = (("front", 0, 10), ("side", 90, 10), ("rear", 180, 10), ("top", 225, 50))
PIPELINE_VERSION = "0.2.0"


def import_mesh(path):
    existing = set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=str(path), merge_vertices=False)
    added = set(bpy.context.scene.objects) - existing
    parts = sorted((obj for obj in added if obj.type == "MESH"), key=lambda obj: obj.name)
    if not parts or any(obj.type == "ARMATURE" or obj.animation_data for obj in added):
        raise ValueError("Optimization requires a static mesh")
    for part in parts:
        world = part.matrix_world.copy()
        part.parent = None
        part.matrix_world = world
    for obj in added - set(parts):
        bpy.data.objects.remove(obj, do_unlink=True)
    select(parts)
    if len(parts) > 1:
        bpy.ops.object.join()
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return parts[0]


def geometry(obj):
    edges = {}
    axes = area = 0.0
    parent = list(range(len(obj.data.vertices)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for face in obj.data.polygons:
        axes += face.area * (max(map(abs, face.normal)) > 0.97)
        area += face.area
        for edge in face.edge_keys:
            edges[edge] = edges.get(edge, 0) + 1
            parent[root(edge[0])] = root(edge[1])
    areas = {}
    for face in obj.data.polygons:
        component = root(face.vertices[0])
        areas[component] = areas.get(component, 0) + face.area
    return {"axis_aligned_area": axes / max(area, 1e-12),
            "boundary_fraction": sum(value == 1 for value in edges.values()) / max(1, len(edges)),
            "non_manifold_fraction": sum(value > 2 for value in edges.values()) / max(1, len(edges)),
            "significant_islands": sum(value >= area * 0.01 for value in areas.values())}


def recommended(category, shape, level):
    if category == "npc":
        return "hybrid" if level == 0 and shape["boundary_fraction"] < 0.08 else "voxel"
    if level > 0 and (category == "building" or shape["boundary_fraction"] >= 0.04
                      or shape["axis_aligned_area"] >= 0.55):
        return "voxel"
    return "hybrid" if category in ("building", "vehicle") or shape["axis_aligned_area"] >= 0.55 else "conservative"


def candidate(method, source, scaffold, scratch, target, category, level, threads):
    if method == "conservative":
        path = scratch / "_conservative.glb"
        simplify(source, path, target)
        return import_mesh(path)
    if method == "instant":
        return remesh(scaffold, scratch, target, {"building": 40, "vehicle": 55}.get(category, 75), threads)
    cell = 0.008 if category == "npc" else 0.010
    if method == "quadri":
        return quadriflow(scaffold, target, cell)
    low = scaffold_mesh(scaffold)
    select_only(low)
    if method == "voxel":
        low.data.remesh_voxel_size = cell * max(low.dimensions) * (1.35 if level >= 2 else 0.85)
        bpy.ops.object.voxel_remesh()
    if category in ("building", "vehicle"):
        planar = low.modifiers.new("Protect planar features", "DECIMATE")
        planar.decimate_type = "DISSOLVE"
        planar.angle_limit = math.radians(6 if category == "building" else 3)
        planar.delimit = {"NORMAL", "SHARP"}
        bpy.ops.object.modifier_apply(modifier=planar.name)
    triangulate = low.modifiers.new("Triangulate", "TRIANGULATE")
    bpy.ops.object.modifier_apply(modifier=triangulate.name)
    triangles = tri_count(low)
    if triangles > target:
        decimate(low, target / triangles)
    finalize_mesh(low)
    return low


def projection_settings(tree, low, extent, mode):
    low.data.calc_loop_triangles()
    cage = None
    if mode == "adaptive":
        cage = low.copy()
        cage.data = low.data.copy()
        cage.name = "AssetForge projection cage"
        bpy.context.collection.objects.link(cage)
        distances = []
        for vertex, outer in zip(low.data.vertices, cage.data.vertices):
            hit, _, _, distance = tree.find_nearest(vertex.co)
            signed = (hit - vertex.co).dot(vertex.normal) if hit is not None else 0
            push = min(extent * 0.035, max(extent * 0.002, signed + extent * 0.002))
            outer.co = vertex.co + vertex.normal * push
            distances.append((distance or 0) + push)
        cage.data.update()
        limit = min(extent * 0.11, max(extent * 0.012, float(np.quantile(distances, 0.98)) * 2))
    else:
        limit = extent * 0.072
    samples = low.data.loop_triangles
    misses, total = 0, 0
    for index in range(0, len(samples), max(1, len(samples) // 2000)):
        tri = samples[index]
        verts = [low.data.vertices[i] for i in tri.vertices]
        point = sum((v.co for v in verts), verts[0].co * 0) / 3
        if cage:
            origin = sum((cage.data.vertices[i].co for i in tri.vertices), point * 0) / 3
        else:
            origin = point + tri.normal * (extent * 0.018)
        direction = (point - origin).normalized()
        misses += tree.ray_cast(origin, direction, limit)[0] is None
        total += 1
    return cage, limit, misses / max(1, total)


def load_pixels(path):
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        image.colorspace_settings.name = "Non-Color"
        values = np.empty(int(image.size[0] * image.size[1] * 4), dtype=np.float32)
        image.pixels.foreach_get(values)
        return values.reshape(image.size[1], image.size[0], 4)
    finally:
        bpy.data.images.remove(image)


def drift(tree, low, high, extent):
    reverse = BVHTree.FromObject(low, bpy.context.evaluated_depsgraph_get())
    values = []
    for obj, surface in ((low, tree), (high, reverse)):
        vertices = obj.data.vertices
        sample = (vertices[i].co for i in range(0, len(vertices), max(1, len(vertices) // 2500)))
        distances = [surface.find_nearest(point)[3] for point in sample]
        values.append(float(np.quantile([x if x is not None else extent for x in distances], 0.95) / extent))
    return max(values)


def evaluate(low, high, tree, framing, original, scratch, args, level, miss):
    render(low, framing, scratch, "test", args.pixels, args.threads, VIEWS)
    deformed = drift(tree, low, high, framing[1])
    views = {name: compare(original[name], load_pixels(scratch / f"test-{name}.png"), args.category)
             for name, _, _ in VIEWS}
    issues, limits = concerns(views.values(), deformed, miss, level)
    return {"views": views, "surface_drift_p95": deformed, "projection_miss": miss,
            "issues": issues, "limits": limits}


def atlas(master, root, source_hash, args, threshold):
    folder = root / "impostor"
    folder.mkdir()
    azimuths = [(f"view-{i}", i * 45, 12) for i in range(8)]
    framing = framing_from(master)
    tile = 256
    render(master, framing, folder, "atlas", tile, args.threads, azimuths)
    packed = np.zeros((3 * tile, 3 * tile, 4), dtype=np.float32)
    frames = []
    for i, (name, azimuth, _) in enumerate(azimuths):
        x, y = i % 3 * tile, (2 - i // 3) * tile
        path = folder / f"atlas-{name}.png"
        data = load_pixels(path)
        if not np.any(data[:, :, 3] > 0.5):
            raise ValueError(f"Empty impostor view {name}")
        packed[y:y + tile, x:x + tile] = data
        frames.append({"azimuth_degrees": azimuth, "x": x, "y": y})
        path.unlink()
    image = bpy.data.images.new("Impostor atlas", 3 * tile, 3 * tile, alpha=True)
    image.colorspace_settings.name = "Non-Color"
    image.pixels.foreach_set(packed.ravel())
    image.filepath_raw, image.file_format = str(folder / "atlas.png"), "PNG"
    image.save()
    bpy.data.images.remove(image)
    center = framing[0]
    report = {"atlas": "impostor/atlas.png", "tile_size": tile, "columns": 3, "rows": 3,
              "elevation_degrees": 12, "origin": "bottom_left", "frames": frames,
              "relativeHeight": 0.0, "meshTransitionHeight": threshold,
              "world_extent": framing[1] * 1.06, "center_gltf": [center.x, center.z, -center.y],
              "master_sha256": source_hash}
    (folder / "atlas.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def export_package(high, levels, root, args, source_hash, quality):
    dimensions = normalize([high, *levels], args.rotation_deg, args.height_m, reference=[high])
    bpy.context.scene.unit_settings.system = "METRIC"
    (root / "textures").mkdir()
    (root / "unity").mkdir()
    templates = Path(__file__).resolve().parents[2] / "integrations/unity-export"
    for directory in ("Editor", "Runtime"):
        shutil.copytree(templates / directory, root / "unity" / directory)
    report = {"schema": 2, "sourceSha256": source_hash, "category": args.category,
              "units": "meters", "pivot": "ground_center", "rotationBlenderDegrees": args.rotation_deg,
              "dimensions": [dimensions.x, dimensions.z, dimensions.y], "quality": "quality.json",
              "collider": collider(args.category, dimensions), "materials": maps(levels, root), "lods": []}
    shutil.copy2(templates / "README.md", root / "unity" / "README.md")
    if args.impostor:
        report["impostor"] = atlas(high, root, source_hash, args, args.lod_heights[-1])
    bpy.data.objects.remove(high, do_unlink=True)
    hierarchy = bpy.data.objects.new("AssetForge", None)
    bpy.context.collection.objects.link(hierarchy)
    for i, (part, threshold) in enumerate(zip(levels, args.lod_heights)):
        part.name = f"Part_00_LOD{i}"
        part.parent = hierarchy
        select_only(part)
        name = f"lod{i}.glb"
        bpy.ops.export_scene.gltf(filepath=str(root / name), export_format="GLB", use_selection=True, export_tangents=True)
        count = inspect_glb(root / name)["triangles"]
        if not count:
            raise ValueError(f"LOD {i} has no triangles")
        entry = quality["levels"][i]
        entry.update(triangles=count, bytes=(root / name).stat().st_size, target_met=count <= entry["target"])
        report["lods"].append({"index": i, "relativeHeight": threshold, "file": name, "triangles": count,
                               "materialSlots": [item.name if item else "" for item in part.data.materials]})
    select([hierarchy, *levels])
    bpy.ops.export_scene.fbx(filepath=str(root / "model.fbx"), use_selection=True, apply_unit_scale=True,
                             apply_scale_options="FBX_SCALE_UNITS", axis_forward="-Z", axis_up="Y",
                             path_mode="COPY", embed_textures=True)
    bpy.data.orphans_purge(do_recursive=True)
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(root / "model.blend"))
    (root / "assetforge-import.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


def choose_level(high, previous, tree, framing, original, scratch, evidence, scaffold, args, level, target, selection, ceiling):
    attempts = []
    existing = set(bpy.context.scene.objects)
    strategies = [(selection, None if selection == "conservative" else args.projection)]
    comparison = args.compare_projection and selection != "conservative" and level == 0
    if selection != "conservative" and (args.projection == "adaptive" or comparison):
        strategies.append((selection, "fixed" if args.projection == "adaptive" else "adaptive"))
    if level:
        strategies.append(("conservative_previous", None))
    if selection != "conservative":
        strategies.append(("conservative", None))
    best = None
    for method, mode in strategies:
        started = time.monotonic()
        entry = {"method": method, "projection": mode}
        low = None
        retained = False
        try:
            source, geometry_method = args.master, method
            if method == "conservative_previous":
                source = scratch / "_accepted.glb"
                select_only(previous)
                bpy.ops.export_scene.gltf(filepath=str(source), export_format="GLB", use_selection=True, export_tangents=True)
                geometry_method = "conservative"
            low = candidate(geometry_method, source, scaffold, scratch, target, args.category, level, args.threads)
            count = tri_count(low)
            entry["triangles"] = count
            if not count or count > ceiling:
                entry["issues"] = ["geometry_ceiling"]
                continue
            if mode:
                cage, limit, miss = projection_settings(tree, low, max(high.dimensions), mode)
                entry["projection_distance"] = limit
                bake(high, low, max(128, args.bake_size >> level), cage=cage, max_distance=limit)
            else:
                miss = None
            entry.update(evaluate(low, high, tree, framing, original, scratch, args, level, miss))
            if entry["issues"]:
                prefix = f"lod{level}-attempt{len(attempts) + 1}"
                for name, _, _ in VIEWS:
                    shutil.copyfile(scratch / f"test-{name}.png", evidence / f"{prefix}-{name}.png")
                entry["preview_prefix"] = prefix
            if comparison and mode:
                for name, _, _ in VIEWS:
                    shutil.copyfile(scratch / f"test-{name}.png", args.output_dir.parent / f"projection-{mode}-{name}.png")
            if not entry["issues"] and comparison and not attempts and mode:
                retained = True
                best = (low, entry)
                existing.add(low)
            elif not entry["issues"] and best is None:
                retained = True
                return low, entry, attempts
        except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
            entry.update(issues=["method_failed"], error=str(error))
        finally:
            entry["seconds"] = round(time.monotonic() - started, 3)
            attempts.append(entry)
            for obj in set(bpy.context.scene.objects) - existing:
                if not retained or obj != low:
                    bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.orphans_purge(do_recursive=True)
        if best and len(attempts) >= 2:
            accepted, entry = best
            for name, _, _ in VIEWS:
                shutil.copyfile(args.output_dir.parent / f"projection-{entry['projection']}-{name}.png",
                                scratch / f"test-{name}.png")
            return accepted, entry, attempts
    low = previous.copy()
    low.data = previous.data.copy()
    bpy.context.collection.objects.link(low)
    entry = {"method": "reuse_previous" if level else "preserve_master", "projection": None,
             "triangles": tri_count(low)}
    entry.update(evaluate(low, high, tree, framing, original, scratch, args, level, None))
    return low, entry, attempts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("master", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--category", choices=("building", "vehicle", "npc", "prop"), required=True)
    parser.add_argument("--height-m", type=float, required=True)
    parser.add_argument("--rotation-deg", type=numbers, default=[0, 0, 0])
    parser.add_argument("--lod-heights", type=numbers, required=True)
    parser.add_argument("--triangle-targets", type=lambda v: [int(x) for x in v.split(",")], required=True)
    parser.add_argument("--method", choices=("auto", "hybrid", "voxel", "instant", "quadri", "conservative"), required=True)
    parser.add_argument("--bake-size", type=int, default=512)
    parser.add_argument("--pixels", type=int, default=192)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--projection", choices=("adaptive", "fixed"), default="adaptive")
    parser.add_argument("--compare-projection", action="store_true", help="Benchmark both projection modes")
    parser.add_argument("--impostor", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    args.master, args.output_dir = args.master.resolve(), args.output_dir.resolve()
    if args.output_dir.exists() or args.master.is_relative_to(args.output_dir):
        parser.error("Choose a new derivative directory outside the master")
    if len(args.lod_heights) != len(args.triangle_targets):
        parser.error("One screen height per target is required")
    started = time.monotonic()
    source_hash = digest(args.master)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    high = import_mesh(args.master)
    framing = framing_from(high)
    if framing[1] <= 0:
        raise ValueError("Master has empty bounds")
    tree = BVHTree.FromObject(high, bpy.context.evaluated_depsgraph_get())
    args.output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".optimize-", dir=args.output_dir.parent) as temp:
        scratch, root = Path(temp) / "scratch", Path(temp) / "package"
        scratch.mkdir()
        root.mkdir()
        evidence = root / "quality"
        evidence.mkdir()
        high_count = inspect_glb(args.master)["triangles"]
        scaffold = scratch / "_scaffold.glb"
        simplify(args.master, scaffold, max(90000, args.triangle_targets[0] * 6))
        sample = scaffold_mesh(scaffold)
        shape = geometry(sample)
        bpy.data.objects.remove(sample, do_unlink=True)
        render(high, framing, evidence, "master", args.pixels, args.threads, VIEWS)
        original = {name: load_pixels(evidence / f"master-{name}.png") for name, _, _ in VIEWS}
        quality = {"schema": 1, "pipeline_version": PIPELINE_VERSION,
                   "master_sha256": source_hash, "master_triangles": high_count,
                   "master_bytes": args.master.stat().st_size, "category": args.category,
                   "requested_method": args.method, "geometry": shape, "semantic_review_required": True,
                   "views": [name for name, _, _ in VIEWS], "levels": []}
        levels = []
        ceiling = high_count
        for i, target in enumerate(args.triangle_targets):
            selection = recommended(args.category, shape, i) if args.method == "auto" else args.method
            low, accepted, attempts = choose_level(high, levels[-1] if levels else high, tree, framing, original,
                                                   scratch, evidence, scaffold, args, i, target, selection, ceiling)
            ceiling = tri_count(low)
            levels.append(low)
            for name, _, _ in VIEWS:
                shutil.copyfile(scratch / f"test-{name}.png", evidence / f"lod{i}-{name}.png")
            quality["levels"].append({"index": i, "target": target, "selected_method": selection,
                                      "accepted": accepted, "attempts": attempts})
        export_package(high, levels, root, args, source_hash, quality)
        if digest(args.master) != source_hash:
            raise RuntimeError("Master changed during package construction")
        quality["seconds"] = round(time.monotonic() - started, 3)
        (root / "quality.json").write_text(json.dumps(quality, indent=2), encoding="utf-8")
        root.replace(args.output_dir)


if __name__ == "__main__":
    main()
