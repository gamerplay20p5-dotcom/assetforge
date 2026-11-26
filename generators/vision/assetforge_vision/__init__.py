"""Vision front-end of AI-Assisted Procedural Modeling: image -> validated house description (JSON) -> HouseSpec for the kit."""

from .schema import CATEGORIES, COLORS, AssetAnalysis, HouseDescription, parse_analysis, parse_description
from .truth import TRUTH

__all__ = ["CATEGORIES", "COLORS", "AssetAnalysis", "HouseDescription", "parse_analysis", "parse_description", "TRUTH"]
