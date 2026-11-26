#!/usr/bin/env python3
"""Hardware/capability diagnostic for an AssetForge node. Read-only: it changes nothing on the host.

    python scripts/diagnose_hardware.py            # human readable
    python scripts/diagnose_hardware.py --json     # machine readable (attach to support requests)

It reports what is DETECTED (CPU, RAM, disk, Intel GPUs visible to the OS, Blender, OpenVINO/PyTorch presence).
Detecting a GPU or a library is NOT a compatibility claim - see scripts/validate_intel_gpu.py and docs/HARDWARE_COMPATIBILITY.md.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for d in ("workers/cpu", "generators/procedural", "generators/intel_ai", "generators/mesh", "pipeline/export", "pipeline/validation", "pipeline/optimization", "packages/asset-contract"):
    sys.path.insert(0, str(ROOT / d))

import psutil  # noqa: E402
from assetforge_export.pipeline import find_blender  # noqa: E402
from assetforge_worker.resources import ai_runtimes, blender_version, detect_gpus  # noqa: E402


def collect() -> dict:
    vm = psutil.virtual_memory()
    freq = psutil.cpu_freq()
    blender = find_blender()
    disk = shutil.disk_usage(ROOT)
    report = {
        "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "python": sys.version.split()[0],
        "cpu": {"model": platform.processor() or "unknown", "logical_cores": psutil.cpu_count(logical=True),
                "physical_cores": psutil.cpu_count(logical=False), "max_mhz": round(freq.max) if freq else None,
                "load_percent": psutil.cpu_percent(interval=1.0)},
        "ram_mb": {"total": int(vm.total / 2**20), "available": int(vm.available / 2**20)},
        "disk_gb": {"total": round(disk.total / 1e9, 1), "free": round(disk.free / 1e9, 1)},
        "gpus": detect_gpus(),
        "dri_render_nodes": sorted(p.name for p in Path("/dev/dri").glob("renderD*")) if Path("/dev/dri").exists() else [],
        "blender": {"path": blender, "version": blender_version(blender)},
        "ai_runtimes_installed": ai_runtimes(),
        "docker": shutil.which("docker") is not None,
        "recommended_limits": {"cpu_cores": max(1, (psutil.cpu_count(logical=True) or 2) // 2),
                               "ram_mb": max(1024, int(vm.total / 2**20) // 2)},
    }
    try:
        import openvino as ov  # type: ignore[import-not-found]

        report["openvino_devices_visible"] = list(ov.Core().available_devices)
    except Exception as exc:  # noqa: BLE001
        report["openvino_devices_visible"] = f"unavailable ({type(exc).__name__})"
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    r = collect()
    if args.json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return 0
    print(f"OS            : {r['os']}")
    print(f"CPU           : {r['cpu']['model']} - {r['cpu']['logical_cores']} threads ({r['cpu']['physical_cores']} cores), load {r['cpu']['load_percent']}%")
    print(f"RAM           : {r['ram_mb']['total']} MB total / {r['ram_mb']['available']} MB available")
    print(f"Disk (repo)   : {r['disk_gb']['free']} GB free of {r['disk_gb']['total']} GB")
    if r["gpus"]:
        for g in r["gpus"]:
            print(f"GPU           : {g['vendor']} {g['name']} ({g['kind']}, via {g['source']}) - VRAM/util not measured")
    else:
        print("GPU           : none detected")
    print(f"DRI nodes     : {', '.join(r['dri_render_nodes']) or 'none'}")
    print(f"Blender       : {r['blender']['version'] or 'not found'} {r['blender']['path'] or ''}")
    rt = r["ai_runtimes_installed"]
    print(f"OpenVINO      : {rt['openvino'] or 'not installed'}   devices: {r['openvino_devices_visible']}")
    print(f"PyTorch       : {rt['torch'] or 'not installed'}   IPEX: {rt['intel_extension_for_pytorch'] or 'not installed'}")
    print(f"Docker        : {'found' if r['docker'] else 'not found'}")
    print(f"Suggested worker limits (half of the machine): {r['recommended_limits']}")
    print("\nNOTE: detection is not validation. No GPU/AI compatibility is claimed until validate_intel_gpu.py + a benchmark pass.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
