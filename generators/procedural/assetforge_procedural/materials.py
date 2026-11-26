"""Palettes and material definitions for the Premium Stylized art profile."""

from __future__ import annotations

import colorsys
from dataclasses import dataclass

import numpy as np

ART_PROFILE_ID = "premium-stylized-v1"


@dataclass(frozen=True)
class MaterialDef:
    name: str
    color: str  # sRGB hex
    texture: str | None  # texture kind or None for flat color
    roughness: float = 0.85
    metallic: float = 0.0
    tile_m: float = 2.0


def _hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    r, g, b = (int(round(max(0, min(1, c)) * 255)) for c in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def srgb_to_linear(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb)  # type: ignore[misc]


def hex_to_linear(h: str) -> tuple[float, float, float]:
    return srgb_to_linear(_hex_to_rgb(h))


def weather(color: str, wear: float) -> str:
    """Darken and desaturate a color according to the conservation level (0 pristine .. 1 worn)."""
    h, s, v = colorsys.rgb_to_hsv(*_hex_to_rgb(color))
    s *= 1 - 0.35 * wear
    v *= 1 - 0.22 * wear
    return _rgb_to_hex(colorsys.hsv_to_rgb(h, s, v))


# Palettes are hand-picked harmonious sets: wall / trim / base / roof / accent / door / frame / metal / awning / awning_b
PALETTES: dict[str, dict[str, dict[str, str]]] = {
    "modern": {
        "chalk": dict(wall="#EAE6DD", trim="#BFC4C9", base="#8C9299", roof="#4B5058", accent="#E0713A", door="#2E3B4E",
                      frame="#2B2F36", metal="#9AA3AD", awning="#E0713A", awning_b="#F4E8D8"),
        "slate": dict(wall="#C9CED4", trim="#E8EAEC", base="#6D7680", roof="#2F353C", accent="#2F9C95", door="#1F2A33",
                      frame="#20262C", metal="#8E98A3", awning="#2F9C95", awning_b="#E8EAEC"),
        "sand": dict(wall="#DCCBB0", trim="#F3ECE0", base="#9A8670", roof="#5A5148", accent="#C2503A", door="#3A2F28",
                     frame="#352E29", metal="#A39B90", awning="#C2503A", awning_b="#F3ECE0"),
    },
    "classic": {
        "brick-red": dict(wall="#B5543E", trim="#E6DCC8", base="#7D736A", roof="#4A3B36", accent="#2F5D50", door="#2F5D50",
                          frame="#F1EBDD", metal="#7D858C", awning="#2F5D50", awning_b="#F1EBDD"),
        "brick-brown": dict(wall="#9C6B4E", trim="#E9DFCB", base="#6F6258", roof="#3E3A3A", accent="#8A2F2F",
                            door="#5B2B26", frame="#F0E8D6", metal="#7C838A", awning="#8A2F2F", awning_b="#F0E8D6"),
        "cream": dict(wall="#E3D2B0", trim="#F7F1E3", base="#9B8C75", roof="#6A4A3C", accent="#3C5E8C", door="#3C5E8C",
                      frame="#F7F1E3", metal="#868C92", awning="#3C5E8C", awning_b="#F7F1E3"),
    },
    "mediterranean": {
        "terracotta": dict(wall="#EFD9B8", trim="#FBF4E6", base="#B9A07C", roof="#C0603A", accent="#2E7C99", door="#2E7C99",
                           frame="#FBF4E6", metal="#8D8A83", awning="#2E7C99", awning_b="#FBF4E6"),
        "ochre": dict(wall="#E5B96A", trim="#FAF1DC", base="#A98349", roof="#B4502F", accent="#3F7F5C", door="#3F7F5C",
                      frame="#FAF1DC", metal="#8D8A83", awning="#3F7F5C", awning_b="#FAF1DC"),
        "rose": dict(wall="#E8B5A0", trim="#FBEFE6", base="#A8806E", roof="#9E4B36", accent="#4C7EA3", door="#4C7EA3",
                     frame="#FBEFE6", metal="#8D8A83", awning="#4C7EA3", awning_b="#FBEFE6"),
    },
    "nordic": {
        "falu": dict(wall="#A5362F", trim="#F2EEE6", base="#5E5A57", roof="#33373B", accent="#F2EEE6", door="#2C4A5A",
                     frame="#F2EEE6", metal="#7C8288", awning="#2C4A5A", awning_b="#F2EEE6"),
        "ice": dict(wall="#CFDCE3", trim="#F4F7F8", base="#7A8891", roof="#3C464E", accent="#D88C3A", door="#3C464E",
                    frame="#F4F7F8", metal="#8A949C", awning="#D88C3A", awning_b="#F4F7F8"),
        "pine": dict(wall="#8A6A4A", trim="#E8DCC4", base="#5A4A3C", roof="#37393A", accent="#3F6B52", door="#3F6B52",
                     frame="#E8DCC4", metal="#7C8288", awning="#3F6B52", awning_b="#E8DCC4"),
    },
    "industrial": {
        "steel": dict(wall="#A9B2BA", trim="#D6DBDF", base="#5E666E", roof="#6E7780", accent="#E3B02F", door="#3A4650",
                      frame="#3A4650", metal="#8A949E", awning="#E3B02F", awning_b="#2B3036"),
        "rust": dict(wall="#B98C6C", trim="#D9C7B3", base="#6C5A4C", roof="#5D6A73", accent="#2F7FA8", door="#2F4B5E",
                     frame="#38424A", metal="#8A949E", awning="#2F7FA8", awning_b="#D9C7B3"),
        "concrete": dict(wall="#B9B7B1", trim="#D8D6D0", base="#76746F", roof="#4E5258", accent="#D4562B", door="#2F3338",
                         frame="#2F3338", metal="#8A949E", awning="#D4562B", awning_b="#D8D6D0"),
    },
}

CURTAIN_COLORS = ["#E8D9C0", "#C9D6E3", "#E3C9C9", "#D2E3C9", "#F0E6B8", "#B8C4E0"]


def list_palettes() -> dict[str, list[str]]:
    return {style: sorted(p) for style, p in PALETTES.items()}


def pick_palette(style: str, name: str | None, rng: np.random.Generator) -> tuple[str, dict[str, str]]:
    options = PALETTES[style]
    if name and name in options:
        return name, options[name]
    key = sorted(options)[int(rng.integers(len(options)))]
    return key, options[key]


def build_materials(palette: dict[str, str], wear: float, curtain: str) -> dict[str, MaterialDef]:
    w = lambda k: weather(palette[k], wear)  # noqa: E731
    return {
        "wall": MaterialDef("wall", w("wall"), "plaster", 0.9, 0.0, 2.0),
        "brick": MaterialDef("brick", w("wall"), "brick", 0.9, 0.0, 2.0),
        "cladding": MaterialDef("cladding", w("wall"), "metal", 0.6, 0.35, 2.0),
        "trim": MaterialDef("trim", w("trim"), "stone", 0.8, 0.0, 2.0),
        "base": MaterialDef("base", w("base"), "concrete", 0.95, 0.0, 2.0),
        "roof": MaterialDef("roof", w("roof"), "tiles", 0.75, 0.0, 2.0),
        "roof_flat": MaterialDef("roof_flat", weather("#5F646B", wear), "concrete", 0.95, 0.0, 3.0),
        "accent": MaterialDef("accent", w("accent"), "plaster", 0.7, 0.0, 2.0),
        "door": MaterialDef("door", w("door"), "wood", 0.6, 0.0, 2.0),
        "frame": MaterialDef("frame", w("frame"), None, 0.5, 0.0),
        "metal": MaterialDef("metal", w("metal"), "metal", 0.45, 0.85, 2.0),
        "glass": MaterialDef("glass", "#7FB4C9", "glass", 0.08, 0.0, 1.0),
        "glass_lit": MaterialDef("glass_lit", "#F3D58B", "glass", 0.25, 0.0, 1.0),
        "curtain": MaterialDef("curtain", curtain, "fabric", 0.95, 0.0, 1.0),
        "awning": MaterialDef("awning", w("awning"), "fabric", 0.9, 0.0, 1.0),
        "awning_b": MaterialDef("awning_b", w("awning_b"), "fabric", 0.9, 0.0, 1.0),
        "sign_white": MaterialDef("sign_white", "#F4F4F0", None, 0.7, 0.0),
        "sign_red": MaterialDef("sign_red", "#C93A3A", None, 0.7, 0.0),
        "sign_blue": MaterialDef("sign_blue", "#2F5FA8", None, 0.7, 0.0),
        "dark": MaterialDef("dark", "#2A2D33", None, 0.9, 0.0),
    }
