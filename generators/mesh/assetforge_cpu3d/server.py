"""CPU image-to-3D provider service (one per container). Standard library HTTP server, no framework dependencies so it can't
conflict with the pinned dependencies of Stable Fast 3D / TripoSR.

Each job runs the official CLI in its own subprocess/process group: cancellable, killable on timeout, CPU/RAM measured.
Internal network only (no authentication): never publish its port.

Env: PROVIDER_NAME (sf3d|triposr)  PROVIDER_PORT=8080  PROVIDER_THREADS  PROVIDER_CONCURRENCY=1  PROVIDER_JOB_TIMEOUT=3600
     HF_HOME=/models/hf  PROVIDER_WORK_DIR=/work  PROVIDER_CMD_OVERRIDE (tests)
"""

from __future__ import annotations

import collections
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psutil

from . import adapters
from .registry import PROVIDERS

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"RIFF")  # PNG, JPEG, WEBP(RIFF)


class Job:
    def __init__(self, params: dict, tag: str) -> None:
        self.id = "c3d_" + uuid.uuid4().hex[:12]
        self.params, self.tag = params, tag
        self.status = "queued"
        self.created = time.time()
        self.started: float | None = None
        self.finished: float | None = None
        self.error: str | None = None
        self.log: collections.deque[str] = collections.deque(maxlen=400)
        self.cancel = threading.Event()
        self.proc: subprocess.Popen | None = None
        self.result: Path | None = None
        self.info: dict = {}
        self.metrics = {"peak_rss_mb": 0, "peak_cpu_percent": 0.0, "seconds": None, "attempts": 0}

    def public(self) -> dict:
        return {"id": self.id, "status": self.status, "tag": self.tag, "error": self.error, "created": self.created, "started": self.started,
                "finished": self.finished, "metrics": self.metrics, "info": self.info, "log_tail": list(self.log)[-25:]}


