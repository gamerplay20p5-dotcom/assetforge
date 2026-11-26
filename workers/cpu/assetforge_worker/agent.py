"""Worker agent: register, heartbeat, lease, execute in an isolated subprocess, upload, complete."""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import signal
import sys
import tempfile
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import psutil
from assetforge_export.ai_pipeline import plan_for
from assetforge_export.pipeline import find_blender
from assetforge_export.proc import JobCancelled, SubprocessFailed, SubprocessTimeout, run_supervised

from .ai import AiRuntime, Cpu3dRuntime
from .client import AuthFailed, LeaseLost, ServerClient
from .config import WorkerConfig
from .policy import lease_gate, parse_active_hours
from .resources import capabilities, detect_gpus, telemetry

log = logging.getLogger("assetforge.worker")
WORKER_VERSION = "0.1.0"


class Agent:
    def __init__(self, cfg: WorkerConfig) -> None:
        self.cfg = cfg
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        cfg.work_dir.mkdir(parents=True, exist_ok=True)
        self.blender = cfg.blender_bin or find_blender()
        self.client = ServerClient(cfg.server_url)
        self.stop = threading.Event()
        self.state = "enabled"
        self.queue_paused = False
        self._lock = threading.Lock()
        self.active: dict[str, threading.Event] = {}  # job_id -> cancel flag
        self.pool = ThreadPoolExecutor(max_workers=max(1, cfg.max_jobs), thread_name_prefix="job")
        self.heartbeat_seconds = 10
        self.windows = parse_active_hours(cfg.active_hours)
        self.cpu_samples: deque[float] = deque(maxlen=6)
        self.gate_reason: str | None = None
        self.gpus = detect_gpus() if cfg.kind in ("intel", "hybrid") else []
        self.ai = AiRuntime(cfg.state_dir)
        self.cpu3d = Cpu3dRuntime()
        if cfg.low_priority:  # children inherit: keep other services on this host responsive
            try:
                psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 10)
            except (psutil.Error, OSError, AttributeError):
                log.warning("could not lower process priority")

    def _caps(self) -> dict:
        ai = self.ai.status()
        return capabilities(self.cfg, self.blender, ai, self.ai.model_rows() if ai.get("enabled") else None, self.cpu3d.status())

    def _gate(self) -> str | None:
        self.cpu_samples.append(psutil.cpu_percent(interval=None))
        avg = sum(self.cpu_samples) / len(self.cpu_samples) if len(self.cpu_samples) >= 3 else None
        procs: list[str] = []
        if self.cfg.yield_to:
            for p in psutil.process_iter(["name", "cmdline"]):
                try:
                    procs.append(f"{p.info['name'] or ''} {' '.join(p.info['cmdline'] or [])}")
                except (psutil.Error, TypeError):
                    continue
        # The worker's own running jobs must not make the host look "busy": only gate when idle of our own work.
        with self._lock:
            own = len(self.active)
        return lease_gate(windows=self.windows, now=datetime.now(), max_host_cpu_percent=self.cfg.max_host_cpu_percent if not own else 0.0,
                          host_cpu_avg=avg, yield_patterns=self.cfg.yield_to, running_processes=procs)

    # ------------------------------------------------------------------ registration
    def _state_file(self) -> Path:
        return self.cfg.state_dir / "worker.json"

    def ensure_registered(self) -> None:
        sf = self._state_file()
        if sf.is_file():
            saved = json.loads(sf.read_text(encoding="utf-8"))
            if saved.get("server_url") == self.cfg.server_url and saved.get("name") == self.cfg.name:
                self.client.token = saved["token"]
                self.heartbeat_seconds = saved.get("heartbeat_seconds", 10)
                log.info("using saved credentials for worker %s (%s)", self.cfg.name, saved["worker_id"])
                return
        if not self.cfg.enrollment_token:
            raise SystemExit("no saved credentials and ASSETFORGE_ENROLLMENT_TOKEN is not set")
        payload = {
            "enrollment_token": self.cfg.enrollment_token, "name": self.cfg.name, "kind": self.cfg.kind,
            "hostname": platform.node() or self.cfg.name,
            "version": WORKER_VERSION, "capabilities": self._caps(),
            "limits": {"max_concurrent_jobs": self.cfg.max_jobs, "cpu_cores": self.cfg.cpu_cores,
                       "ram_mb": self.cfg.ram_mb, **({"vram_mb": v} if (v := self.ai.vram_limit_mb()) else {})},
        }
        data = self.client.register(payload)
        self.client.token = data["token"]
        self.heartbeat_seconds = data["heartbeat_seconds"]
        sf.write_text(json.dumps({"server_url": self.cfg.server_url, "name": self.cfg.name, "worker_id": data["worker_id"],
                                  "token": data["token"], "heartbeat_seconds": data["heartbeat_seconds"]}), encoding="utf-8")
        try:
            os.chmod(sf, 0o600)
        except OSError:
            pass
        log.info("registered as %s (%s)", self.cfg.name, data["worker_id"])

    # ------------------------------------------------------------------ heartbeat
    def heartbeat_loop(self) -> None:
        caps_sent = False
        beat = 0
        while not self.stop.is_set():
            try:
                with self._lock:
                    ids = list(self.active)
                body = {"telemetry": telemetry(len(ids), str(self.cfg.work_dir), self.gate_reason, self.ai.gpus() or self.gpus, self.cpu3d.telemetry()), "active_jobs": ids}
                beat += 1
                if not caps_sent or beat % 6 == 0:  # re-publish: ComfyUI/models may come up or change
                    body["capabilities"] = self._caps()
                resp = self.client.heartbeat(body)
                caps_sent = True
                self.state = resp["state"]
                self.queue_paused = resp["queue_paused"]
                with self._lock:
                    for jid in resp.get("cancel", []) + resp.get("lost", []):
                        if jid in self.active:
                            log.warning("job %s cancelled/lost according to server", jid)
                            self.active[jid].set()
            except AuthFailed:
                log.error("server rejected our token (worker deleted or credentials rotated); exiting")
                self.stop.set()
                os._exit(3)
            except Exception as exc:  # noqa: BLE001
                log.warning("heartbeat failed: %s", exc)
            self.stop.wait(self.heartbeat_seconds)

    # ------------------------------------------------------------------ main loop
    def run(self) -> None:
        self.ensure_registered()
        threading.Thread(target=self.heartbeat_loop, daemon=True, name="heartbeat").start()
        log.info("worker up: blender=%s max_jobs=%s cpu=%s ram=%sMB", self.blender or "none", self.cfg.max_jobs,
                 self.cfg.cpu_cores, self.cfg.ram_mb)
        while not self.stop.is_set():
            with self._lock:
                free = self.cfg.max_jobs - len(self.active)
            self.gate_reason = self._gate()
            if free > 0 and self.state == "enabled" and not self.queue_paused and self.gate_reason is None:
                try:
                    leased = self.client.lease()
                except AuthFailed:
                    log.error("token rejected; exiting")
                    return
                except Exception as exc:  # noqa: BLE001
                    log.warning("lease request failed: %s", exc)
                    leased = None
                if leased:
                    flag = threading.Event()
                    with self._lock:
                        self.active[leased["job_id"]] = flag
                    self.pool.submit(self.execute, leased, flag)
                    continue
            self.stop.wait(self.cfg.poll_interval_s)
        self.pool.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------ one job
    def execute(self, leased: dict, cancel: threading.Event) -> None:
        job_id, token = leased["job_id"], leased["lease_token"]
        job = leased["job"]
        workdir = Path(tempfile.mkdtemp(prefix=f"{job_id}-", dir=self.cfg.work_dir))
        buf: list[dict] = []
        buf_lock = threading.Lock()
        done = threading.Event()
        plan = [{"name": n, "weight": w} for n, w in plan_for(job["job_type"])]

        def flush(first: bool = False) -> None:
            with buf_lock:
                batch, buf[:] = list(buf), []
            if not batch and not first:
                return
            try:
                resp = self.client.events(job_id, token, batch, plan=plan if first else None)
                if resp.get("cancel_requested"):
                    cancel.set()
            except LeaseLost:
                cancel.set()
            except Exception as exc:  # noqa: BLE001
                log.warning("could not send events for %s: %s", job_id, exc)
                with buf_lock:
                    buf[:0] = batch  # keep for the next flush

        def flusher() -> None:
            while not done.wait(1.0):
                flush()

        def on_line(line: str) -> None:
            if line.startswith("@@WORKER "):
                ev = json.loads(line[9:])
                with buf_lock:
                    buf.append(ev if ev["type"] != "stage" else {k: ev[k] for k in ("type", "name", "status", "detail") if k in ev})
            elif line.strip():
                with buf_lock:
                    buf.append({"type": "log", "level": "debug", "message": line[:1000]})

        try:
            flush(first=True)
            if job["job_type"].startswith("ai.") and job["requirements"].get("vram_mb", 0) > 0:
                need = job["requirements"].get("vram_mb", 0)
                free = self.ai.free_vram_mb()
                if free is not None and free < need * 0.9:  # protect other GPU users (e.g. AI Stream Clipper)
                    self._report_failure(job_id, token, f"VRAM livre insuficiente: {free} MB < {need} MB necessários "
                                         "(outro processo está usando a GPU?)", True)
                    return
            ref_id = job["params"].get("reference_id")
            if job["job_type"].startswith("ai.") and ref_id:
                self.client.download_reference(ref_id, workdir / "reference.png")
                job = {**job, "reference_path": str(workdir / "reference.png")}
            (workdir / "job.json").write_text(json.dumps(job), encoding="utf-8")
            threading.Thread(target=flusher, daemon=True).start()
            log.info("job %s started: %s", job_id, job["name"])
            cmd = [sys.executable, "-m", "assetforge_worker.run_job", str(workdir), "--engine", self.cfg.engine]
            env = {**os.environ, "PYTHONUNBUFFERED": "1", "OMP_NUM_THREADS": str(job["requirements"].get("cpu_cores", 1))}
            if self.blender:
                env["BLENDER_BIN"] = self.blender
            retryable, error = True, None
            try:
                run_supervised(cmd, timeout=self.cfg.job_timeout_s, on_line=on_line, should_cancel=cancel.is_set,
                               cwd=workdir, env=env)
            except JobCancelled:
                if job["job_type"].startswith("ai."):
                    if job["params"].get("provider") in ("sf3d", "triposr"):
                        self.cpu3d.cancel(job_id)  # stop the CPU work inside the provider container
                    elif self.ai.enabled:
                        self.ai.provider().client.interrupt()  # stop the GPU work too, not only our subprocess
                done.set()
                flush()
                log.info("job %s cancelled", job_id)
                try:
                    self.client.cancelled(job_id, token)
                except LeaseLost:
                    pass
                return
            except SubprocessTimeout as exc:
                error = f"job timed out: {exc}"
            except SubprocessFailed as exc:
                err_file = workdir / "error.txt"
                error = err_file.read_text(encoding="utf-8") if err_file.is_file() else str(exc)
                retryable = exc.code != 10  # deliberate validation failures are deterministic
            done.set()
            flush()
            if error:
                log.error("job %s failed: %s", job_id, error[:300])
                self._report_failure(job_id, token, error, retryable)
                return
            result = json.loads((workdir / "result.json").read_text(encoding="utf-8"))
            for f in result["files"]:
                self.client.upload(job_id, token, f["name"], workdir / "out" / f["name"])
            resp = self.client.complete(job_id, token, result)
            log.info("job %s completed -> asset %s v%s", job_id, resp.get("asset_id"), resp.get("version"))
        except LeaseLost as exc:
            log.warning("job %s: lease lost (%s); discarding results", job_id, str(exc)[:120])
        except Exception as exc:  # noqa: BLE001
            log.exception("job %s crashed in the agent", job_id)
            self._report_failure(job_id, token, f"agent error: {type(exc).__name__}: {exc}", True)
        finally:
            done.set()
            with self._lock:
                self.active.pop(job_id, None)
            shutil.rmtree(workdir, ignore_errors=True)

    def _report_failure(self, job_id: str, token: str, error: str, retryable: bool) -> None:
        try:
            self.client.fail(job_id, token, error, retryable)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not report failure of %s: %s", job_id, exc)


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    agent = Agent(WorkerConfig.from_env())
    signal.signal(signal.SIGINT, lambda *_: agent.stop.set())
    try:
        signal.signal(signal.SIGTERM, lambda *_: agent.stop.set())
    except (AttributeError, ValueError):
        pass
    agent.run()


if __name__ == "__main__":
    main()
