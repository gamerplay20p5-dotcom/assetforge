"""Intel AI provider: text-to-image and image-to-3D through a headless ComfyUI (XPU) backend."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from assetforge_contract import QualityProfile

from .comfy_client import ComfyClient, ComfyError, parse_devices
from .models import ModelStore, required_specs
from .presets import (
    AIPG_COMMIT,
    COMFYUI_VERSION,
    Preset,
    apply_settings,
    load_preset,
    normalize_model_names,
    set_node_input,
    set_seeds,
    text_to_image_workflow,
    workflow_sha,
)
from .profiles import PROFILES, STYLE_SUFFIX
from .vram import VramMonitor

PROVIDER_ID = "intel-ai-playground-comfyui"


@dataclass
class Health:
    reachable: bool = False
    comfyui_version: str | None = None
    xpu_devices: list[dict] = field(default_factory=list)
    models_missing: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.reachable and bool(self.xpu_devices) and not self.models_missing

    def as_dict(self) -> dict:
        return {"reachable": self.reachable, "comfyui_version": self.comfyui_version, "xpu_devices": self.xpu_devices,
                "models_missing": self.models_missing, "errors": self.errors, "ready": self.ready}


@dataclass
class GenerationResult:
    path: Path
    seconds: float
    peak_vram_mb: int | None
    vram_total_mb: int | None
    prompt_id: str
    workflow_sha: str
    preset: str


Emit = Callable[[dict], None]


class IntelAIProvider:
    """Thin orchestration over ComfyUI. All heavy lifting stays in Intel's workflows."""

    id = PROVIDER_ID

    def __init__(self, comfy_url: str, models_dir: Path | None = None, client: ComfyClient | None = None) -> None:
        self.client = client or ComfyClient(comfy_url)
        self.store = ModelStore(models_dir) if models_dir else None
        self.t2i: Preset = load_preset("z-image")
        self.i23d: Preset = load_preset("pixel3d-trellis")

    # ---------------------------------------------------------------- health / capabilities
    def health(self) -> Health:
        h = Health()
        try:
            stats = self.client.system_stats()
        except Exception as exc:  # noqa: BLE001
            h.errors.append(f"ComfyUI unreachable: {type(exc).__name__}")
            return h
        h.reachable = True
        h.comfyui_version = stats.get("system", {}).get("comfyui_version")
        h.xpu_devices = [g for g in parse_devices(stats) if g["backend"] not in ("cpu", "")]
        if not h.xpu_devices:
            h.errors.append("ComfyUI reports no GPU device (torch XPU not active?)")
        if self.store:
            h.models_missing = [s.key for s in self.store.missing(required_specs())]
        else:
            h.errors.append("models dir not configured")
        return h

    # ---------------------------------------------------------------- generation
    def _execute(self, workflow: dict, preset_key: str, dest: Path, kinds: tuple[str, ...], *, timeout: float,
                 should_cancel: Callable[[], bool] | None) -> GenerationResult:
        t0 = time.monotonic()
        with VramMonitor(self.client) as vram:
            pid = self.client.queue_prompt(normalize_model_names(workflow))
            entry = self.client.wait(pid, timeout=timeout, should_cancel=should_cancel)
        files = [f for f in self.client.output_files(entry) if f.type == "output" and f.filename.lower().endswith(kinds)]
        if not files:
            raise ComfyError(f"workflow finished but produced no {'/'.join(kinds)} output")
        self.client.download(files[-1], dest)
        if not dest.is_file() or dest.stat().st_size == 0:
            raise ComfyError("downloaded output is empty")
        return GenerationResult(dest, time.monotonic() - t0, vram.peak_used_mb, vram.total_mb, pid, workflow_sha(workflow), preset_key)

    def text_to_image(self, prompt: str, dest: Path, *, negative: str = "", size: int = 1024, seed: int = 1, art_style: bool = True,
                      steps: int | None = None, timeout: float = 900.0, should_cancel: Callable[[], bool] | None = None) -> GenerationResult:
        text = prompt.strip() + (STYLE_SUFFIX if art_style else "")
        wf = text_to_image_workflow(self.t2i, text, negative, size, size, seed, steps)
        return self._execute(wf, self.t2i.key, dest, (".png", ".jpg", ".webp"), timeout=timeout, should_cancel=should_cancel)

    def image_to_3d(self, image: Path, dest: Path, *, profile: QualityProfile, target_faces: int, seed: int = 1,
                    use_trellis2: bool = False, remove_background: bool = True, timeout: float = 3600.0,
                    should_cancel: Callable[[], bool] | None = None) -> GenerationResult:
        p = PROFILES[profile]
        uploaded = self.client.upload_image(image)
        wf = apply_settings(self.i23d, {
            "Input Image": uploaded, "Base Steps": p.steps, "Use TRELLIS.2": use_trellis2,
            "Remove Background": remove_background, "Texture Resolution": p.texture_resolution,
            "Target Face Count": target_faces,
        })
        # Retopology / detail preservation = Intel's own graph: DC remesh -> decimate -> UV unwrap -> bake normal + AO from the
        # high-poly. We only set resolutions per quality profile.
        set_node_input(wf, "Remesh Mesh (Narrow-Band DC)", "resolution", p.remesh_resolution)
        set_node_input(wf, "Bake Normal Map from Mesh", "resolution", p.normal_bake_resolution)
        set_node_input(wf, "Bake Ambient Occlusion", "resolution", p.ao_bake_resolution)
        set_seeds(wf, seed)
        return self._execute(wf, self.i23d.key, dest, (".glb",), timeout=timeout, should_cancel=should_cancel)

    def provenance(self) -> dict[str, str]:
        return {"provider": self.id, "aipg_commit": AIPG_COMMIT, "comfyui_version_pinned": COMFYUI_VERSION,
                "presets": f"{self.t2i.key},{self.i23d.key}"}
