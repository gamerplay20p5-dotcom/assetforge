"""Build and render experimental city-builder candidates from a read-only GLB."""

import argparse
import math
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipeline/export/assetforge_export"))
from ai_runner import (NeutralMetal, bake_pass, decimate, finalize_mesh, import_and_join,
                       principled_nodes, select_only, smart_uv, tri_count, weld_copy)
from optimize_master import inspect_glb

VIEWS = (("front", 35, 17), ("rear", 145, 17), ("top", 245, 42))


def simplify(source, output, count, permissive=False):
    ratio = min(1, count / inspect_glb(source)["triangles"])
    command = ["gltfpack", "-i", str(source), "-o", str(output), "-si", str(ratio), "-noq", "-kn", "-km", "-ke"]
    if permissive:
        command += ["-sp", "-se", "0.025"]
    subprocess.run(command, check=True, timeout=120)


def render(object_, framing, folder, label, pixels, threads, views=VIEWS):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.render.threads_mode, scene.render.threads = "FIXED", threads
    scene.cycles.device, scene.cycles.samples = "CPU", 4
    scene.cycles.use_denoising = False
    scene.render.use_persistent_data = True
    scene.render.resolution_x = scene.render.resolution_y = pixels
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format, scene.render.image_settings.color_mode = "PNG", "RGBA"
    world = scene.world
    scene.world = bpy.data.worlds.new("Neutral light")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs[0].default_value = (0.68, 0.68, 0.68, 1)
    scene.world.node_tree.nodes["Background"].inputs[1].default_value = 0.55
    light = bpy.data.lights.new("Key", "SUN")
    light.energy = 2
    sun = bpy.data.objects.new("Key", light)
    scene.collection.objects.link(sun)
    sun.rotation_euler = (0.55, -0.55, -0.3)
    camera = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    scene.collection.objects.link(camera)
    scene.camera = camera
    center, extent = framing
    camera.data.type, camera.data.ortho_scale = "ORTHO", extent * 1.06
    camera.data.clip_start, camera.data.clip_end = extent * 0.001, extent * 10
    hidden = [(mesh, tuple(mesh.users_collection)) for mesh in scene.objects if mesh.type == "MESH" and mesh != object_]
    for mesh, collections in hidden:
        for collection in collections:
            collection.objects.unlink(mesh)
    try:
        for name, azimuth, elevation in views:
            a, e = math.radians(azimuth), math.radians(elevation)
            direction = Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
            camera.location = center + direction * extent * 2
            camera.rotation_euler = (-direction).to_track_quat("-Z", "Y").to_euler()
            scene.render.filepath = str(folder / f"{label}-{name}.png")
            bpy.ops.render.render(write_still=True)
    finally:
        for mesh, collections in hidden:
            for collection in collections:
                collection.objects.link(mesh)
        bpy.data.objects.remove(camera, do_unlink=True)
        bpy.data.objects.remove(sun, do_unlink=True)
        bpy.data.lights.remove(light)
        current = scene.world
        scene.world = world
        bpy.data.worlds.remove(current)
        scene.render.use_persistent_data = False


def framing_from(object_):
    points = [object_.matrix_world @ Vector(point) for point in object_.bound_box]
    lo = Vector(min(point[i] for point in points) for i in range(3))
    hi = Vector(max(point[i] for point in points) for i in range(3))
    return (lo + hi) / 2, (hi - lo).length


@contextmanager
def metallic_emission(high):
    saved = []
    for bsdf in principled_nodes(high):
        tree = bsdf.id_data
        for output in [node for node in tree.nodes if node.type == "OUTPUT_MATERIAL" and node.is_active_output]:
            surface = output.inputs["Surface"]
            links = [link.from_socket for link in surface.links]
            metal = bsdf.inputs["Metallic"]
            node = tree.nodes.new("ShaderNodeEmission")
            value = metal.default_value
            node.inputs["Color"].default_value = (value, value, value, 1)
            if metal.is_linked:
                tree.links.new(metal.links[0].from_socket, node.inputs["Color"])
            tree.links.new(node.outputs[0], surface)
            saved.append((tree, surface, links, node))
    try:
        yield
    finally:
        for tree, surface, links, node in reversed(saved):
            tree.nodes.remove(node)
            for link in links:
                tree.links.new(link, surface)


