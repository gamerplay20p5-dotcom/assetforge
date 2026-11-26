"""Minimal HTTP service around Qwen2.5-VL (CPU only): ``POST /describe`` with an image -> job id; ``GET /jobs/<id>`` -> status/answer.

* One inference at a time (a 7B model on CPU uses ~32 GB of RAM and many cores); further requests wait in a queue.
* The model is loaded on the first request and unloaded after ``VLM_IDLE_UNLOAD_SECONDS`` without work, so the RAM goes back to the host.
* Weights come from the persistent cache (``HF_HOME``); with ``HF_HUB_OFFLINE=1`` nothing is ever downloaded at run time.
* Only the internal network reaches this port. The service never executes anything it is sent: it only decodes an image.
"""

from __future__ import annotations

import gc
import hmac
import io
import json
import os
import queue
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .prompt import SYSTEM, USER, USER_ANALYSIS

MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_PENDING = 8


class Engine:
    def __init__(self, model: str, threads: int, max_side: int, max_new_tokens: int, idle_unload: int, quant: str = "fp32", device: str = "cpu") -> None:
        self.model_name, self.threads, self.max_side, self.max_new_tokens, self.idle_unload = model, threads, max_side, max_new_tokens, idle_unload
        self.quant = quant
        self.device = device
        self._model: Any = None
        self._processor: Any = None
        self.last_used = time.monotonic()
        self.lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def weights_cached(self) -> bool:
        try:
            from huggingface_hub import snapshot_download

            snapshot_download(self.model_name, local_files_only=True)
            return True
        except Exception:  # noqa: BLE001 - any failure means "not usable offline"
            return False

    def _load(self) -> None:
        import torch
        from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

        torch.set_num_threads(self.threads)
        self._processor = AutoProcessor.from_pretrained(self.model_name, min_pixels=128 * 28 * 28, max_pixels=self.max_side * self.max_side)
        from .quant import apply_quant

        if self.device == "cuda":  # weights go straight to the GPU in bf16 (the host RAM stays small)
            self._model = Qwen2_5_VLForConditionalGeneration.from_pretrained(self.model_name, torch_dtype=torch.bfloat16, device_map="cuda").eval()
        else:
            self._model = apply_quant(Qwen2_5_VLForConditionalGeneration.from_pretrained(self.model_name, torch_dtype=torch.float32, low_cpu_mem_usage=True).eval(), self.quant)

    def unload(self) -> None:
        with self.lock:
            self._model = self._processor = None
            gc.collect()

    def describe(self, png: bytes, task: str = "house") -> dict[str, Any]:
        import torch
        from PIL import Image

        with self.lock:
            t0 = time.monotonic()
            if self._model is None:
                self._load()
            load_s = time.monotonic() - t0
            img = Image.open(io.BytesIO(png)).convert("RGB")
            messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": [{"type": "image", "image": img}, {"type": "text", "text": USER_ANALYSIS if task == "analysis" else USER}]}]
            text = self._processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = self._processor(text=[text], images=[img], return_tensors="pt")
            if self.device == "cuda":
                inputs = inputs.to("cuda")
            n_in = int(inputs["input_ids"].shape[1])
            t1 = time.monotonic()
            with torch.inference_mode():
                out = self._model.generate(**inputs, max_new_tokens=self.max_new_tokens, do_sample=False)
            new = out[:, n_in:]
            answer = self._processor.batch_decode(new, skip_special_tokens=True)[0]
            self.last_used = time.monotonic()
            return dict(answer=answer, seconds=round(time.monotonic() - t1, 1), load_seconds=round(load_s, 1), input_tokens=n_in, new_tokens=int(new.shape[1]))


