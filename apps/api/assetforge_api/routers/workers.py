"""Worker administration (admin UI) and the worker-facing protocol (register, heartbeat, lease, events, upload)."""

from __future__ import annotations

import hashlib
import json
import secrets
import shutil
from datetime import timedelta
from pathlib import Path

from assetforge_validation import read_glb_json
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Asset, AssetVersion, EnrollmentToken, Job, JobLog, User, Worker
from ..scheduler import (
    fail_or_retry,
    mark_cancelled_ack,
    mark_succeeded,
    try_lease,
)
from ..schemas import (
    CompleteIn,
    EnrollmentCreate,
    EventsIn,
    FailIn,
    Heartbeat,
    TokenOnly,
    WorkerPatch,
    WorkerRegister,
    worker_out,
)
from ..security import (
    current_worker,
    get_db,
    hash_token,
    new_token,
    require_admin,
    require_viewer,
)
from ..services import audit, emit_event
from ..storage import UnsafePath, safe_join, validate_relative

admin_router = APIRouter(prefix="/workers", tags=["workers"])
worker_router = APIRouter(prefix="/worker", tags=["worker-protocol"])

REQUIRED_FILES = {"model.glb", "thumbnail.png", "manifest.json", "validation.json"}


# =============================================================================== admin
@admin_router.get("", dependencies=[Depends(require_viewer)])
def list_workers(request: Request, db: Session = Depends(get_db)) -> list[dict]:
    s = request.app.state.settings
    return [worker_out(db, w, s) for w in db.scalars(select(Worker).order_by(Worker.name))]


@admin_router.post("/enrollment-tokens", status_code=201)
def create_enrollment(body: EnrollmentCreate, request: Request, admin: User = Depends(require_admin),
                      db: Session = Depends(get_db)) -> dict:
    """The plaintext token is returned ONCE; only its hash is stored."""
    token = new_token("enr")
    expires = utcnow() + timedelta(hours=body.hours)
    row = EnrollmentToken(token_hash=hash_token(token), label=body.label, expires_at=expires, created_by=admin.username)
    db.add(row)
    audit(db, admin.username, "worker.enrollment_token", "enrollment", row.id, label=body.label)
    db.commit()
    return {"id": row.id, "token": token, "expires_at": expires.isoformat(), "label": body.label}


