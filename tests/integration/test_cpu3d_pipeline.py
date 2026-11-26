"""CPU image-to-3D providers through the whole AssetForge pipeline: REAL provider service process plumbing (stub CLI that returns a
genuine textured GLB), REAL Blender post-processing, REAL API/queue/worker. No AI model runs here: these tests prove integration,
not model quality or Arc/CPU performance (see docs/CPU3D.md for the measurements made on the real node)."""

import io
import os
import shutil
import socket
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
import uvicorn
from assetforge_api.main import create_app
from assetforge_cpu3d import CpuProvider
from assetforge_cpu3d.server import Service, make_handler
from assetforge_export.ai_pipeline import plan_for, run_ai_job
from assetforge_export.pipeline import run_building_job
from assetforge_worker.agent import Agent
from assetforge_worker.config import WorkerConfig
from conftest import ADMIN_PW, make_settings
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
STUB = ROOT / "tests" / "support" / "provider_stub.py"
API = "/api/v1"


def _blender():
    cand = os.environ.get("BLENDER_BIN")
    if cand and Path(cand).is_file():
        return cand
    local = next((ROOT / ".tools" / "blender").glob("*/blender.exe"), None) or next((ROOT / ".tools" / "blender").glob("*/blender"), None)
    return str(local) if local else shutil.which("blender")


@pytest.fixture(scope="module")
def blender():
    b = _blender()
    if not b:
        pytest.skip("no Blender executable")
    return b


@pytest.fixture(scope="module")
def stand_in_glb(tmp_path_factory):
    d = tmp_path_factory.mktemp("standin")
    run_building_job(dict(asset_id="ast_s", name="s", version=1, job_id="s", formats=["glb"],
                          params=dict(category="school", style="classic", seed=4, detail=2, texture_resolution=256)), d, lambda e: None, engine="trimesh")
    return d / "out" / "model.glb"


@pytest.fixture
def start_provider(tmp_path, stand_in_glb, monkeypatch):
    servers = []

    def factory(name):
        monkeypatch.setenv("PROVIDER_CMD_OVERRIDE", str(STUB))
        monkeypatch.setenv("STUB_GLB", str(stand_in_glb))
        monkeypatch.setenv("STUB_SLEEP", "0.6")
        svc = Service(name, tmp_path / f"w-{name}", tmp_path / "hf", 2, 1, 120)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(svc))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return f"http://127.0.0.1:{srv.server_address[1]}"

    yield factory
    for s in servers:
        s.shutdown()


def _ref(tmp_path) -> Path:
    p = tmp_path / "ref.png"
    Image.new("RGB", (256, 256), (230, 230, 230)).save(p)
    return p


def _job(provider, tmp_path, **params):
    base = {"provider": provider, "category": "school", "reference_id": "ref_000000000000", "target_size_m": 14.0, "lod_ratios": [0.5, 0.2]}
    base.update(params)
    return {"job_id": f"j-{provider}", "asset_id": "ast_cpu0001", "name": "Escola", "version": 1, "job_type": "ai.image_to_3d",
            "params": base, "quality_profile": "stylized_standard", "formats": ["glb", "fbx", "blend"], "reference_path": str(_ref(tmp_path)),
            "thumbnail_size": 256, "thumbnail_samples": 4}


@pytest.mark.parametrize("provider,license_bit", [("triposr", "MIT"), ("sf3d", "Stability AI Community")])
def test_pipeline_with_cpu_provider(blender, start_provider, tmp_path, provider, license_bit):
    url = start_provider(provider)
    events = []
    res = run_ai_job(_job(provider, tmp_path), tmp_path / "wd", events.append, CpuProvider(provider, url), blender_bin=blender, threads=2)
    out, m = tmp_path / "wd" / "out", res["manifest"]
    for n in ("model.glb", "model_lod1.glb", "model_lod2.glb", "model.fbx", "model.blend", "thumbnail.png", "preview_raw.png", "manifest.json"):
        assert (out / n).stat().st_size > 500, n
    assert m["ai_model"] == provider and m["engine"] == f"blender+{provider}-cpu" and m["generation_params"]["provider"] == provider
    assert license_bit in m["license"] and m["provenance"]["provider"] == f"cpu3d:{provider}"
    assert "cuda" not in m["provenance"]["device"].replace("no CUDA", "").lower()
    tris = [x["triangles"] for x in m["lods"]]
    assert tris[0] > tris[1] > tris[2] > 0 and abs(m["dimensions_m"][1] - 14.0) < 0.3
    st = m["generation_params"]["ai"]["stages"]["image_to_3d"]
    assert st["provider"] == provider and st["peak_ram_mb"] >= 0 and st["seconds"] > 0 and st["color"] == {"sf3d": "pbr_texture", "triposr": "vertex_color"}[provider]
    checks = {c["name"]: c["status"] for c in res["validation"]["checks"]}
    assert checks["material_preserved"] == "pass" and res["validation"]["passed"]
    assert any(f["name"] == "preview_raw.png" for f in res["files"])
    assert [n for n, s in [(e["name"], e["status"]) for e in events if e["type"] == "stage"] if s == "done"] == [n for n, _ in plan_for("ai.image_to_3d")]


def test_max_triangles_overrides_the_category_budget(blender, start_provider, tmp_path):
    url = start_provider("triposr")
    res = run_ai_job(_job("triposr", tmp_path, max_triangles=1000), tmp_path / "wd", lambda e: None, CpuProvider("triposr", url), blender_bin=blender)
    m = res["manifest"]
    assert m["triangle_count"] <= 1050 and m["triangle_budget"][1] == 1000 and m["generation_params"]["raw_triangles"] > 1500


