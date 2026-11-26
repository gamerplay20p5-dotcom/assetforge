"""Procedural, tileable, neutral (near-white) detail textures.

Palette colour is applied through the material base-colour factor, so one small texture set serves
every palette. All textures are deterministic for a given (kind, size, contrast).
"""

from __future__ import annotations

import numpy as np
from PIL import Image

TEXTURE_KINDS = ("plaster", "brick", "tiles", "concrete", "glass", "wood", "metal", "stone", "fabric")


def _noise(size: int, cells: int, rng: np.random.Generator) -> np.ndarray:
    """Tileable value noise in [0,1] using smoothstep interpolation with wrap-around."""
    grid = rng.random((cells, cells))
    xs = np.linspace(0, cells, size, endpoint=False)
    i0 = np.floor(xs).astype(int)
    f = xs - i0
    f = f * f * (3 - 2 * f)
    i1 = (i0 + 1) % cells
    i0 %= cells
    a = grid[np.ix_(i0, i0)]
    b = grid[np.ix_(i0, i1)]
    c = grid[np.ix_(i1, i0)]
    d = grid[np.ix_(i1, i1)]
    fx = f[None, :]
    fy = f[:, None]
    top = a * (1 - fx) + b * fx
    bot = c * (1 - fx) + d * fx
    return top * (1 - fy) + bot * fy


def _fbm(size: int, rng: np.random.Generator, octaves: int = 3, base: int = 4) -> np.ndarray:
    out = np.zeros((size, size))
    amp, total = 1.0, 0.0
    for o in range(octaves):
        out += amp * _noise(size, base * 2**o, rng)
        total += amp
        amp *= 0.5
    return out / total


def generate(kind: str, size: int = 512, contrast: float = 0.15) -> Image.Image:
    """Return an RGB PIL image (``size`` x ``size``) for a texture kind."""
    rng = np.random.default_rng(sum(map(ord, kind)) * 7919)  # deterministic per kind (hash() is salted)
    y, x = np.mgrid[0:size, 0:size] / size  # y downwards, both in [0,1)
    contrast = float(np.clip(contrast, 0.02, 0.8))
    if kind == "plaster":
        v = 0.93 - contrast * 0.6 * _fbm(size, rng, 4, 3) - contrast * 0.25 * _noise(size, 64, rng)
    elif kind == "concrete":
        v = 0.88 - contrast * 0.7 * _fbm(size, rng, 4, 4) - contrast * 0.4 * (_noise(size, 96, rng) > 0.93)
    elif kind == "brick":
        rows, per = 12, 4
        ry = y * rows
        row = np.floor(ry).astype(int)
        rx = x * per + (row % 2) * 0.5
        col = np.floor(rx).astype(int)
        fy, fx = ry - row, rx - np.floor(rx)
        mortar = (fy < 0.1) | (fy > 0.92) | (fx < 0.04) | (fx > 0.96)
        shade_tbl = rng.random((rows, per + 1))
        shade = shade_tbl[row, col % per]
        v = np.where(mortar, 0.97, 0.66 + 0.2 * shade * (0.5 + contrast) - contrast * 0.3 * _fbm(size, rng, 3, 6))
    elif kind == "tiles":
        rows, per = 10, 5
        ry = y * rows
        row = np.floor(ry).astype(int)
        rx = x * per + (row % 2) * 0.5
        col = np.floor(rx).astype(int)
        fy, fx = ry - row, rx - np.floor(rx)
        shade = rng.random((rows, per + 1))[row, col % per]
        edge = np.minimum(fx, 1 - fx) < 0.05
        v = 0.55 + 0.38 * (1 - fy) ** 1.5 * (1 - 0.35 * shade) + 0.08 * shade
        v = np.where(edge, v * 0.8, v)
        v = np.where(fy > 0.9, v * 0.7, v)
    elif kind == "glass":
        v = 0.55 + 0.45 * (1 - y)
        streak = np.exp(-(((x + y * 0.6) % 1.0 - 0.3) ** 2) / 0.003) * 0.35 + np.exp(
            -(((x + y * 0.6) % 1.0 - 0.45) ** 2) / 0.0008) * 0.25
        v = np.clip(v + streak, 0, 1)
    elif kind == "wood":
        planks = 6
        px = np.floor(x * planks)
        pshade = rng.random(planks + 1)[px.astype(int)]
        grain = _noise(size, 8, rng)[:, :] * 0.5 + np.sin((y * 40 + _fbm(size, rng, 2, 3) * 6) * np.pi) * 0.1
        gap = (x * planks - px) < 0.04
        v = np.where(gap, 0.45, 0.72 + 0.12 * pshade + contrast * 0.3 * grain)
    elif kind == "metal":
        v = 0.74 + 0.2 * np.sin(x * 2 * np.pi * 24) * 0.5 + 0.04 * _noise(size, 32, rng) - contrast * 0.2 * _fbm(
            size, rng, 3, 4)
    elif kind == "stone":
        rows, per = 4, 3
        ry = y * rows
        row = np.floor(ry).astype(int)
        rx = x * per + (row % 2) * 0.5
        col = np.floor(rx).astype(int)
        fy, fx = ry - row, rx - np.floor(rx)
        joint = (fy < 0.04) | (fx < 0.02)
        shade = rng.random((rows, per + 1))[row, col % per]
        v = np.where(joint, 0.6, 0.86 + 0.08 * shade - contrast * 0.3 * _fbm(size, rng, 3, 6))
    elif kind == "fabric":
        v = 0.85 + 0.08 * np.sin(x * 2 * np.pi * 48) * np.sin(y * 2 * np.pi * 48) + 0.05 * _noise(size, 16, rng)
    else:
        raise ValueError(f"unknown texture kind {kind!r}")
    v = np.clip(v, 0.0, 1.0)
    img = (np.stack([v, v, v], axis=-1) * 255).astype(np.uint8)
    return Image.fromarray(img, "RGB")