class Service:
    def __init__(self, provider: str, work_dir: Path, hf_home: Path, threads: int, concurrency: int, timeout: float) -> None:
        if provider not in PROVIDERS:
            raise SystemExit(f"unknown provider {provider!r}")
        self.provider, self.work, self.hf_home = provider, Path(work_dir), Path(hf_home)
        self.threads, self.timeout = threads, timeout
        self.sem = threading.BoundedSemaphore(concurrency)
        self.concurrency = concurrency
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self.work.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ jobs
    def submit(self, image: bytes, params: dict, tag: str = "") -> Job:
        if len(image) > MAX_IMAGE_BYTES or not image.startswith(MAGIC):
            raise ValueError("body must be a PNG/JPEG/WEBP image up to 20 MB")
        clean = adapters.validate_params(self.provider, params)
        ok, why = adapters.weights_ready(self.provider, self.hf_home)
        if not ok and "PROVIDER_CMD_OVERRIDE" not in os.environ:
            raise RuntimeError(why)
        job = Job(clean, tag)
        d = self.work / job.id
        d.mkdir(parents=True)
        (d / "input").write_bytes(image)
        with self.lock:
            self._gc()
            self.jobs[job.id] = job
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def _gc(self) -> None:
        done = sorted((j for j in self.jobs.values() if j.finished), key=lambda j: j.finished)  # type: ignore[arg-type,return-value]
        for j in done[:-10] + [j for j in done if time.time() - (j.finished or 0) > 3600]:
            shutil.rmtree(self.work / j.id, ignore_errors=True)
            self.jobs.pop(j.id, None)

    def cancel_job(self, job: Job) -> None:
        job.cancel.set()
        self._kill(job)
        if job.status == "queued":
            job.status, job.finished = "cancelled", time.time()

    @staticmethod
    def _kill(job: Job) -> None:
        p = job.proc
        if p and p.poll() is None:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, AttributeError):
                p.kill()

    def _sample(self, job: Job, proc: subprocess.Popen, stop: threading.Event) -> None:
        try:
            root = psutil.Process(proc.pid)
        except psutil.Error:
            return
        while not stop.wait(0.5):
            try:
                procs = [root, *root.children(recursive=True)]
                rss = sum(p.memory_info().rss for p in procs) / 2**20
                cpu = sum(p.cpu_percent(interval=None) for p in procs)
                job.metrics["peak_rss_mb"] = max(job.metrics["peak_rss_mb"], int(rss))
                job.metrics["peak_cpu_percent"] = max(job.metrics["peak_cpu_percent"], round(cpu, 1))
            except psutil.Error:
                continue

    def _exec(self, job: Job, cmd: list[str], extra_env: dict[str, str], out: Path) -> int:
        env = {**os.environ, **extra_env, "OMP_NUM_THREADS": str(self.threads), "MKL_NUM_THREADS": str(self.threads),
               "OPENBLAS_NUM_THREADS": str(self.threads), "PYTHONUNBUFFERED": "1", "HF_HOME": str(self.hf_home)}
        override = os.environ.get("PROVIDER_CMD_OVERRIDE")  # tests: a stub that writes the expected output files
        if override:
            cmd = [sys.executable, override, str(self.work / job.id / "input"), str(out)]
        job.metrics["attempts"] += 1
        job.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env, start_new_session=True,
                                    cwd=str(self.work / job.id))
        stop = threading.Event()
        threading.Thread(target=self._sample, args=(job, job.proc, stop), daemon=True).start()
        killer = threading.Timer(self.timeout, lambda: (job.log.append(f"TIMEOUT after {self.timeout:.0f}s: killing"), job.info.setdefault("timeout", True), self._kill(job)))
        killer.start()
        try:
            assert job.proc.stdout is not None
            for line in job.proc.stdout:
                job.log.append(line.rstrip()[:300])
            return job.proc.wait()
        finally:
            killer.cancel()
            stop.set()

    def _run(self, job: Job) -> None:
        d = self.work / job.id
        out = d / "out"
        with self.sem:
            if job.cancel.is_set():
                return
            job.status, job.started = "running", time.time()
            try:
                cmd, env = adapters.build_command(self.provider, d / "input", out, job.params)
                code = self._exec(job, cmd, env, out)
                if code != 0 and not job.cancel.is_set() and adapters.can_fallback(self.provider, job.params):
                    job.info["bake_error"] = " | ".join(list(job.log)[-6:])[:900]
                    job.log.append("texture bake failed; retrying with vertex colors")
                    shutil.rmtree(out, ignore_errors=True)
                    cmd, env = adapters.build_command(self.provider, d / "input", out, job.params, bake=False)
                    code = self._exec(job, cmd, env, out)
                    job.info["bake_fallback"] = True
                if job.cancel.is_set():
                    job.status = "cancelled"
                elif code != 0:
                    raise RuntimeError("timed out" if job.info.get("timeout") else f"provider exited with code {code}")
                else:
                    dest = d / "result.glb"
                    job.info.update(adapters.collect_result(self.provider, out, dest))
                    job.result, job.status = dest, "succeeded"
            except Exception as exc:  # noqa: BLE001
                job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"
            finally:
                job.finished = time.time()
                job.metrics["seconds"] = round(job.finished - (job.started or job.finished), 1)
                shutil.rmtree(out, ignore_errors=True)

    # ------------------------------------------------------------------ info
    def health(self) -> dict:
        ok, why = adapters.weights_ready(self.provider, self.hf_home)
        spec = PROVIDERS[self.provider]
        return {"provider": self.provider, "title": spec.title, "ready": ok or "PROVIDER_CMD_OVERRIDE" in os.environ, "reason": why,
                "threads": self.threads, "concurrency": self.concurrency,
                "active_jobs": sum(1 for j in self.jobs.values() if j.status in ("queued", "running")),
                "license": {"code": spec.code_license, "weights": spec.weights_license, "commercial": spec.commercial}, "upstream_commit": spec.commit}

    def stats(self) -> dict:
        vm = psutil.virtual_memory()
        cg = {}
        for name, key in (("/sys/fs/cgroup/memory.current", "container_mem_mb"), ("/sys/fs/cgroup/memory.max", "container_mem_limit_mb")):
            try:
                raw = Path(name).read_text().strip()
                cg[key] = None if raw == "max" else int(raw) // 2**20
            except OSError:
                cg[key] = None
        return {"host_cpu_percent": psutil.cpu_percent(interval=None), "host_ram_used_mb": int(vm.used / 2**20), "host_ram_total_mb": int(vm.total / 2**20), **cg}