class Service:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.jobs: dict[str, dict[str, Any]] = {}
        self.q: queue.Queue[tuple[str, bytes, str]] = queue.Queue()
        self.guard = threading.Lock()
        threading.Thread(target=self._worker, daemon=True).start()
        threading.Thread(target=self._reaper, daemon=True).start()

    def submit(self, png: bytes, task: str = "house") -> str:
        with self.guard:
            pending = sum(1 for j in self.jobs.values() if j["status"] in ("queued", "running"))
            if pending >= MAX_PENDING:
                raise RuntimeError("too many pending analyses")
            jid = f"vis_{uuid.uuid4().hex[:12]}"
            self.jobs[jid] = dict(id=jid, status="queued", created=time.time(), started=None, finished=None, result=None, error=None)
        self.q.put((jid, png, task))
        return jid

    def _worker(self) -> None:
        while True:
            jid, png, task = self.q.get()
            j = self.jobs[jid]
            j.update(status="running", started=time.time())
            try:
                j["result"] = self.engine.describe(png, task)
                j["status"] = "succeeded"
            except Exception as exc:  # noqa: BLE001
                j.update(status="failed", error=f"{type(exc).__name__}: {str(exc)[:300]}")
            j["finished"] = time.time()

    def _reaper(self) -> None:
        while True:
            time.sleep(5)
            idle = time.monotonic() - self.engine.last_used
            busy = any(j["status"] in ("queued", "running") for j in self.jobs.values())
            if self.engine.loaded and not busy and idle > self.engine.idle_unload:
                self.engine.unload()
            for k in [k for k, j in self.jobs.items() if j["finished"] and time.time() - j["finished"] > 3600]:
                self.jobs.pop(k, None)

    def public(self, j: dict[str, Any]) -> dict[str, Any]:
        out = {k: v for k, v in j.items() if k not in ("created",)}
        out["queue_position"] = None
        return out

    def health(self) -> dict[str, Any]:
        e = self.engine
        return dict(ready=e.weights_cached(), loaded=e.loaded, model=e.model_name, quant=e.quant, device=e.device, threads=e.threads, max_side=e.max_side,
                    pending=sum(1 for j in self.jobs.values() if j["status"] in ("queued", "running")))


def make_handler(svc: Service, token: str = ""):  # noqa: ANN201
    class H(BaseHTTPRequestHandler):
        server_version = "assetforge-vlm"

        def _authorized(self) -> bool:
            """With VLM_TOKEN set (service reachable from another machine) every request except /health must carry it."""
            if not token:
                return True
            given = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            return hmac.compare_digest(given.encode(), token.encode())

        def _send(self, code: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                return self._send(200, svc.health())
            if not self._authorized():
                return self._send(401, {"error": "missing or wrong token"})
            if self.path.startswith("/jobs/"):
                j = svc.jobs.get(self.path[6:])
                return self._send(200, svc.public(j)) if j else self._send(404, {"error": "unknown job"})
            self._send(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if not self._authorized():
                return self._send(401, {"error": "missing or wrong token"})
            path, _, query = self.path.partition("?")
            if path != "/describe":
                return self._send(404, {"error": "not found"})
            task = "analysis" if "task=analysis" in query else "house"
            n = int(self.headers.get("Content-Length") or 0)
            if not 0 < n <= MAX_IMAGE_BYTES:
                return self._send(413, {"error": "image must be 1 byte .. 12 MB"})
            body = self.rfile.read(n)
            if body[:8] != b"\x89PNG\r\n\x1a\n" and body[:3] != b"\xff\xd8\xff" and body[:4] != b"RIFF":
                return self._send(415, {"error": "body must be a PNG/JPEG/WEBP image"})
            try:
                self._send(202, {"id": svc.submit(body, task)})
            except RuntimeError as exc:
                self._send(429, {"error": str(exc)})

        def log_message(self, fmt: str, *args: Any) -> None:  # keep the container log quiet
            pass

    return H


def main() -> None:
    env = os.environ.get
    engine = Engine(env("VLM_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct"), int(env("VLM_THREADS", "20")), int(env("VLM_MAX_SIDE", "640")),
                    int(env("VLM_MAX_NEW_TOKENS", "520")), int(env("VLM_IDLE_UNLOAD_SECONDS", "900")), env("VLM_QUANT", "fp32"), env("VLM_DEVICE", "cpu"))
    svc = Service(engine)
    ThreadingHTTPServer(("0.0.0.0", 8080), make_handler(svc, env("VLM_TOKEN", ""))).serve_forever()


if __name__ == "__main__":
    main()
