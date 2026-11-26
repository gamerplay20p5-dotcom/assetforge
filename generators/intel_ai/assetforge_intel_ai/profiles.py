"""Quality profiles for the generative pipeline.

STARTING VALUES derived from the defaults of Intel's Pixel3D-Trellis preset (steps 12, texture 4096, 7000 faces).
They are NOT calibrated for the Arc A750 8 GB: calibrate with scripts/intel_ai/benchmark_ai.py on the real node.
The triangle target is not fixed here: it comes from the asset contract budget of the category/profile.
"""

from __future__ import annotations

from dataclasses import dataclass

from assetforge_contract import QualityProfile, triangle_budget


@dataclass(frozen=True)
class AiProfile:
    steps: int
    texture_resolution: int
    remesh_resolution: int  # Narrow-Band DC remesh grid (topology cleanup)
    normal_bake_resolution: int
    ao_bake_resolution: int
    budget_fraction: float  # LOD0 target = budget_max * fraction


PROFILES: dict[QualityProfile, AiProfile] = {
    QualityProfile.prototype: AiProfile(8, 1024, 384, 1024, 512, 0.8),
    QualityProfile.stylized_standard: AiProfile(12, 2048, 512, 2048, 1024, 0.9),
    QualityProfile.stylized_detailed: AiProfile(16, 4096, 640, 2048, 1024, 0.9),
    QualityProfile.high_quality: AiProfile(20, 4096, 768, 4096, 2048, 0.95),
    QualityProfile.custom: AiProfile(12, 2048, 512, 2048, 1024, 0.9),
}


def target_faces(category: str, profile: QualityProfile, triangle_limit: int | None) -> int:
    _, hi = triangle_budget(category, profile, triangle_limit)
    return max(200, int(hi * PROFILES[profile].budget_fraction))


# Prompt scaffolding for the "Premium Stylized Low/Mid Poly" art direction (generative side).
STYLE_SUFFIX = (
    ", single isolated game asset, premium stylized low-poly 3D model look, clean readable shapes, harmonious color palette, "
    "detailed trims and window frames, soft even lighting, plain light-gray background, three-quarter view"
)
