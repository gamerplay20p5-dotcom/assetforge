"""Loading and parameterising the Intel AI Playground (AIPG) ComfyUI presets.

We REUSE Intel's workflows instead of re-implementing them. A preset JSON contains the ComfyUI API graph plus
``settings`` that name the node/input each UI control drives (``nodeTitle`` / ``nodeInput``). ``apply_settings``
applies the same convention. Presets are vendored (MIT, see vendor/aipg/NOTICE.md) at a pinned AIPG commit.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

VENDOR = Path(__file__).parent / "vendor" / "aipg"
AIPG_COMMIT = "1aa842352bebe454774c4c3840755451810ca8ab"
COMFYUI_VERSION = "v0.34.0"  # WebUI/external/backend-versions.json at AIPG_COMMIT


class PresetError(Exception):
    pass


@dataclass
class Preset:
    key: str
    name: str
    workflow: dict[str, dict]
    settings: list[dict]
    required_models: list[dict]
    required_comfy_args: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    def setting(self, label: str, nth: int = 0) -> dict:
        hits = [s for s in self.settings if s["label"] == label]
        if len(hits) <= nth:
            raise PresetError(f"preset {self.key!r} has no setting {label!r}")
        return hits[nth]


def load_preset(key: str, directory: Path | None = None) -> Preset:
    path = (directory or VENDOR) / f"{key}.json"
    d = json.loads(path.read_text(encoding="utf-8"))
    return Preset(key=key, name=d["name"], workflow=d["comfyUiApiWorkflow"], settings=d.get("settings", []),
                  required_models=d.get("requiredModels", []), required_comfy_args=d.get("requiredComfyUiParameters") or [],
                  tags=d.get("tags", []), raw=d)


def nodes_by_title(workflow: dict, title: str) -> list[str]:
    return [nid for nid, n in workflow.items() if n.get("_meta", {}).get("title") == title]


def set_node_input(workflow: dict, title: str, name: str, value: Any, *, required: bool = True) -> int:
    ids = nodes_by_title(workflow, title)
    if not ids and required:
        raise PresetError(f"workflow has no node titled {title!r}")
    for nid in ids:
        workflow[nid]["inputs"][name] = value
    return len(ids)


def apply_settings(preset: Preset, values: dict[str, Any]) -> dict:
    """Return a copy of the workflow with ``values`` (keyed by setting *label*) injected the AIPG way."""
    wf = copy.deepcopy(preset.workflow)
    for label, value in values.items():
        matches = [s for s in preset.settings if s["label"] == label and s.get("nodeTitle")]
        if not matches:
            raise PresetError(f"preset {preset.key!r} has no node-bound setting {label!r}")
        for s in matches:
            set_node_input(wf, s["nodeTitle"], s["nodeInput"], value)
    return wf


def normalize_model_names(workflow: dict) -> dict:
    """AIPG stores model names with Windows separators (``Comfy-Org---Pixal3D\\\\diffusion_models\\\\x``).
    ComfyUI on Linux needs forward slashes."""
    for node in workflow.values():
        for k, v in list(node.get("inputs", {}).items()):
            if isinstance(v, str) and "---" in v and "\\" in v:
                node["inputs"][k] = v.replace("\\", "/")
    return workflow


def set_seeds(workflow: dict, seed: int) -> None:
    for n in workflow.values():
        if n["class_type"] in ("KSampler", "KSamplerAdvanced") and "seed" in n["inputs"]:
            n["inputs"]["seed"] = seed
        if "noise_seed" in n.get("inputs", {}):
            n["inputs"]["noise_seed"] = seed


def workflow_sha(workflow: dict) -> str:
    return hashlib.sha256(json.dumps(workflow, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def text_to_image_workflow(preset: Preset, prompt: str, negative: str, width: int, height: int, seed: int,
                           steps: int | None = None) -> dict:
    """Z-Image-Turbo graph from AIPG, minus the NSFW SafetyChecker custom node (which needs extra custom nodes and a
    classifier; asset prompts are architectural, and this keeps the backend 100% native ComfyUI nodes)."""
    wf = copy.deepcopy(preset.workflow)
    safety = [k for k, n in wf.items() if n["class_type"] == "SafetyChecker"]
    for k in safety:
        image_src = wf[k]["inputs"]["image"]
        for n in wf.values():
            for name, v in n.get("inputs", {}).items():
                if isinstance(v, list) and v and v[0] == k:
                    n["inputs"][name] = image_src
        del wf[k]
    for k in [k for k, n in wf.items() if n["class_type"] == "CM_FloatBinaryOperation"]:
        del wf[k]
    ids = nodes_by_title(wf, "prompt")
    if not ids:
        raise PresetError("z-image preset has no 'prompt' node")
    wf[ids[0]]["inputs"]["text"] = prompt
    for n in wf.values():
        if n["class_type"] == "EmptySD3LatentImage":
            n["inputs"].update(width=width, height=height, batch_size=1)
        if n["class_type"] == "KSampler" and steps:
            n["inputs"]["steps"] = steps
        if n["class_type"] == "SaveImage":
            n["inputs"]["filename_prefix"] = "assetforge_ref"
    set_seeds(wf, seed)
    _ = negative  # Z-Image-Turbo uses ConditioningZeroOut as negative; the field is kept for other presets
    return normalize_model_names(wf)
