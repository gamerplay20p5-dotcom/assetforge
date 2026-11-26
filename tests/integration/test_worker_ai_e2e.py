"""REAL API server (uvicorn) + REAL worker agent + FAKE ComfyUI + REAL Blender.

Verifies the safety gate (no AI features until the node is validated), VRAM-aware scheduling, reference download,
execution in the isolated child process, upload and registration. Says nothing about Intel Arc: no model runs here.
"""

import json
import os
import shutil
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from assetforge_api.main import create_app
from assetforge_export.pipeline import run_building_job
from assetforge_intel_ai import required_specs
from assetforge_worker.agent import Agent
from assetforge_worker.config import WorkerConfig
from conftest import ADMIN_PW, make_settings
from PIL import Image
from support.fake_comfy import FakeComfy

ROOT = Path(__file__).resolve().parents[2]


def _blender():
    cand = os.environ.get("BLENDER_BIN")
    if cand and Path(cand).is_file():
        return cand
    local = next((ROOT / ".tools" / "blender").glob("*/blender.exe"), None) or next((ROOT / ".tools" / "blender").glob("*/blender"), None)
    return str(local) if local else shutil.which("blender")


def _wait(cond, timeout, step=0.5):
    end = time.time() + timeout
    while time.time() < end:
        v = cond()
        if v:
            return v
        time.sleep(step)
    return None


@pytest.mark.blender
def test_worker_gates_ai_until_validated_then_runs_job(tmp_path, monkeypatch):
    blender = _blender()
    if not blender:
        pytest.skip("no Blender")
    # stand-in "AI output" + fake backend with 16 GB so the VRAM preflight passes
    sd = tmp_path / "standin"
    run_building_job(dict(asset_id="ast_s", name="s", version=1, job_id="s", formats=["glb"], params=dict(category="house", seed=2, texture_resolution=256)),
                     sd, lambda e: None, engine="trimesh")
    png = tmp_path / "c.png"
    Image.new("RGB", (256, 256), "white").save(png)
    fake = FakeComfy(sd / "out" / "model.glb", png, vram_total_gb=16, polls_before_done=1)
    models = tmp_path / "models"
    for s in required_specs():
        p = s.local_path(models)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")  # presence only; nothing loads these files
    monkeypatch.setenv("ASSETFORGE_COMFYUI_URL", fake.url)
    monkeypatch.setenv("ASSETFORGE_ENABLE_INTEL_AI", "1")  # the Intel integration is opt-in
    monkeypatch.setenv("ASSETFORGE_AI_MODELS_DIR", str(models))
    monkeypatch.setenv("BLENDER_BIN", blender)
    monkeypatch.delenv("ASSETFORGE_AI_ALLOW_UNVALIDATED", raising=False)

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    app = create_app(make_settings(tmp_path, heartbeat_seconds=1, lease_seconds=60), start_reaper=False)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    assert _wait(lambda: httpx.get(f"{base}/api/v1/health", timeout=1).status_code == 200 if True else None, 20)
    token = httpx.post(f"{base}/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PW}).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    enr = httpx.post(f"{base}/api/v1/workers/enrollment-tokens", headers=h, json={}).json()["token"]

    monkeypatch.setenv("ASSETFORGE_SERVER_URL", base)
    cfg = WorkerConfig.from_env()
    cfg.name, cfg.enrollment_token, cfg.kind = "ai-node-test", enr, "hybrid"
    cfg.state_dir, cfg.work_dir = tmp_path / "ws", tmp_path / "ws" / "jobs"
    cfg.poll_interval_s, cfg.low_priority, cfg.ram_mb = 0.5, False, 12000  # AI jobs reserve 8192 MB of RAM
    agent = Agent(cfg)
    agent.heartbeat_seconds = 1
    threading.Thread(target=agent.run, daemon=True).start()
    try:
        def worker():
            return next(iter(httpx.get(f"{base}/api/v1/workers", headers=h).json()), None)

        w = _wait(worker, 30)
        assert w and "ai.text_to_3d" not in w["capabilities"]["features"]  # gate closed: node not validated
        assert "não validado" in w["capabilities"]["ai"]["reason"]
        assert w["limits"]["vram_mb"] > 7000  # derived from the (fake) device, not invented

        ref = httpx.post(f"{base}/api/v1/references", headers=h, files={"file": ("r.png", png.read_bytes(), "image/png")}).json()["id"]
        job = httpx.post(f"{base}/api/v1/jobs", headers=h, json={"name": "IA", "job_type": "ai.image_to_3d", "formats": ["glb"],
                                                                  "params": {"reference_id": ref, "category": "house", "target_size_m": 8, "lod_ratios": [0.4], "provider": "intel"}}).json()
        time.sleep(4)
        assert httpx.get(f"{base}/api/v1/jobs/{job['id']}", headers=h).json()["status"] == "queued"  # nobody may take it yet

        (cfg.state_dir / "ai_validated.json").write_text(json.dumps([{"ok": True, "preset": "pixel3d-trellis", "gpu": "fake"}]))
        agent.ai._cache = None
        done = _wait(lambda: (j := httpx.get(f"{base}/api/v1/jobs/{job['id']}", headers=h).json())["status"] in ("succeeded", "failed") and j, 180)
        assert done and done["status"] == "succeeded", done
        # the downloaded reference was uploaded to ComfyUI and wired into the LoadImage node of Intel's workflow
        assert fake.uploads and any(n["class_type"] == "LoadImage" and n["inputs"]["image"] == "ref_upload.png" for wf in fake.prompts for n in wf.values())
        a = httpx.get(f"{base}/api/v1/assets/{job['asset_id']}", headers=h).json()
        assert a["manifest"]["ai_model"] == "pixal3d" and len(a["manifest"]["lods"]) == 2
        w2 = worker()
        assert "ai.image_to_3d" in w2["capabilities"]["features"] and "pixel3d-trellis@fake" in w2["capabilities"]["ai_runtimes"]["validated"]
        assert w2["telemetry"]["gpus"][0]["vram_total_mb"] == 16384  # real (fake-backend) VRAM telemetry
    finally:
        agent.stop.set()
        server.should_exit = True
        fake.close()
