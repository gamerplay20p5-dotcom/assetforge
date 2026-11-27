import hashlib
import json
from io import BytesIO

from assetforge_api.models import Asset, AssetVersion
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
    lease = worker.lease()
    assert lease["job"]["version"] == 2
    route = f"/api/v1/worker/jobs/{lease['job_id']}/master"
    assert client.get(route, headers={**worker.headers, "X-Lease-Token": "invalid"}).status_code == 409
    downloaded = client.get(route, headers={**worker.headers, "X-Lease-Token": lease["lease_token"]})
    assert downloaded.status_code == 200
    assert downloaded.content == (source / "model.glb").read_bytes() == b"immutable source"