def bake(high, low, pixels, *, cage=None, max_distance=None):
    smart_uv(low)
    mat = bpy.data.materials.new(f"Master {low.name}")
    mat.use_nodes = True
    low.data.materials.clear()
    low.data.materials.append(mat)
    tree = mat.node_tree
    bsdf = tree.nodes["Principled BSDF"]
    radius = max(high.dimensions) * 0.018
    projection = {"cage": cage, "max_distance": max_distance}
    with NeutralMetal(high):
        color = bake_pass(high, low, "DIFFUSE", pixels, "Base Color", radius, **projection)
    normal = bake_pass(high, low, "NORMAL", pixels, "Tangent Normal", radius, **projection)
    roughness = bake_pass(high, low, "ROUGHNESS", pixels, "Roughness", radius, **projection)
    with metallic_emission(high):
        metallic = bake_pass(high, low, "EMIT", pixels, "Metallic", radius, **projection)
    tangent = tree.nodes.new("ShaderNodeNormalMap")
    tree.links.new(normal.outputs["Color"], tangent.inputs["Color"])
    tree.links.new(tangent.outputs["Normal"], bsdf.inputs["Normal"])
    for node, slot in ((color, "Base Color"), (roughness, "Roughness"), (metallic, "Metallic")):
        tree.links.new(node.outputs["Color"], bsdf.inputs[slot])


def scaffold_mesh(coarse):
    # A welded scaffold makes the field solver independent of the master's UV seams.
    existing = set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=str(coarse))
    meshes = [obj for obj in bpy.context.scene.objects if obj not in existing and obj.type == "MESH"]
    select_only(meshes[0])
    for obj in meshes:
        matrix = obj.matrix_world.copy()
        obj.parent = None
        obj.matrix_world = matrix
        obj.select_set(True)
    if len(meshes) > 1:
        bpy.ops.object.join()
    coarse_mesh = bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    low = weld_copy(coarse_mesh, "Retopology scaffold")
    bpy.data.objects.remove(coarse_mesh, do_unlink=True)
    return low


