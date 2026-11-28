import base64
import hashlib
import json
from io import BytesIO
from types import SimpleNamespace

from assetforge_api.models import Asset, AssetVersion
from assetforge_api.routers import assets
from assetforge_contract.engines import ENGINES, ReconstructionParams
from assetforge_worker.engine_job import cpp_command, prepare_views
from PIL import Image


def test_replay_retains_prepared_inputs_and_native_flags(client, app, admin, tmp_path):
    views = ENGINES["pixal3d-mv"]["views"]
    refs = {}
    work = tmp_path / "output"
    work.mkdir()
    for index, view in enumerate(views):
        image = BytesIO()
        Image.new("RGBA", (16, 16), (index, 50, 90, 0)).save(image, "PNG")
        data = image.getvalue()
        ref = "ref_" + hashlib.sha256(data).hexdigest()[:12]
        refs[view] = ref
        directory = app.state.storage.root / "references"
        directory.mkdir(exist_ok=True)
        (directory / f"{ref}.png").write_bytes(data)
        (work / f"{view}.png").write_bytes(data)
    pose = [[1, 0, 0, 0], [0, 0, -1, -3.119], [0, 1, 0, 0], [0, 0, 0, 1]]
    params = {"engine": "pixal3d-mv", "category": "building", "references": refs,
              "prepared_inputs": True, "resolution": 1536, "seed": 7, "skip_decimation": False,
              "use_native_threads": True, "structure_guidance": None, "shape_guidance": None,
              "archived_projection": {"camera_angle_x": 0.349, "transforms": {view: pose for view in views}}}
    response = client.post("/api/v1/jobs", headers=admin, json={
        "name": "Replay", "job_type": "experimental.reconstruct", "params": params,
    })
    assert response.status_code == 201, response.text
    job = response.json()
    assert "engine.archive-inputs" in job["requirements"]["features"]
    validated = ReconstructionParams.model_validate(job["params"])
    folder, report = prepare_views(work, validated, lambda _: None)
    assert report["archived_inputs"]
    assert json.loads((folder / "transforms.json").read_text())["frames"][3]["transform_matrix"] == pose
    for index, view in enumerate(views):
        assert (folder / f"view{index}.png").read_bytes() == (work / f"{view}.png").read_bytes()
    command = cpp_command(work, work / "model.glb", validated, folder, 4)
    assert command[command.index("--seed") + 1] == "7"
    assert not set(command) & {"--threads", "--decim", "--gss", "--gsh"}


def test_text_reconstruction_requires_the_image_generation_runtime(client, admin, make_worker):
    worker = make_worker(kind="nvidia", features=("engine.trellis2-gguf",))
    payload = {"name": "Machine", "job_type": "experimental.reconstruct", "params": {
        "engine": "trellis2-gguf", "category": "prop", "references": {}, "prompt": "  Retro vending machine  ",
    }}
    assert client.post("/api/v1/jobs", headers=admin, json={**payload, "worker_id": worker.id}).status_code == 422
    answer = client.post("/api/v1/jobs", headers=admin, json=payload)
    assert answer.status_code == 201, answer.text
    assert "engine.text-reference" in answer.json()["requirements"]["features"]
    assert answer.json()["params"]["prompt"] == "Retro vending machine"
    assert worker.lease() is None


