"""Local hardware observations used by the adaptive NVIDIA workers."""

import csv
import os
import shutil
import subprocess
import time
from pathlib import Path

import psutil


CPP_WEIGHTS = {
    "trellis2-gguf": "trellis2-q8",
    "pixal3d-sv": "pixal3d-sv-q8",
    "pixal3d-mv": "pixal3d-mv-q8",
}


def sample() -> dict:
    memory = psutil.virtual_memory()
    report = {"ram_available_mb": memory.available // 2**20, "ram_total_mb": memory.total // 2**20}
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free,temperature.gpu,utilization.gpu",
             "--format=csv,noheader,nounits"], check=True, capture_output=True, text=True, timeout=4,
        )
        rows = list(csv.reader(proc.stdout.splitlines(), skipinitialspace=True))
        if len(rows) != 1:
            return report
        name, total, free, temp, util = rows[0]
    except (OSError, ValueError, subprocess.SubprocessError):
        return report
    return {**report, "name": name, "unified": "GB10" in name and not total.strip().isdigit(),
            **{k: int(v) if v.strip().isdigit() else None for k, v in
               (("vram_total_mb", total), ("vram_free_mb", free), ("temperature_c", temp), ("utilization_percent", util))}}


def features(work_dir: Path) -> list[str]:
    if not sample().get("name"):
        return []
    root = Path(os.environ.get("ASSETFORGE_ENGINE_MODELS", "/models"))
    names = [name for name, weights in CPP_WEIGHTS.items() if next((root / weights).glob("*.gguf"), None)]
    if not shutil.which("trellis-cli"):
        names.clear()
    marker = work_dir / ".pixal3d-python-heartbeat"
    try:
        if time.time() - marker.stat().st_mtime < 20:
            names.append("pixal3d-python")
    except FileNotFoundError:
        pass
    features = [f"engine.{name}" for name in names]
    if names:
        features.append("engine.archive-inputs")
    try:
        if time.time() - (work_dir / ".zimage-heartbeat").stat().st_mtime < 20:
            features.append("engine.text-reference")
    except FileNotFoundError:
        pass
    if shutil.which("trellis-cli") and (root / CPP_WEIGHTS["trellis2-gguf"] / "birefnet.gguf").is_file():
        features.append("engine.reference-prep")
    return features
