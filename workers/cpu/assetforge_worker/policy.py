"""Lease gate: decides whether this node may START new work right now.

The servers also host other projects (e.g. AI Stream Clipper). AssetForge therefore only takes jobs when
all of these allow it:
* the current time is inside the configured active hours (idle windows, e.g. nights),
* the host CPU is not busier than ``max_host_cpu_percent`` (rolling average),
* none of the ``yield_to`` processes (name/cmdline substrings) is running.
Jobs already running are never killed by the gate; it only stops new leases.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, time


def parse_active_hours(spec: str) -> list[tuple[time, time]]:
    """'22:00-07:00,12:00-13:30' -> windows. Empty string = always active. Windows may cross midnight."""
    windows: list[tuple[time, time]] = []
    for part in filter(None, (p.strip() for p in spec.split(","))):
        try:
            a, b = part.split("-")
            windows.append((time.fromisoformat(a.strip()), time.fromisoformat(b.strip())))
        except ValueError as exc:
            raise ValueError(f"invalid active-hours window {part!r} (expected HH:MM-HH:MM)") from exc
    return windows


def in_active_hours(windows: list[tuple[time, time]], now: datetime) -> bool:
    if not windows:
        return True
    t = now.time()
    for start, end in windows:
        if start <= end:
            if start <= t < end:
                return True
        elif t >= start or t < end:  # crosses midnight
            return True
    return False


def find_yield_process(patterns: Iterable[str], processes: Iterable[str]) -> str | None:
    """Return the first pattern that matches a running process name/cmdline (case-insensitive)."""
    lowered = [p.lower() for p in processes]
    for pat in patterns:
        p = pat.strip().lower()
        if p and any(p in proc for proc in lowered):
            return pat.strip()
    return None


def lease_gate(*, windows: list[tuple[time, time]], now: datetime, max_host_cpu_percent: float,
               host_cpu_avg: float | None, yield_patterns: list[str], running_processes: Iterable[str]) -> str | None:
    """Return None when leasing is allowed, otherwise a human-readable reason."""
    if not in_active_hours(windows, now):
        return "fora da janela de processamento configurada"
    if max_host_cpu_percent > 0 and host_cpu_avg is not None and host_cpu_avg > max_host_cpu_percent:
        return f"host ocupado (CPU {host_cpu_avg:.0f}% > limite {max_host_cpu_percent:.0f}%)"
    hit = find_yield_process(yield_patterns, running_processes) if yield_patterns else None
    if hit:
        return f"cedendo recursos ao processo '{hit}'"
    return None
