"""Create a category-specific static GLB derivative in Blender, without modifying the master.

blender -b -t 4 --python-exit-code 1 --python derive_master.py -- master.glb draft.glb --category building --remove-floor
"""

import argparse
import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path

import bmesh
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from optimize_master import inspect_glb


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def components(bm):
    seen = set()
    for seed in bm.faces:
        if seed in seen:
            continue
        pending, faces = [seed], []
        seen.add(seed)
        while pending:
            face = pending.pop()
            faces.append(face)
            for edge in face.edges:
                for neighbor in edge.link_faces:
                    if neighbor not in seen:
                        seen.add(neighbor)
                        pending.append(neighbor)
        yield faces


def measurements(obj, faces):
    points = [obj.matrix_world @ vertex.co for vertex in {v for f in faces for v in f.verts}]
    lo = [min(p[i] for p in points) for i in range(3)]
    hi = [max(p[i] for p in points) for i in range(3)]
    return lo, hi, sum(f.calc_area() for f in faces)


def clean(meshes, args):
    data = []
    try:
        for obj in meshes:
            bm = bmesh.new()
            bm.from_mesh(obj.data)
            data.append((obj, bm, [(faces, *measurements(obj, faces)) for faces in components(bm)]))
        groups = [group for _, _, groups in data for group in groups]
        if not groups:
            raise ValueError("No surface found")
        largest = max(groups, key=lambda g: g[3])
        main_lo, main_hi = largest[1:3]
        height = main_hi[2] - main_lo[2]
        main_footprint = (main_hi[0] - main_lo[0]) * (main_hi[1] - main_lo[1])
        removed = []
        for obj, bm, groups in data:
            discard = []
            for group in groups:
                if group is largest:
                    continue
                faces, lo, hi, area = group
                sx, sy, sz = (hi[i] - lo[i] for i in range(3))
                at_base = abs(hi[2] - main_lo[2]) <= height * 0.06
                flat = sz < height * 0.018 and sz < 0.05 * min(sx, sy)
                if args.remove_floor and at_base and flat and sx * sy > main_footprint * 0.20:
                    reason = "detached_ground"
                elif args.component_area_ratio and area < largest[3] * args.component_area_ratio:
                    reason = "detached_small_component"
                else:
                    continue
                discard.extend(faces)
                removed.append({"reason": reason, "faces": len(faces), "area": area, "bounds": [lo, hi]})
            if discard:
                bmesh.ops.delete(bm, geom=discard, context="FACES")
                bm.to_mesh(obj.data)
                obj.data.update()
        return removed
    finally:
        for _, bm, _ in data:
            bm.free()


def dissolve(meshes, angle):
    for obj in meshes:
        bpy.context.view_layer.objects.active = obj
        mod = obj.modifiers.new("Coplanar surfaces", "DECIMATE")
        mod.decimate_type = "DISSOLVE"
        mod.angle_limit = math.radians(angle)
        mod.delimit = {"NORMAL", "MATERIAL", "SEAM", "SHARP", "UV"}
        mod.use_dissolve_boundaries = False
        bpy.ops.object.modifier_apply(modifier=mod.name)


