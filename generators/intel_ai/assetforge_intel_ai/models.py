"""Model registry (licenses!), local cache layout and verified downloads.

Layout is the AI Playground one (``models/<type>/<owner>---<repo>/<path in repo>``) so a node that already runs AIPG's
ComfyUI shares its weights. Downloads are explicit (operator action), resumable, verified against the SHA-256 that
Hugging Face publishes for LFS files, and never needed again afterwards (offline operation).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from .presets import load_preset

HF = "https://huggingface.co"

# License facts verified on 2026-11-26 from the Hugging Face cards / upstream LICENSE files (see docs/INTEL_AI.md).
# commercial_br: "ok" = permissive license without territorial restriction naming Brazil; "verify" = needs a human check.
LICENSES: dict[str, dict] = {
    "Comfy-Org/Pixal3D": {"license": "MIT (base TencentARC/Pixal3D: MIT)", "commercial_br": "ok",
                          "note": "inclui o encoder DINOv3 'dino_v3_L_naf' (ver linha própria) e os VAEs TRELLIS.2 (MIT)"},
    "Comfy-Org/TRELLIS.2": {"license": "MIT (base microsoft/TRELLIS.2-4B: MIT)", "commercial_br": "ok", "note": ""},
    "Comfy-Org/MoGe": {"license": "MIT", "commercial_br": "ok", "note": ""},
    "Comfy-Org/BiRefNet": {"license": "MIT", "commercial_br": "ok", "note": ""},
    "Comfy-Org/Z-Image-Turbo": {"license": "Apache-2.0 (base Tongyi-MAI/Z-Image-Turbo)", "commercial_br": "ok",
                                "note": "text encoder Qwen3-4B: Apache-2.0; ae.safetensors é o VAE FLUX — o repack declara Apache-2.0, mas confirmar origem"},
    "Comfy-Org/z_image_turbo": {"license": "Apache-2.0 (alias do anterior)", "commercial_br": "ok", "note": "repo renomeado no HF (redirect)"},
    "AdamCodd/vit-base-nsfw-detector": {"license": "Apache-2.0", "commercial_br": "ok", "note": "não usado (SafetyChecker removido)"},
}
# Per-file exceptions that differ from their repo license.
FILE_LICENSES: dict[str, dict] = {
    "clip_vision/dino_v3_L_naf_fp32.safetensors": {
        "license": "DINOv3 License (Meta) — o card Comfy-Org diz MIT, mas o encoder deriva do DINOv3", "commercial_br": "verify",
        "note": "Licença lida em 2026-11-26: royalty-free, mundial, permite uso/distribuição/derivados; exige repassar a licença, "
                "cumprir leis de controle de exportação e proíbe ITAR/uso militar. 'NAF' (variante) NÃO teve licença própria verificada."},
}


@dataclass(frozen=True)
class ModelSpec:
    type: str  # ComfyUI models/<type> folder
    repo: str  # owner/name
    path: str  # path inside the repo
    preset: str

    @property
    def key(self) -> str:
        return f"{self.repo}/{self.path}"

    def local_path(self, models_dir: Path) -> Path:
        return models_dir / self.type / self.repo.replace("/", "---") / self.path

    @property
    def license_info(self) -> dict:
        return FILE_LICENSES.get(self.path) or LICENSES.get(self.repo) or {"license": "DESCONHECIDA", "commercial_br": "verify", "note": ""}


def specs_for(preset_key: str) -> list[ModelSpec]:
    out = []
    for m in load_preset(preset_key).required_models:
        owner, repo, *rest = m["model"].split("/")
        out.append(ModelSpec(type=m["type"], repo=f"{owner}/{repo}", path="/".join(rest), preset=preset_key))
    return out


PRESET_KEYS = {"image_to_3d": "pixel3d-trellis", "text_to_image": "z-image"}
# SafetyChecker (NSFW classifier) is intentionally not installed: the text-to-image workflow variant drops it.
SKIP_REPOS = {"AdamCodd/vit-base-nsfw-detector"}


def required_specs(capabilities: tuple[str, ...] = ("image_to_3d", "text_to_image")) -> list[ModelSpec]:
    seen, out = set(), []
    for cap in capabilities:
        for s in specs_for(PRESET_KEYS[cap]):
            if s.repo in SKIP_REPOS or s.key in seen:
                continue
            seen.add(s.key)
            out.append(s)
    return out


class ModelStore:
    def __init__(self, models_dir: Path, client: httpx.Client | None = None) -> None:
        self.dir = Path(models_dir)
        self.http = client or httpx.Client(timeout=httpx.Timeout(30.0, read=120.0), follow_redirects=True)
        self.lock_path = self.dir / "assetforge-models.lock.json"

    def status(self, specs: list[ModelSpec]) -> list[dict]:
        lock = self._lock()
        rows = []
        for s in specs:
            p = s.local_path(self.dir)
            present = p.is_file() and p.stat().st_size > 0
            rows.append({"key": s.key, "type": s.type, "present": present, "size": p.stat().st_size if present else 0,
                         "verified": bool(present and lock.get(s.key, {}).get("sha256")), **s.license_info})
        return rows

    def missing(self, specs: list[ModelSpec]) -> list[ModelSpec]:
        return [s for s in specs if not (s.local_path(self.dir).is_file() and s.local_path(self.dir).stat().st_size > 0)]

    def _lock(self) -> dict:
        try:
            return json.loads(self.lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_lock(self, lock: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock_path.write_text(json.dumps(lock, indent=2), encoding="utf-8")

    def expected(self, s: ModelSpec) -> tuple[int | None, str | None]:
        """(size, sha256) published by Hugging Face for this file, when available."""
        folder, _, name = s.path.rpartition("/")
        r = self.http.get(f"{HF}/api/models/{s.repo}/tree/main/{folder}" if folder else f"{HF}/api/models/{s.repo}/tree/main")
        r.raise_for_status()
        for it in r.json():
            if it.get("path") == s.path:
                return it.get("size"), (it.get("lfs") or {}).get("oid")
        raise FileNotFoundError(f"{s.key} not found on Hugging Face")

    def download(self, s: ModelSpec, on_progress: Callable[[int, int | None], None] | None = None) -> Path:
        dest = s.local_path(self.dir)
        size, sha = self.expected(s)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        have = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        h = hashlib.sha256()
        if have:  # re-hash the partial file so resume keeps the digest consistent
            with part.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 22), b""):
                    h.update(chunk)
        with self.http.stream("GET", f"{HF}/{s.repo}/resolve/main/{s.path}", headers=headers) as r:
            if r.status_code == 416:  # already complete
                pass
            else:
                if r.status_code not in (200, 206):
                    raise RuntimeError(f"download of {s.key} failed: HTTP {r.status_code}")
                if r.status_code == 200 and have:  # server ignored Range: restart
                    have, h = 0, hashlib.sha256()
                with part.open("ab" if have else "wb") as fh:
                    done = have
                    for chunk in r.iter_bytes(1 << 20):
                        fh.write(chunk)
                        h.update(chunk)
                        done += len(chunk)
                        if on_progress:
                            on_progress(done, size)
        digest = h.hexdigest()
        if size is not None and part.stat().st_size != size:
            raise RuntimeError(f"{s.key}: size {part.stat().st_size} != expected {size} (resume the download)")
        if sha and digest != sha:
            part.unlink(missing_ok=True)
            raise RuntimeError(f"{s.key}: SHA-256 mismatch (expected {sha}, got {digest}); partial file removed")
        part.replace(dest)
        lock = self._lock()
        lock[s.key] = {"sha256": digest, "size": dest.stat().st_size, "source": f"{HF}/{s.repo}", "verified_against_hf": bool(sha)}
        self._save_lock(lock)
        return dest

    def verify(self, s: ModelSpec) -> bool:
        p = s.local_path(self.dir)
        want = self._lock().get(s.key, {}).get("sha256")
        if not p.is_file() or not want:
            return False
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 22), b""):
                h.update(chunk)
        return h.hexdigest() == want
