"""Jobs, batches and queue control."""

from __future__ import annotations

import copy
from assetforge_contract import JobCreate
from assetforge_contract.engines import ENGINES, RECONSTRUCT
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Asset, AssetVersion, Batch, Job, JobLog, User, Worker
from ..scheduler import cancel_job, requirements_for
from ..scheduler.core import new_asset_id
from ..schemas import BatchCreate, JobPatch, iso, job_out
from ..security import get_db, require_operator, require_viewer
from ..services import audit, emit_event, get_setting, set_setting

router = APIRouter(tags=["queue"])


def create_job(db: Session, spec: JobCreate, user: User, settings, batch_id: str | None = None,
               retry_of: str | None = None) -> Job:
    if spec.idempotency_key:
        existing = db.execute(select(Job).where(Job.idempotency_key == spec.idempotency_key)).scalar_one_or_none()
        if existing is not None:
            return existing
    if spec.asset_id:
        if db.get(Asset, spec.asset_id) is None:
            raise HTTPException(404, f"asset {spec.asset_id} not found")
        asset_id = spec.asset_id
    else:
        asset_id = new_asset_id()
    if spec.job_type == "asset.prepare":
        version = db.scalar(select(AssetVersion).where(AssetVersion.asset_id == asset_id,
                                                       AssetVersion.version == spec.params["source_version"]))
        if version is None or not any(f["name"] == "model.glb" for f in version.files):
            raise HTTPException(404, "Versão do master indisponível.")
        if version.manifest.get("generator_id") == "asset.prepare":
            raise HTTPException(422, "Selecione uma versão original para a preparação.")
        if version.manifest.get("category") != spec.params["category"]:
            raise HTTPException(422, "A categoria precisa corresponder à do master.")
    if spec.job_type == "ai.image_to_3d":
        ref = spec.params.get("reference_id")
        if not (settings.storage_root / "references" / f"{ref}.png").is_file():
            raise HTTPException(404, f"reference image {ref} not found (upload it first)")
    needs_matte = False
    needs_replay_worker = False
    if spec.job_type == RECONSTRUCT:
        needs_replay_worker = any(spec.params.get(k) for k in ("prepared_inputs", "use_native_threads")) or any(
            spec.params.get(k) is None for k in ("structure_guidance", "shape_guidance")) or (
            spec.params["engine"] == "pixal3d-python" and spec.params.get("skip_decimation"))
        for ref in spec.params["references"].values():
            path = settings.storage_root / "references" / f"{ref}.png"
            if not path.is_file():
                raise HTTPException(404, f"reference image {ref} not found")
            if not needs_matte and spec.params["engine"] != "trellis2-gguf" and not spec.params.get("prepared_inputs"):
                with Image.open(path) as image:
                    alpha = image.getchannel("A") if "A" in image.getbands() else None
                    needs_matte = alpha is None or alpha.getextrema() == (255, 255)
    if spec.job_type == "agent.building":
        from ..ai.router import get_ai_settings

        ai_cfg = get_ai_settings(db)
        if spec.params.get("max_iterations") is None:
            spec.params["max_iterations"] = int(ai_cfg["agent_iterations"])
        if spec.params.get("target_score") is None:
            spec.params["target_score"] = float(ai_cfg["target_score"])
        for ref in spec.params.get("reference_ids", []):
            if not (settings.storage_root / "references" / f"{ref}.png").is_file():
                raise HTTPException(404, f"reference image {ref} not found (upload it first)")
    if spec.worker_id:
        worker = db.get(Worker, spec.worker_id)
        if worker is None:
            raise HTTPException(404, f"worker {spec.worker_id} not found")
        if spec.job_type == RECONSTRUCT and f"engine.{spec.params['engine']}" not in (worker.capabilities or {}).get("features", []):
            raise HTTPException(422, "worker does not support the selected engine")
        if needs_matte and "engine.reference-prep" not in (worker.capabilities or {}).get("features", []):
            raise HTTPException(422, "O worker escolhido ainda requer PNG recortado para este motor. Selecione o worker automático.")
        if needs_replay_worker and "engine.archive-inputs" not in (worker.capabilities or {}).get("features", []):
            raise HTTPException(422, "O worker ainda não suporta estas opções de reprodução.")
        if spec.job_type == "asset.prepare" and "asset.prepare" not in (worker.capabilities or {}).get("features", []):
            raise HTTPException(422, "O worker precisa ter Blender e a preparação de assets.")
    if spec.depends_on:
        found = set(db.scalars(select(Job.id).where(Job.id.in_(spec.depends_on))))
        missing = set(spec.depends_on) - found
        if missing:
            raise HTTPException(404, f"dependency jobs not found: {sorted(missing)}")
    job = Job(
        batch_id=batch_id, asset_id=asset_id, name=spec.name, job_type=spec.job_type,
        params=spec.params, quality_profile=spec.quality_profile.value,
        triangle_limit=spec.triangle_limit, formats=list(spec.formats), tags=list(spec.tags),
        art_profile_id=spec.art_profile_id, category=spec.category, priority=spec.priority,
        requirements=requirements_for(spec.job_type, list(spec.formats), vram_mb=settings.ai_vram_mb, provider=spec.params.get("provider"),
                                      cpu3d_cores=settings.cpu3d_cores, cpu3d_ram_mb=settings.cpu3d_ram_mb,
                                      params=spec.params), pinned_worker_id=spec.worker_id,
        not_before=spec.scheduled_at, depends_on=list(spec.depends_on), has_deps=bool(spec.depends_on),
        idempotency_key=spec.idempotency_key, max_attempts=settings.default_max_attempts, created_by=user.username,
        retry_of=retry_of,
    )
    if needs_matte:
        job.requirements = {**job.requirements, "features": [*job.requirements["features"], "engine.reference-prep"]}
    if needs_replay_worker:
        job.requirements = {**job.requirements, "features": [*job.requirements["features"], "engine.archive-inputs"]}
    db.add(job)
    db.flush()
    emit_event(db, "job.created", job.id, name=job.name, batch_id=batch_id)
    return job


