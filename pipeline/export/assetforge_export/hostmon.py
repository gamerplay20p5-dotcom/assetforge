"""Host resource sampler used by benchmarks/validation: peak RAM, CPU and the hottest temperature the kernel exposes (hwmon)."""

from __future__ import annotations

import threading

import psutil


class HostSampler:
    def __init__(self, interval: float = 2.0) -> None:
        self.interval = interval
        self.peak_ram_mb = 0
        self.peak_cpu = 0.0
        self.peak_temp_c: float | None = None
        self.samples = 0
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        psutil.cpu_percent(interval=None)
        while not self._stop.is_set():
            self.samples += 1
            self.peak_ram_mb = max(self.peak_ram_mb, int(psutil.virtual_memory().used / 2**20))
            self.peak_cpu = max(self.peak_cpu, psutil.cpu_percent(interval=None))
            try:
                temps = [t.current for entries in psutil.sensors_temperatures().values() for t in entries if t.current]
                if temps:
                    self.peak_temp_c = max(self.peak_temp_c or 0.0, max(temps))
            except (AttributeError, OSError):
                pass
            self._stop.wait(self.interval)

    def __enter__(self) -> HostSampler:
        self._t.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._t.join(timeout=5)
