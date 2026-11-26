"""Pydantic models for job parameters, validation reports and the asset manifest."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .budgets import QualityProfile

CONTRACT_VERSION = "1.0.0"

BuildingCategory = Literal[
    "house",
    "apartment",
    "commercial",
    "skyscraper",
    "industrial",
    "hospital",
    "school",
    "university",
    "police",
    "fire_station",
    "transport_station",
    "warehouse",
    "government",
]
ArchStyle = Literal["modern", "classic", "mediterranean", "nordic", "industrial"]
RoofType = Literal["gable", "hip", "flat", "shed", "sawtooth"]
ExportFormat = Literal["glb", "blend", "fbx"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BuildingParams(StrictModel):
    """Parameters of the procedural building generator. ``None`` means "choose from category preset + seed"."""

    category: BuildingCategory = "house"
    style: ArchStyle = "modern"
    seed: int = Field(default=1, ge=0, le=2**31 - 1)
    width: float | None = Field(default=None, ge=3, le=200, description="X size in meters")
    depth: float | None = Field(default=None, ge=3, le=200, description="Z size in meters")
    floors: int | None = Field(default=None, ge=1, le=80)
    floor_height: float | None = Field(default=None, ge=2.2, le=8)
    roof: RoofType | None = None
    bay_width: float | None = Field(default=None, ge=1.8, le=8)
    balconies: bool | None = None
    garage: bool | None = None
    palette: str | None = Field(default=None, max_length=64)
    wear: float = Field(default=0.15, ge=0, le=1, description="Conservation level: 0 pristine, 1 worn")
    detail: int = Field(default=1, ge=0, le=2, description="0 = simplified windows, 2 = full moldings")
    texture_resolution: Literal[128, 256, 512, 1024, 2048] = 512
    archetype: Literal["tudor_cottage", "colonial", "mediterranean", "nordic_cabin", "modern", "bungalow"] | None = Field(
        default=None, description="Premium Stylized house kit: builds the house from a named archetype spec (category must be house)")
    construction_stage: int | None = Field(default=None, ge=1, le=6, description="house kit: 1 terrain .. 6 landscaped (same geometry at every stage)")
    house_spec: dict[str, Any] | None = Field(
        default=None, description="Full architectural spec (JSON) for the house kit; overrides `archetype`. Validated by the generator")


JobType = Literal["procedural.building", "ai.text_to_3d", "ai.image_to_3d"]
AI_JOB_TYPES = ("ai.text_to_3d", "ai.image_to_3d")


class AiParams(StrictModel):
    """Parameters of the generative (Intel AI / ComfyUI) pipeline. Complements, never replaces, the procedural generators."""

    category: str = Field(default="prop", max_length=48)
    prompt: str | None = Field(default=None, max_length=1200, description="text -> image -> 3D")
    negative_prompt: str = Field(default="", max_length=600)
    reference_id: str | None = Field(default=None, pattern=r"^ref_[0-9a-f]{12}$", description="uploaded reference image")
    seed: int = Field(default=1, ge=0, le=2**31 - 1)
    target_size_m: float = Field(default=8.0, ge=0.2, le=300, description="real-world size used to normalise the mesh")
    size_axis: Literal["height", "max"] = "height"
    art_style: Literal["premium_stylized", "none"] = "premium_stylized"
    use_trellis2: bool = False
    remove_background: bool = True
    lod_ratios: list[float] = Field(default_factory=lambda: [0.5, 0.25, 0.1], max_length=5)
    image_size: Literal[768, 1024] = 1024
    # --- image-to-3D provider selection (CPU providers are the default; "intel" = ComfyUI/XPU, disabled unless explicitly enabled) ---
    provider: Literal["sf3d", "triposr", "intel"] = "sf3d"
    texture_resolution: int | None = Field(default=None, ge=256, le=4096, description="default comes from the quality profile")
    mc_resolution: int | None = Field(default=None, ge=64, le=512, description="TripoSR marching-cubes grid")
    remesh: Literal["none", "triangle", "quad"] = "none"  # Stable Fast 3D
    max_triangles: int | None = Field(default=None, ge=200, le=2_000_000, description="overrides the category/profile budget for LOD0")

    @field_validator("lod_ratios")
    @classmethod
    def _ratios(cls, v: list[float]) -> list[float]:
        if any(not 0.02 <= r < 1.0 for r in v) or v != sorted(v, reverse=True):
            raise ValueError("lod_ratios must be descending values in [0.02, 1.0)")
        return v

    @field_validator("category")
    @classmethod
    def _cat(cls, v: str) -> str:
        from .budgets import CATEGORY_BUDGETS

        if v not in CATEGORY_BUDGETS:
            raise ValueError(f"unknown category {v!r}")
        return v


class JobCreate(StrictModel):
    """Request to generate one asset. ``params`` is validated against the model of ``job_type``."""

    name: str = Field(min_length=1, max_length=120)
    job_type: JobType = "procedural.building"
    params: dict[str, Any] = Field(default_factory=dict)
    quality_profile: QualityProfile = QualityProfile.stylized_standard
    triangle_limit: int | None = Field(default=None, ge=50, le=2_000_000)
    formats: list[ExportFormat] = Field(default_factory=lambda: ["glb"])
    priority: int = Field(default=0, ge=-100, le=100)
    worker_id: str | None = None
    scheduled_at: datetime | None = None
    depends_on: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list, max_length=20)
    art_profile_id: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=120)
    asset_id: str | None = Field(default=None, description="Existing asset id: generate a new version of it")

    @model_validator(mode="after")
    def _validate_params(self) -> "JobCreate":
        if self.job_type == "procedural.building":
            self.params = BuildingParams.model_validate(self.params).model_dump(mode="json")
        else:
            ai = AiParams.model_validate(self.params)
            if self.job_type == "ai.text_to_3d" and ai.provider != "intel":
                raise ValueError("text-to-3D needs a text-to-image model: only the (currently disabled) Intel provider has one; use ai.image_to_3d with a reference image")
            if self.job_type == "ai.text_to_3d" and not ai.prompt:
                raise ValueError("ai.text_to_3d requires 'prompt'")
            if self.job_type == "ai.image_to_3d" and not ai.reference_id:
                raise ValueError("ai.image_to_3d requires 'reference_id' (upload a reference image first)")
            self.params = ai.model_dump(mode="json")
        return self

    @property
    def category(self) -> str:
        return str(self.params.get("category", ""))

    @field_validator("formats")
    @classmethod
    def _glb_always(cls, v: list[str]) -> list[str]:
        out = list(dict.fromkeys(v))
        if "glb" not in out:
            out.insert(0, "glb")
        return out


class FileEntry(StrictModel):
    name: str
    role: Literal["model", "editable", "interchange", "texture", "preview", "metadata", "package", "report"]
    format: str
    size: int
    sha256: str


class MaterialInfo(StrictModel):
    name: str
    base_color: str  # sRGB hex
    texture: str | None = None
    roughness: float = 0.8
    metallic: float = 0.0
    tile_meters: float | None = None


class ConnectionPoint(StrictModel):
    name: str
    position: tuple[float, float, float]
    direction: tuple[float, float, float] = (0, 0, 1)


class LodInfo(StrictModel):
    level: int
    triangles: int
    file: str
    screen_height_percent: float | None = None


class ColliderInfo(StrictModel):
    type: Literal["box", "convex", "mesh"]
    center: tuple[float, float, float]
    size: tuple[float, float, float]


class ValidationCheck(StrictModel):
    name: str
    status: Literal["pass", "warn", "fail", "skip"]
    detail: str = ""


class ValidationReport(StrictModel):
    passed: bool
    checks: list[ValidationCheck] = Field(default_factory=list)
    metrics: dict[str, float | int | str] = Field(default_factory=dict)

    @property
    def warnings(self) -> list[ValidationCheck]:
        return [c for c in self.checks if c.status == "warn"]

    @property
    def errors(self) -> list[ValidationCheck]:
        return [c for c in self.checks if c.status == "fail"]


class AssetManifest(StrictModel):
    """``manifest.json`` shipped with every asset package (spec section 11).

    Conventions: units are meters (1 unit = 1 m), glTF Y-up right-handed, pivot at the bottom center
    of the footprint, +Z is the front of the asset. Visual assets carry no gameplay rules.
    """

    contract_version: str = CONTRACT_VERSION
    asset_id: str
    name: str
    category: str
    version: int
    art_profile: str
    seed: int
    generator_id: str
    generator_version: str
    ai_model: str | None = None
    quality_profile: str
    dimensions_m: tuple[float, float, float]
    footprint_m: tuple[float, float]
    bounding_box: tuple[tuple[float, float, float], tuple[float, float, float]]
    pivot: str = "bottom_center"
    connection_points: list[ConnectionPoint] = Field(default_factory=list)
    materials: list[MaterialInfo] = Field(default_factory=list)
    textures: list[str] = Field(default_factory=list)
    lods: list[LodInfo] = Field(default_factory=list)
    colliders: list[ColliderInfo] = Field(default_factory=list)
    skeleton: str | None = None
    animations: list[str] = Field(default_factory=list)
    construction_states: list[str] = Field(default_factory=list)
    triangle_count: int
    triangle_budget: tuple[int, int]
    license: str = "CC0-1.0 (procedurally generated, no third-party assets)"
    provenance: dict[str, str] = Field(default_factory=dict)
    engine: str = "trimesh"
    generation_params: dict = Field(default_factory=dict)
    files: list[FileEntry] = Field(default_factory=list)
    created_at: datetime
