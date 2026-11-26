"""Minimal client for ComfyUI's HTTP API (headless backend, no AI Playground desktop UI required)."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


class ComfyError(Exception):
    pass


class ComfyCancelled(ComfyError):
    pass


@dataclass
class OutputFile:
    node: str
    kind: str  # key under which ComfyUI listed it (images, 3d, ...)
    filename: str
    subfolder: str
    type: str


def parse_devices(stats: dict) -> list[dict]:
    """Convert ComfyUI ``/system_stats`` devices into AssetForge GPU records (real numbers only)."""
    out = []
    for d in stats.get("devices", []):
        total, free = d.get("vram_total"), d.get("vram_free")
        out.append({
            "vendor": "Intel" if "intel" in d.get("name", "").lower() or d.get("type") == "xpu" else d.get("type", ""),
            "name": d.get("name", ""), "backend": d.get("type", ""), "kind": "discrete",
            "vram_total_mb": round(total / 2**20) if total else None,
            "vram_used_mb": round((total - free) / 2**20) if total and free is not None else None,
            "utilization_percent": None, "temperature_c": None, "source": "comfyui",
        })
    return out


class ComfyClient:
    def __init__(self, base_url: str, client: httpx.Client | None = None, timeout: float = 30.0) -> None:
        self.base = base_url.rstrip("/")
        self.http = client or httpx.Client(timeout=timeout)

    # ---------------------------------------------------------------- info
    def system_stats(self) -> dict:
        r = self.http.get(f"{self.base}/system_stats")
        r.raise_for_status()
        return r.json()

    def reachable(self) -> bool:
        try:
            self.system_stats()
            return True
        except (httpx.HTTPError, ValueError):
            return False

    # ---------------------------------------------------------------- jobs
    def upload_image(self, path: Path, name: str | None = None) -> str:
        with path.open("rb") as fh:
            r = self.http.post(f"{self.base}/upload/image", files={"image": (name or path.name, fh, "image/png")},
                               data={"overwrite": "true"})
        if r.status_code != 200:
            raise ComfyError(f"upload failed: {r.status_code} {r.text[:200]}")
        j = r.json()
        return f"{j['subfolder']}/{j['name']}" if j.get("subfolder") else j["name"]

    def queue_prompt(self, workflow: dict, client_id: str | None = None) -> str:
        r = self.http.post(f"{self.base}/prompt", json={"prompt": workflow, "client_id": client_id or uuid.uuid4().hex})
        if r.status_code != 200:
            raise ComfyError(f"workflow rejected by ComfyUI ({r.status_code}): {r.text[:800]}")
        return r.json()["prompt_id"]

    def interrupt(self) -> None:
        try:
            self.http.post(f"{self.base}/interrupt")
        except httpx.HTTPError:
            pass

    def free_memory(self) -> None:
        try:
            self.http.post(f"{self.base}/free", json={"unload_models": True, "free_memory": True})
        except httpx.HTTPError:
            pass

    def wait(self, prompt_id: str, *, timeout: float = 1800.0, poll: float = 1.0,
             should_cancel: Callable[[], bool] | None = None) -> dict:
        start = time.monotonic()
        while True:
            if should_cancel and should_cancel():
                self.interrupt()
                raise ComfyCancelled("cancelled")
            r = self.http.get(f"{self.base}/history/{prompt_id}")
            r.raise_for_status()
            entry = r.json().get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error" or status.get("completed") is False and status.get("status_str") != "success":
                    msgs = [m for m in status.get("messages", []) if m and m[0] == "execution_error"]
                    detail = msgs[-1][1].get("exception_message", "") if msgs else ""
                    raise ComfyError(f"ComfyUI execution failed: {detail or status}")
                if entry.get("outputs") is not None and status.get("status_str", "success") == "success":
                    return entry
            if time.monotonic() - start > timeout:
                self.interrupt()
                raise ComfyError(f"timed out after {timeout:.0f}s waiting for ComfyUI")
            time.sleep(poll)

    @staticmethod
    def output_files(entry: dict) -> list[OutputFile]:
        files: list[OutputFile] = []
        for node, out in (entry.get("outputs") or {}).items():
            for kind, items in out.items():
                if not isinstance(items, list):
                    continue
                for it in items:
                    if isinstance(it, dict) and "filename" in it:
                        files.append(OutputFile(node, kind, it["filename"], it.get("subfolder", ""), it.get("type", "output")))
        return files

    def download(self, f: OutputFile, dest: Path) -> Path:
        with self.http.stream("GET", f"{self.base}/view", params={"filename": f.filename, "subfolder": f.subfolder, "type": f.type}) as r:
            if r.status_code != 200:
                raise ComfyError(f"could not download {f.filename}: {r.status_code}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as fh:
                for chunk in r.iter_bytes(1 << 20):
                    fh.write(chunk)
        return dest


_ = Any