def _parse_spec(data: dict) -> JobCreate:
    try:
        return JobCreate.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_url=False, include_context=False)) from exc


# ----------------------------------------------------------------------------- jobs
@router.get("/engines", dependencies=[Depends(require_viewer)])
def engine_catalog() -> dict:
    return {"items": [
        {"id": key, **entry, "experimental": True, "commercial_status": "pending"}
        for key, entry in ENGINES.items()
    ]}


@router.post("/jobs", status_code=201)
def post_job(body: JobCreate, request: Request, user: User = Depends(require_operator),
             db: Session = Depends(get_db)) -> dict:
    hd = (body.params or {}).get("house_description") if isinstance(body.params, dict) else None
    if hd is not None:  # refuse a bad description now instead of failing later inside a worker
        from assetforge_vision.schema import DescriptionError, parse_description

        try:
            parse_description(hd)
        except DescriptionError as exc:
            raise HTTPException(422, f"house_description: {exc}") from exc
    job = create_job(db, body, user, request.app.state.settings)
    audit(db, user.username, "job.create", "job", job.id, name=job.name)
    db.commit()
    return job_out(db, job, detail=True)


@router.get("/jobs", dependencies=[Depends(require_viewer)])
def list_jobs(db: Session = Depends(get_db), status: str | None = None, batch_id: str | None = None,
              worker_id: str | None = None, q: str | None = None, limit: int = Query(100, ge=1, le=500),
              offset: int = Query(0, ge=0)) -> dict:
    stmt = select(Job)
    if status:
        stmt = stmt.where(Job.status.in_(status.split(",")))
    if batch_id:
        stmt = stmt.where(Job.batch_id == batch_id)
    if worker_id:
        stmt = stmt.where(Job.worker_id == worker_id)
    if q:
        stmt = stmt.where(Job.name.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Job.created_at.desc(), Job.id).limit(limit).offset(offset)).all()
    return {"total": total, "items": [job_out(db, j) for j in rows]}


@router.get("/jobs/{job_id}", dependencies=[Depends(require_viewer)])
def get_job(job_id: str, db: Session = Depends(get_db)) -> dict:
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job_out(db, job, detail=True)