def test_cpu_jobs_are_routed_by_provider_feature(client, admin, make_worker, tmp_path):
    ref = client.post(f"{API}/references", headers=admin, files={"file": ("r.png", _png_bytes(), "image/png")}).json()["id"]
    body = {"name": "X", "job_type": "ai.image_to_3d", "formats": ["glb"], "params": {"reference_id": ref, "provider": "sf3d", "category": "prop"}}
    job = client.post(f"{API}/jobs", headers=admin, json=body).json()
    assert job["requirements"] == {"features": ["ai.image_to_3d", "provider.sf3d", "blender"], "cpu_cores": 12, "ram_mb": 16384, "vram_mb": 0}
    limits = {"max_concurrent_jobs": 1, "cpu_cores": 16, "ram_mb": 32000}
    tri_only = make_worker(features=("ai.image_to_3d", "provider.triposr", "blender"), limits=limits)
    cpu_only = make_worker(features=("procedural.building", "blender"), limits=limits)
    small = make_worker(features=("ai.image_to_3d", "provider.sf3d", "blender"), limits={"max_concurrent_jobs": 1, "cpu_cores": 4, "ram_mb": 32000})
    assert tri_only.lease() is None and cpu_only.lease() is None  # wrong provider / no provider
    assert small.lease() is None  # not enough cores reserved on this worker
    good = make_worker(features=("ai.image_to_3d", "provider.sf3d", "blender"), limits=limits)
    assert good.lease()["job_id"] == job["id"]
    # CPU providers never reserve VRAM: no GPU worker is needed
    r = client.post(f"{API}/jobs", headers=admin, json={**body, "job_type": "ai.text_to_3d", "params": {"prompt": "a school", "provider": "sf3d"}})
    assert r.status_code == 422 and "text-to-image" in r.text


def _png_bytes() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (200, 200), "red").save(b, "PNG")
    return b.getvalue()


@pytest.mark.blender
def test_worker_advertises_only_ready_providers_and_runs_a_cpu_job(blender, start_provider, tmp_path, monkeypatch):
    ready_url = start_provider("sf3d")
    monkeypatch.setenv("ASSETFORGE_CPU3D_PROVIDERS", f"sf3d={ready_url},triposr=http://127.0.0.1:9")  # triposr is down
    monkeypatch.setenv("BLENDER_BIN", blender)
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    app = create_app(make_settings(tmp_path, heartbeat_seconds=1, lease_seconds=60), start_reaper=False)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            if httpx.get(f"{base}/api/v1/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.3)
    token = httpx.post(f"{base}/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PW}).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    enr = httpx.post(f"{base}/api/v1/workers/enrollment-tokens", headers=h, json={}).json()["token"]
    monkeypatch.setenv("ASSETFORGE_SERVER_URL", base)
    cfg = WorkerConfig.from_env()
    cfg.name, cfg.enrollment_token = "cpu3d-node", enr
    cfg.state_dir, cfg.work_dir = tmp_path / "ws", tmp_path / "ws" / "jobs"
    cfg.poll_interval_s, cfg.low_priority, cfg.ram_mb, cfg.cpu_cores = 0.5, False, 32000, 16
    agent = Agent(cfg)
    agent.heartbeat_seconds = 1
    threading.Thread(target=agent.run, daemon=True).start()
    try:
        def worker():
            return next(iter(httpx.get(f"{base}/api/v1/workers", headers=h).json()), None)

        end = time.time() + 30
        w = None
        while time.time() < end:
            w = worker()
            if w and "provider.sf3d" in w["capabilities"]["features"]:
                break
            time.sleep(0.5)
        assert w and "provider.sf3d" in w["capabilities"]["features"] and "provider.triposr" not in w["capabilities"]["features"]
        assert w["capabilities"]["cpu3d"]["providers"]["triposr"]["ready"] is False
        ref = httpx.post(f"{base}/api/v1/references", headers=h, files={"file": ("r.png", _png_bytes(), "image/png")}).json()["id"]
        mk = lambda prov: httpx.post(f"{base}/api/v1/jobs", headers=h, json={"name": f"J {prov}", "job_type": "ai.image_to_3d", "formats": ["glb", "fbx"],
                                    "params": {"reference_id": ref, "provider": prov, "category": "house", "target_size_m": 8, "lod_ratios": [0.4]}}).json()
        tri, sf = mk("triposr"), mk("sf3d")
        end = time.time() + 180
        done = None
        while time.time() < end:
            done = httpx.get(f"{base}/api/v1/jobs/{sf['id']}", headers=h).json()
            if done["status"] in ("succeeded", "failed"):
                break
            time.sleep(1)
        assert done and done["status"] == "succeeded", done
        assert httpx.get(f"{base}/api/v1/jobs/{tri['id']}", headers=h).json()["status"] == "queued"  # its provider is not ready: nobody takes it
        a = httpx.get(f"{base}/api/v1/assets/{sf['asset_id']}", headers=h).json()
        assert a["manifest"]["ai_model"] == "sf3d" and len(a["manifest"]["lods"]) == 2 and a["validation_passed"]
        assert httpx.get(f"{base}/api/v1/assets/{sf['asset_id']}/files/preview_raw.png", headers=h).content[:4] == b"\x89PNG"
        w2 = worker()
        assert "cpu3d" in w2["telemetry"]
    finally:
        agent.stop.set()
        server.should_exit = True
