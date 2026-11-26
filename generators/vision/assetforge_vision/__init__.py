"""Vision front-end of AI-Assisted Procedural Modeling: image -> validated house description (JSON) -> HouseSpec for the kit."""

from .schema import COLORS, HouseDescription, parse_description
from .truth import TRUTH

__all__ = ["COLORS", "HouseDescription", "parse_description", "TRUTH"]
