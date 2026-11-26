"""Prompt sent to the vision model. The answer is constrained to the schema in :mod:`assetforge_vision.schema`."""

from .schema import COLORS, PORCHES, ROOF_TYPES, VOLUMES, WALL_MATERIALS

SYSTEM = "You are an architectural analyst. You answer with a single JSON object and nothing else."

USER = f"""Look at the house in the image and describe the FINISHED house (ignore the ground block, grass and background).
Answer with ONE JSON object with exactly these keys:
- "floors": integer 1-3 (number of storeys of the main volume)
- "roof_type": one of {list(ROOF_TYPES)} (the dominant roof)
- "roof_color": one of {list(COLORS)}
- "wall_material": one of {list(WALL_MATERIALS)} (main wall material; "siding" = horizontal boards)
- "wall_color": one of {list(COLORS)}
- "lower_wall_material": a wall material when the lower storey differs from the upper one (e.g. brick under siding), else "none"
- "lower_wall_color": a colour for it, else "none"
- "trim_color": colour of window frames / corner trim, one of {list(COLORS)}
- "door_color": one of {list(COLORS)}
- "door_position": "left", "center" or "right" on the front facade
- "windows_front_per_floor": list of integers, windows visible on the front facade for each floor starting at the ground floor
- "porch": one of {list(PORCHES)}
- "garage": true/false, "garage_side": "left", "right" or "none"
- "chimney": true/false
- "volumes": one of {list(VOLUMES)}
- "bay_window": true/false
Use only values from the lists. JSON only."""