def test_studio_dispatches_reference_and_reconstruction_to_different_workers(client, admin, make_worker, tmp_path):
    spark = make_worker("Spark", kind="nvidia", features=("engine.split-reference",))
    gpu = make_worker("Compute", kind="nvidia", features=("engine.trellis2-gguf",))
    waiting = make_worker("Maintenance", kind="nvidia", features=("engine.trellis2-gguf",))
    sample = {"temperature_c": 47, "ram_total_mb": 120000, "ram_available_mb": 116000,
              "vram_total_mb": 24576, "vram_free_mb": 23300, "utilization_percent": 3}
    spark.heartbeat(telemetry={"engine_gpu": {**sample, "unified": True}})
    for worker in (gpu, waiting):
        worker.heartbeat(telemetry={"engine_gpu": sample})
    assert client.patch(f"/api/v1/workers/{waiting.id}", headers=admin, json={"state": "maintenance"}).status_code == 200
    recommendation = client.get("/api/v1/engines/recommend?mode=text&category=prop&resolution=1024", headers=admin)
    assert recommendation.json() == {"engine": "trellis2-gguf", "worker": {"id": gpu.id, "name": "Compute"}}

    payload = {"name": "Studio", "job_type": "experimental.reconstruct", "worker_id": gpu.id, "params": {
        "engine": "trellis2-gguf", "category": "prop", "references": {}, "prompt": "Retro vending machine",
    }}
    first = client.post("/api/v1/studio/text", headers=admin, json=payload)
    assert first.status_code == 201, first.text
    child = first.json()
    source_id, = child["depends_on"]
    assert gpu.lease() is None
    lease = spark.lease()
    assert lease["job_id"] == source_id and lease["job"]["job_type"] == "reference.generate"

    png = tmp_path / "reference.png"
    Image.new("RGB", (1024, 1024), "yellow").save(png)
    digest = hashlib.sha256(png.read_bytes()).hexdigest()
    assert spark.upload(lease, "reference.png", png).status_code == 201
    result = {"files": [{"name": "reference.png", "sha256": digest, "size": png.stat().st_size}]}
    saved = spark.complete(lease, result)
    assert saved.status_code == 200, saved.text
    assert spark.complete(lease, result).json()["duplicate"]
    reference_id = saved.json()["reference_id"]
    assert client.get(f"/api/v1/worker/references/{reference_id}", headers=gpu.headers).content == png.read_bytes()
    assert waiting.lease() is None
    reconstruction = gpu.lease()
    assert reconstruction["job_id"] == child["id"]
    assert reconstruction["job"]["params"]["references"] == {"front": reference_id}
    assert "prompt" not in reconstruction["job"]["params"]
    assert reconstruction["job"]["params"]["skip_decimation"]
    replay = client.post("/api/v1/studio/text", headers=admin, json=payload).json()
    assert replay["id"] != child["id"]
    assert replay["depends_on"] == [source_id]
    assert spark.lease() is None


def test_preparation_master_requires_the_lease_and_preserves_source(client, app, admin, make_worker):
    asset_id = "ast_archive_test"
    with app.state.db.session() as db:
        db.add(Asset(id=asset_id, name="Source", category="building", current_version=1))
        db.flush()
        db.add(AssetVersion(asset_id=asset_id, version=1, files=[{"name": "model.glb"}],
                            manifest={"category": "building", "generator_id": "experimental.reconstruct"}))
        db.commit()
    source = app.state.storage.asset_dir(asset_id, 1)
    source.mkdir(parents=True)
    (source / "model.glb").write_bytes(b"immutable source")
    worker = make_worker(features=("asset.prepare", "blender"))
    response = client.post("/api/v1/jobs", headers=admin, json={
        "name": "Derivado", "job_type": "asset.prepare", "asset_id": asset_id,
        "params": {"category": "building", "source_version": 1, "height_m": 30},
    })
    assert response.status_code == 201, response.text
    duplicate = client.post("/api/v1/jobs", headers=admin, json={
        "name": "Derivado", "job_type": "asset.prepare", "asset_id": asset_id,
        "params": {"category": "building", "source_version": 1, "height_m": 30},
    })
    assert duplicate.json()["id"] == response.json()["id"]
    lease = worker.lease()
    assert lease["job"]["version"] == 2
    route = f"/api/v1/worker/jobs/{lease['job_id']}/master"
    assert client.get(route, headers={**worker.headers, "X-Lease-Token": "invalid"}).status_code == 409
    downloaded = client.get(route, headers={**worker.headers, "X-Lease-Token": lease["lease_token"]})
    assert downloaded.status_code == 200
    assert downloaded.content == (source / "model.glb").read_bytes() == b"immutable source"


def test_gemini_review_uses_the_original_reference(client, app, admin, monkeypatch):
    def png(color):
        buffer = BytesIO()
        Image.new("RGB", (16, 16), color).save(buffer, "PNG")
        return buffer.getvalue()

    original, prepared = png("green"), png("red")
    refs = app.state.storage.root / "references"
    refs.mkdir(exist_ok=True)
    originals_id, prepared_id = "ref_a12345678901", "ref_b12345678901"
    (refs / f"{originals_id}.png").write_bytes(original)
    (refs / f"{prepared_id}.png").write_bytes(prepared)
    aid = "ast_original_ref"
    with app.state.db.session() as db:
        db.add(Asset(id=aid, name="Archive", category="building", current_version=1))
        db.flush()
        db.add(AssetVersion(asset_id=aid, version=1, manifest={"generation_params": {
            "original_references": {"front": originals_id}, "references": {"front": prepared_id},
        }}))
        db.commit()

    def review(self, task, system, prompt, images, *args, **kwargs):
        assert images[0] == assets.evaluation_image(original)
        assert len(images) == 2
        return SimpleNamespace(data={"overall": 7}, provider="gemini", model="stub", cached=False)

    monkeypatch.setattr(assets.AiRouter, "generate_json", review)
    response = client.post(f"/api/v1/assets/{aid}/versions/1/evaluate", headers=admin, json={
        "renders": [base64.b64encode(prepared).decode()],
    })
    assert response.status_code == 200, response.text
    assert response.json()["overall"] == 7
