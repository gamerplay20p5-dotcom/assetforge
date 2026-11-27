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
import math
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
    mod.ratio = max(1e-4, min(1.0, ratio))
    mod.use_collapse_triangulate = True
    bpy.ops.object.modifier_apply(modifier=mod.name)


def clean_loose(obj) -> None:
    """Drop vertices/edges not used by any face (they would inflate the bounding box but are not exported)."""
    select_only(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.delete_loose(use_verts=True, use_edges=True, use_faces=False)
    bpy.ops.object.mode_set(mode="OBJECT")


def finalize_mesh(obj) -> None:
    """After a heavy decimation a few triangles can end up degenerate (zero area / repeated vertices). Blender then warns that the mesh
    "is not valid" and exporters/readers drop those faces, so the exported count would not match the reported one. Remove them here."""
    select_only(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.dissolve_degenerate(threshold=1e-6)
    bpy.ops.mesh.delete_loose(use_verts=True, use_edges=True, use_faces=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.data.validate(clean_customdata=True)
    obj.data.update()


def weld_copy(src, name: str):
    """Copy without UVs and with vertices merged by distance: AI meshes come with one vertex per UV-seam side (xatlas), which makes
    a straight Decimate tear the surface apart. Merging first restores a connected surface that decimates cleanly."""
    dup = src.copy()
    dup.data = src.data.copy()
    dup.name = name
    bpy.context.collection.objects.link(dup)
    me = dup.data
    while me.uv_layers:
        me.uv_layers.remove(me.uv_layers[0])
    select_only(dup)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=1e-5)
    bpy.ops.mesh.dissolve_degenerate()
    bpy.ops.object.mode_set(mode="OBJECT")
    clean_loose(dup)
    me.materials.clear()
    return dup


def smart_uv(obj) -> None:
    select_only(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.004)
    bpy.ops.object.mode_set(mode="OBJECT")


def principled_nodes(obj):
    for slot in obj.material_slots:
        nt = slot.material.node_tree if slot.material and slot.material.use_nodes else None
        if nt:
            yield from (n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")


def source_pbr(high) -> tuple[float, float, bool]:
    """(roughness, metallic, roughness_is_textured). A provider without PBR data (e.g. TripoSR) exports glTF defaults
    (metallic=1) that mean "unspecified": use dielectric constants then. Real PBR textures (Stable Fast 3D) are baked."""
    for bsdf in principled_nodes(high):
        if bsdf.inputs["Roughness"].is_linked:
            return 0.8, 0.0, True
    return 0.85, 0.0, False


class NeutralMetal:
    """Diffuse baking of a metal gives black. Temporarily make the high-poly dielectric so the BASE COLOR is what gets baked."""

    def __init__(self, obj) -> None:
        self.obj, self.saved = obj, []

    def __enter__(self):
        for bsdf in principled_nodes(self.obj):
            sock = bsdf.inputs["Metallic"]
            links = [(lk.from_socket, lk.to_socket) for lk in sock.links]
            for lk in list(sock.links):
                bsdf.id_data.links.remove(lk)
            self.saved.append((bsdf, sock.default_value, links))
            sock.default_value = 0.0
        return self

    def __exit__(self, *exc):
        for bsdf, val, links in self.saved:
            bsdf.inputs["Metallic"].default_value = val
            for src, dst in links:
                bsdf.id_data.links.new(src, dst)


def bake_pass(high, low, kind: str, res: int, label: str, extrusion: float):
    img = bpy.data.images.new(label, res, res, alpha=False)
    if kind in ("NORMAL", "ROUGHNESS"):
        img.colorspace_settings.name = "Non-Color"
    nt = low.data.materials[0].node_tree
    node = nt.nodes.new("ShaderNodeTexImage")
    node.image = img
    nt.nodes.active = node
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = 1
    sc.cycles.use_denoising = False
    bk = sc.render.bake
    bk.use_selected_to_active = True
    bk.cage_extrusion = extrusion
    bk.max_ray_distance = extrusion * 4
    bk.margin = 8
    bk.margin_type = "EXTEND"
    bk.use_clear = True
    bk.target = "IMAGE_TEXTURES"
    bk.use_pass_direct = False
    bk.use_pass_indirect = False
    bk.use_pass_color = True
    bk.normal_space = "TANGENT"
    bpy.ops.object.select_all(action="DESELECT")
    high.select_set(True)
    low.select_set(True)
    bpy.context.view_layer.objects.active = low
    bpy.ops.object.bake(type=kind)
    img.pack()
    return node


def reduce_with_bake(high, target_tris: int, res: int, name: str):
    """Retopology-by-reduction with detail/material preservation: weld -> decimate (no UV constraints) -> new UV ->
    bake base color + tangent normal from the high-poly onto the low-poly (Cycles, CPU)."""
    low = weld_copy(high, name)
    welded = tri_count(low)
    if welded > target_tris:
        decimate(low, target_tris / welded)
        clean_loose(low)
    finalize_mesh(low)
    project_with_bake(high, low, res, name)
    return low


def project_with_bake(high, low, res: int, name: str):
    """Generate UVs and transfer base color, normals and available roughness onto a new surface."""
    smart_uv(low)
    rough, metal, rough_tex = source_pbr(high)
    mat = bpy.data.materials.new(name + "_mat")
    mat.use_nodes = True
    low.data.materials.append(mat)
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    extrusion = 0.02 * max(high.dimensions)
    with NeutralMetal(high):
        color_node = bake_pass(high, low, "DIFFUSE", res, name + "_color", extrusion)
    normal_node = bake_pass(high, low, "NORMAL", res, name + "_normal", extrusion)
    nt.links.new(color_node.outputs["Color"], bsdf.inputs["Base Color"])
    nmap = nt.nodes.new("ShaderNodeNormalMap")
    nt.links.new(normal_node.outputs["Color"], nmap.inputs["Color"])
    nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    if rough_tex:  # real PBR source: keep the roughness detail too
        rough_node = bake_pass(high, low, "ROUGHNESS", res, name + "_roughness", extrusion)
        nt.links.new(rough_node.outputs["Color"], bsdf.inputs["Roughness"])


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
    res = int(cfg.get("bake_resolution", 1024))
    textured = bool(obj.data.materials)
    method = "none"
    high = obj
    if tri_count(obj) > limit:  # cap LOD0 to the category/profile budget
        if textured and cfg.get("reduction", "bake") == "bake":
            obj = reduce_with_bake(high, limit, res, f"{name}_LOD0")
            method = "bake"
        else:
            decimate(obj, limit / tri_count(obj))
            finalize_mesh(obj)
            method = "collapse"
    obj.name = f"{name}_LOD0"
    lod_objs = [obj]
    base = tri_count(obj)
    for i, ratio in enumerate(cfg["lod_ratios"], start=1):
        if textured and cfg.get("reduction", "bake") == "bake":
            lod = reduce_with_bake(high, max(50, int(base * ratio)), max(256, res // (2**i)), f"{name}_LOD{i}")
        else:
            lod = obj.copy()
            lod.data = obj.data.copy()
            bpy.context.collection.objects.link(lod)
            decimate(lod, ratio)
            finalize_mesh(lod)
            lod.name = f"{name}_LOD{i}"
        lod_objs.append(lod)
    if high not in lod_objs:  # the high-poly was only the bake source
        bpy.data.objects.remove(high, do_unlink=True)
    # Reduction changes the silhouette slightly: re-centre every LOD on the FINAL LOD0 (pivot = bottom center) and report ITS size.
    pts = [lod_objs[0].matrix_world @ Vector(c) for c in lod_objs[0].bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    shift = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    for o in lod_objs:
        o.location -= shift
        select_only(o)
        bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)
    dims = (hi.x - lo.x, hi.z - lo.z, hi.y - lo.y)  # glTF-style (x, height, depth)
    report = {"raw_triangles": raw_tris, "scale_applied": scale, "dimensions_m": list(dims),
              "lods": [{"level": i, "triangles": tri_count(o), "target_ratio": ([1.0] + cfg["lod_ratios"])[i]} for i, o in enumerate(lod_objs)],
              "lod0_triangles": base, "reduction": {"method": method, "bake_resolution": res, "textured_source": textured}}
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
