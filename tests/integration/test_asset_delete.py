"""Deleting assets from the library: rows and files go, space is reported, busy/unknown/forbidden cases are handled."""

from pathlib import Path

from assetforge_api.models import Asset, AssetVersion

API = "/api/v1"


def _asset(client, admin, make_worker, job_body, tmp_path, name):
    w = make_worker()
    job = client.post(f"{API}/jobs", headers=admin, json=job_body(name, params={"category": "house", "seed": 1})).json()
    lease = w.lease()
    result = w.run_real_pipeline(lease, tmp_path / name)
    assert w.complete(lease, result).status_code == 200
    return job["asset_id"]


def test_delete_removes_rows_and_files_and_reports_space(app, client, admin, make_worker, job_body, tmp_path):
    a1 = _asset(client, admin, make_worker, job_body, tmp_path, "Casa A")
    a2 = _asset(client, admin, make_worker, job_body, tmp_path, "Casa B")
    root: Path = app.state.storage.assets
    assert (root / a1).is_dir() and (root / a2).is_dir()
    size1 = app.state.storage.asset_bytes(a1)
    assert size1 > 0

    r = client.post(f"{API}/assets/delete", headers=admin, json={"asset_ids": [a1, "ast_nao_existe", a1]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] == [a1] and body["freed_bytes"] == size1  # duplicates counted once
    assert [s["id"] for s in body["skipped"]] == ["ast_nao_existe"]
    assert not (root / a1).exists() and (root / a2).is_dir()  # only the chosen one left the disk
    assert client.get(f"{API}/assets/{a1}", headers=admin).status_code == 404
    assert client.get(f"{API}/assets/{a2}", headers=admin).status_code == 200
    with app.state.db.session() as db:
        assert db.get(Asset, a1) is None and db.query(AssetVersion).filter_by(asset_id=a1).count() == 0

    one = client.delete(f"{API}/assets/{a2}", headers=admin)
    assert one.status_code == 200 and one.json()["deleted"] == [a2] and not (root / a2).exists()
    assert client.delete(f"{API}/assets/{a2}", headers=admin).status_code == 404
    audit = client.get(f"{API}/audit", headers=admin)
    if audit.status_code == 200:
        assert "asset.delete" in audit.text


def test_asset_with_a_running_job_is_not_deleted(app, client, admin, make_worker, job_body, tmp_path):
    a = _asset(client, admin, make_worker, job_body, tmp_path, "Casa C")
    w = make_worker()
    client.post(f"{API}/jobs", headers=admin, json=job_body("Casa C v2", asset_id=a, params={"category": "house", "seed": 2}))
    assert w.lease() is not None  # the new version is being generated
    r = client.post(f"{API}/assets/delete", headers=admin, json={"asset_ids": [a]}).json()
    assert r["deleted"] == [] and "andamento" in r["skipped"][0]["reason"]
    assert (app.state.storage.assets / a).is_dir()


def test_viewer_cannot_delete_and_ids_are_validated(client, admin, make_worker, job_body, tmp_path):
    a = _asset(client, admin, make_worker, job_body, tmp_path, "Casa D")
    client.post(f"{API}/auth/users", headers=admin, json={"username": "visitante", "password": "visitante-pass-1", "role": "viewer"})
    t = client.post(f"{API}/auth/login", json={"username": "visitante", "password": "visitante-pass-1"}).json()["access_token"]
    h = {"Authorization": f"Bearer {t}"}
    assert client.post(f"{API}/assets/delete", headers=h, json={"asset_ids": [a]}).status_code == 403
    assert client.delete(f"{API}/assets/{a}", headers=h).status_code == 403
    assert client.get(f"{API}/assets/{a}", headers=admin).status_code == 200
    bad = client.post(f"{API}/assets/delete", headers=admin, json={"asset_ids": ["../../etc"]}).json()
    assert bad["deleted"] == [] and bad["skipped"]  # a path-like id is skipped, nothing outside assets/ is touched
    assert client.post(f"{API}/assets/delete", headers=admin, json={"asset_ids": []}).status_code == 422