@router.get("/jobs/{job_id}/logs", dependencies=[Depends(require_viewer)])
def job_logs(job_id: str, after_id: int = 0, limit: int = Query(500, ge=1, le=2000),
             db: Session = Depends(get_db)) -> dict:
    if not db.get(Job, job_id):
        raise HTTPException(404, "job not found")
    rows = db.scalars(select(JobLog).where(JobLog.job_id == job_id, JobLog.id > after_id)
                      .order_by(JobLog.id).limit(limit)).all()
    return {"items": [{"id": r.id, "ts": iso(r.ts), "attempt": r.attempt_no, "level": r.level, "source": r.source,
                       "message": r.message} for r in rows]}


@router.post("/jobs/{job_id}/cancel")
def post_cancel(job_id: str, user: User = Depends(require_operator), db: Session = Depends(get_db)) -> dict:
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if job.status in ("succeeded", "failed", "cancelled"):
        raise HTTPException(409, f"job already {job.status}")
    cancel_job(db, job)
    audit(db, user.username, "job.cancel", "job", job.id)
    db.commit()
    return job_out(db, job)


@router.post("/jobs/{job_id}/retry", status_code=201)
def post_retry(job_id: str, request: Request, user: User = Depends(require_operator),
               db: Session = Depends(get_db)) -> dict:
    """Re-run a finished job as a NEW job (history of the original is preserved). The asset id is kept, so a
    success produces a new version of the same asset."""
    src = db.get(Job, job_id)
    if not src:
        raise HTTPException(404, "job not found")
    if src.status in ("queued", "running"):
        raise HTTPException(409, "job is still active")
    spec = JobCreate(
        name=src.name, job_type=src.job_type, params=src.params, quality_profile=src.quality_profile,  # type: ignore[arg-type]
        triangle_limit=src.triangle_limit, formats=list(src.formats), priority=src.priority, tags=list(src.tags),
        worker_id=src.pinned_worker_id, asset_id=src.asset_id if src.status == "succeeded" else None,
    )
    if src.status != "succeeded":  # nothing was produced: reuse the reserved asset id so the library stays clean
        from ..models import Asset as _A

        if db.get(_A, src.asset_id) is not None:
            spec.asset_id = src.asset_id
    job = create_job(db, spec, user, request.app.state.settings, batch_id=src.batch_id, retry_of=src.id)
    if not spec.asset_id:
        job.asset_id = src.asset_id
    audit(db, user.username, "job.retry", "job", src.id, new_job=job.id)
    db.commit()
    return job_out(db, job, detail=True)


@router.patch("/jobs/{job_id}")
def patch_job(job_id: str, body: JobPatch, user: User = Depends(require_operator),
              db: Session = Depends(get_db)) -> dict:
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if job.status != "queued":
        raise HTTPException(409, "only queued jobs can be rescheduled or re-prioritised")
    if body.priority is not None:
        job.priority = body.priority
    if body.clear_schedule:
        job.not_before = None
    elif body.not_before is not None:
        job.not_before = body.not_before
    audit(db, user.username, "job.update", "job", job.id, priority=body.priority,
          not_before=iso(body.not_before))
    emit_event(db, "job.updated", job.id)
    db.commit()
    return job_out(db, job)


# ----------------------------------------------------------------------------- batches
@router.post("/batches", status_code=201)
def post_batch(body: BatchCreate, request: Request, user: User = Depends(require_operator),
               db: Session = Depends(get_db)) -> dict:
    s = request.app.state.settings
    if body.items is None and body.template is None:
        raise HTTPException(422, "provide 'items' or 'template'")
    specs: list[JobCreate] = []
    if body.items is not None:
        specs = [_parse_spec(i) for i in body.items]
    else:
        base = copy.deepcopy(body.template or {})
        seed0 = body.seed_start if body.seed_start is not None else int((base.get("params") or {}).get("seed", 1))
        base_name = base.get("name") or body.name
        for i in range(body.count):
            item = copy.deepcopy(base)
            item["name"] = f"{base_name} {i + 1:03d}"
            item.setdefault("params", {})["seed"] = seed0 + i
            if body.priority is not None:
                item["priority"] = body.priority
            specs.append(_parse_spec(item))
    if len(specs) > s.max_batch_jobs:
        raise HTTPException(422, f"batch too large (max {s.max_batch_jobs})")
    batch = Batch(name=body.name, spec={"count": len(specs), "template": body.template, "seed_start": body.seed_start},
                  created_by=user.username)
    db.add(batch)
    db.flush()
    jobs = [create_job(db, sp, user, s, batch_id=batch.id) for sp in specs]
    audit(db, user.username, "batch.create", "batch", batch.id, name=body.name, jobs=len(jobs))
    emit_event(db, "batch.created", batch.id, name=body.name, jobs=len(jobs))
    db.commit()
    return batch_out(db, batch) | {"job_ids": [j.id for j in jobs]}


