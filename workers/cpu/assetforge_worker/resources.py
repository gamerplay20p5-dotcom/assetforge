"""Capability detection and live telemetry.

Everything reported here is *detected*, never assumed. In particular:
* GPUs are listed from what the OS exposes (sysfs/lspci/xpu-smi on Linux, WMI on Windows).
* Installed AI runtimes (OpenVINO, PyTorch XPU) are reported as *installed*; the ``validated`` list stays
  empty until a benchmark/validation script (scripts/validate_intel_gpu.py, Milestone 2) has actually run a
  model on that node. No compatibility is claimed without that evidence.
"""

from __future__ import annotations

import importlib.metadata
from functools import lru_cache
import importlib.util
import json
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

import psutil
from assetforge_procedural import GENERATOR_ID

from .config import WorkerConfig

INTEL_VENDOR_ID = "0x8086"


@lru_cache(maxsize=4)
def blender_version(blender_bin: str | None) -> str | None:
    if not blender_bin:
        return None
    try:
        out = subprocess.run([blender_bin, "--version"], capture_output=True, text=True, timeout=60, check=False).stdout
        m = re.search(r"Blender\s+([0-9][0-9.]*)", out)
        return m.group(1) if m else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _run(cmd: list[str], timeout: float = 15) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _classify_intel(name: str) -> str:
    n = name.lower()
    if "arc" in n or "flex" in n or "max" in n:
        return "discrete"
    return "integrated"


def detect_gpus() -> list[dict]:
    """List GPUs visible to the OS. Fields that cannot be measured are ``None`` (never invented)."""
    gpus: list[dict] = []
    system = platform.system()
    if system == "Linux":
        xpu = shutil.which("xpu-smi")
        if xpu:  # Intel's own tool: gives memory/utilisation for Arc / Flex / Max
            try:
                data = json.loads(_run([xpu, "discovery", "-j"]) or "{}")
                for dev in data.get("device_list", []):
                    gpus.append({"vendor": "Intel", "name": dev.get("device_name", "Intel GPU"), "kind": "discrete",
                                 "vram_total_mb": None, "vram_used_mb": None, "utilization_percent": None,
                                 "temperature_c": None, "source": "xpu-smi", "pci": dev.get("pci_bdf_address")})
            except (json.JSONDecodeError, TypeError):
                pass
        if not gpus:
            lspci = shutil.which("lspci")
            names = _run([lspci, "-mm", "-d", "8086::0300"]) + _run([lspci, "-mm", "-d", "8086::0380"]) if lspci else ""
            labels = [re.findall(r'"([^"]*)"', ln) for ln in names.splitlines()]
            for card in sorted(Path("/sys/class/drm").glob("card[0-9]")):
                try:
                    if (card / "device/vendor").read_text().strip() != INTEL_VENDOR_ID:
                        continue
                except OSError:
                    continue
                label = labels[len(gpus)][2] if len(gpus) < len(labels) and len(labels[len(gpus)]) > 2 else "Intel GPU"
                gpus.append({"vendor": "Intel", "name": label, "kind": _classify_intel(label), "vram_total_mb": None,
                             "vram_used_mb": None, "utilization_percent": None, "temperature_c": None,
                             "source": "sysfs", "render_node": any(Path("/dev/dri").glob("renderD*"))})
    elif system == "Windows":
        out = _run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_VideoController | Select-Object Name,PNPDeviceID | ConvertTo-Json -Compress"], 30)
        try:
            data = json.loads(out) if out.strip() else []
            for d in data if isinstance(data, list) else [data]:
                name = d.get("Name", "")
                if "intel" in name.lower():
                    gpus.append({"vendor": "Intel", "name": name, "kind": _classify_intel(name), "vram_total_mb": None,
                                 "vram_used_mb": None, "utilization_percent": None, "temperature_c": None,
                                 "source": "wmi"})
        except (json.JSONDecodeError, AttributeError):
            pass
    return gpus


def _pkg_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def ai_runtimes() -> dict:
    """Installed (NOT validated) acceleration stacks."""
    torch_xpu = None
    if importlib.util.find_spec("torch") is not None:
        torch_xpu = _pkg_version("torch")
    return {"openvino": _pkg_version("openvino"), "optimum_intel": _pkg_version("optimum-intel"),
            "torch": torch_xpu, "intel_extension_for_pytorch": _pkg_version("intel-extension-for-pytorch"),
            "validated": []}


def capabilities(cfg: WorkerConfig, blender_bin: str | None, ai: dict | None = None, ai_models: list[dict] | None = None,
                 cpu3d: dict | None = None) -> dict:
    features = [GENERATOR_ID, "trimesh"]
    bver = blender_version(blender_bin)
    if bver:
        features += ["blender", "agent.building"]  # cloud-AI agent: the AI is reached through the API, the worker builds + renders
        scripts = Path(__file__).resolve().parents[3] / "scripts/engines"
        if (scripts / "prepare_game.py").is_file():
            features.extend(("asset.prepare", "asset.prepare-density"))
        if shutil.which("gltfpack") and (scripts / "prepare_optimized.py").is_file():
            features.append("asset.prepare-optimization")
            if shutil.which("instant-meshes"):
                features.append("asset.prepare-instant")
    vm = psutil.virtual_memory()
    gpus = detect_gpus() if cfg.kind in ("intel", "hybrid") else []
    runtimes = ai_runtimes()
    if cpu3d and cpu3d.get("features") and bver:  # post-processing needs Blender
        features += [f for f in cpu3d["features"] if f not in features]
    if ai and ai.get("enabled"):
        features += ai["features"]
        runtimes["validated"] = ai.get("validated", [])
    return {
        "kind": cfg.kind, "features": features, "job_types": [GENERATOR_ID] + [f for f in features if f.startswith(("ai.", "agent.", "asset."))], "blender_version": bver,
        "formats": ["glb"] + (["blend", "fbx"] if bver else []),
        "os": f"{platform.system()} {platform.release()}", "python": sys.version.split()[0],
        "cpu_model": platform.processor() or platform.machine(), "cpu_cores_total": psutil.cpu_count(logical=True),
        "ram_total_mb": int(vm.total / 1024 / 1024), "gpus": gpus, "ai_runtimes": runtimes, "models": ai_models or [], "ai": ai or {"enabled": False}, "cpu3d": cpu3d or {"enabled": False},
        "schedule": {"active_hours": cfg.active_hours, "max_host_cpu_percent": cfg.max_host_cpu_percent,
                     "yield_to": cfg.yield_to},
    }


def telemetry(active_jobs: int, work_dir: str, gate_reason: str | None = None, gpus: list[dict] | None = None, cpu3d: dict | None = None) -> dict:
    vm = psutil.virtual_memory()
    temp = None
    try:
        sensors = psutil.sensors_temperatures()  # not available on every platform
        flat = [t.current for entries in sensors.values() for t in entries if t.current]
        temp = round(max(flat), 1) if flat else None
    except (AttributeError, OSError):
        temp = None
    try:
        free_gb = round(shutil.disk_usage(work_dir).free / 1e9, 1)
    except OSError:
        free_gb = None
    return {
        "cpu_percent": psutil.cpu_percent(interval=None), "ram_used_mb": int(vm.used / 1024 / 1024),
        "ram_total_mb": int(vm.total / 1024 / 1024), "temperature_c": temp, "work_disk_free_gb": free_gb,
        "active_jobs": active_jobs, "gpus": gpus or [], "gate": gate_reason, "cpu3d": cpu3d or {},
    }
