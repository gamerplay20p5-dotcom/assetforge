"""Worker-side Intel AI runtime: health of the local headless ComfyUI, real VRAM, and the validation gate.

AI features (``ai.text_to_3d`` / ``ai.image_to_3d``) are advertised to the scheduler ONLY when:
  1. ComfyUI answers and reports a GPU device,
  2. every required model file is present locally, and
  3. this node has a validation record produced by ``scripts/intel_ai/validate_node.py`` after a REAL successful run
     (or the operator explicitly sets ASSETFORGE_AI_ALLOW_UNVALIDATED=1 to try an unvalidated node).
Point 3 keeps an untested workflow from taking the GPU that other services (e.g. AI Stream Clipper) share.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from assetforge_cpu3d import CpuProvider, parse_providers_env
from assetforge_intel_ai import ComfyClient, IntelAIProvider, ModelStore, parse_devices, required_specs

AI_FEATURES = ["comfyui", "ai.text_to_3d", "ai.image_to_3d"]


class AiRuntime:
    def __init__(self, state_dir: Path) -> None:
        self.url = os.environ.get("ASSETFORGE_COMFYUI_URL", "").rstrip("/")
        default_models = Path.home() / "assetforge-ai" / "ComfyUI" / "models"
        self.models_dir = Path(os.environ.get("ASSETFORGE_AI_MODELS_DIR", str(default_models)))
        self.allow_unvalidated = os.environ.get("ASSETFORGE_AI_ALLOW_UNVALIDATED", "0") in ("1", "true", "yes")
        self.validation_file = Path(state_dir) / "ai_validated.json"
        self._provider: IntelAIProvider | None = None
        self._cache: tuple[float, dict] | None = None

    @property
    def enabled(self) -> bool:
        # The Intel/ComfyUI integration is DISABLED unless explicitly enabled (project decision 2026-11-26: CPU providers first).
        return bool(self.url) and os.environ.get("ASSETFORGE_ENABLE_INTEL_AI", "0") in ("1", "true", "yes")

    def provider(self) -> IntelAIProvider:
        if self._provider is None:
            self._provider = IntelAIProvider(self.url, models_dir=self.models_dir)
        return self._provider

    def validated(self) -> list[dict]:
        try:
            data = json.loads(self.validation_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [d for d in data if d.get("ok")] if isinstance(data, list) else []

    def status(self, max_age: float = 30.0) -> dict:
        """Cached health + gating decision, with the reason when AI is not offered."""
        if self._cache and time.monotonic() - self._cache[0] < max_age:
            return self._cache[1]
        if not self.enabled:
            st = {"enabled": False, "features": [], "reason": "integração Intel/ComfyUI desabilitada (ASSETFORGE_ENABLE_INTEL_AI=1 e ASSETFORGE_COMFYUI_URL para habilitar)"}
        else:
            h = self.provider().health()
            val = self.validated()
            reason = None
            if not h.reachable:
                reason = "ComfyUI inacessível"
            elif not h.xpu_devices:
                reason = "ComfyUI sem dispositivo de GPU (torch XPU inativo?)"
            elif h.models_missing:
                reason = f"{len(h.models_missing)} modelo(s) ausente(s) em {self.models_dir}"
            elif not val and not self.allow_unvalidated:
                reason = "nó não validado: rode scripts/intel_ai/validate_node.py (ou ASSETFORGE_AI_ALLOW_UNVALIDATED=1 por sua conta)"
            st = {"enabled": True, "features": [] if reason else list(AI_FEATURES), "reason": reason, "health": h.as_dict(),
                  "validated": [f"{v.get('preset')}@{v.get('gpu')}" for v in val], "unvalidated_override": self.allow_unvalidated and not val}
        self._cache = (time.monotonic(), st)
        return st

    def gpus(self) -> list[dict]:
        if not self.enabled:
            return []
        try:
            return [g for g in parse_devices(ComfyClient(self.url).system_stats()) if g["backend"] not in ("cpu", "")]
        except Exception:  # noqa: BLE001
            return []

    def free_vram_mb(self) -> int | None:
        for g in self.gpus():
            if g["vram_total_mb"] is not None and g["vram_used_mb"] is not None:
                return g["vram_total_mb"] - g["vram_used_mb"]
        return None

    def vram_limit_mb(self) -> int | None:
        env = os.environ.get("ASSETFORGE_WORKER_VRAM_MB")
        if env:
            return int(env)
        gpus = self.gpus()
        return int(gpus[0]["vram_total_mb"] * 0.9) if gpus and gpus[0]["vram_total_mb"] else None

    def model_rows(self) -> list[dict]:
        return ModelStore(self.models_dir).status(required_specs()) if self.enabled else []


class Cpu3dRuntime:
    """CPU-only image-to-3D providers running as sibling containers (Stable Fast 3D, TripoSR)."""

    def __init__(self) -> None:
        self.urls = parse_providers_env(os.environ.get("ASSETFORGE_CPU3D_PROVIDERS", ""))
        self.providers = {n: CpuProvider(n, u) for n, u in self.urls.items()}
        self._cache: tuple[float, dict] | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.providers)

    def status(self, max_age: float = 15.0) -> dict:
        """Per-provider readiness (container reachable AND weights cached). Only ready providers become scheduler features."""
        if self._cache and time.monotonic() - self._cache[0] < max_age:
            return self._cache[1]
        info, features = {}, []
        for name, p in self.providers.items():
            h = p.health()
            ready = bool(h.get("reachable") and h.get("ready"))
            info[name] = {"ready": ready, "reason": None if ready else h.get("reason", "not ready"), "threads": h.get("threads"),
                          "concurrency": h.get("concurrency"), "active_jobs": h.get("active_jobs", 0), "commercial": (h.get("license") or {}).get("commercial")}
            if ready:
                features.append(f"provider.{name}")
        st = {"enabled": self.enabled, "providers": info, "features": (["ai.image_to_3d"] + features) if features else []}
        self._cache = (time.monotonic(), st)
        return st

    def telemetry(self) -> dict:
        out = {}
        for name, p in self.providers.items():
            s = p.stats()
            if s:
                out[name] = {k: s.get(k) for k in ("container_mem_mb", "container_mem_limit_mb", "host_cpu_percent")}
        return out

    def cancel(self, tag: str) -> None:
        for p in self.providers.values():
            p.cancel_tag(tag)