def batch_out(db: Session, b: Batch) -> dict:
    counts = dict(db.execute(select(Job.status, func.count()).where(Job.batch_id == b.id).group_by(Job.status)).all())
    total = sum(counts.values())
    done = sum(counts.get(k, 0) for k in ("succeeded", "failed", "cancelled"))
    prog = db.scalar(select(func.coalesce(func.sum(Job.progress), 0.0)).where(
        Job.batch_id == b.id, Job.status.in_(("running", "queued")))) or 0.0
    return {"id": b.id, "name": b.name, "created_at": iso(b.created_at), "created_by": b.created_by,
            "total": total, "counts": counts, "finished": done,
            "progress": round((counts.get("succeeded", 0) + counts.get("failed", 0) + counts.get("cancelled", 0) + prog)
                              / total, 4) if total else 0.0}


@router.get("/batches", dependencies=[Depends(require_viewer)])
def list_batches(db: Session = Depends(get_db), limit: int = Query(50, ge=1, le=200)) -> list[dict]:
    return [batch_out(db, b) for b in db.scalars(select(Batch).order_by(Batch.created_at.desc()).limit(limit))]


@router.get("/batches/{batch_id}", dependencies=[Depends(require_viewer)])
def get_batch(batch_id: str, db: Session = Depends(get_db)) -> dict:
    b = db.get(Batch, batch_id)
    if not b:
        raise HTTPException(404, "batch not found")
    jobs = db.scalars(select(Job).where(Job.batch_id == b.id).order_by(Job.created_at, Job.id)).all()
    return batch_out(db, b) | {"jobs": [job_out(db, j) for j in jobs]}


@router.post("/batches/{batch_id}/cancel")
def cancel_batch(batch_id: str, user: User = Depends(require_operator), db: Session = Depends(get_db)) -> dict:
    b = db.get(Batch, batch_id)
    if not b:
        raise HTTPException(404, "batch not found")
    n = 0
    for j in db.scalars(select(Job).where(Job.batch_id == b.id, Job.status.in_(("queued", "running")))):
        cancel_job(db, j)
        n += 1
    audit(db, user.username, "batch.cancel", "batch", b.id, jobs=n)
    db.commit()
    return {"cancelled": n}


@router.post("/batches/{batch_id}/retry-failed", status_code=201)
def retry_failed(batch_id: str, request: Request, user: User = Depends(require_operator),
                 db: Session = Depends(get_db)) -> dict:
    b = db.get(Batch, batch_id)
    if not b:
        raise HTTPException(404, "batch not found")
    new_ids = []
    for j in db.scalars(select(Job).where(Job.batch_id == b.id, Job.status == "failed")).all():
        newer = db.scalar(select(Job.id).where(Job.retry_of == j.id).limit(1))
        if newer:
            continue
        r = post_retry(j.id, request, user, db)
        new_ids.append(r["id"])
    return {"created": new_ids}


# ----------------------------------------------------------------------------- queue control
@router.get("/queue/state", dependencies=[Depends(require_viewer)])
def queue_state(db: Session = Depends(get_db)) -> dict:
    counts = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    return {"paused": bool(get_setting(db, "queue_paused", False)), "counts": counts,
            "now": iso(utcnow())}


@router.post("/queue/pause")
def queue_pause(user: User = Depends(require_operator), db: Session = Depends(get_db)) -> dict:
    set_setting(db, "queue_paused", True)
    audit(db, user.username, "queue.pause")
    emit_event(db, "queue.paused")
    db.commit()
    return {"paused": True}


@router.post("/queue/resume")
def queue_resume(user: User = Depends(require_operator), db: Session = Depends(get_db)) -> dict:
    set_setting(db, "queue_paused", False)
    audit(db, user.username, "queue.resume")
    emit_event(db, "queue.resumed")
    db.commit()
    return {"paused": False}

