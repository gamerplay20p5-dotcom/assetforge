"""AI pipeline end-to-end with a FAKE ComfyUI (no model runs) and the REAL Blender post-processing, then through the API.

The "AI output" is a genuine textured GLB made by the procedural generator, so LOD/export/validation are exercised on real
geometry. These tests prove integration plumbing, NOT Intel Arc compatibility."""

import hashlib
import io
import os
import shutil
from pathlib import Path

import pytest
from assetforge_export.ai_pipeline import plan_for, run_ai_job
from assetforge_export.pipeline import PipelineError, run_building_job
from assetforge_intel_ai import IntelAIProvider
from PIL import Image
from support.fake_comfy import FakeComfy

ROOT = Path(__file__).resolve().parents[2]
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
    run_building_job(dict(asset_id="ast_standin", name="s", version=1, job_id="s", formats=["glb"],
                          params=dict(category="school", style="classic", seed=4, detail=2, texture_resolution=256)),
                     d, lambda e: None, engine="trimesh")
    return d / "out" / "model.glb"


@pytest.fixture
def fake(tmp_path, stand_in_glb):
    png = tmp_path / "c.png"
    Image.new("RGB", (256, 256), (200, 210, 220)).save(png)
    f = FakeComfy(stand_in_glb, png, polls_before_done=1)
    yield f
    f.close()


def _job(job_type="ai.text_to_3d", **params):
    base = {"category": "school", "prompt": "a small stylized school with brick facade", "target_size_m": 14.0, "seed": 5, "lod_ratios": [0.5, 0.2], "provider": "intel"}
    base.update(params)
    return dict(job_id="jai", asset_id="ast_ai00001", name="Escola IA", version=1, job_type=job_type, params=base,
                quality_profile="stylized_standard", formats=["glb", "fbx", "blend"], thumbnail_size=256, thumbnail_samples=4)


def test_text_to_3d_produces_lods_exports_and_manifest(blender, fake, tmp_path):
    events = []
    prov = IntelAIProvider(fake.url, models_dir=tmp_path / "m")
    res = run_ai_job(_job(), tmp_path / "wd", events.append, prov, blender_bin=blender, threads=2)
    out = tmp_path / "wd" / "out"
    for n in ("model.glb", "model_lod1.glb", "model_lod2.glb", "model.fbx", "model.blend", "thumbnail.png", "concept.png", "manifest.json"):
        assert (out / n).stat().st_size > 500, n
    m = res["manifest"]
    assert m["ai_model"] == "pixal3d+z-image-turbo" and m["engine"] == "blender+comfyui" and m["generator_id"] == "ai.text_to_3d"
    tris = [x["triangles"] for x in m["lods"]]
    assert len(tris) == 3 and tris[0] > tris[1] > tris[2] > 0 and m["triangle_count"] == tris[0]
    assert abs(m["dimensions_m"][1] - 14.0) < 0.3  # height normalised to the requested real-world size
    assert abs(m["bounding_box"][0][1]) < 1e-6
    assert "MIT" in m["license"] and "Apache-2.0" in m["license"]
    assert res["validation"]["passed"]
    stages = [(e["name"], e["status"]) for e in events if e["type"] == "stage"]
    assert [s for s, st in stages if st == "done"] == [n for n, _ in plan_for("ai.text_to_3d")]
    assert m["generation_params"]["ai"]["stages"]["image_to_3d"]["peak_vram_mb"] > 0


def test_triangle_budget_cap_is_enforced_on_lod0(blender, fake, tmp_path):
    job = _job("ai.image_to_3d", prompt=None)
    job["triangle_limit"] = 1200
    ref = tmp_path / "ref.png"
    Image.new("RGB", (300, 300), "white").save(ref)
    job["reference_path"] = str(ref)
    res = run_ai_job(job, tmp_path / "wd", lambda e: None, IntelAIProvider(fake.url, models_dir=tmp_path), blender_bin=blender)
    assert res["manifest"]["triangle_count"] <= 1250 and res["manifest"]["generation_params"]["raw_triangles"] > 1500
    assert [n for n, _ in plan_for("ai.image_to_3d")][0] == "image_to_3d" and not (tmp_path / "wd" / "out" / "concept.png").exists()