@admin_router.get("/{worker_id}", dependencies=[Depends(require_viewer)])
def get_worker(worker_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    w = db.get(Worker, worker_id)
    if not w:
        raise HTTPException(404, "worker not found")
    return worker_out(db, w, request.app.state.settings, detail=True)


@admin_router.patch("/{worker_id}")
def patch_worker(worker_id: str, body: WorkerPatch, request: Request, admin: User = Depends(require_admin),
                 db: Session = Depends(get_db)) -> dict:
    w = db.get(Worker, worker_id)
    if not w:
        raise HTTPException(404, "worker not found")
    changes = {}
    if body.state is not None:
        w.state = body.state
        changes["state"] = body.state
    if body.limits is not None:
        allowed = {"max_concurrent_jobs", "cpu_cores", "ram_mb", "vram_mb"}
        bad = set(body.limits) - allowed
        if bad:
            raise HTTPException(422, f"unknown limit keys: {sorted(bad)}")
        if any((not isinstance(v, (int, float))) or v < 0 for v in body.limits.values()):
            raise HTTPException(422, "limits must be non-negative numbers")
        w.limits = {**(w.limits or {}), **body.limits}
        changes["limits"] = body.limits
    audit(db, admin.username, "worker.update", "worker", w.id, **changes)
    emit_event(db, "worker.updated", w.id, **changes)
    db.commit()
    return worker_out(db, w, request.app.state.settings)


@admin_router.delete("/{worker_id}", status_code=204)
def delete_worker(worker_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> Response:
    w = db.get(Worker, worker_id)
    if not w:
        raise HTTPException(404, "worker not found")
    if db.scalar(select(Job.id).where(Job.worker_id == w.id, Job.status == "running").limit(1)):
        raise HTTPException(409, "worker has running jobs; disable it and wait for them to finish")
    audit(db, admin.username, "worker.delete", "worker", w.id, name=w.name)
    db.delete(w)
    db.commit()
    return Response(status_code=204)


# =============================================================================== worker protocol
@worker_router.post("/register", status_code=201)
def register(body: WorkerRegister, request: Request, db: Session = Depends(get_db)) -> dict:
    s = request.app.state.settings
    tok = db.execute(select(EnrollmentToken).where(EnrollmentToken.token_hash == hash_token(body.enrollment_token))
                     ).scalar_one_or_none()
    now = utcnow()
    if tok is None or tok.used_at is not None or tok.expires_at < now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid, expired or already used enrollment token")
    token = new_token("wkr")
    existing = db.execute(select(Worker).where(Worker.name == body.name)).scalar_one_or_none()
    if existing is not None:
        if db.scalar(select(Job.id).where(Job.worker_id == existing.id, Job.status == "running").limit(1)):
            raise HTTPException(409, "a worker with this name has running jobs")
        worker = existing  # re-enrollment rotates the credentials of the same logical worker
        worker.token_hash = hash_token(token)
    else:
        worker = Worker(name=body.name, token_hash=hash_token(token))
        db.add(worker)
    worker.kind, worker.hostname, worker.version = body.kind, body.hostname, body.version
    worker.address = body.address or (request.client.host if request.client else "")
    worker.capabilities = body.capabilities
    worker.limits = {"max_concurrent_jobs": 1, **body.limits} if existing is None else {**(worker.limits or {}), **body.limits}
    worker.last_heartbeat = now
    db.flush()
    tok.used_at, tok.used_by_worker_id = now, worker.id
    audit(db, "worker:" + worker.name, "worker.register", "worker", worker.id, kind=body.kind)
    emit_event(db, "worker.registered", worker.id, name=worker.name)
    db.commit()
    return {"worker_id": worker.id, "token": token, "heartbeat_seconds": s.heartbeat_seconds,
            "lease_seconds": s.lease_seconds, "limits": worker.limits}


@worker_router.post("/heartbeat")
def heartbeat(body: Heartbeat, request: Request, worker: Worker = Depends(current_worker),
              db: Session = Depends(get_db)) -> dict:
    s = request.app.state.settings
    now = utcnow()
    worker.last_heartbeat = now
    worker.telemetry = body.telemetry
    if body.capabilities is not None:
        worker.capabilities = body.capabilities
    worker.address = body.address or worker.address or (request.client.host if request.client else "")
    mine = {j.id: j for j in db.scalars(select(Job).where(Job.worker_id == worker.id, Job.status == "running"))}
    lost = [jid for jid in body.active_jobs if jid not in mine]
    for jid in body.active_jobs:
        if jid in mine:
            mine[jid].lease_expires_at = now + timedelta(seconds=s.lease_seconds)
    cancel = [j.id for j in mine.values() if j.cancel_requested]
    from ..services import get_setting

    paused = bool(get_setting(db, "queue_paused", False))
    db.commit()
    return {"state": worker.state, "queue_paused": paused, "cancel": cancel, "lost": lost,
            "server_time": now.isoformat()}


@worker_router.post("/lease")
def lease(request: Request, worker: Worker = Depends(current_worker), db: Session = Depends(get_db)):
    s = request.app.state.settings
    if worker.kind != "nvidia":
        worker.last_heartbeat = utcnow()
    job = try_lease(db, worker, s)
    db.commit()
    if job is None:
        return Response(status_code=204)
    return {
        "job_id": job.id, "lease_token": job.lease_token, "attempt": job.attempts, "lease_seconds": s.lease_seconds,
        "job": {"job_id": job.id, "asset_id": job.asset_id, "name": job.name, "version": job.asset_version,
                "job_type": job.job_type, "params": job.params, "quality_profile": job.quality_profile,
                "triangle_limit": job.triangle_limit, "formats": job.formats, "requirements": job.requirements},
    }


def _lease_job(db: Session, job_id: str, worker: Worker, token: str, *, need_running: bool = True) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    if job.worker_id != worker.id or not job.lease_token or not secrets.compare_digest(job.lease_token, token):
        raise HTTPException(409, "lease mismatch: this job is not leased to you (anymore)")
    if need_running and job.status != "running":
        raise HTTPException(409, f"job is {job.status}, not running")
    return job


@worker_router.post("/jobs/{job_id}/events")
def post_events(job_id: str, body: EventsIn, request: Request, worker: Worker = Depends(current_worker),
                db: Session = Depends(get_db)) -> dict:
    s = request.app.state.settings
    job = _lease_job(db, job_id, worker, body.lease_token)
    now = utcnow()
    job.lease_expires_at = now + timedelta(seconds=s.lease_seconds)
    if body.plan is not None:
        job.plan = [{"name": p.name, "weight": p.weight} for p in body.plan]
    stages = dict(job.stages or {})
    for ev in body.events:
        if ev.type == "log" and ev.message:
            db.add(JobLog(job_id=job.id, attempt_no=job.attempts, level=ev.level, source="worker",
                          message=ev.message[:2000]))
        elif ev.type == "stage" and ev.name and ev.status:
            st = dict(stages.get(ev.name, {}))
            if ev.status == "start":
                st.update(status="running", started_at=now.isoformat())
                job.current_stage = ev.name
            elif ev.status == "done":
                st.update(status="done", finished_at=now.isoformat(), detail=ev.detail)
            else:
                st.update(status="failed", finished_at=now.isoformat(), detail=ev.detail)
            stages[ev.name] = st
    job.stages = stages
    plan = job.plan or []
    total = sum(p["weight"] for p in plan) or 0
    if total:  # progress only counts stages that actually finished
        done = sum(p["weight"] for p in plan if stages.get(p["name"], {}).get("status") == "done")
        job.progress = min(done / total, 0.99)
    db.commit()
    return {"cancel_requested": job.cancel_requested}


@worker_router.put("/jobs/{job_id}/artifacts/{path:path}", status_code=201)
async def upload_artifact(job_id: str, path: str, request: Request, worker: Worker = Depends(current_worker),
                          db: Session = Depends(get_db), x_lease_token: str = Header(...),
                          x_sha256: str = Header(..., description="hex SHA-256 of the body")) -> dict:
    s = request.app.state.settings
    storage = request.app.state.storage
    job = await run_in_threadpool(_lease_job, db, job_id, worker, x_lease_token)
    try:
        validate_relative(path)
        target = safe_join(storage.staging_dir(job.id, job.attempts), path)
    except UnsafePath as exc:
        raise HTTPException(400, str(exc)) from exc
    declared = request.headers.get("content-length")
    limit = s.max_upload_mb * 1024 * 1024
    if declared and int(declared) > limit:
        raise HTTPException(413, f"file larger than {s.max_upload_mb} MB")
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    h, size = hashlib.sha256(), 0
    with part.open("wb") as fh:
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                fh.close()
                part.unlink(missing_ok=True)
                raise HTTPException(413, f"file larger than {s.max_upload_mb} MB")
            h.update(chunk)
            fh.write(chunk)
    if not secrets.compare_digest(h.hexdigest(), x_sha256.lower()):
        part.unlink(missing_ok=True)
        raise HTTPException(422, "checksum mismatch: upload corrupted in transit")
    part.replace(target)
    return {"path": path, "size": size, "sha256": h.hexdigest()}


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@worker_router.post("/jobs/{job_id}/complete")
def complete(job_id: str, body: CompleteIn, request: Request, worker: Worker = Depends(current_worker),
             db: Session = Depends(get_db)) -> dict:
    """Register the asset ONLY after every uploaded file has been re-hashed and the GLB re-parsed."""
    s = request.app.state.settings
    storage = request.app.state.storage
    job = _lease_job(db, job_id, worker, body.lease_token, need_running=False)
    if job.status == "succeeded":  # idempotent retry of a completed call
        return {"status": "succeeded", "asset_id": job.asset_id, "version": job.asset_version, "duplicate": True}
    if job.status != "running":
        raise HTTPException(409, f"job is {job.status}, not running")
    if job.cancel_requested:
        mark_cancelled_ack(db, job)
        db.commit()
        raise HTTPException(409, "job was cancelled")

    result = body.result
    files = result.get("files") or []
    try:
        staging = storage.staging_dir(job.id, job.attempts)
        names = set()
        for f in files:
            name = validate_relative(f["name"])
            p = safe_join(staging, name)
            if not p.is_file():
                raise ValueError(f"file declared but not uploaded: {name}")
            if p.stat().st_size != int(f["size"]) or _sha(p) != f["sha256"]:
                raise ValueError(f"size/checksum mismatch for {name}")
            names.add(name)
        # the manifest and package are produced last; accept them if uploaded
        missing = REQUIRED_FILES - names
        if missing:
            raise ValueError(f"missing required files: {sorted(missing)}")
        if not (result.get("validation") or {}).get("passed"):
            raise ValueError("worker reported failed validation")
        read_glb_json(staging / "model.glb")
        manifest = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("asset_id") != job.asset_id or manifest.get("version") != job.asset_version:
            raise ValueError("manifest asset_id/version does not match the leased job")
    except (ValueError, KeyError, UnsafePath, json.JSONDecodeError) as exc:
        raise HTTPException(422, f"result rejected: {exc}") from exc

    dest = storage.asset_dir(job.asset_id, job.asset_version)
    if dest.exists():
        fail_or_retry(db, job, s, error=f"version v{job.asset_version} already exists (concurrent regeneration)",
                      retryable=True)
        db.commit()
        raise HTTPException(409, "asset version already exists; job re-queued")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staging), str(dest))
    storage.drop_staging(job.id)

    asset = db.scalar(select(Asset).where(Asset.id == job.asset_id).with_for_update())
    if asset is None:
        asset = Asset(id=job.asset_id, name=job.name, category=job.category, tags=list(job.tags or []),
                      art_profile=manifest.get("art_profile", ""), generator_id=manifest.get("generator_id", ""))
        db.add(asset)
        db.flush()
        emit_event(db, "asset.created", asset.id, name=asset.name)
    else:
        emit_event(db, "asset.version_created", asset.id, version=job.asset_version)
        if asset.review_status != "pending":
            previous = db.scalar(select(AssetVersion).where(
                AssetVersion.asset_id == asset.id, AssetVersion.version == asset.current_version,
            ).with_for_update())
            if previous and "art_review" not in previous.manifest:
                previous.manifest = {**previous.manifest, "art_review": {"status": asset.review_status}}
        asset.review_status = "pending"
    asset.current_version = job.asset_version
    asset.generator_id = manifest.get("generator_id", asset.generator_id)
    db.add(AssetVersion(
        asset_id=asset.id, version=job.asset_version, job_id=job.id, files=files, manifest=manifest,
        validation=result.get("validation", {}), triangle_count=int(manifest.get("triangle_count", 0)),
        engine=result.get("engine", ""), note=f"job {job.id} attempt {job.attempts}"))
    mark_succeeded(db, job)
    job.result = {"asset_id": asset.id, "version": job.asset_version, "files": len(files),
                  "triangles": manifest.get("triangle_count"), "engine": result.get("engine")}
    if job.job_type == "experimental.reconstruct":
        job.result = {**job.result, "engine_runtime": manifest.get("generation_params", {}).get("runtime", {})}
    try:
        db.commit()
    except IntegrityError as exc:  # duplicate (asset_id, version): another completion won
        db.rollback()
        shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(409, "asset version conflict") from exc
    return {"status": "succeeded", "asset_id": asset.id, "version": job.asset_version}


@worker_router.post("/jobs/{job_id}/fail")
def fail(job_id: str, body: FailIn, request: Request, worker: Worker = Depends(current_worker),
         db: Session = Depends(get_db)) -> dict:
    job = _lease_job(db, job_id, worker, body.lease_token)
    new_status = fail_or_retry(db, job, request.app.state.settings, error=body.error, retryable=body.retryable,
                               quota_wait_s=body.quota_wait_s if job.job_type == "agent.building" else None)
    request.app.state.storage.drop_staging(job.id)
    db.commit()
    return {"status": new_status}


@worker_router.post("/jobs/{job_id}/cancelled")
def cancelled(job_id: str, body: TokenOnly, request: Request, worker: Worker = Depends(current_worker),
              db: Session = Depends(get_db)) -> dict:
    job = _lease_job(db, job_id, worker, body.lease_token)
    mark_cancelled_ack(db, job)
    request.app.state.storage.drop_staging(job.id)
    db.commit()
    return {"status": job.status}
