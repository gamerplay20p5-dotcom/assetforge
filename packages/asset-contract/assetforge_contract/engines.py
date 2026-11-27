"""The supported inputs of the experimental reconstruction engines."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


RECONSTRUCT = "experimental.reconstruct"
CATEGORIES = ("building", "vehicle", "npc", "prop")
ENGINES = {
    "trellis2-gguf": {"label": "TRELLIS.2 GGUF", "resolutions": [512, 1024, 1536], "views": ["front"]},
    "pixal3d-sv": {"label": "Pixal3D Single-View", "resolutions": [1024], "views": ["front"]},
    "pixal3d-mv": {"label": "Pixal3D Multi-View", "resolutions": [1024, 1536], "views": ["front", "right", "back", "three_quarter"]},
    "pixal3d-python": {"label": "Pixal3D Python", "resolutions": [1024, 1536], "views": ["front", "right", "back", "three_quarter"]},
}

View = Literal["front", "right", "back", "three_quarter"]
Row = tuple[float, float, float, float]


class ArchivedProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    camera_angle_x: float = Field(gt=0, lt=3.142)
    transforms: dict[View, tuple[Row, Row, Row, Row]]


class ReconstructionParams(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    engine: Literal["trellis2-gguf", "pixal3d-sv", "pixal3d-mv", "pixal3d-python"]
    category: Literal["building", "vehicle", "npc", "prop"]
    references: dict[View, str]
    resolution: int = 1024
    max_tokens: int = Field(default=49152, gt=0, le=2**31 - 1)
    seed: int = Field(default=1, ge=0, le=2**31 - 1)
    texture_size: int = Field(default=4096, ge=128, le=16384)
    structure_guidance: float | None = Field(default=7.5, ge=0, le=32)
    shape_guidance: float | None = Field(default=7.5, ge=0, le=32)
    mesh_scale: float = Field(default=1.0, gt=0, le=10)
    three_quarter_angle: float = Field(default=45, gt=0, lt=360)
    skip_decimation: bool = True
    prepared_inputs: bool = False
    archived_projection: ArchivedProjection | None = None
    archive_azimuth_override: float | None = Field(default=None, gt=0, lt=360)
    use_native_threads: bool = False

    @model_validator(mode="after")
    def check_engine(self):
        import re

        entry = ENGINES[self.engine]
        if self.resolution not in entry["resolutions"]:
            raise ValueError("resolution is unsupported by this engine")
        if set(self.references) != set(entry["views"]):
            raise ValueError(f"required reference views: {', '.join(entry['views'])}")
        if any(not re.fullmatch(r"ref_[0-9a-f]{12}", ref) for ref in self.references.values()):
            raise ValueError("invalid reference id")
        if len(set(self.references.values())) != len(self.references):
            raise ValueError("use a distinct reference for each view")
        if self.texture_size & (self.texture_size - 1):
            raise ValueError("texture_size must be a power of two")
        if self.prepared_inputs and self.engine == "trellis2-gguf":
            raise ValueError("TRELLIS.2 accepts the original image")
        if self.prepared_inputs and len(entry["views"]) > 1:
            if not self.archived_projection or set(self.archived_projection.transforms) != set(entry["views"]):
                raise ValueError("prepared multi-view references require archived camera poses")
        elif self.archived_projection:
            raise ValueError("archived camera poses require prepared multi-view references")
        if self.archive_azimuth_override is not None and not self.archived_projection:
            raise ValueError("an archived azimuth override requires archived camera poses")
        return self
