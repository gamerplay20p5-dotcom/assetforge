"""Scheduler: capability/resource matching, leasing, retries and abandoned-job recovery.

Design (see docs/ARCHITECTURE.md, ADR-002): the queue lives in the relational database and workers PULL
jobs through a lease. This gives capability-aware routing (a Celery/Redis queue cannot route on live
VRAM/limits), crash recovery for free (all state is durable) and one fewer service to operate.

Safety properties:
* A job is claimed with a conditional ``UPDATE ... WHERE status='queued'`` -> exactly one worker wins.
* Every lease has an opaque token; progress/upload/complete calls must present it (stale or duplicate
  workers get 409 and cannot corrupt state).
* Leases expire unless the worker heartbeats; expired jobs are marked ``abandoned`` and re-queued
  (bounded by ``max_attempts``) with exponential backoff.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session
from assetforge_contract.engines import RECONSTRUCT, TEXT_REFERENCE

from ..config import Settings
from ..db import utcnow
from ..models import Asset, AssetVersion, Job, JobAttempt, JobLog, Worker, new_id
from ..services import emit_event, get_setting
from .engines import admission, estimate, estimate_reference

TERMINAL = ("succeeded", "failed", "cancelled")
ADAPTIVE_JOBS = {RECONSTRUCT, TEXT_REFERENCE}


# ------------------------------------------------------------------------------ requirements
def requirements_for(job_type: str, formats: list[str], vram_mb: int = 7000, provider: str | None = None, cpu3d_cores: int = 12,
                     cpu3d_ram_mb: int = 16384, params: dict | None = None) -> dict:
    if job_type == RECONSTRUCT:
        features = [f"engine.{params['engine']}"]
        if params.get("prompt"):
            features.append("engine.text-reference")
        return {"features": features, **estimate(params, unified=False)}
    if job_type == TEXT_REFERENCE:
        return {"features": ["engine.split-reference"], **estimate_reference(unified=False)}
    if job_type == "asset.prepare":
        features = ["asset.prepare", "blender"]
        if params and params.get("method", "legacy") != "legacy":
            features.append("asset.prepare-optimization")
            if params["method"] == "instant":
                features.append("asset.prepare-instant")
        elif params and params["lod_ratios"][0] < 1:
            features.append("asset.prepare-density")
        return {"features": features, "cpu_cores": 4, "ram_mb": 4096, "vram_mb": 0}
    if job_type == "ai.image_to_3d" and provider in ("sf3d", "triposr"):
        # CPU-only providers: no VRAM; reserve cores/RAM of the node. Needs Blender (post-processing) and that provider's container.
        return {"features": ["ai.image_to_3d", f"provider.{provider}", "blender"], "cpu_cores": cpu3d_cores, "ram_mb": cpu3d_ram_mb, "vram_mb": 0}
    if job_type == "agent.building":
        # cloud AI is reached through the API; the worker only needs Blender (build + review renders) and some CPU
        return {"features": ["agent.building", "blender"], "cpu_cores": 4, "ram_mb": 4096, "vram_mb": 0}
    if job_type.startswith("ai."):
        # generative jobs need a ComfyUI/Intel-GPU node, Blender for post-processing, and reserve VRAM
        return {"features": [job_type, "comfyui", "blender"], "cpu_cores": 2, "ram_mb": 8192, "vram_mb": vram_mb}
    features = [job_type]
    cpu_cores = 1
    if "blend" in formats or "fbx" in formats:
        features.append("blender")
    if "blender" in features:
        cpu_cores = 2
    return {"features": features, "cpu_cores": cpu_cores, "ram_mb": 1536, "vram_mb": 0}


def worker_online(worker: Worker, settings: Settings, now: datetime | None = None) -> bool:
    now = now or utcnow()
    return bool(worker.last_heartbeat and (now - worker.last_heartbeat).total_seconds() <= settings.worker_offline_seconds)


@dataclass
class Reserved:
    jobs: int = 0
    cpu_cores: float = 0
    ram_mb: float = 0
    vram_mb: float = 0


def reserved_for(db: Session, worker_id: str) -> Reserved:
    r = Reserved()
    for job in db.scalars(select(Job).where(Job.worker_id == worker_id, Job.status == "running")):
        req = job.requirements or {}
        r.jobs += 1
        r.cpu_cores += req.get("cpu_cores", 1)
        r.ram_mb += req.get("ram_mb", 0)
        r.vram_mb += req.get("vram_mb", 0)
    return r


def incompatibility(job: Job, worker: Worker, res: Reserved) -> str | None:
    """Return why ``worker`` cannot take ``job`` right now, or None if it can."""
    req, caps, lim = job.requirements or {}, worker.capabilities or {}, worker.limits or {}
    missing = [f for f in req.get("features", []) if f not in set(caps.get("features", []))]
    if missing:
        return f"missing capabilities: {', '.join(missing)}"
    if job.job_type in ADAPTIVE_JOBS:
        return None
    kinds = req.get("worker_kinds")
    if kinds and worker.kind not in kinds:
        return f"worker kind {worker.kind} not allowed"
    if res.jobs >= lim.get("max_concurrent_jobs", 1):
        return "worker at max_concurrent_jobs"
    if lim.get("cpu_cores") is not None and res.cpu_cores + req.get("cpu_cores", 1) > lim["cpu_cores"]:
        return "cpu reservation exceeded"
    if lim.get("ram_mb") is not None and res.ram_mb + req.get("ram_mb", 0) > lim["ram_mb"]:
        return "ram reservation exceeded"
    if req.get("vram_mb", 0) > 0:
        free = (lim.get("vram_mb") or 0) - res.vram_mb
        if req["vram_mb"] > free:
            return "vram reservation exceeded"
    return None


def dependencies_state(db: Session, job: Job) -> str:
    """ready | waiting | failed"""
    if not job.depends_on:
        return "ready"
    rows = db.execute(select(Job.id, Job.status).where(Job.id.in_(job.depends_on))).all()
    found = {r[0]: r[1] for r in rows}
    if any(found.get(d) in ("failed", "cancelled") for d in job.depends_on) or any(d not in found for d in job.depends_on):
        return "failed"
    return "ready" if all(found[d] == "succeeded" for d in job.depends_on) else "waiting"


def next_version(db: Session, asset_id: str) -> int:
    cur = db.scalar(select(AssetVersion.version).where(AssetVersion.asset_id == asset_id)
                    .order_by(AssetVersion.version.desc()).limit(1))
    return (cur or 0) + 1


def server_log(db: Session, job: Job, message: str, level: str = "info") -> None:
    db.add(JobLog(job_id=job.id, attempt_no=job.attempts, level=level, source="server", message=message))


def rank_workers(db: Session, job: Job, workers: list[Worker], settings: Settings, now: datetime,
                 running_by_worker: dict[str, list[Job]]) -> list[tuple[float, Worker, dict]]:
    """Rank workers that can accept the exact job now, using the same admission as leasing."""
    choices = []
    for candidate in workers:
        if (candidate.kind != "nvidia" or candidate.state != "enabled" or not worker_online(candidate, settings, now)
                or (job.pinned_worker_id and job.pinned_worker_id != candidate.id)
                or incompatibility(job, candidate, Reserved()) is not None):
            continue
        running = running_by_worker.get(candidate.id, [])
        need, _ = admission(db, job, candidate, running, now)
        if need is None:
            continue
        utilization = (candidate.telemetry or {}).get("engine_gpu", {}).get("utilization_percent") or 0
        score = need.get("historical_seconds", need["expected_seconds"]) * (1 + utilization / 200 + len(running) / 5)
        choices.append((score, candidate, need))
    return sorted(choices, key=lambda row: (row[0], row[1].id))


def running_by_nvidia_worker(db: Session, workers: list[Worker]) -> dict[str, list[Job]]:
    grouped: dict[str, list[Job]] = {}
    for running in db.scalars(select(Job).where(Job.status == "running", Job.worker_id.in_([w.id for w in workers]))):
        grouped.setdefault(running.worker_id, []).append(running)
    return grouped


# ------------------------------------------------------------------------------ leasing
def try_lease(db: Session, worker: Worker, settings: Settings, now: datetime | None = None) -> Job | None:
    now = now or utcnow()
    adaptive = worker.kind == "nvidia"
    if adaptive:
        worker = db.scalar(select(Worker).where(Worker.id == worker.id).with_for_update()
                           .execution_options(populate_existing=True))
    if worker.state != "enabled" or get_setting(db, "queue_paused", False):
        return None
    res = reserved_for(db, worker.id)
    if not adaptive and res.jobs >= (worker.limits or {}).get("max_concurrent_jobs", 1):
        return None
    workers = []
    running = {}
    if adaptive:
        workers = list(db.scalars(select(Worker).where(Worker.kind == "nvidia", Worker.state == "enabled",
                                                      Worker.last_heartbeat >= now - timedelta(seconds=settings.worker_offline_seconds))))
        running = running_by_nvidia_worker(db, workers)
    candidates = db.scalars(
        select(Job).where(Job.status == "queued", or_(Job.not_before.is_(None), Job.not_before <= now))
        .order_by(Job.priority.desc(), Job.created_at.asc()).limit(200)
    ).all()
    for job in candidates:
        if job.pinned_worker_id and job.pinned_worker_id != worker.id:
            continue
        if incompatibility(job, worker, res) is not None:
            continue
        if dependencies_state(db, job) != "ready":
            continue
        requirements = job.requirements
        if job.job_type in ADAPTIVE_JOBS:
            if not adaptive:
                continue
            ranked = rank_workers(db, job, workers, settings, now, running)
            if not ranked or ranked[0][1].id != worker.id:
                continue
            requirements = ranked[0][2]
        asset_query = select(Asset.id).where(Asset.id == job.asset_id)
        if db.scalar(asset_query):
            if not db.scalar(asset_query.with_for_update(skip_locked=True)):
                continue
            if db.scalar(select(Job.id).where(Job.asset_id == job.asset_id, Job.status == "running").limit(1)):
                continue
        token = secrets.token_hex(24)
        claimed = db.execute(
            update(Job).where(Job.id == job.id, Job.status == "queued").values(
                status="running", worker_id=worker.id, lease_token=token, requirements=requirements,
                lease_expires_at=now + timedelta(seconds=settings.lease_seconds), attempts=Job.attempts + 1,
                started_at=now, finished_at=None, progress=0.0, stages={}, plan=[], current_stage=None,
                cancel_requested=False, error=None, asset_version=next_version(db, job.asset_id),
            )
        )
        if claimed.rowcount != 1:  # lost the race to another worker
            continue
        db.refresh(job)
        db.add(JobAttempt(job_id=job.id, attempt_no=job.attempts, worker_id=worker.id, started_at=now))
        server_log(db, job, f"leased to worker {worker.name} (attempt {job.attempts}/{job.max_attempts})")
        emit_event(db, "job.started", job.id, worker_id=worker.id, attempt=job.attempts)
        return job
    return None


# ------------------------------------------------------------------------------ completion paths
def _close_attempt(db: Session, job: Job, outcome: str, error: str | None, now: datetime) -> None:
    row = db.scalar(select(JobAttempt).where(JobAttempt.job_id == job.id, JobAttempt.attempt_no == job.attempts))
    if row is not None and row.outcome == "running":
        row.outcome, row.error, row.finished_at = outcome, error, now


def fail_or_retry(db: Session, job: Job, settings: Settings, *, error: str, retryable: bool, outcome: str = "failed",
                  now: datetime | None = None, quota_wait_s: float | None = None) -> str:
    """Close the current attempt, then re-queue (with backoff) or mark the job terminal. Returns new status."""
    now = now or utcnow()
    worker = db.get(Worker, job.worker_id) if job.worker_id else None
    _close_attempt(db, job, outcome, error, now)
    if worker is not None and outcome == "failed":
        worker.jobs_failed += 1
    job.lease_token, job.lease_expires_at = None, None
    if job.cancel_requested:
        job.status, job.finished_at, job.error = "cancelled", now, "cancelled by request"
        server_log(db, job, "job cancelled")
        emit_event(db, "job.cancelled", job.id)
    elif quota_wait_s is not None and job.max_attempts < 60:
        # waiting for the AI quota to renew is not a failure of the job: re-queue it and give the attempt back (bounded)
        job.status, job.not_before, job.worker_id = "queued", now + timedelta(seconds=max(quota_wait_s, 30.0)), None
        job.max_attempts += 1
        job.error = error
        server_log(db, job, f"AI quota exhausted; resuming automatically in {int(max(quota_wait_s, 30.0))}s: {error[:300]}", "warning")
        emit_event(db, "job.requeued", job.id, reason="ai_quota")
    elif retryable and job.attempts < job.max_attempts:
        delay = settings.retry_backoff_seconds * (2 ** (job.attempts - 1))
        job.status, job.not_before, job.worker_id = "queued", now + timedelta(seconds=delay), None
        job.error = error
        server_log(db, job, f"attempt {job.attempts} {outcome}: {error}. Retrying in {delay}s", "warning")
        emit_event(db, "job.requeued", job.id, reason=outcome)
    else:
        job.status, job.finished_at, job.error = "failed", now, error
        server_log(db, job, f"job failed after {job.attempts} attempt(s): {error}", "error")
        emit_event(db, "job.failed", job.id, error=error[:300])
    return job.status


def mark_cancelled_ack(db: Session, job: Job, now: datetime | None = None) -> None:
    now = now or utcnow()
    _close_attempt(db, job, "cancelled", "cancelled by request", now)
    job.status, job.finished_at, job.lease_token, job.lease_expires_at = "cancelled", now, None, None
    job.error = "cancelled by request"
    server_log(db, job, "worker acknowledged cancellation")
    emit_event(db, "job.cancelled", job.id)


def mark_succeeded(db: Session, job: Job, now: datetime | None = None) -> None:
    now = now or utcnow()
    worker = db.get(Worker, job.worker_id) if job.worker_id else None
    _close_attempt(db, job, "succeeded", None, now)
    if worker is not None:
        worker.jobs_succeeded += 1
    job.status, job.finished_at, job.progress, job.error = "succeeded", now, 1.0, None
    # lease_token is kept so a retried "complete" call from the same worker stays idempotent
    job.lease_expires_at, job.current_stage = None, None
    emit_event(db, "job.succeeded", job.id, asset_id=job.asset_id)


def cancel_job(db: Session, job: Job, now: datetime | None = None) -> str:
    """Cooperative cancellation. Queued jobs stop immediately; running jobs are asked to stop."""
    now = now or utcnow()
    if job.status == "queued":
        job.status, job.finished_at, job.cancel_requested, job.error = "cancelled", now, True, "cancelled before start"
        server_log(db, job, "job cancelled before start")
        emit_event(db, "job.cancelled", job.id)
    elif job.status == "running":
        job.cancel_requested = True
        server_log(db, job, "cancellation requested; waiting for the worker to stop", "warning")
        emit_event(db, "job.cancelling", job.id)
    return job.status


# ------------------------------------------------------------------------------ reaper
def reap(db: Session, settings: Settings, now: datetime | None = None, *, allow_abandon: bool = True) -> dict[str, int]:
    """Recover expired leases and propagate dependency failures. Safe to call from many processes."""
    now = now or utcnow()
    stats = {"abandoned": 0, "dependency_failed": 0}
    if allow_abandon:
        expired = db.scalars(select(Job).where(Job.status == "running", Job.lease_expires_at < now)).all()
        for job in expired:
            fail_or_retry(db, job, settings, error="worker lost: lease expired (no heartbeat)", retryable=True,
                          outcome="abandoned", now=now)
            stats["abandoned"] += 1
    waiting = db.scalars(select(Job).where(Job.status == "queued", Job.has_deps.is_(True))).all()
    for job in waiting:
        if dependencies_state(db, job) == "failed":
            job.status, job.finished_at, job.error = "failed", now, "a dependency failed, was cancelled or does not exist"
            server_log(db, job, job.error, "error")
            emit_event(db, "job.failed", job.id, error=job.error)
            stats["dependency_failed"] += 1
    if any(stats.values()):
        db.commit()
    return stats


# ------------------------------------------------------------------------------ job creation
def new_asset_id() -> str:
    return new_id("ast_")[:14]


def asset_exists(db: Session, asset_id: str) -> bool:
    return db.get(Asset, asset_id) is not None
