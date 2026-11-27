"""Run pinned Pixal3D Python in its own container, through a shared job volume."""

from contextlib import suppress
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def respond(work: Path, code: int) -> None:
    temporary = work / "python.response.tmp"
    with suppress(FileNotFoundError):
        temporary.write_text(json.dumps({"exit_code": code}), encoding="utf-8")
        temporary.replace(work / "python.response.json")


def main() -> None:
    root = Path(os.environ.get("ASSETFORGE_WORKER_WORK_DIR", "/state/jobs"))
    root.mkdir(parents=True, exist_ok=True)
    marker = root / ".pixal3d-python-heartbeat"
    runner = Path(__file__).with_name("pixal3d_python.py").resolve()
    models = Path(os.environ.get("PIXAL3D_MODELS", "/python-models"))
    dino = Path(os.environ.get("PIXAL3D_DINOV3", "/dino"))
    dino_checkpoint = (dino / "model.safetensors", dino / "model.safetensors.index.json")
    if (not os.access(models / "pipeline_mv.json", os.R_OK)
            or not os.access(dino / "config.json", os.R_OK)
            or not any(os.access(file, os.R_OK) for file in dino_checkpoint)):
        raise SystemExit("Pixal3D Python model files are unavailable")
    processes: dict[Path, subprocess.Popen] = {}
    try:
        while True:
            marker.touch()
            for work, process in list(processes.items()):
                if not work.is_dir() or (work / "python.cancel").exists():
                    if process.poll() is None:
                        with suppress(ProcessLookupError):
                            os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    del processes[work]
                elif (code := process.poll()) is not None:
                    respond(work, code)
                    del processes[work]
            for request in root.glob("job_*/python.request.json"):
                work = request.parent
                if work.is_symlink() or request.is_symlink() or work in processes or (work / "python.cancel").exists():
                    continue
                claimed = request.with_name("python.claimed.json")
                try:
                    request.rename(claimed)
                    params = json.loads(claimed.read_text(encoding="utf-8"))
                    if params["engine"] != "pixal3d-python":
                        raise ValueError("wrong engine")
                    with (work / "engine.log").open("wb") as log:
                        cmd = [sys.executable, str(runner), "generate", "--views", str(work / "views"),
                               "--models", str(models), "--dinov3", str(dino), "--output", str(work / "out/model.glb")]
                        for name in ("resolution", "max_tokens", "texture_size", "seed", "structure_guidance", "shape_guidance"):
                            if params[name] is not None:
                                cmd += [f"--{name.replace('_', '-')}", str(params[name])]
                        if params.get("skip_decimation"):
                            cmd.append("--skip-decimation")
                        processes[work] = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                except (OSError, ValueError, KeyError) as exc:
                    with suppress(FileNotFoundError):
                        (work / "engine.log").write_text(str(exc), encoding="utf-8")
                    respond(work, 1)
            time.sleep(1)
    finally:
        marker.unlink(missing_ok=True)
        for process in processes.values():
            if process.poll() is None:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
            process.wait()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    main()
