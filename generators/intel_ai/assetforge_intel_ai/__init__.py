"""Intel AI provider for AssetForge (headless ComfyUI + Intel AI Playground workflows)."""

from .comfy_client import ComfyCancelled, ComfyClient, ComfyError, parse_devices
from .models import LICENSES, ModelSpec, ModelStore, required_specs
from .profiles import PROFILES, STYLE_SUFFIX, target_faces
from .provider import GenerationResult, Health, IntelAIProvider
from .vram import VramMonitor

__all__ = [
    "LICENSES", "PROFILES", "STYLE_SUFFIX", "ComfyCancelled", "ComfyClient", "ComfyError", "GenerationResult", "Health",
    "IntelAIProvider", "ModelSpec", "ModelStore", "VramMonitor", "parse_devices", "required_specs", "target_faces",
]
