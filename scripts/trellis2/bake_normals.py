"""Adds a normal map to a LOD GLB, baked in Blender from the MASTER (selected-to-active, Cycles, 1 sample). The LOD keeps its own UVs, base colour and
metallic/roughness (TRELLIS.2's to_glb samples those straight from the attribute volume); only the normal map, which carries the master's relief, is baked.

    blender -b -P bake_normals.py -- master.glb lod.glb out_lod.glb [normal_px=2048]
"""

import os
import sys
import time

import bpy

master, lod, out = sys.argv[sys.argv.index("--") + 1:][:3]
size = int(sys.argv[sys.argv.index("--") + 4]) if len(sys.argv) > sys.argv.index("--") + 4 else 2048

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=master)
high = [o for o in bpy.context.scene.objects if o.type == "MESH"][0]
before = set(bpy.context.scene.objects)
bpy.ops.import_scene.gltf(filepath=lod)
low = [o for o in bpy.context.scene.objects if o.type == "MESH" and o not in before][0]
dims = max(high.dimensions)
sc = bpy.context.scene
sc.render.engine, sc.cycles.device, sc.cycles.samples, sc.cycles.use_denoising = "CYCLES", "CPU", 1, False
sc.render.bake.margin, sc.render.bake.margin_type = 8, "EXTEND"

mat = low.data.materials[0]
nt = mat.node_tree
bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
img = bpy.data.images.new("normal", size, size, alpha=False)
img.colorspace_settings.name = "Non-Color"
img.generated_color = (0.5, 0.5, 1, 1)
tex = nt.nodes.new("ShaderNodeTexImage")
tex.image = img
nt.nodes.active = tex
bpy.ops.object.select_all(action="DESELECT")
high.select_set(True)
low.select_set(True)
bpy.context.view_layer.objects.active = low
t = time.time()
bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT", use_selected_to_active=True, cage_extrusion=dims * 0.02, max_ray_distance=dims * 0.06, use_clear=True)
secs = round(time.time() - t, 1)
nm = nt.nodes.new("ShaderNodeNormalMap")
nt.links.new(tex.outputs["Color"], nm.inputs["Color"])
nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
bpy.ops.object.select_all(action="DESELECT")
low.select_set(True)
bpy.context.view_layer.objects.active = low
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", use_selection=True, export_image_format="AUTO")
print("BAKED", os.path.basename(out), "normal_px", size, "bake_seconds", secs, "triangles", sum(len(p.vertices) - 2 for p in low.data.polygons))