def test_invalid_reference_and_failed_backend_are_reported(blender, fake, tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    job = _job("ai.image_to_3d", prompt=None)
    job["reference_path"] = str(bad)
    with pytest.raises(PipelineError, match="not a valid image"):
        run_ai_job(job, tmp_path / "a", lambda e: None, IntelAIProvider(fake.url, models_dir=tmp_path), blender_bin=blender)
    fake.fail_with = "XPU out of memory"
    from assetforge_intel_ai import ComfyError

    with pytest.raises(ComfyError, match="out of memory"):
        run_ai_job(_job(), tmp_path / "b", lambda e: None, IntelAIProvider(fake.url, models_dir=tmp_path), blender_bin=blender)


def test_ai_job_flows_through_queue_and_registers_asset(blender, fake, tmp_path, client, admin, make_worker):
    w = make_worker(kind="hybrid", features=("ai.text_to_3d", "comfyui", "blender"), limits={"max_concurrent_jobs": 1, "cpu_cores": 4, "ram_mb": 16000, "vram_mb": 7500})
    plain = make_worker(features=("procedural.building", "blender"))
    r = client.post(f"{API}/jobs", headers=admin, json={"name": "Escola IA", "job_type": "ai.text_to_3d", "formats": ["glb", "fbx"],
                                                         "params": {"prompt": "stylized school", "category": "school", "target_size_m": 14, "lod_ratios": [0.5], "provider": "intel"}})
    assert r.status_code == 201, r.text
    job = r.json()
    assert plain.lease() is None  # a CPU-only worker never receives a generative job
    low_vram = make_worker(features=("ai.text_to_3d", "comfyui", "blender"), limits={"max_concurrent_jobs": 1, "cpu_cores": 4, "ram_mb": 16000, "vram_mb": 4000})
    assert low_vram.lease() is None  # reserved VRAM (7000) does not fit a 4000 MB budget
    lease = w.lease()
    assert lease["job_id"] == job["id"] and lease["job"]["requirements"]["vram_mb"] == 7000
    prov = IntelAIProvider(fake.url, models_dir=tmp_path)
    result = run_ai_job({**lease["job"], "job_id": job["id"], "thumbnail_size": 256, "thumbnail_samples": 4}, tmp_path / "wd", lambda e: None, prov, blender_bin=blender)
    for f in result["files"]:
        assert w.upload(lease, f["name"], tmp_path / "wd" / "out" / f["name"]).status_code == 201
    assert w.complete(lease, result).status_code == 200
    a = client.get(f"{API}/assets/{job['asset_id']}", headers=admin).json()
    assert a["manifest"]["ai_model"] == "pixal3d+z-image-turbo" and len(a["manifest"]["lods"]) == 2 and a["validation_passed"]
    assert client.get(f"{API}/assets/{job['asset_id']}/files/model_lod1.glb", headers=admin).status_code == 200


def test_reference_upload_validation_and_job_requires_existing_reference(client, admin):
    def up(data: bytes, name="r.png"):
        return client.post(f"{API}/references", headers=admin, files={"file": (name, data, "image/png")})

    buf = io.BytesIO()
    Image.new("RGB", (200, 100), "red").save(buf, "PNG")
    ok = up(buf.getvalue())
    assert ok.status_code == 201 and ok.json()["width"] == 200 and ok.json()["id"].startswith("ref_")
    assert up(b"GIF89a-not-really").status_code == 422
    assert up(b"x" * 100).status_code == 422
    huge = io.BytesIO()
    Image.new("RGB", (5000, 10), "red").save(huge, "PNG")
    assert up(huge.getvalue()).status_code == 422
    assert client.get(f"{API}/references/{ok.json()['id']}", headers=admin).headers["content-type"] == "image/png"
    assert client.get(f"{API}/references/ref_000000000000", headers=admin).status_code == 404
    assert client.get(f"{API}/references/..%2f..%2fx", headers=admin).status_code in (404, 422)
    missing = client.post(f"{API}/jobs", headers=admin, json={"name": "x", "job_type": "ai.image_to_3d", "params": {"reference_id": "ref_aaaaaaaaaaaa", "provider": "intel"}})
    assert missing.status_code == 404
    good = client.post(f"{API}/jobs", headers=admin, json={"name": "x", "job_type": "ai.image_to_3d", "params": {"reference_id": ok.json()["id"], "category": "prop", "provider": "intel"}})
    assert good.status_code == 201 and good.json()["requirements"]["features"] == ["ai.image_to_3d", "comfyui", "blender"]


_ = hashlib
