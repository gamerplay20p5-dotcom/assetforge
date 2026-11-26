"""Fixtures: a real FastAPI app on a real database (SQLite file by default, PostgreSQL if provided) and a
protocol-level fake worker that talks to the same HTTP endpoints the real worker uses."""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
from assetforge_api.config import Settings
from assetforge_api.main import create_app
from assetforge_export.pipeline import run_building_job
from fastapi.testclient import TestClient

ADMIN_PW = "test-admin-password-1"


def make_settings(tmp_path: Path, **over) -> Settings:
    pg = os.environ.get("ASSETFORGE_TEST_PG_URL")
    db = pg or f"sqlite:///{(tmp_path / 'db.sqlite3').as_posix()}"
    base = dict(env="test", database_url=db, storage_root=tmp_path / "storage", secret_key="k" * 40,
                admin_password=ADMIN_PW, lease_seconds=30, retry_backoff_seconds=0, default_max_attempts=2)
    base.update(over)
    return Settings(**base)


@pytest.fixture
def app(tmp_path):
    a = create_app(make_settings(tmp_path), start_reaper=False)
    yield a
    if os.environ.get("ASSETFORGE_TEST_PG_URL"):
        from assetforge_api.db import Base

        a.state.db.engine.dispose()
        import sqlalchemy as sa

        eng = sa.create_engine(a.state.db.engine.url)
        Base.metadata.drop_all(eng)
        eng.dispose()
    else:
        a.state.db.dispose()


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin(client):
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@dataclass
class FakeWorker:
    client: TestClient
    id: str
    headers: dict

    def lease(self):
        r = self.client.post("/api/v1/worker/lease", headers=self.headers)
        return None if r.status_code == 204 else r.json()

    def heartbeat(self, active=(), telemetry=None):
        r = self.client.post("/api/v1/worker/heartbeat", headers=self.headers,
                             json={"active_jobs": list(active), "telemetry": telemetry or {"cpu_percent": 5.0}})
        assert r.status_code == 200, r.text
        return r.json()

    def events(self, lease, events, plan=None):
        body = {"lease_token": lease["lease_token"], "events": events}
        if plan:
            body["plan"] = plan
        return self.client.post(f"/api/v1/worker/jobs/{lease['job_id']}/events", headers=self.headers, json=body)

    def upload(self, lease, rel, path: Path, sha: str | None = None):
        data = path.read_bytes()
        return self.client.put(f"/api/v1/worker/jobs/{lease['job_id']}/artifacts/{rel}", content=data,
                               headers={**self.headers, "X-Lease-Token": lease["lease_token"],
                                        "X-SHA256": sha or hashlib.sha256(data).hexdigest()})

    def complete(self, lease, result):
        return self.client.post(f"/api/v1/worker/jobs/{lease['job_id']}/complete", headers=self.headers,
                                json={"lease_token": lease["lease_token"], "result": result})

    def fail(self, lease, error="boom", retryable=True):
        return self.client.post(f"/api/v1/worker/jobs/{lease['job_id']}/fail", headers=self.headers,
                                json={"lease_token": lease["lease_token"], "error": error, "retryable": retryable})

    def run_real_pipeline(self, lease, workdir: Path):
        """Execute the actual generation pipeline (trimesh engine) and upload every file, like the real worker."""
        events: list[dict] = []
        result = run_building_job(lease["job"], workdir, events.append, engine="trimesh")
        for f in result["files"]:
            r = self.upload(lease, f["name"], workdir / "out" / f["name"])
            assert r.status_code == 201, r.text
        return result


@pytest.fixture
def make_worker(client, admin):
    def factory(name=None, kind="cpu", features=("procedural.building", "trimesh"), limits=None) -> FakeWorker:
        name = name or f"w-{uuid.uuid4().hex[:6]}"
        enr = client.post("/api/v1/workers/enrollment-tokens", headers=admin, json={"label": name}).json()["token"]
        r = client.post("/api/v1/worker/register", json={
            "enrollment_token": enr, "name": name, "kind": kind, "capabilities": {"features": list(features)},
            "limits": limits or {"max_concurrent_jobs": 1, "cpu_cores": 4, "ram_mb": 8192}})
        assert r.status_code == 201, r.text
        d = r.json()
        return FakeWorker(client, d["worker_id"], {"Authorization": f"Bearer {d['token']}"})

    return factory


@pytest.fixture
def job_body():
    def factory(name="Casa", **over):
        body = {"name": name, "params": {"category": "house", "seed": 1}, "formats": ["glb"]}
        body.update(over)
        return body

    return factory