def retopologize(master, quads, bake_size, voxel_size):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipeline/export/assetforge_export"))
    from ai_runner import project_with_bake, select_only, weld_copy

    low = weld_copy(master, master.name + "_Retopo")
    if voxel_size:
        # Use a temporary watertight surface for nonmanifold input. Bake from the original.
        low.data.remesh_voxel_size = voxel_size * max(low.dimensions)
        select_only(low)
        bpy.ops.object.voxel_remesh()
        bm = bmesh.new()
        try:
            bm.from_mesh(low.data)
            groups = list(components(bm))
            if not groups:
                raise RuntimeError("Voxel reconstruction produced no surface")
            main = max(groups, key=lambda faces: sum(face.calc_area() for face in faces))
            piece_area = sum(face.calc_area() for face in main)
            detached = [face for group in groups if group is not main
                        and sum(face.calc_area() for face in group) < piece_area * 0.001 for face in group]
            if detached:
                bmesh.ops.delete(bm, geom=detached, context="FACES")
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
            bm.to_mesh(low.data)
        finally:
            bm.free()
    select_only(low)
    before = len(low.data.polygons)
    bpy.ops.object.quadriflow_remesh(
        use_mesh_symmetry=False, use_preserve_sharp=True, use_preserve_boundary=True,
        mode="FACES", target_faces=quads, seed=1,
    )
    if not low.data.polygons or len(low.data.polygons) == before or any(len(f.vertices) != 4 for f in low.data.polygons):
        raise RuntimeError("QuadriFlow did not produce a new quad surface")
    project_with_bake(master, low, bake_size, low.name)
    select_only(low)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("master", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--category", choices=("building", "vehicle", "npc"), required=True)
    parser.add_argument("--plane-angle", type=float, help="Override planar dissolve angle in degrees (0 disables)")
    parser.add_argument("--remove-floor", action="store_true", help="Remove broad detached plates near the object's base")
    parser.add_argument("--component-area-ratio", type=float, default=0,
                        help="Remove detached components below this fraction of the largest component's area")
    parser.add_argument("--retopo-quads", type=int, help="Experimental QuadriFlow target for the derivative")
    parser.add_argument("--bake-size", type=int, default=1024, help="Pixel size for projected base color, normals and roughness")
    parser.add_argument("--voxel-size", type=float, help="Optional pre-remesh cell size as a fraction of the longest dimension")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    src, dst = args.master.resolve(), args.output.resolve()
    if src == dst or dst.exists() or dst.suffix.lower() != ".glb":
        parser.error("Output must be a new GLB path distinct from the master")
    angle = args.plane_angle if args.plane_angle is not None else {"building": 2, "vehicle": 0.35, "npc": 0}[args.category]
    if not 0 <= angle <= 15 or not 0 <= args.component_area_ratio <= 0.005:
        parser.error("Angle must be 0–15 and detached area ratio must be 0–0.005")
    if args.remove_floor and args.category == "npc":
        parser.error("Ground plate cleanup is intended for buildings and vehicles")
    if args.retopo_quads and (args.retopo_quads < 100 or not 128 <= args.bake_size <= 16384):
        parser.error("Retopology requires at least 100 quads and 128–16384 px bake textures")
    if args.voxel_size is not None and (not args.retopo_quads or not 0 < args.voxel_size < 0.1):
        parser.error("Voxel size requires retopology and must be in (0, 0.1)")
    if not (angle or args.remove_floor or args.component_area_ratio or args.retopo_quads):
        parser.error("Select at least one derivative operation")
    before = inspect_glb(src)
    sha = digest(src)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(src), merge_vertices=True)
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes or any(o.type == "ARMATURE" or o.animation_data for o in bpy.context.scene.objects) or any(
        o.data.shape_keys for o in meshes
    ):
        raise ValueError("The experimental derivative is for static GLBs with a surface")
    if args.retopo_quads and (len(meshes) != 1 or args.remove_floor or args.component_area_ratio):
        raise ValueError("Retopology takes one baked mesh; run cleanup as a separate derivative")
    removed = clean(meshes, args) if args.remove_floor or args.component_area_ratio else []
    if args.retopo_quads:
        retopologize(meshes[0], args.retopo_quads, args.bake_size, args.voxel_size)
    elif angle:
        dissolve(meshes, angle)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".derive-", dir=dst.parent) as work:
        temp = Path(work) / dst.name
        bpy.ops.export_scene.gltf(filepath=str(temp), export_format="GLB", use_selection=bool(args.retopo_quads))
        after = inspect_glb(temp)
        if not after["triangles"] or (before["image_sha256"] and not after["image_sha256"]):
            raise RuntimeError("Derivative lost its surface or all of its textures")
        if digest(src) != sha:
            raise RuntimeError("Master changed during processing")
        # Publish atomically and refuse to replace another concurrently produced derivative.
        dst.hardlink_to(temp)
    print(json.dumps({"category": args.category, "master_sha256": sha,
                      "plane_angle": angle if not args.retopo_quads else None,
                      "retopo_quads": args.retopo_quads, "removed_components": removed,
                      "master": before, "derivative": after}))


if __name__ == "__main__":
    main()
