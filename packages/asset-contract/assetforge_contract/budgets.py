"""Geometry budgets per category and quality profile.

The numbers for ``stylized_standard`` come from the project brief (section 10). They are *preliminary
targets*, configurable per job, never hard universal limits. Other profiles scale them with a
multiplier. Exceeding a budget yields a validation warning, not a failure.
"""

from __future__ import annotations

from enum import Enum


class QualityProfile(str, Enum):
    prototype = "prototype"
    stylized_standard = "stylized_standard"
    stylized_detailed = "stylized_detailed"
    high_quality = "high_quality"
    custom = "custom"


# Multipliers applied to the Stylized Standard LOD0 budget.
QUALITY_PROFILES: dict[QualityProfile, float] = {
    QualityProfile.prototype: 0.4,
    QualityProfile.stylized_standard: 1.0,
    QualityProfile.stylized_detailed: 2.0,
    QualityProfile.high_quality: 4.0,
    QualityProfile.custom: 1.0,
}

# (min, max) LOD0 triangles for Stylized Standard.
CATEGORY_BUDGETS: dict[str, tuple[int, int]] = {
    "house": (1_000, 4_000),
    "apartment": (3_000, 10_000),
    "commercial": (3_000, 10_000),
    "skyscraper": (5_000, 15_000),
    "industrial": (3_000, 10_000),
    "hospital": (3_000, 10_000),
    "school": (3_000, 10_000),
    "university": (3_000, 10_000),
    "police": (3_000, 10_000),
    "fire_station": (3_000, 10_000),
    "transport_station": (3_000, 10_000),
    "warehouse": (3_000, 10_000),
    "government": (3_000, 10_000),
    "vehicle": (2_000, 6_000),
    "character": (2_000, 5_000),
    "tree": (300, 1_500),
    "prop": (50, 1_000),
}


def triangle_budget(category: str, profile: QualityProfile | str, override: int | None = None) -> tuple[int, int]:
    """Return the (min, max) triangle budget for a category/profile; ``override`` replaces the max."""
    lo, hi = CATEGORY_BUDGETS.get(category, (50, 10_000))
    mult = QUALITY_PROFILES[QualityProfile(profile)]
    lo, hi = int(lo * mult), int(hi * mult)
    if override is not None:
        hi = int(override)
    return lo, hi
