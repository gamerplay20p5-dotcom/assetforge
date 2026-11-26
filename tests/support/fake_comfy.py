"""A tiny fake ComfyUI HTTP server (real sockets) for provider/pipeline tests.

It implements only the endpoints the AssetForge client uses and records every workflow it receives, so tests can assert
that settings were injected correctly. It does NOT run any AI model: the "3D output" is a real GLB supplied by the test,
and results say nothing about Intel Arc compatibility.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class FakeComfy:
    def __init__(self, glb: Path, png: Path, *, vram_total_gb: float = 8.0, fail_with: str | None = None, polls_before_done: int = 2) -> None:
        self.glb, self.png = glb, png
        self.vram_total = int(vram_total_gb * 2**30)
        self.fail_with = fail_with
        self.polls_before_done = polls_before_done
        self.prompts: list[dict] = []
        self.uploads: list[str] = []
        self.interrupts = 0
        self._polls: dict[str, int] = {}
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # noqa: ANN002
                pass

            def _json(self, obj, code=200):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: N802
                u = urlparse(self.path)
                if u.path == "/system_stats":
                    used = int(outer.vram_total * (0.35 + 0.1 * len(outer.prompts)))
                    return self._json({"system": {"comfyui_version": "0.34.0"}, "devices": [
                        {"name": "xpu:0 Intel(R) Arc(TM) A750 Graphics (fake)", "type": "xpu", "index": 0,
                         "vram_total": outer.vram_total, "vram_free": outer.vram_total - used}]})
                if u.path.startswith("/history/"):
                    pid = u.path.rsplit("/", 1)[1]
                    outer._polls[pid] = outer._polls.get(pid, 0) + 1
                    if outer._polls[pid] <= outer.polls_before_done:
                        return self._json({})
                    if outer.fail_with:
                        return self._json({pid: {"status": {"status_str": "error", "completed": False, "messages": [
                            ["execution_error", {"exception_message": outer.fail_with}]]}, "outputs": {}}})
                    wf = outer.prompts[-1]
                    is3d = any(n["class_type"] == "SaveGLB" for n in wf.values())
                    out = {"322": {"3d": [{"filename": "AIPG_3D_00001_.glb", "subfolder": "", "type": "output"}]}} if is3d else \
                          {"9": {"images": [{"filename": "assetforge_ref_00001_.png", "subfolder": "", "type": "output"}]}}
                    return self._json({pid: {"status": {"status_str": "success", "completed": True}, "outputs": out}})
                if u.path == "/view":
                    name = parse_qs(u.query)["filename"][0]
                    data = (outer.glb if name.endswith(".glb") else outer.png).read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    return self.wfile.write(data)
                self._json({"error": "not found"}, 404)

            def do_POST(self):  # noqa: N802
                n = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(n)
                if self.path == "/prompt":
                    wf = json.loads(body)["prompt"]
                    bad = [k for k, v in wf.items() if "\\" in json.dumps(v)]  # Windows separators must have been normalised
                    if bad:
                        return self._json({"error": "bad model path", "node_errors": bad}, 400)
                    outer.prompts.append(wf)
                    return self._json({"prompt_id": f"p{len(outer.prompts)}"})
                if self.path == "/upload/image":
                    outer.uploads.append(f"{len(body)} bytes")
                    return self._json({"name": "ref_upload.png", "subfolder": "", "type": "input"})
                if self.path == "/interrupt":
                    outer.interrupts += 1
                    return self._json({})
                self._json({})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
