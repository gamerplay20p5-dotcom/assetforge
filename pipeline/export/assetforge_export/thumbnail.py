"""Software thumbnail renderer (painter's algorithm, flat Lambert shading).

Used by the trimesh/CPU export engine so thumbnails work with no GPU, no OpenGL and no Blender. The
Blender engine renders its own thumbnail with Cycles; both end up as ``thumbnail.png``.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from assetforge_procedural import MaterialDef, MeshSpec, hex_to_linear
from PIL import Image, ImageDraw, ImageFilter

_TEX_TINT = {"glass": 0.85, "plaster": 0.9, "brick": 0.78, "tiles": 0.78, "metal": 0.85, "concrete": 0.88,
             "wood": 0.8, "stone": 0.85, "fabric": 0.9}


def _to_srgb(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def render_thumbnail(spec: MeshSpec, materials: dict[str, MaterialDef], path: Path, size: int = 512,
                     yaw_deg: float = 38.0, pitch_deg: float = 24.0) -> None:
    ss = 2  # supersampling
    S = size * ss
    tris, colors = [], []
    for name, part in spec.parts.items():
        m = materials[name]
        base = np.array(hex_to_linear(m.color)) * _TEX_TINT.get(m.texture or "", 1.0)
        v = part.vertices[part.faces]  # (m,3,3)
        tris.append(v)
        colors.append(np.broadcast_to(base, (len(v), 3)))
    tri = np.concatenate(tris).astype(np.float64)
    col = np.concatenate(colors)
    lo, hi = spec.bounds()
    centre = (lo + hi) / 2
    radius = float(np.linalg.norm(hi - lo)) / 2

    yaw, pitch = math.radians(yaw_deg), math.radians(pitch_deg)
    cy, sy, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
    rot = rx @ ry  # world -> view (x right, y up, z towards viewer)
    view = (tri - centre) @ rot.T
    n = np.cross(view[:, 1] - view[:, 0], view[:, 2] - view[:, 0])
    ln = np.linalg.norm(n, axis=1)
    keep = ln > 1e-12
    n[keep] /= ln[keep, None]
    facing = n[:, 2] > 0  # back-face culling (camera looks down -z in view space)
    light = np.array([-0.45, 0.8, 0.55])
    light /= np.linalg.norm(light)
    # light direction in view space -> compare with view-space normals
    lam = np.clip(n @ light, 0, 1)
    shade = 0.42 + 0.62 * lam
    scale = S * 0.46 / radius
    px = view[:, :, 0] * scale + S / 2
    py = S * 0.52 - view[:, :, 1] * scale
    vz = view[:, :, 2]

    img = Image.new("RGB", (S, S))
    d = ImageDraw.Draw(img)
    top, bot = np.array([232, 238, 244]), np.array([196, 206, 218])
    for yy in range(0, S, 4):
        t = yy / S
        c = tuple(int(top[i] * (1 - t) + bot[i] * t) for i in range(3))
        d.rectangle([0, yy, S, yy + 4], fill=c)
    # ground disc with soft contact shadow
    r_g = radius * 1.35
    ground = []
    for k in range(48):
        a = 2 * math.pi * k / 48
        p = np.array([r_g * math.cos(a), lo[1] - centre[1], r_g * math.sin(a)]) @ rot.T
        ground.append((p[0] * scale + S / 2, S * 0.52 - p[1] * scale))
    shadow = Image.new("L", (S, S), 0)
    ImageDraw.Draw(shadow).polygon(ground, fill=70)
    shadow = shadow.filter(ImageFilter.GaussianBlur(S * 0.02))
    d.polygon(ground, fill=(150, 168, 140))
    img.paste(Image.new("RGB", (S, S), (60, 70, 60)), (0, 0), shadow.point(lambda v: v // 3))

    # z-buffer rasteriser: orthographic, larger view-space z is nearer to the camera
    frame = np.asarray(img, dtype=np.uint8).copy()
    zbuf = np.full((S, S), -1e9, dtype=np.float32)
    for i in np.nonzero(facing)[0]:
        x0, x1, x2 = px[i]
        y0, y1, y2 = py[i]
        minx, maxx = max(int(math.floor(min(x0, x1, x2))), 0), min(int(math.ceil(max(x0, x1, x2))), S - 1)
        miny, maxy = max(int(math.floor(min(y0, y1, y2))), 0), min(int(math.ceil(max(y0, y1, y2))), S - 1)
        if minx > maxx or miny > maxy:
            continue
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if abs(area) < 1e-9:
            continue
        gx, gy = np.meshgrid(np.arange(minx, maxx + 1) + 0.5, np.arange(miny, maxy + 1) + 0.5)
        w1 = ((gx - x0) * (y2 - y0) - (gy - y0) * (x2 - x0)) / area
        w2 = ((x1 - x0) * (gy - y0) - (y1 - y0) * (gx - x0)) / area
        w0 = 1 - w1 - w2
        eps = -1e-4
        mask = (w0 >= eps) & (w1 >= eps) & (w2 >= eps)
        if not mask.any():
            continue
        z = w0 * vz[i, 0] + w1 * vz[i, 1] + w2 * vz[i, 2]
        sub = zbuf[miny:maxy + 1, minx:maxx + 1]
        upd = mask & (z > sub + 1e-5)
        if not upd.any():
            continue
        sub[upd] = z[upd]
        rgb = np.array([int(_to_srgb(c * shade[i]) * 255) for c in col[i]], dtype=np.uint8)
        frame[miny:maxy + 1, minx:maxx + 1][upd] = rgb
    img = Image.fromarray(frame, "RGB")
    img = img.resize((size, size), Image.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, optimize=True)
