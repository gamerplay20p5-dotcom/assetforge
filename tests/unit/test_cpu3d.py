import io
import json
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from assetforge_cpu3d import PROVIDERS, CpuProvider, ProviderCancelled, ProviderError, parse_providers_env
from assetforge_cpu3d import adapters
from assetforge_cpu3d.server import Service, make_handler
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
STUB = ROOT / "tests" / "support" / "provider_stub.py"


def _png() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(b, "PNG")
    return b.getvalue()


@pytest.fixture
def glb(tmp_path):
    from assetforge_export.pipeline import run_building_job

    run_building_job(dict(asset_id="ast_s", name="s", version=1, job_id="s", formats=["glb"], params=dict(category="house", seed=2, texture_resolution=128)),
                     tmp_path / "g", lambda e: None, engine="trimesh")
    return tmp_path / "g" / "out" / "model.glb"


@pytest.fixture
def make_service(tmp_path, glb, monkeypatch):
    started = []

    def factory(provider="triposr", timeout=60.0, concurrency=1, **env):
        monkeypatch.setenv("PROVIDER_CMD_OVERRIDE", str(STUB))
        monkeypatch.setenv("STUB_GLB", str(glb))
        for k, v in env.items():
            monkeypatch.setenv(k, str(v))
        svc = Service(provider, tmp_path / f"w{len(started)}", tmp_path / "hf", threads=2, concurrency=concurrency, timeout=timeout)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(svc))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        started.append(srv)
        return svc, CpuProvider(provider, f"http://127.0.0.1:{srv.server_address[1]}")

    yield factory
    for s in started:
        s.shutdown()


# ----------------------------------------------------------------------------- adapters
def test_command_lines_are_cpu_only_and_whitelisted():
    cmd, env = adapters.build_command("sf3d", Path("/w/in.png"), Path("/w/out"), {"texture_resolution": 2048, "remesh": "quad", "target_vertex_count": 5000})
    assert env == {"SF3D_USE_CPU": "1"} and cmd[cmd.index("--device") + 1] == "cpu" and "cuda" not in " ".join(cmd).lower()
    assert cmd[cmd.index("--remesh_option") + 1] == "quad" and "--target_vertex_count" in cmd
    cmd, _ = adapters.build_command("triposr", Path("/w/in.png"), Path("/w/out"), {"mc_resolution": 320, "texture_resolution": 1024})
    assert cmd[cmd.index("--device") + 1] == "cpu" and "--bake-texture" in cmd and cmd[cmd.index("--mc-resolution") + 1] == "320"
    assert cmd[0] == "xvfb-run" or not __import__("shutil").which("xvfb-run")  # bake needs a (virtual) display when available
    cmd, _ = adapters.build_command("triposr", Path("/w/in.png"), Path("/w/out"), {}, bake=False)
    assert "--bake-texture" not in cmd and cmd[cmd.index("--model-save-format") + 1] == "glb"


@pytest.mark.parametrize("provider,params", [
    ("sf3d", {"remesh": "evil; rm -rf /"}), ("sf3d", {"texture_resolution": 99999}), ("triposr", {"mc_resolution": "$(id)"}),
    ("triposr", {"mc_resolution": 9}), ("sf3d", {"foreground_ratio": 5}), ("nope", {})])
def test_parameters_are_validated_never_passed_through(provider, params):
    with pytest.raises(ValueError):
        adapters.validate_params(provider, params)


def test_triposr_baked_obj_becomes_textured_glb(tmp_path):
    out = tmp_path / "out" / "0"
    out.mkdir(parents=True)
    (out / "mesh.obj").write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 0 1\nf 1/1 2/2 3/3\n")
    Image.new("RGB", (16, 16), (200, 30, 30)).save(out / "texture.png")
    info = adapters.collect_result("triposr", tmp_path / "out", tmp_path / "r.glb")
    from assetforge_validation import read_glb_json

    doc, _ = read_glb_json(tmp_path / "r.glb")
    assert info["color"] == "baked_texture" and "baseColorTexture" in doc["materials"][0]["pbrMetallicRoughness"]


