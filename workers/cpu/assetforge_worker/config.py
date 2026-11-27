"""Worker configuration from environment variables (no addresses are hardcoded)."""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass, field
from pathlib import Path

import psutil


def _int(name: str, default: int) -> int:
    v = os.environ.get(name)
    return int(v) if v else default


@dataclass
class WorkerConfig:
    server_url: str
    name: str
    kind: str = "cpu"
    enrollment_token: str = ""
    state_dir: Path = Path("./worker-state")
    work_dir: Path = Path("./worker-state/jobs")
    max_jobs: int = 1
    cpu_cores: int = 2
    ram_mb: int = 4096
    blender_bin: str | None = None
    job_timeout_s: int = 1800
    poll_interval_s: float = 2.0
    engine: str = "auto"
    # --- coexistence with other services on the same host (idle-time processing) ---
    active_hours: str = ""  # "22:00-07:00" ; empty = always
    max_host_cpu_percent: float = 0.0  # 0 = disabled; otherwise do not start jobs while host CPU is above this
    yield_to: list[str] = field(default_factory=list)  # e.g. ["ai-stream-clipper"]
    low_priority: bool = True  # run the worker (and its children) at below-normal priority
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> WorkerConfig:
        server = os.environ.get("ASSETFORGE_SERVER_URL", "").rstrip("/")
        if not server:
            raise SystemExit("ASSETFORGE_SERVER_URL is required (e.g. http://central-host:8000)")
        total_cores = psutil.cpu_count(logical=True) or 2
        total_ram = int(psutil.virtual_memory().total / 1024 / 1024)
        kind = os.environ.get("ASSETFORGE_WORKER_KIND", "cpu")
        state = Path(os.environ.get("ASSETFORGE_WORKER_STATE_DIR", "./worker-state"))
        return cls(
            server_url=server,
            name=os.environ.get("ASSETFORGE_WORKER_NAME", platform.node() or "cpu-worker").replace(" ", "-"),
            kind=kind,
            enrollment_token=os.environ.get("ASSETFORGE_ENROLLMENT_TOKEN", ""),
            state_dir=state,
            work_dir=Path(os.environ.get("ASSETFORGE_WORKER_WORK_DIR", str(state / "jobs"))),
            max_jobs=_int("ASSETFORGE_WORKER_MAX_JOBS", 1),
            # Legacy CPU jobs use fixed reservations. NVIDIA admission uses live host headroom.
            cpu_cores=_int("ASSETFORGE_WORKER_CPU_CORES", max(1, total_cores // 2)),
            ram_mb=_int("ASSETFORGE_WORKER_RAM_MB", total_ram if kind == "nvidia" else max(1024, total_ram // 2)),
            blender_bin=os.environ.get("BLENDER_BIN") or None,
            job_timeout_s=_int("ASSETFORGE_WORKER_JOB_TIMEOUT", 1800),
            poll_interval_s=float(os.environ.get("ASSETFORGE_WORKER_POLL_SECONDS", "2")),
            engine=os.environ.get("ASSETFORGE_WORKER_ENGINE", "auto"),
            active_hours=os.environ.get("ASSETFORGE_WORKER_ACTIVE_HOURS", ""),
            max_host_cpu_percent=float(os.environ.get("ASSETFORGE_WORKER_MAX_HOST_CPU_PERCENT", "0")),
            yield_to=[x.strip() for x in os.environ.get("ASSETFORGE_WORKER_YIELD_TO", "").split(",") if x.strip()],
            low_priority=os.environ.get("ASSETFORGE_WORKER_LOW_PRIORITY", "1") not in ("0", "false", "no"),
        )
