"""Child process entry point: runs ONE job in an isolated interpreter and temp directory.

Usage: python -m assetforge_worker.run_job <workdir> [--engine auto|trimesh|blender]
Reads <workdir>/job.json, writes <workdir>/result.json and streams JSON-line events on stdout.
Exit codes: 0 success, 10 deliberate pipeline failure (do not retry), 1 unexpected error.

The job document is validated by pydantic models inside the pipeline; no code from the job or from
uploaded files is ever executed.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

from assetforge_export.pipeline import PipelineError, run_building_job


def emit(event: dict) -> None:
    print("@@WORKER " + json.dumps(event), flush=True)


def main() -> int:
    workdir = Path(sys.argv[1])
    engine = "auto"
    if "--engine" in sys.argv:
        engine = sys.argv[sys.argv.index("--engine") + 1]
    job = json.loads((workdir / "job.json").read_text(encoding="utf-8"))
    threads = int(job.get("requirements", {}).get("cpu_cores", 1))
    try:
        if job["job_type"].startswith("ai."):
            from assetforge_export.ai_pipeline import run_ai_job
            from assetforge_intel_ai import IntelAIProvider

            url = os.environ.get("ASSETFORGE_COMFYUI_URL")
            if not url:
                raise PipelineError("ASSETFORGE_COMFYUI_URL is not set on this worker")
            provider = IntelAIProvider(url, models_dir=Path(os.environ["ASSETFORGE_AI_MODELS_DIR"]) if os.environ.get("ASSETFORGE_AI_MODELS_DIR") else None)
            result = run_ai_job(job, workdir, emit, provider, blender_bin=os.environ.get("BLENDER_BIN") or None, threads=threads,
                                blender_timeout=float(os.environ.get("ASSETFORGE_BLENDER_TIMEOUT", "900")))
            (workdir / "result.json").write_text(json.dumps(result), encoding="utf-8")
            return 0
        if job["job_type"] != "procedural.building":
            raise PipelineError(f"unsupported job type {job['job_type']!r}")
        result = run_building_job(job, workdir, emit, engine=engine, threads=threads,
                                  blender_bin=os.environ.get("BLENDER_BIN") or None,
                                  blender_timeout=float(os.environ.get("ASSETFORGE_BLENDER_TIMEOUT", "900")))
        (workdir / "result.json").write_text(json.dumps(result), encoding="utf-8")
        return 0
    except PipelineError as exc:
        emit({"type": "log", "level": "error", "message": str(exc)})
        (workdir / "error.txt").write_text(str(exc), encoding="utf-8")
        return 10
    except Exception as exc:  # noqa: BLE001
        emit({"type": "log", "level": "error", "message": traceback.format_exc()[-1800:]})
        (workdir / "error.txt").write_text(f"{type(exc).__name__}: {exc}", encoding="utf-8")
        return 1


if __name__ == "__main__":
    sys.exit(main())