def test_triposr_orientation_puts_raw_z_up_on_y_up():
    import numpy as np
    import trimesh

    m = trimesh.Trimesh(vertices=[[0, 0, 1], [1, 0, 0], [0, 1, 0]], faces=[[0, 1, 2]], process=False)
    adapters.to_gradio_3d_orientation(m)
    assert np.allclose(m.vertices[0], [0, 1, 0], atol=1e-9)  # raw +Z (up) -> +Y (up)


def test_weights_readiness_detects_cached_snapshot(tmp_path):
    assert adapters.weights_ready("sf3d", tmp_path)[0] is False
    snap = tmp_path / "hub" / "models--stabilityai--stable-fast-3d" / "snapshots" / "abc"
    snap.mkdir(parents=True)
    (snap / "model.safetensors").write_bytes(b"x")
    assert adapters.weights_ready("sf3d", tmp_path)[0] is True and adapters.weights_ready("triposr", tmp_path)[0] is False


def test_env_parser_ignores_unknown_names():
    assert parse_providers_env("sf3d=http://a:1, triposr=http://b:2,evil=http://c,bad") == {"sf3d": "http://a:1", "triposr": "http://b:2"}


# ----------------------------------------------------------------------------- service (real HTTP, stub CLI)
def test_job_lifecycle_returns_glb_and_measures_resources(make_service, tmp_path):
    svc, prov = make_service(STUB_SLEEP=1.5, STUB_ALLOC_MB=60)
    assert prov.health()["ready"] and prov.health()["threads"] == 2
    img = tmp_path / "i.png"
    img.write_bytes(_png())
    res = prov.image_to_3d(img, tmp_path / "o.glb", params={"mc_resolution": 128}, tag="t1", poll=0.3)
    assert (tmp_path / "o.glb").read_bytes()[:4] == b"glTF" and res.peak_ram_mb >= 50 and res.seconds >= 1.5
    assert res.info["color"] == "vertex_color" and res.peak_cpu_percent >= 0
    assert "host_ram_total_mb" in prov.stats()


def test_concurrency_limit_queues_second_job(make_service, tmp_path):
    svc, prov = make_service(concurrency=1, STUB_SLEEP=2.0)
    j1 = svc.submit(_png(), {}, "a")
    j2 = svc.submit(_png(), {}, "b")
    time.sleep(0.8)
    assert j1.status == "running" and j2.status == "queued"
    deadline = time.time() + 20
    while time.time() < deadline and j2.status != "succeeded":
        time.sleep(0.3)
    assert j1.status == "succeeded" and j2.status == "succeeded" and j2.started >= j1.finished - 0.05


def test_cancel_kills_the_running_process(make_service, tmp_path):
    svc, prov = make_service(STUB_SLEEP=60)
    img = tmp_path / "i.png"
    img.write_bytes(_png())
    cancel = threading.Event()
    threading.Timer(1.5, cancel.set).start()
    with pytest.raises(ProviderCancelled):
        prov.image_to_3d(img, tmp_path / "o.glb", params={}, tag="x", poll=0.3, should_cancel=cancel.is_set)
    job = next(iter(svc.jobs.values()))
    time.sleep(0.5)
    assert job.status == "cancelled" and job.proc.poll() is not None


def test_cancel_by_tag(make_service):
    svc, prov = make_service(STUB_SLEEP=60)
    job = svc.submit(_png(), {}, "lease-123")
    time.sleep(1.0)
    prov.cancel_tag("lease-123")
    time.sleep(0.8)
    assert job.status == "cancelled"


def test_timeout_kills_runaway_jobs(make_service, tmp_path):
    svc, prov = make_service(timeout=2.0, STUB_SLEEP=60)
    img = tmp_path / "i.png"
    img.write_bytes(_png())
    with pytest.raises(ProviderError, match="timed out"):
        prov.image_to_3d(img, tmp_path / "o.glb", params={}, poll=0.3)


def test_triposr_retries_without_texture_bake_once(make_service, tmp_path):
    svc, prov = make_service(STUB_FAIL_ONCE=str(tmp_path / "marker"))
    img = tmp_path / "i.png"
    img.write_bytes(_png())
    res = prov.image_to_3d(img, tmp_path / "o.glb", params={}, poll=0.3)
    job = next(iter(svc.jobs.values()))
    assert job.metrics["attempts"] == 2 and res.info["bake_fallback"] is True