def remesh(coarse, folder, target, crease, threads):
    low = scaffold_mesh(coarse)
    select_only(low)
    source_obj, output_obj = folder / "_scaffold.obj", folder / "_remesh.obj"
    bpy.ops.wm.obj_export(filepath=str(source_obj), export_selected_objects=True, export_triangulated_mesh=True,
                          export_materials=False, forward_axis="NEGATIVE_Z", up_axis="Y")
    bpy.data.objects.remove(low, do_unlink=True)
    subprocess.run(["instant-meshes", "-t", str(threads), "-b", "-c", str(crease),
                    "-D", "-f", str(max(100, target // 2)), "-o", str(output_obj), str(source_obj)],
                   check=True, timeout=180)
    existing = set(bpy.context.scene.objects)
    bpy.ops.wm.obj_import(filepath=str(output_obj), forward_axis="NEGATIVE_Z", up_axis="Y")
    candidates = [obj for obj in bpy.context.scene.objects if obj not in existing and obj.type == "MESH"]
    if len(candidates) != 1 or not tri_count(candidates[0]):
        raise ValueError("Instant Meshes produced an empty surface")
    return candidates[0]


def quadriflow(coarse, target, cell):
    low = scaffold_mesh(coarse)
    select_only(low)
    low.data.remesh_voxel_size = cell * max(low.dimensions)
    bpy.ops.object.voxel_remesh()
    before = len(low.data.polygons)
    result = bpy.ops.object.quadriflow_remesh(use_mesh_symmetry=False, use_preserve_sharp=True,
                                             use_preserve_boundary=True, mode="FACES",
                                             target_faces=max(100, target // 2), seed=1)
    if "FINISHED" not in result or len(low.data.polygons) == before or not tri_count(low):
        raise ValueError("QuadriFlow could not produce a new surface")
    return low


def export_baked(master, low, path, bake_size):
    bake(master, low, bake_size)
    select_only(low)
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_selection=True, export_tangents=True)


def hybrid_lods(master, scaffold, folder, args, first_level=0):
    for level in range(first_level, len(args.budgets)):
        budget = args.budgets[level]
        low = scaffold_mesh(scaffold)
        if first_level:
            select_only(low)
            low.data.remesh_voxel_size = args.voxel * max(low.dimensions) * (0.7 if level == 1 else 1.35)
            bpy.ops.object.voxel_remesh()
        if args.planar_angle:
            select_only(low)
            planar = low.modifiers.new("Limited planar dissolve", "DECIMATE")
            planar.decimate_type = "DISSOLVE"
            planar.angle_limit = math.radians(args.planar_angle)
            planar.delimit = {"NORMAL", "SHARP"}
            bpy.ops.object.modifier_apply(modifier=planar.name)
        select_only(low)
        split = low.modifiers.new("Triangulate for budget", "TRIANGULATE")
        bpy.ops.object.modifier_apply(modifier=split.name)
        triangles = tri_count(low)
        if triangles > budget:
            decimate(low, budget / triangles)
        finalize_mesh(low)
        export_baked(master, low, folder / f"lod{level}.glb", max(128, args.bake_size >> level))
        bpy.data.objects.remove(low, do_unlink=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("master", type=Path)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--budgets", type=int, nargs=3, required=True)
    parser.add_argument("--crease", type=float, required=True)
    parser.add_argument("--voxel", type=float, default=0.014)
    parser.add_argument("--planar-angle", type=float, default=0)
    parser.add_argument("--threads", type=int, default=3)
    parser.add_argument("--pixels", type=int, default=144)
    parser.add_argument("--bake-size", type=int, default=512)
    parser.add_argument("--method", choices=("baseline", "instant", "quadri", "lod-permissive", "hybrid", "lod-voxel"), required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    source, folder = args.master.resolve(), args.folder.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    output = folder / "lod0.glb"
    master = import_and_join(str(source))
    framing = framing_from(master)
    first_level = 0
    if args.method == "lod-permissive":
        parent = folder.parent / "instant" / "lod0.glb"
        if not parent.is_file():
            raise ValueError("A completed Instant LOD0 is required")
        output.hardlink_to(parent)
        for level, target in enumerate(args.budgets[1:], 1):
            simplify(output, folder / f"lod{level}.glb", target, permissive=True)
        print(f"BENCH_SECONDS {time.monotonic() - started:.3f}", flush=True)
        first_level = 1
    elif args.method == "baseline":
        simplify(source, output, args.budgets[0])
        for level, target in enumerate(args.budgets[1:], 1):
            simplify(output, folder / f"lod{level}.glb", target)
        print(f"BENCH_SECONDS {time.monotonic() - started:.3f}", flush=True)
        render(master, framing, folder, "master", args.pixels, args.threads)
    else:
        scaffold = folder / "_scaffold.glb"
        simplify(source, scaffold, max(90000, args.budgets[0] * 6))
        scene = bpy.context.scene
        scene.render.threads_mode, scene.render.threads = "FIXED", args.threads
        if args.method in ("hybrid", "lod-voxel"):
            if args.method == "lod-voxel":
                parent = folder.parent / "hybrid" / "lod0.glb"
                if not parent.is_file():
                    raise ValueError("A completed hybrid LOD0 is required")
                output.hardlink_to(parent)
                first_level = 1
            hybrid_lods(master, scaffold, folder, args, first_level)
        else:
            target = remesh(scaffold, folder, args.budgets[0], args.crease, args.threads) if args.method == "instant" else (
                quadriflow(scaffold, args.budgets[0], args.voxel))
            export_baked(master, target, output, args.bake_size)
            for level, budget in enumerate(args.budgets[1:], 1):
                simplify(output, folder / f"lod{level}.glb", budget)
        for temp in folder.glob("_*"):
            temp.unlink()
        print(f"BENCH_SECONDS {time.monotonic() - started:.3f}", flush=True)
    for level in range(first_level, 3):
        candidate = import_and_join(str(folder / f"lod{level}.glb"))
        render(candidate, framing, folder, f"lod{level}", args.pixels, args.threads)


if __name__ == "__main__":
    main()