def make_handler(svc: Service):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # noqa: ANN002
            pass

        def _send(self, code: int, obj) -> None:
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _job(self, jid: str) -> Job | None:
            return svc.jobs.get(jid)

        def do_GET(self):  # noqa: N802
            u = urlparse(self.path)
            parts = [p for p in u.path.split("/") if p]
            if parts == ["health"]:
                return self._send(200, svc.health())
            if parts == ["stats"]:
                return self._send(200, svc.stats())
            if len(parts) >= 3 and parts[:2] == ["v1", "jobs"]:
                job = self._job(parts[2])
                if not job:
                    return self._send(404, {"error": "job not found"})
                if len(parts) == 3:
                    return self._send(200, job.public())
                if parts[3] == "result":
                    if job.status != "succeeded" or not job.result or not job.result.is_file():
                        return self._send(409, {"error": f"job is {job.status}"})
                    data = job.result.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "model/gltf-binary")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    return self.wfile.write(data)
            self._send(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            u = urlparse(self.path)
            parts = [p for p in u.path.split("/") if p]
            if parts == ["v1", "jobs"]:
                n = int(self.headers.get("Content-Length", 0))
                if n > MAX_IMAGE_BYTES:
                    return self._send(413, {"error": "image too large"})
                body = self.rfile.read(n)
                q = parse_qs(u.query)
                try:
                    params = json.loads(q.get("params", ["{}"])[0])
                    job = svc.submit(body, params, tag=q.get("tag", [""])[0][:64])
                except ValueError as exc:
                    return self._send(422, {"error": str(exc)})
                except RuntimeError as exc:
                    return self._send(503, {"error": str(exc)})
                return self._send(202, job.public())
            if len(parts) == 4 and parts[:2] == ["v1", "jobs"] and parts[3] == "cancel":
                job = self._job(parts[2])
                if not job:
                    return self._send(404, {"error": "job not found"})
                svc.cancel_job(job)
                return self._send(200, job.public())
            if parts == ["v1", "cancel"]:  # cancel everything submitted with a tag (used when a lease is cancelled)
                tag = parse_qs(u.query).get("tag", [""])[0]
                hit = [j for j in svc.jobs.values() if tag and j.tag == tag and not j.finished]
                for j in hit:
                    svc.cancel_job(j)
                return self._send(200, {"cancelled": len(hit)})
            self._send(404, {"error": "not found"})

    return H


def main() -> None:
    name = os.environ["PROVIDER_NAME"]
    svc = Service(name, Path(os.environ.get("PROVIDER_WORK_DIR", "/work")), Path(os.environ.get("HF_HOME", "/models/hf")),
                  int(os.environ.get("PROVIDER_THREADS", "8")), int(os.environ.get("PROVIDER_CONCURRENCY", "1")),
                  float(os.environ.get("PROVIDER_JOB_TIMEOUT", "3600")))
    psutil.cpu_percent(interval=None)
    srv = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PROVIDER_PORT", "8080"))), make_handler(svc))
    print(f"[cpu3d] provider={name} threads={svc.threads} concurrency={svc.concurrency} ready={svc.health()['ready']}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
