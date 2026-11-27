"""Master GLB -> LOD chain with baked PBR maps, in headless Blender. The master is never modified.

    blender -b -P make_lods.py -- master.glb out_dir [targets=15000,7500,2500,500] [tex=2048,2048,1024,512] [albedo_gain=1.0]

For every LOD: Decimate (collapse, from the previous LOD) -> fresh UVs (Smart UV Project) -> bake from the MASTER (selected-to-active, Cycles, 1 sample):
base colour (reprojected texture), tangent-space normal map (all the master's detail), roughness and metallic (re-packed into glTF's G/B channels) ->
export GLB with a PBR material. `albedo_gain` (default 1 = untouched) multiplies the baked base colour, for the optional colour calibration.
Writes lods.json with triangle counts, sizes and timings.
"""

import json
import math
import os
import sys
import time

import bmesh
import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
glb, out = argv[0], argv[1]
targets = [int(x) for x in (argv[2] if len(argv) > 2 else "15000,7500,2500,500").split(",")]
sizes = [int(x) for x in (argv[3] if len(argv) > 3 else "2048,2048,1024,512").split(",")]
gain = float(argv[4]) if len(argv) > 4 else 1.0
os.makedirs(out, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
if len(meshes) > 1:
    bpy.ops.object.join()
high = bpy.context.view_layer.objects.active
high.name = "HIGH"
high_tris = len(high.data.polygons)
bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
dims = tuple(high.dimensions)

sc = bpy.context.scene
sc.render.engine = "CYCLES"
sc.cycles.device = "CPU"
sc.cycles.samples = 1
sc.cycles.use_denoising = False
sc.render.bake.margin = 8
sc.render.bake.margin_type = "EXTEND"
EXTR = max(dims) * 0.02  # cage extrusion / ray distance relative to the model size
RAY = max(dims) * 0.06

hm = high.data.materials[0]
ht = hm.node_tree
bsdf = next(n for n in ht.nodes if n.type == "BSDF_PRINCIPLED")


def new_image(name, size, color, srgb):
    im = bpy.data.images.new(name, size, size, alpha=False, float_buffer=False)
    im.generated_color = color
    im.colorspace_settings.name = "sRGB" if srgb else "Non-Color"
    return im


def bake(low, node_img, btype, **kw):
    mat = low.data.materials[0]
    nt = mat.node_tree
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = node_img
    nt.nodes.active = tex
    for n in nt.nodes:
        n.select = n is tex
    bpy.ops.object.select_all(action="DESELECT")
    high.select_set(True)
    low.select_set(True)
    bpy.context.view_layer.objects.active = low
    t = time.time()
    bpy.ops.object.bake(type=btype, use_selected_to_active=True, cage_extrusion=EXTR, max_ray_distance=RAY, use_clear=True, **kw)
    nt.nodes.remove(tex)
    return round(time.time() - t, 1)


def metallic_as_emission():
    """Blender can't bake 'metallic' directly: route it to an Emission shader on the master's material, bake EMIT, then restore."""
    mlink = bsdf.inputs["Metallic"].links[0] if bsdf.inputs["Metallic"].links else None
    out_node = next(n for n in ht.nodes if n.type == "OUTPUT_MATERIAL")
    em = ht.nodes.new("ShaderNodeEmission")
    if mlink:
        sep = ht.nodes.new("ShaderNodeCombineColor")
        for k in range(3):  # metallic -> grey (all three channels) so the baked image reads back as the scalar
            ht.links.new(mlink.from_socket, sep.inputs[k])
        ht.links.new(sep.outputs[0], em.inputs["Color"])
    old = out_node.inputs["Surface"].links[0].from_socket
    ht.links.new(em.outputs[0], out_node.inputs["Surface"])
    return old, em



def tri_count(o):
    return sum(len(p.vertices) - 2 for p in o.data.polygons)


def collapse(o, target):
    cur = tri_count(o)
    if cur <= target:
        return
    mod = o.modifiers.new("dec", "DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.ratio = min(1.0, target / max(cur, 1))
    mod.use_collapse_triangulate = True
    bpy.ops.object.modifier_apply(modifier="dec")


def drop_small_parts(o, frac):
    """Delete loose pieces whose bounding box is smaller than frac * the model's largest dimension (a master of ~1,100 separate shells cannot be
    collapsed below what its pieces need; pieces this small are invisible at the distance that LOD is used)."""
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.verts.ensure_lookup_table()
    limit = frac * max(dims)
    seen, kill = set(), []
    for v0 in bm.verts:
        if v0.index in seen:
            continue
        stack, comp = [v0], []
        seen.add(v0.index)
        while stack:
            v = stack.pop()
            comp.append(v)
            for e in v.link_edges:
                w = e.other_vert(v)
                if w.index not in seen:
                    seen.add(w.index)
                    stack.append(w)
        xs = [c.co for c in comp]
        ext = max(max(c[k] for c in xs) - min(c[k] for c in xs) for k in range(3))
        if ext < limit:
            kill += comp
    if kill:
        bmesh.ops.delete(bm, geom=kill, context="VERTS")
    bm.to_mesh(o.data)
    bm.free()


def voxel_remesh(o, voxel):
    o.data.remesh_voxel_size = voxel
    o.data.use_remesh_fix_poles = True
    bpy.ops.object.voxel_remesh()


def reduce_to(o, target):
    """Collapse; if it stalls (loose shells), drop tiny pieces, then rebuild the surface by voxel remesh. Returns what was needed."""
    steps = []
    collapse(o, target)
    for frac in (0.02, 0.04, 0.08):
        if tri_count(o) <= target * 1.1:
            return steps
        drop_small_parts(o, frac)
        collapse(o, target)
        steps.append(f"drop_parts<{frac}")
    for div in (100, 70, 45, 30, 20):
        if tri_count(o) <= target * 1.1:
            return steps
        voxel_remesh(o, max(dims) / div)
        collapse(o, target)
        steps.append(f"voxel_remesh/{div}")
    return steps


report = {"master": os.path.basename(glb), "master_triangles": high_tris, "dimensions_unit_box": [round(d, 3) for d in dims], "albedo_gain": gain, "lods": []}
prev = high
for i, (target, size) in enumerate(zip(targets, sizes)):
    t0 = time.time()
    low = prev.copy()
    low.data = prev.data.copy()
    low.name = f"LOD{i}"
    bpy.context.collection.objects.link(low)
    bpy.ops.object.select_all(action="DESELECT")
    low.select_set(True)
    bpy.context.view_layer.objects.active = low
    # 1. reduce (collapse; drop tiny loose pieces and voxel-remesh only when collapse stalls); triangulated, so faces == triangles
    steps = reduce_to(low, target)
    # 2. fresh UVs
    low.data.materials.clear()
    for uv in list(low.data.uv_layers):
        low.data.uv_layers.remove(uv)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.004)
    bpy.ops.object.mode_set(mode="OBJECT")
    mat = bpy.data.materials.new(f"lod{i}")
    mat.use_nodes = True
    low.data.materials.append(mat)
    # 3. bake from the master
    timings = {}
    img_c = new_image(f"lod{i}_color", size, (0, 0, 0, 1), True)
    timings["color"] = bake(low, img_c, "DIFFUSE", pass_filter={"COLOR"})
    img_n = new_image(f"lod{i}_normal", size, (0.5, 0.5, 1, 1), False)
    timings["normal"] = bake(low, img_n, "NORMAL", normal_space="TANGENT")
    img_r = new_image(f"lod{i}_rough", size, (0.5, 0.5, 0.5, 1), False)
    timings["roughness"] = bake(low, img_r, "ROUGHNESS")
    old, em = metallic_as_emission()
    img_m = new_image(f"lod{i}_metal", size, (0, 0, 0, 1), False)
    timings["metallic"] = bake(low, img_m, "EMIT")
    ht.links.new(old, next(n for n in ht.nodes if n.type == "OUTPUT_MATERIAL").inputs["Surface"])
    ht.nodes.remove(em)
    # 4. final PBR material: colour, normal map, and rough/metal packed in G/B (glTF convention)
    px = np.array(img_c.pixels[:], dtype=np.float32).reshape(size, size, 4)
    if gain != 1.0:  # optional calibration, in linear light
        lin = np.power(np.clip(px[..., :3], 0, 1), 2.2) * gain
        px[..., :3] = np.power(np.clip(lin, 0, 1), 1 / 2.2)
        img_c.pixels = px.ravel().tolist()
    r = np.array(img_r.pixels[:], dtype=np.float32).reshape(size, size, 4)[..., 0]
    m = np.array(img_m.pixels[:], dtype=np.float32).reshape(size, size, 4)[..., 0]
    packed = np.zeros((size, size, 4), dtype=np.float32)
    packed[..., 1], packed[..., 2], packed[..., 3] = r, m, 1.0
    img_mr = new_image(f"lod{i}_mr", size, (0, 0, 0, 1), False)
    img_mr.pixels = packed.ravel().tolist()
    d = os.path.join(out, f"lod{i}")
    os.makedirs(d, exist_ok=True)
    for im, nm in ((img_c, "color"), (img_n, "normal"), (img_mr, "metallicRoughness")):
        im.filepath_raw = os.path.join(d, f"{nm}.png")
        im.file_format = "PNG"
        im.save()
    nt = mat.node_tree
    nt.nodes.clear()
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(b.outputs[0], o.inputs["Surface"])
    tc = nt.nodes.new("ShaderNodeTexImage"); tc.image = img_c
    nt.links.new(tc.outputs["Color"], b.inputs["Base Color"])
    tn = nt.nodes.new("ShaderNodeTexImage"); tn.image = img_n
    nm_node = nt.nodes.new("ShaderNodeNormalMap")
    nt.links.new(tn.outputs["Color"], nm_node.inputs["Color"])
    nt.links.new(nm_node.outputs["Normal"], b.inputs["Normal"])
    tm = nt.nodes.new("ShaderNodeTexImage"); tm.image = img_mr
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(tm.outputs["Color"], sep.inputs["Color"])
    nt.links.new(sep.outputs["Green"], b.inputs["Roughness"])
    nt.links.new(sep.outputs["Blue"], b.inputs["Metallic"])
    # 5. export this LOD alone
    bpy.ops.object.select_all(action="DESELECT")
    low.select_set(True)
    bpy.context.view_layer.objects.active = low
    path = os.path.join(out, f"lod{i}_{target}.glb")
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_image_format="AUTO")
    report["lods"].append({"lod": i, "target_triangles": target, "triangles": tri_count(low), "reduction_steps": steps, "texture_px": size, "bake_seconds": timings,
                           "total_seconds": round(time.time() - t0, 1), "file": os.path.basename(path), "file_mb": round(os.path.getsize(path) / 1048576, 2)})
    print(json.dumps(report["lods"][-1]), flush=True)
    prev = low
    low.hide_set(True)

with open(os.path.join(out, "lods.json"), "w") as f:
    json.dump(report, f, indent=2)
print("LODS DONE")
