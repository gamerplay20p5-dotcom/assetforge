"""VRAM monitoring from ComfyUI's own device stats (real values reported by torch XPU)."""

from __future__ import annotations

import threading

from .comfy_client import ComfyClient, parse_devices


class VramMonitor:
    """Samples VRAM use while a generation runs and keeps the peak (for scheduling data and benchmarks)."""

    def __init__(self, client: ComfyClient, interval: float = 1.0) -> None:
        self.client, self.interval = client, interval
        self.peak_used_mb: int | None = None
        self.total_mb: int | None = None
        self.samples = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample(self) -> None:
        try:
            gpus = parse_devices(self.client.system_stats())
        except Exception:  # noqa: BLE001 - monitoring must never break a job
            return
        gpus = [g for g in gpus if g["backend"] in ("xpu", "cuda") and g["vram_used_mb"] is not None] or [g for g in gpus if g["vram_used_mb"] is not None]
        if not gpus:
            return
        g = gpus[0]
        self.samples += 1
        self.total_mb = g["vram_total_mb"]
        self.peak_used_mb = max(self.peak_used_mb or 0, g["vram_used_mb"])

    def _run(self) -> None:
        while not self._stop.is_set():
            self._sample()
            self._stop.wait(self.interval)

    def __enter__(self) -> VramMonitor:
        self._sample()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._sample()
