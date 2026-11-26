"""Host resource sampler used by benchmarks/validation: peak RAM, CPU and the hottest temperature the kernel exposes (hwmon)."""

from __future__ import annotations

import threading

import psutil


class HostSampler:
    def __init__(self, interval: float = 2.0) -> None:
        self.interval = interval
        self.peak_ram_mb = 0
        self.peak_cpu = 0.0
        self.peak_temp_c: float | None = None  # hottest CPU sensor (k10temp/coretemp/zenpower)
        self.peak_temps: dict[str, float] = {}  # per-sensor peaks, e.g. {'k10temp:Tctl': 95.0, 'nvme:Composite': 41.9}
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
                for chip, entries in psutil.sensors_temperatures().items():
                    for t in entries:
                        if not t.current:
                            continue
                        key = f"{chip}:{t.label or 'temp'}"
                        self.peak_temps[key] = round(max(self.peak_temps.get(key, 0.0), t.current), 1)
                        if chip in ("k10temp", "coretemp", "zenpower", "cpu_thermal"):
                            self.peak_temp_c = max(self.peak_temp_c or 0.0, t.current)
            except (AttributeError, OSError):
                pass
            self._stop.wait(self.interval)

    def __enter__(self) -> HostSampler:
        self._t.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._t.join(timeout=5)