def test_failures_and_bad_input_are_reported(make_service, tmp_path):
    svc, prov = make_service("sf3d", STUB_FAIL=1)
    img = tmp_path / "i.png"
    img.write_bytes(_png())
    with pytest.raises(ProviderError, match="exited with code 3"):
        prov.image_to_3d(img, tmp_path / "o.glb", params={}, poll=0.3)
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"MZ-not-an-image")
    with pytest.raises(ProviderError, match="422"):
        prov.image_to_3d(bad, tmp_path / "o.glb", params={})
    with pytest.raises(ProviderError, match="422"):
        prov.image_to_3d(img, tmp_path / "o.glb", params={"remesh": "$(reboot)"})


def test_service_refuses_jobs_when_weights_are_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("PROVIDER_CMD_OVERRIDE", raising=False)
    svc = Service("sf3d", tmp_path / "w", tmp_path / "hf", 2, 1, 10)
    assert svc.health()["ready"] is False and "download" in svc.health()["reason"]
    with pytest.raises(RuntimeError, match="not downloaded"):
        svc.submit(_png(), {})


def test_registry_license_facts_are_recorded():
    sf, tr = PROVIDERS["sf3d"], PROVIDERS["triposr"]
    assert sf.weights_gated and "1 milhão" in sf.commercial and "Powered by Stability AI" in sf.commercial
    assert not tr.weights_gated and tr.code_license == "MIT" and "MIT" in tr.weights_license
    assert len(sf.commit) == 40 and len(tr.commit) == 40
    json.dumps({k: v.__dict__ for k, v in PROVIDERS.items()})


# ----------------------------------------------------------------------------- GPU box: device, token, several URLs
def test_device_comes_from_the_environment_and_is_whitelisted(monkeypatch):
    monkeypatch.setenv("PROVIDER_DEVICE", "cuda:0")
    cmd, env = adapters.build_command("triposr", Path("/w/in.png"), Path("/w/out"), {})
    assert cmd[cmd.index("--device") + 1] == "cuda:0"
    cmd, env = adapters.build_command("sf3d", Path("/w/in.png"), Path("/w/out"), {})
    assert cmd[cmd.index("--device") + 1] == "cuda:0" and "SF3D_USE_CPU" not in env  # CPU-forcing env only on CPU
    for bad in ("cuda; rm -rf /", "tpu", "cuda:x"):
        monkeypatch.setenv("PROVIDER_DEVICE", bad)
        with pytest.raises(ValueError, match="PROVIDER_DEVICE"):
            adapters.build_command("triposr", Path("/w/in.png"), Path("/w/out"), {})


def test_provider_token_is_required_except_for_health(tmp_path, monkeypatch):
    import httpx

    svc = Service("triposr", tmp_path / "w", tmp_path / "hf", 2, 1, 10)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(svc, token="tok"))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        for _ in range(50):  # wait until the server thread is accepting (avoids a start-up race)
            try:
                if httpx.get(f"{base}/health").status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        assert httpx.get(f"{base}/health").status_code == 200
        assert httpx.get(f"{base}/stats").status_code == 401
        assert httpx.post(f"{base}/v1/jobs", content=b"x").status_code == 401
        assert httpx.post(f"{base}/v1/jobs", content=b"x", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert httpx.get(f"{base}/stats", headers={"Authorization": "Bearer tok"}).status_code == 200
    finally:
        srv.shutdown()


def test_client_uses_the_first_healthy_url_and_sends_the_token(make_service, monkeypatch):
    svc, cp = make_service()
    gpu_dead = "http://127.0.0.1:9"
    monkeypatch.setenv("ASSETFORGE_CPU3D_TOKEN", "tok")
    p = CpuProvider("triposr", f"{gpu_dead}|{cp.base}")
    assert p.bases == [gpu_dead, cp.base] and "Bearer tok" == p.http.headers["Authorization"]
    h = p.health()
    assert h["reachable"] and p.base == cp.base  # the dead GPU box is skipped, the next URL answers
    assert parse_providers_env(f"triposr={gpu_dead}|http://b:8080")["triposr"] == f"{gpu_dead}|http://b:8080"
