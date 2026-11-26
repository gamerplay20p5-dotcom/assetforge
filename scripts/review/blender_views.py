"""Blender (headless) multi-view renderer used for VISUAL APPROVAL of procedural assets.

    blender -b -P blender_views.py -- model.glb out_prefix [samples] [size] [views]

Renders the model on a soft sky + grass ground from several perspectives (Cycles CPU). Nothing here is part of the exported asset.
"""

import math
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
glb, prefix = argv[0], argv[1]
samples = int(argv[2]) if len(argv) > 2 else 64
size = int(argv[3]) if len(argv) > 3 else 960
VIEWS = {  # name: (azimuth deg from front (+Z of the glTF), elevation deg, distance factor)
    "front_left": (-38, 14, 1.0),
    "front_right": (38, 14, 1.0),
    "side": (88, 9, 1.0),
    "back": (150, 16, 1.05),
    "aerial": (28, 42, 1.12),
    "front_low": (0, 5, 0.95),
}
wanted = argv[4].split(",") if len(argv) > 4 else list(VIEWS)
plain = len(argv) > 5 and argv[5] == "plain"  # neutral backdrop, fixed framing (stage sheets)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
centre = (lo + hi) / 2
radius = (hi - lo).length / 2
if plain:
    radius = max(hi.x - lo.x, hi.y - lo.y) * 0.62

# ground
if not plain:
  bpy.ops.mesh.primitive_plane_add(size=radius * 60, location=(centre.x, centre.y, lo.z - 0.005))
  ground = bpy.context.active_object
  gm = bpy.data.materials.new("grass")
  gm.use_nodes = True
  nt = gm.node_tree
  bsdf = nt.nodes["Principled BSDF"]
  noise = nt.nodes.new("ShaderNodeTexNoise")
  noise.inputs["Scale"].default_value = 1.2
  noise.inputs["Detail"].default_value = 6.0
  ramp = nt.nodes.new("ShaderNodeValToRGB")
  ramp.color_ramp.elements[0].color = (0.035, 0.085, 0.02, 1)
  ramp.color_ramp.elements[1].color = (0.085, 0.16, 0.04, 1)
  nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
  nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
  bsdf.inputs["Roughness"].default_value = 1.0
  ground.data.materials.append(gm)

# context dressing (render only, NOT part of the asset): low-poly trees and rocks around the lot
import random

random.seed(7)
leaf = bpy.data.materials.new("leaf")
leaf.use_nodes = True
leaf.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.09, 0.22, 0.06, 1)
leaf.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 1.0
leaf2 = bpy.data.materials.new("leaf2")
leaf2.use_nodes = True
leaf2.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.20, 0.34, 0.08, 1)
leaf2.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 1.0
bark = bpy.data.materials.new("bark")
bark.use_nodes = True
bark.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.12, 0.07, 0.04, 1)
rock = bpy.data.materials.new("rock")
rock.use_nodes = True
rock.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.25, 0.24, 0.22, 1)


def tree(x, y, h, mat):
    bpy.ops.mesh.primitive_cylinder_add(vertices=6, radius=h * 0.05, depth=h * 0.35, location=(x, y, lo.z + h * 0.175))
    t = bpy.context.active_object
    t.data.materials.append(bark)
    for k, (zz, rr) in enumerate(((0.45, 0.30), (0.68, 0.24), (0.88, 0.15))):
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=h * rr, location=(x, y, lo.z + h * zz))
        o = bpy.context.active_object
        o.scale.z = 0.85
        o.data.materials.append(mat if k != 1 else leaf2)


for ang, dist, h in (() if plain else ((205, 1.9, 5.5), (255, 2.0, 4.6), (330, 1.95, 6.0), (120, 1.9, 5.0), (160, 2.1, 6.5), (20, 2.0, 5.2), (292, 2.2, 6.2), (75, 2.0, 4.8))):
    a_ = math.radians(ang)
    tree(centre.x + math.sin(a_) * radius * dist, centre.y - math.cos(a_) * radius * dist, h, leaf if ang % 2 else leaf2)
for _ in range(0 if plain else 9):
    a_ = random.uniform(0, math.tau)
    d_ = radius * random.uniform(1.05, 1.5)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=random.uniform(0.25, 0.55), location=(centre.x + math.sin(a_) * d_, centre.y - math.cos(a_) * d_, lo.z + 0.1))
    bpy.context.active_object.data.materials.append(rock)

# sky + sun
world = bpy.data.worlds.new("sky")
world.use_nodes = True
wn = world.node_tree
sky = wn.nodes.new("ShaderNodeTexSky")
sky.sky_type = "NISHITA"
sky.sun_elevation = math.radians(38)
sky.sun_rotation = math.radians(210)
sky.sun_size = math.radians(1.2)
sky.sun_intensity = 0.38
bg = wn.nodes["Background"]
bg.inputs["Strength"].default_value = 1.0
wn.links.new(sky.outputs["Color"], bg.inputs["Color"])
bpy.context.scene.world = world
if plain:
    sky_c = wn.nodes.new('ShaderNodeRGB')
    sky_c.outputs[0].default_value = (0.80, 0.80, 0.79, 1)
    wn.links.new(sky_c.outputs[0], bg.inputs['Color'])
    bg.inputs['Strength'].default_value = 0.9

scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = samples
scene.cycles.use_denoising = True
try:
    scene.cycles.denoiser = "OPENIMAGEDENOISE"
except Exception:  # noqa: BLE001
    pass
scene.view_settings.view_transform = "AgX"
scene.view_settings.exposure = 0.0 if plain else -0.95
try:
    scene.view_settings.look = "AgX - High Contrast"
except Exception:  # noqa: BLE001
    pass
scene.render.resolution_x, scene.render.resolution_y = size, int(size * 0.75)
scene.render.image_settings.file_format = "PNG"

cam = bpy.data.cameras.new("cam")
cam.lens = 42
cam_obj = bpy.data.objects.new("cam", cam)
scene.collection.objects.link(cam_obj)
scene.camera = cam_obj
target = Vector((centre.x, centre.y, lo.z + (2.0 if plain else (hi.z - lo.z) * 0.42)))
for name in wanted:
    az, el, k = VIEWS[name]
    a, e = math.radians(az), math.radians(el)
    d = radius * 2.55 * k
    # glTF front (+Z) is Blender -Y
    cam_obj.location = target + Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e))) * d
    cam_obj.rotation_euler = (target - cam_obj.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = f"{prefix}_{name}.png"
    bpy.ops.render.render(write_still=True)
print("DONE", len(wanted))
