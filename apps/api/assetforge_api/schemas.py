"""Request/response schemas and serializers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import Settings
from .db import utcnow
from .models import Asset, AssetVersion, Job, JobAttempt, Worker
from .scheduler import dependencies_state, worker_online


# ----------------------------------------------------------------------------- auth
class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    expires_in: int


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=256)
    role: Literal["admin", "operator", "viewer"] = "operator"


# ----------------------------------------------------------------------------- workers
class EnrollmentCreate(BaseModel):
    label: str = Field(default="", max_length=120)
    hours: int = Field(default=24, ge=1, le=24 * 30)


class WorkerRegister(BaseModel):
    enrollment_token: str
    name: str = Field(min_length=2, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    kind: Literal["cpu", "intel", "hybrid"] = "cpu"
    address: str = ""
    hostname: str = ""
    version: str = ""
    capabilities: dict[str, Any] = Field(default_factory=dict)
    limits: dict[str, Any] = Field(default_factory=dict)


class WorkerPatch(BaseModel):
    state: Literal["enabled", "disabled", "maintenance"] | None = None
    limits: dict[str, Any] | None = None


class Heartbeat(BaseModel):
    telemetry: dict[str, Any] = Field(default_factory=dict)
    active_jobs: list[str] = Field(default_factory=list)
    capabilities: dict[str, Any] | None = None
    address: str | None = None


class PlanStage(BaseModel):
    name: str
    weight: float = 1.0


class WorkerEvent(BaseModel):
    type: Literal["stage", "log"]
    name: str | None = None
    status: Literal["start", "done", "failed"] | None = None
    detail: str | None = None
    level: Literal["debug", "info", "warning", "error"] = "info"
    message: str | None = None


class EventsIn(BaseModel):
    lease_token: str
    plan: list[PlanStage] | None = None
    events: list[WorkerEvent] = Field(default_factory=list, max_length=300)


class CompleteIn(BaseModel):
    lease_token: str
    result: dict[str, Any]


class FailIn(BaseModel):
    lease_token: str
    error: str = Field(max_length=4000)
    retryable: bool = True
    quota_wait_s: float | None = Field(default=None, ge=0, le=172800, description="cloud AI quota exhausted: re-queue after this wait without using an attempt")


class TokenOnly(BaseModel):
    lease_token: str


# ----------------------------------------------------------------------------- jobs / queue
class JobPatch(BaseModel):
    priority: int | None = Field(default=None, ge=-100, le=100)
    not_before: datetime | None = None
    clear_schedule: bool = False


class BatchCreate(BaseModel):
    """Either explicit ``items`` or a ``template`` repeated ``count`` times with sequential seeds."""

    name: str = Field(min_length=1, max_length=160)
    template: dict[str, Any] | None = None
    count: int = Field(default=1, ge=1, le=1000)
    items: list[dict[str, Any]] | None = None
    seed_start: int | None = Field(default=None, ge=0)
    priority: int | None = Field(default=None, ge=-100, le=100)


class AssetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    tags: list[str] | None = Field(default=None, max_length=40)
    favorite: bool | None = None
    review_status: Literal["pending", "approved", "rejected"] | None = None


class AssetDeleteRequest(BaseModel):
    asset_ids: list[str] = Field(min_length=1, max_length=500)


class DownloadRequest(BaseModel):
    asset_ids: list[str] = Field(min_length=1, max_length=500)
    version: int | None = None
    include: Literal["package", "glb"] = "package"


class PlanIn(BaseModel):
    description: str = Field(min_length=3, max_length=2000)
    use_llm: bool = True


class PresetIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    data: dict[str, Any]


class ArtProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


# ----------------------------------------------------------------------------- serializers
def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def eta_seconds(db: Session, job: Job) -> float | None:
    """Estimate remaining seconds from real history of this job type (needs >= 3 completed samples)."""
    if job.status != "running" or not job.started_at:
        return None
    rows = db.execute(
        select(JobAttempt.started_at, JobAttempt.finished_at).join(Job, Job.id == JobAttempt.job_id)
        .where(Job.job_type == job.job_type, JobAttempt.outcome == "succeeded", JobAttempt.finished_at.is_not(None))
        .order_by(JobAttempt.id.desc()).limit(30)
    ).all()
    durs = [(f - s).total_seconds() for s, f in rows if f and s]
    if len(durs) < 3:
        return None
    avg = sum(durs) / len(durs)
    return max(avg - (utcnow() - job.started_at).total_seconds(), 0.0)


def job_out(db: Session, job: Job, detail: bool = False) -> dict:
    now = utcnow()
    state = job.status
    if job.status == "queued":
        if job.not_before and job.not_before > now:
            state = "scheduled"
        elif job.has_deps and dependencies_state(db, job) == "waiting":
            state = "blocked"
        elif job.attempts > 0:
            state = "retrying"
    elif job.status == "running" and job.cancel_requested:
        state = "cancelling"
    out = {
        "id": job.id, "batch_id": job.batch_id, "asset_id": job.asset_id, "name": job.name, "job_type": job.job_type,
        "category": job.category, "status": job.status, "state": state, "priority": job.priority,
        "attempts": job.attempts, "max_attempts": job.max_attempts, "worker_id": job.worker_id,
        "progress": round(job.progress, 4), "current_stage": job.current_stage, "error": job.error,
        "created_at": iso(job.created_at), "started_at": iso(job.started_at), "finished_at": iso(job.finished_at),
        "not_before": iso(job.not_before), "depends_on": job.depends_on or [], "tags": job.tags or [],
        "formats": job.formats or [], "quality_profile": job.quality_profile, "cancel_requested": job.cancel_requested,
        "asset_version": job.asset_version, "retry_of": job.retry_of, "pinned_worker_id": job.pinned_worker_id,
        "seed": (job.params or {}).get("seed"), "eta_seconds": eta_seconds(db, job),
    }
    if detail:
        out.update(params=job.params, requirements=job.requirements, plan=job.plan, stages=job.stages, result=job.result,
                   triangle_limit=job.triangle_limit,
                   attempt_history=[{"attempt": a.attempt_no, "worker_id": a.worker_id, "started_at": iso(a.started_at),
                                     "finished_at": iso(a.finished_at), "outcome": a.outcome, "error": a.error}
                                    for a in job.attempt_rows])
    return out


def worker_out(db: Session, w: Worker, settings: Settings, detail: bool = False) -> dict:
    online = worker_online(w, settings)
    active = db.scalar(select(func.count()).select_from(Job).where(Job.worker_id == w.id, Job.status == "running")) or 0
    out = {
        "id": w.id, "name": w.name, "kind": w.kind, "address": w.address, "hostname": w.hostname, "version": w.version,
        "state": w.state, "online": online, "status": ("offline" if not online else "maintenance" if w.state == "maintenance"
                                                      else "disabled" if w.state == "disabled" else "busy" if active else "idle"),
        "last_heartbeat": iso(w.last_heartbeat), "registered_at": iso(w.registered_at), "capabilities": w.capabilities,
        "limits": w.limits, "telemetry": w.telemetry, "active_jobs": active, "jobs_succeeded": w.jobs_succeeded,
        "jobs_failed": w.jobs_failed,
    }
    if detail:
        recent = db.scalars(select(Job).where(Job.worker_id == w.id).order_by(Job.updated_at.desc()).limit(25)).all()
        out["recent_jobs"] = [{"id": j.id, "name": j.name, "status": j.status, "progress": j.progress,
                               "finished_at": iso(j.finished_at)} for j in recent]
    return out


def asset_out(a: Asset, version: AssetVersion | None = None, detail: bool = False) -> dict:
    v = version
    if v is None and a.versions:
        v = next((x for x in a.versions if x.version == a.current_version), a.versions[-1])
    m = (v.manifest if v else {}) or {}
    out = {
        "id": a.id, "name": a.name, "category": a.category, "tags": a.tags or [], "favorite": a.favorite,
        "review_status": a.review_status, "current_version": a.current_version, "art_profile": a.art_profile,
        "generator_id": a.generator_id, "created_at": iso(a.created_at), "updated_at": iso(a.updated_at),
        "triangle_count": v.triangle_count if v else 0, "engine": v.engine if v else "",
        "dimensions_m": m.get("dimensions_m"), "seed": m.get("seed"), "version_count": len(a.versions),
        "has_thumbnail": bool(v and any(f["name"] == "thumbnail.png" for f in v.files)),
        "validation_passed": bool(v and (v.validation or {}).get("passed")),
    }
    if detail and v:
        out.update(files=v.files, manifest=v.manifest, validation=v.validation, version_info={
            "version": v.version, "job_id": v.job_id, "note": v.note, "created_at": iso(v.created_at)})
        out["versions"] = [{"version": x.version, "job_id": x.job_id, "triangle_count": x.triangle_count,
                            "engine": x.engine, "created_at": iso(x.created_at), "note": x.note} for x in a.versions]
    return out
