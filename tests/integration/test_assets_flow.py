import hashlib
import json
import zipfile
from io import BytesIO

from assetforge_export.pipeline import run_building_job
from assetforge_validation import validate_glb

API = "/api/v1"


def _make_job(client, admin, body):
    r = client.post(f"{API}/jobs", headers=admin, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_full_flow_generates_registers_and_serves_a_real_asset(client, admin, make_worker, job_body, tmp_path):
    w = make_worker()
    job = _make_job(client, admin, job_body("Hospital", params={"category": "hospital", "style": "modern", "seed": 3}))
    lease = w.lease()
    # progress is only ever reported by the worker, per finished stage
    plan = [{"name": "generate_geometry", "weight": 1}, {"name": "export", "weight": 3}]
    w.events(lease, [{"type": "stage", "name": "generate_geometry", "status": "start"}], plan=plan)
    assert client.get(f"{API}/jobs/{job['id']}", headers=admin).json()["progress"] == 0.0
    w.events(lease, [{"type": "stage", "name": "generate_geometry", "status": "done"}])
    assert client.get(f"{API}/jobs/{job['id']}", headers=admin).json()["progress"] == 0.25

    result = w.run_real_pipeline(lease, tmp_path / "wd")
    resp = w.complete(lease, result)
    assert resp.status_code == 200, resp.text
    assert w.complete(lease, result).json().get("duplicate") is True  # idempotent

    done = client.get(f"{API}/jobs/{job['id']}", headers=admin).json()
    assert done["status"] == "succeeded" and done["progress"] == 1.0

    asset = client.get(f"{API}/assets/{job['asset_id']}", headers=admin).json()
    assert asset["current_version"] == 1 and asset["validation_passed"] and asset["triangle_count"] > 1000
    assert asset["manifest"]["category"] == "hospital" and asset["manifest"]["asset_id"] == asset["id"]
    assert {f["name"] for f in asset["files"]} >= {"model.glb", "thumbnail.png", "manifest.json", "validation.json"}

    # files really exist on disk, the download is byte-identical and a valid GLB
    glb = client.get(f"{API}/assets/{asset['id']}/files/model.glb", headers=admin)
    assert glb.status_code == 200 and glb.headers["content-type"] == "model/gltf-binary"
    assert glb.content == (tmp_path / "wd" / "out" / "model.glb").read_bytes()
    out = tmp_path / "dl.glb"
    out.write_bytes(glb.content)
    assert validate_glb(out).passed
    assert client.get(f"{API}/assets/{asset['id']}/files/thumbnail.png", headers=admin).content[:4] == b"\x89PNG"

    pkg = client.get(f"{API}/assets/{asset['id']}/package", headers=admin)
    names = set(zipfile.ZipFile(BytesIO(pkg.content)).namelist())
    assert {"model.glb", "manifest.json", "thumbnail.png"} <= names

    # the download token works for header-less requests (img/a/WebGL) and is not a login token
    tok = client.post(f"{API}/auth/download-token", headers=admin).json()["token"]
    assert client.get(f"{API}/assets/{asset['id']}/files/model.glb?token={tok}").status_code == 200
    assert client.get(f"{API}/jobs?token={tok}").status_code == 401

    z = client.post(f"{API}/assets/download", headers=admin, json={"asset_ids": [asset["id"]]})
    assert z.status_code == 200 and any(n.endswith("model.glb") for n in zipfile.ZipFile(BytesIO(z.content)).namelist())


def test_new_version_of_existing_asset_preserves_original(client, admin, make_worker, job_body, tmp_path):
    w = make_worker()
    j1 = _make_job(client, admin, job_body())
    l1 = w.lease()
    assert w.complete(l1, w.run_real_pipeline(l1, tmp_path / "a")).status_code == 200
    j2 = _make_job(client, admin, job_body(asset_id=j1["asset_id"], params={"category": "house", "seed": 2}))
    l2 = w.lease()
    assert l2["job"]["version"] == 2
    assert w.complete(l2, w.run_real_pipeline(l2, tmp_path / "b")).status_code == 200
    a = client.get(f"{API}/assets/{j1['asset_id']}", headers=admin).json()
    assert a["current_version"] == 2 and [v["version"] for v in a["versions"]] == [1, 2]
    v1 = client.get(f"{API}/assets/{j1['asset_id']}/files/model.glb?version=1", headers=admin).content
    v2 = client.get(f"{API}/assets/{j1['asset_id']}/files/model.glb?version=2", headers=admin).content
    assert v1 != v2 and v1 == (tmp_path / "a" / "out" / "model.glb").read_bytes()
    assert j2["asset_id"] == j1["asset_id"]


def test_complete_is_rejected_when_files_are_missing_or_corrupt(client, admin, make_worker, job_body, tmp_path):
    w = make_worker()
    job = _make_job(client, admin, job_body())
    lease = w.lease()
    result = run_building_job(lease["job"], tmp_path / "wd", lambda e: None, engine="trimesh")
    # 1) nothing uploaded -> completion must never be accepted when files do not exist
    r = w.complete(lease, result)
    assert r.status_code == 422 and "not uploaded" in r.text
    # 2) an upload with a wrong checksum is refused at upload time
    glb = tmp_path / "wd" / "out" / "model.glb"
    assert w.upload(lease, "model.glb", glb, sha="0" * 64).status_code == 422
    # 3) a corrupted GLB whose checksum matches the (forged) declaration is refused: the container is re-parsed
    for f in result["files"]:
        assert w.upload(lease, f["name"], tmp_path / "wd" / "out" / f["name"]).status_code == 201
    bad = tmp_path / "bad.glb"
    bad.write_bytes(b"glTF" + b"\x00" * 64)
    assert w.upload(lease, "model.glb", bad).status_code == 201
    forged = json.loads(json.dumps(result))
    for f in forged["files"]:
        if f["name"] == "model.glb":
            f["size"], f["sha256"] = bad.stat().st_size, hashlib.sha256(bad.read_bytes()).hexdigest()
    assert w.complete(lease, forged).status_code == 422
    assert client.get(f"{API}/jobs/{job['id']}", headers=admin).json()["status"] == "running"
    assert client.get(f"{API}/assets", headers=admin).json()["total"] == 0


def test_complete_rejected_when_worker_reports_failed_validation(client, admin, make_worker, job_body, tmp_path):
    w = make_worker()
    _make_job(client, admin, job_body())
    lease = w.lease()
    result = w.run_real_pipeline(lease, tmp_path / "wd")
    result["validation"]["passed"] = False
    assert w.complete(lease, result).status_code == 422


def test_upload_rejects_path_traversal_and_bad_extensions(client, admin, make_worker, job_body, tmp_path):
    w = make_worker()
    _make_job(client, admin, job_body())
    lease = w.lease()
    f = tmp_path / "x.png"
    f.write_bytes(b"x")
    for rel in ("../../evil.png", "..%2f..%2fevil.png", "a/../../evil.png", "run.exe", "a%5Cb.png"):
        r = w.upload(lease, rel, f)
        assert r.status_code in (400, 404, 422), (rel, r.status_code)
    assert not any(p.name.startswith("evil") for p in tmp_path.rglob("*"))


def test_asset_file_download_is_restricted_to_registered_files(client, admin, make_worker, job_body, tmp_path):
    w = make_worker()
    job = _make_job(client, admin, job_body())
    lease = w.lease()
    assert w.complete(lease, w.run_real_pipeline(lease, tmp_path / "wd")).status_code == 200
    aid = job["asset_id"]
    for rel in ("../../db.sqlite3", "model.glb/../../x", "secret.txt"):
        assert client.get(f"{API}/assets/{aid}/files/{rel}", headers=admin).status_code in (400, 404)


def test_library_search_filter_review_tags_favorites(client, admin, make_worker, job_body, tmp_path):
    w = make_worker()
    ids = []
    for i, (name, cat) in enumerate([("Casa A", "house"), ("Escola B", "school")]):
        j = _make_job(client, admin, job_body(name, params={"category": cat, "seed": i + 1}))
        lease = w.lease()
        assert w.complete(lease, w.run_real_pipeline(lease, tmp_path / f"w{i}")).status_code == 200
        ids.append(j["asset_id"])
    r = client.get(f"{API}/assets?category=school", headers=admin).json()
    assert [a["name"] for a in r["items"]] == ["Escola B"] and r["facets"]["category"] == {"house": 1, "school": 1}
    assert client.get(f"{API}/assets?q=casa", headers=admin).json()["total"] == 1
    client.patch(f"{API}/assets/{ids[0]}", headers=admin, json={"review_status": "approved", "favorite": True, "tags": ["lote", "lote", "residencial"]})
    a = client.get(f"{API}/assets/{ids[0]}", headers=admin).json()
    assert a["review_status"] == "approved" and a["favorite"] and a["tags"] == ["lote", "residencial"]
    assert client.get(f"{API}/assets?review_status=approved&favorite=true", headers=admin).json()["total"] == 1
    assert client.get(f"{API}/assets?tag=lote", headers=admin).json()["total"] == 1
