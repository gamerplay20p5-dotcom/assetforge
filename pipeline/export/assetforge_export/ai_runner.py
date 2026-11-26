"""Executed INSIDE Blender for generative (AI) meshes: ``blender -b --python ai_runner.py -- config.json``.

Imports the GLB produced by the ComfyUI workflow and prepares it for the game:
normalise scale/pivot (1 unit = 1 m, pivot bottom-center), cap LOD0 to the triangle budget, build LODs, export
GLB (per LOD), FBX (all LODs named ``<asset>_LOD<n>`` so Unity creates a LODGroup), BLEND and a Cycles thumbnail.

Detail preservation: the AI workflow already baked normal/AO maps from the high-poly mesh. Here decimation uses the
Collapse mode (UV/material aware, symmetric off) and never touches UVs, so those maps keep working on every LOD.
No user-provided script is evaluated; the config comes from the worker.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import bpy  # type: ignore[import-not-found]
from mathutils import Vector  # type: ignore[import-not-found]

sys.path.insert(0, str(Path(__file__).parent))
import blender_runner as br  # noqa: E402  (shared helpers: thumbnail, events)


def tri_count(obj) -> int:
    mesh = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
    n = sum(len(p.vertices) - 2 for p in mesh.polygons)
    obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh_clear()
    return n


def select_only(obj) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def import_and_join(path: str):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=path)
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("the generated GLB contains no mesh")
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.parent = None
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    for o in [o for o in bpy.context.scene.objects if o.type != "MESH"]:
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return obj


def normalise(obj, target_m: float, axis: str) -> tuple[float, tuple[float, float, float]]:
    """Scale to ``target_m`` (height = Z in Blender, or the largest dimension) and put the pivot at the bottom center."""
    dims = obj.dimensions
    ref = dims.z if axis == "height" else max(dims)
    if ref <= 1e-9:
        raise RuntimeError("degenerate generated mesh (zero size)")
    s = target_m / ref
    obj.scale = (s, s, s)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    obj.location -= Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)
    d = obj.dimensions
    return s, (d.x, d.z, d.y)  # glTF-style (x, height, depth)


def decimate(obj, ratio: float) -> None:
    select_only(obj)
    mod = obj.modifiers.new("lod", "DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.ratio = max(0.01, min(1.0, ratio))
    mod.use_collapse_triangulate = True
    bpy.ops.object.modifier_apply(modifier=mod.name)


def main() -> None:
    cfg = br.load_config()
    out = Path(cfg["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    name = cfg["asset_name"]
    br.event("import", "start")
    obj = import_and_join(cfg["glb_in"])
    raw_tris = tri_count(obj)
    scale, dims = normalise(obj, float(cfg["target_size_m"]), cfg.get("size_axis", "height"))
    br.event("import", "done")

    if cfg.get("compare_preview"):  # render the provider output BEFORE any polygon reduction, for the before/after comparison
        br.render_thumbnail({**cfg, "thumbnail_name": "preview_raw.png"}, [obj])
    br.event("lods", "start")
    limit = int(cfg["triangle_limit"])
    if tri_count(obj) > limit:  # cap LOD0 to the category/profile budget
        decimate(obj, limit / tri_count(obj))
    obj.name = f"{name}_LOD0"
    lod_objs = [obj]
    base = tri_count(obj)
    for i, ratio in enumerate(cfg["lod_ratios"], start=1):
        dup = obj.copy()
        dup.data = obj.data.copy()
        dup.name = f"{name}_LOD{i}"
        bpy.context.collection.objects.link(dup)
        decimate(dup, ratio)
        lod_objs.append(dup)
    report = {"raw_triangles": raw_tris, "scale_applied": scale, "dimensions_m": list(dims),
              "lods": [{"level": i, "triangles": tri_count(o), "target_ratio": ([1.0] + cfg["lod_ratios"])[i]} for i, o in enumerate(lod_objs)],
              "lod0_triangles": base}
    br.event("lods", "done")

    br.event("export", "start")
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "model.blend"), compress=True)
    for i, o in enumerate(lod_objs):
        select_only(o)
        fn = "model.glb" if i == 0 else f"model_lod{i}.glb"
        bpy.ops.export_scene.gltf(filepath=str(out / fn), export_format="GLB", export_yup=True, use_selection=True,
                                  export_apply=True, export_materials="EXPORT", export_cameras=False, export_lights=False)
    if "fbx" in cfg["formats"]:
        for o in lod_objs:
            o.select_set(True)
        bpy.ops.export_scene.fbx(filepath=str(out / "model.fbx"), use_selection=True, object_types={"MESH"},
                                 apply_scale_options="FBX_SCALE_UNITS", axis_forward="-Z", axis_up="Y", bake_space_transform=True,
                                 mesh_smooth_type="FACE", path_mode="COPY", embed_textures=True)
    br.event("export", "done")

    br.event("thumbnail", "start")
    for o in lod_objs[1:]:
        o.hide_render = True
    br.render_thumbnail(cfg, [lod_objs[0]])
    br.event("thumbnail", "done")
    (out / "ai_report.json").write_text(json.dumps(report), encoding="utf-8")
    br.log("finished")


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(3)
