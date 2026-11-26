from datetime import timedelta

from assetforge_api.db import utcnow
from assetforge_api.models import Job
from assetforge_api.scheduler import reap

API = "/api/v1"


def _job(client, admin, body):
    r = client.post(f"{API}/jobs", headers=admin, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _db_job(app, job_id) -> Job:
    with app.state.db.session() as s:
        return s.get(Job, job_id)


def _expire_lease(app, job_id):
    with app.state.db.session() as s:
        j = s.get(Job, job_id)
        j.lease_expires_at = utcnow() - timedelta(seconds=5)
        s.commit()


# ----------------------------------------------------------------------------- auth
def test_protected_endpoints_require_auth(client):
    for path in ("/jobs", "/assets", "/workers", "/dashboard/summary", "/queue/state"):
        assert client.get(f"{API}{path}").status_code == 401
    assert client.get(f"{API}/health").status_code == 200


def test_login_failure_and_throttle(client):
    for _ in range(8):
        assert client.post(f"{API}/auth/login", json={"username": "admin", "password": "nope"}).status_code == 401
    assert client.post(f"{API}/auth/login", json={"username": "admin", "password": "nope"}).status_code == 429


def test_viewer_cannot_mutate(client, admin, job_body):
    client.post(f"{API}/auth/users", headers=admin, json={"username": "viewer1", "password": "viewer-password-1", "role": "viewer"})
    tok = client.post(f"{API}/auth/login", json={"username": "viewer1", "password": "viewer-password-1"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get(f"{API}/jobs", headers=h).status_code == 200
    assert client.post(f"{API}/jobs", headers=h, json=job_body()).status_code == 403
    assert client.post(f"{API}/workers/enrollment-tokens", headers=h, json={}).status_code == 403


def test_worker_token_cannot_call_admin_api_and_vice_versa(client, admin, make_worker):
    w = make_worker()
    assert client.get(f"{API}/jobs", headers=w.headers).status_code == 401
    assert client.post(f"{API}/worker/lease", headers=admin).status_code == 401


def test_enrollment_token_is_single_use(client, admin):
    enr = client.post(f"{API}/workers/enrollment-tokens", headers=admin, json={}).json()["token"]
    body = {"enrollment_token": enr, "name": "node-a", "kind": "cpu", "capabilities": {}, "limits": {}}
    assert client.post(f"{API}/worker/register", json=body).status_code == 201
    assert client.post(f"{API}/worker/register", json={**body, "name": "node-b"}).status_code == 401
    assert client.post(f"{API}/worker/register", json={**body, "enrollment_token": "enr_bogus"}).status_code == 401


def test_nvidia_kind_is_not_accepted(client, admin):
    enr = client.post(f"{API}/workers/enrollment-tokens", headers=admin, json={}).json()["token"]
    r = client.post(f"{API}/worker/register", json={"enrollment_token": enr, "name": "n", "kind": "nvidia"})
    assert r.status_code == 422


# ----------------------------------------------------------------------------- scheduling
def test_only_one_worker_gets_a_job(client, admin, make_worker, job_body):
    a, b = make_worker(), make_worker()
    _job(client, admin, job_body())
    leases = [a.lease(), b.lease()]
    assert sum(1 for x in leases if x) == 1


def test_priority_order_and_fifo(client, admin, make_worker, job_body):
    w = make_worker()
    low = _job(client, admin, job_body("low", priority=0))
    high = _job(client, admin, job_body("high", priority=5))
    low2 = _job(client, admin, job_body("low2", priority=0))
    order = []
    for _ in range(3):
        lease = w.lease()
        order.append(lease["job_id"])
        w.fail(lease, retryable=False)
    assert order == [high["id"], low["id"], low2["id"]]


def test_capability_matching_blender_jobs_need_blender_workers(client, admin, make_worker, job_body):
    plain = make_worker(features=("procedural.building", "trimesh"))
    job = _job(client, admin, job_body(formats=["glb", "fbx"]))
    assert job["id"]
    assert plain.lease() is None  # no blender -> never leased
    blender = make_worker(features=("procedural.building", "trimesh", "blender"))
    assert blender.lease()["job_id"] == job["id"]


def test_pinned_worker(client, admin, make_worker, job_body):
    a, b = make_worker(), make_worker()
    job = _job(client, admin, job_body(worker_id=b.id))
    assert a.lease() is None
    assert b.lease()["job_id"] == job["id"]


def test_resource_reservation_limits_concurrency(client, admin, make_worker, job_body):
    for i in range(3):
        _job(client, admin, job_body(f"j{i}", formats=["glb", "fbx"]))  # blender jobs reserve 2 cores each
    bw = make_worker(features=("procedural.building", "blender"), limits={"max_concurrent_jobs": 2, "cpu_cores": 2, "ram_mb": 8192})
    assert bw.lease() is not None
    assert bw.lease() is None  # 2 cores already reserved by the first job


def test_scheduled_job_waits_until_not_before(client, admin, make_worker, job_body):
    w = make_worker()
    future = (utcnow() + timedelta(hours=1)).isoformat()
    j = _job(client, admin, job_body(scheduled_at=future))
    assert j["state"] == "scheduled" and w.lease() is None


def test_dependencies_block_then_release(client, admin, make_worker, job_body, tmp_path):
    w = make_worker()
    first = _job(client, admin, job_body("first"))
    second = _job(client, admin, job_body("second", depends_on=[first["id"]], priority=50))
    assert second["state"] == "blocked"
    lease = w.lease()
    assert lease["job_id"] == first["id"]  # the higher-priority job is blocked, so its dependency runs first
    result = w.run_real_pipeline(lease, tmp_path / "wd")
    assert w.complete(lease, result).status_code == 200
    assert w.lease()["job_id"] == second["id"]  # released once the dependency succeeded


def test_failed_dependency_fails_dependents(app, client, admin, make_worker, job_body):
    w = make_worker()
    first = _job(client, admin, job_body("first"))
    second = _job(client, admin, job_body("second", depends_on=[first["id"]]))
    lease = w.lease()
    w.fail(lease, "deterministic", retryable=False)
    with app.state.db.session() as s:
        reap(s, app.state.settings)
    j2 = client.get(f"{API}/jobs/{second['id']}", headers=admin).json()
    assert j2["status"] == "failed" and "dependency" in j2["error"]


def test_queue_pause_and_resume(client, admin, make_worker, job_body):
    w = make_worker()
    _job(client, admin, job_body())
    client.post(f"{API}/queue/pause", headers=admin)
    assert w.lease() is None and w.heartbeat()["queue_paused"] is True
    client.post(f"{API}/queue/resume", headers=admin)
    assert w.lease() is not None


def test_disabled_and_maintenance_workers_get_no_jobs(client, admin, make_worker, job_body):
    w = make_worker()
    _job(client, admin, job_body())
    for state in ("disabled", "maintenance"):
        assert client.patch(f"{API}/workers/{w.id}", headers=admin, json={"state": state}).status_code == 200
        assert w.lease() is None
    client.patch(f"{API}/workers/{w.id}", headers=admin, json={"state": "enabled"})
    assert w.lease() is not None


def test_worker_limits_validation(client, admin, make_worker):
    w = make_worker()
    assert client.patch(f"{API}/workers/{w.id}", headers=admin, json={"limits": {"cpu_cores": 2}}).status_code == 200
    assert client.patch(f"{API}/workers/{w.id}", headers=admin, json={"limits": {"rm_rf": 1}}).status_code == 422
    assert client.patch(f"{API}/workers/{w.id}", headers=admin, json={"limits": {"ram_mb": -1}}).status_code == 422


# ----------------------------------------------------------------------------- cancel / retry / recovery
def test_cancel_queued_job_is_immediate(client, admin, job_body):
    j = _job(client, admin, job_body())
    assert client.post(f"{API}/jobs/{j['id']}/cancel", headers=admin).json()["status"] == "cancelled"
    assert client.post(f"{API}/jobs/{j['id']}/cancel", headers=admin).status_code == 409


def test_cooperative_cancel_of_running_job(client, admin, make_worker, job_body):
    w = make_worker()
    j = _job(client, admin, job_body())
    lease = w.lease()
    client.post(f"{API}/jobs/{j['id']}/cancel", headers=admin)
    hb = w.heartbeat(active=[j["id"]])
    assert hb["cancel"] == [j["id"]]
    assert client.get(f"{API}/jobs/{j['id']}", headers=admin).json()["state"] == "cancelling"
    assert w.events(lease, []).json()["cancel_requested"] is True
    r = client.post(f"{API}/worker/jobs/{j['id']}/cancelled", headers=w.headers, json={"lease_token": lease["lease_token"]})
    assert r.json()["status"] == "cancelled"


def test_wrong_lease_token_is_rejected(client, admin, make_worker, job_body):
    a, b = make_worker(), make_worker()
    _job(client, admin, job_body())
    lease = a.lease()
    bad = {**lease, "lease_token": "0" * 48}
    assert a.events(bad, []).status_code == 409
    assert b.events(lease, []).status_code == 409  # another worker with the right token still cannot act
    assert a.fail(bad).status_code == 409


def test_failure_retries_then_gives_up(client, admin, make_worker, job_body):
    w = make_worker()
    j = _job(client, admin, job_body())
    w.fail(w.lease(), "transient")
    mid = client.get(f"{API}/jobs/{j['id']}", headers=admin).json()
    assert mid["status"] == "queued" and mid["state"] == "retrying" and mid["attempts"] == 1
    w.fail(w.lease(), "transient again")
    end = client.get(f"{API}/jobs/{j['id']}", headers=admin).json()
    assert end["status"] == "failed" and end["attempts"] == 2
    assert [a["outcome"] for a in end["attempt_history"]] == ["failed", "failed"]
    logs = client.get(f"{API}/jobs/{j['id']}/logs", headers=admin).json()["items"]
    assert any("Retrying" in l["message"] for l in logs) and any("failed after" in l["message"] for l in logs)


def test_abandoned_job_is_detected_and_requeued(app, client, admin, make_worker, job_body):
    w = make_worker()
    j = _job(client, admin, job_body())
    lease = w.lease()
    _expire_lease(app, j["id"])
    with app.state.db.session() as s:
        assert reap(s, app.state.settings)["abandoned"] == 1
    job = client.get(f"{API}/jobs/{j['id']}", headers=admin).json()
    assert job["status"] == "queued" and job["attempt_history"][0]["outcome"] == "abandoned"
    # the zombie worker can no longer act on the old lease
    assert w.events(lease, []).status_code == 409
    # a healthy worker picks it up again; after max_attempts it is failed for good
    w.lease()
    _expire_lease(app, j["id"])
    with app.state.db.session() as s:
        reap(s, app.state.settings)
    assert client.get(f"{API}/jobs/{j['id']}", headers=admin).json()["status"] == "failed"


def test_heartbeat_extends_lease_and_reports_lost_jobs(app, client, admin, make_worker, job_body):
    w = make_worker()
    j = _job(client, admin, job_body())
    w.lease()
    _expire_lease(app, j["id"])
    assert w.heartbeat(active=[j["id"]])["lost"] == []
    with app.state.db.session() as s:
        assert reap(s, app.state.settings)["abandoned"] == 0  # lease was extended
    assert w.heartbeat(active=["job_does_not_exist"])["lost"] == ["job_does_not_exist"]


def test_queue_survives_api_restart(tmp_path, job_body):
    """State is in the database: a brand-new app instance (a 'restart') sees queued and running jobs."""
    from assetforge_api.main import create_app
    from fastapi.testclient import TestClient
    from conftest import make_settings

    settings = make_settings(tmp_path)
    app1 = create_app(settings, start_reaper=False)
    with TestClient(app1) as c1:
        h = {"Authorization": "Bearer " + c1.post(f"{API}/auth/login", json={"username": "admin", "password": "test-admin-password-1"}).json()["access_token"]}
        enr = c1.post(f"{API}/workers/enrollment-tokens", headers=h, json={}).json()["token"]
        reg = c1.post(f"{API}/worker/register", json={"enrollment_token": enr, "name": "w-restart", "capabilities": {"features": ["procedural.building"]}, "limits": {}}).json()
        wh = {"Authorization": f"Bearer {reg['token']}"}
        ids = [c1.post(f"{API}/jobs", headers=h, json=job_body(f"j{i}")).json()["id"] for i in range(3)]
        leased = c1.post(f"{API}/worker/lease", headers=wh).json()
    app1.state.db.dispose()

    app2 = create_app(settings, start_reaper=False)  # restart
    with TestClient(app2) as c2:
        h2 = {"Authorization": "Bearer " + c2.post(f"{API}/auth/login", json={"username": "admin", "password": "test-admin-password-1"}).json()["access_token"]}
        jobs = {j["id"]: j for j in c2.get(f"{API}/jobs", headers=h2).json()["items"]}
        assert set(jobs) == set(ids)
        assert jobs[leased["job_id"]]["status"] == "running"
        assert sum(1 for j in jobs.values() if j["status"] == "queued") == 2
        # the worker (same credentials) keeps working against the restarted server
        hb = c2.post(f"{API}/worker/heartbeat", headers=wh, json={"active_jobs": [leased["job_id"]]}).json()
        assert hb["lost"] == []
        assert c2.post(f"{API}/worker/lease", headers=wh).status_code in (200, 204)
    app2.state.db.dispose()


def test_idempotency_key_prevents_duplicates(client, admin, job_body):
    a = _job(client, admin, job_body(idempotency_key="same-request"))
    b = _job(client, admin, job_body(idempotency_key="same-request"))
    assert a["id"] == b["id"] and client.get(f"{API}/jobs", headers=admin).json()["total"] == 1


# ----------------------------------------------------------------------------- batches
def test_batch_of_variations_creates_traceable_jobs(client, admin):
    r = client.post(f"{API}/batches", headers=admin, json={"name": "10 casas", "count": 10, "seed_start": 100,
                                                          "template": {"name": "Casa", "params": {"category": "house"}}})
    assert r.status_code == 201
    batch = client.get(f"{API}/batches/{r.json()['id']}", headers=admin).json()
    assert batch["total"] == 10 and batch["counts"] == {"queued": 10}
    assert sorted(j["seed"] for j in batch["jobs"]) == list(range(100, 110))
    assert len({j["asset_id"] for j in batch["jobs"]}) == 10
    assert client.post(f"{API}/batches/{batch['id']}/cancel", headers=admin).json()["cancelled"] == 10


def test_batch_validation_errors_are_reported(client, admin):
    r = client.post(f"{API}/batches", headers=admin, json={"name": "x", "items": [{"name": "ok"}, {"name": "bad", "params": {"category": "castle"}}]})
    assert r.status_code == 422
    assert client.get(f"{API}/jobs", headers=admin).json()["total"] == 0  # nothing half-created


def test_priority_patch_and_retry_creates_new_job(client, admin, make_worker, job_body):
    w = make_worker()
    j = _job(client, admin, job_body())
    assert client.patch(f"{API}/jobs/{j['id']}", headers=admin, json={"priority": 7}).json()["priority"] == 7
    lease = w.lease()
    assert client.patch(f"{API}/jobs/{j['id']}", headers=admin, json={"priority": 1}).status_code == 409
    w.fail(lease, "x", retryable=False)
    new = client.post(f"{API}/jobs/{j['id']}/retry", headers=admin).json()
    assert new["id"] != j["id"] and new["retry_of"] == j["id"] and new["asset_id"] == j["asset_id"]


def test_dashboard_summary_is_real(client, admin, make_worker, job_body):
    w = make_worker()
    w.heartbeat(telemetry={"cpu_percent": 42.0, "ram_used_mb": 1000, "ram_total_mb": 4000, "gpus": []})
    _job(client, admin, job_body())
    s = client.get(f"{API}/dashboard/summary", headers=admin).json()
    assert s["jobs"]["queued"] == 1 and s["workers"]["online"] == 1 and s["resources"]["cpu_percent"] == 42.0
    assert s["resources"]["gpu_percent"] is None and s["storage"]["free_bytes"] > 0 and len(s["history"]) == 24


def test_plan_endpoint(client, admin):
    r = client.post(f"{API}/plan", headers=admin, json={"description": "hospital moderno de cinco andares"})
    assert r.status_code == 200 and r.json()["params"]["floors"] == 5 and r.json()["source"] == "rules"


def test_health_ready(client):
    r = client.get(f"{API}/health/ready")
    assert r.status_code == 200 and r.json()["checks"] == {"database": "ok", "storage": "ok"}

