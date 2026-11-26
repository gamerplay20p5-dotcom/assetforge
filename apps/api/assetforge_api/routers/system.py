"""Dashboard, health, catalogs, presets, art profiles, audit log and the real-time event stream."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta

from assetforge_contract import CATEGORY_BUDGETS, QUALITY_PROFILES, BuildingParams
from assetforge_procedural import GENERATOR_ID, GENERATOR_VERSION, list_palettes
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import ArtProfile, Asset, AuditLog, Event, Job, Preset, User, Worker
from ..scheduler import worker_online
from ..schemas import ArtProfileIn, PlanIn, PresetIn, iso
from ..security import (
    get_db,
    require_admin,
    require_operator,
    require_viewer,
    user_or_download_token,
)
from ..services import audit, get_setting

router = APIRouter(tags=["system"])


# ----------------------------------------------------------------------------- health
@router.get("/health", tags=["health"])
def health() -> dict:
    """Liveness: the process answers."""
    return {"status": "ok"}


@router.get("/health/ready", tags=["health"])
def ready(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    """Readiness: database reachable and storage writable."""
    checks: dict[str, str] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {type(exc).__name__}"
    try:
        probe = request.app.state.storage.root / ".write-probe"
        probe.write_text("ok")
        probe.unlink()
        checks["storage"] = "ok"
    except OSError as exc:
        checks["storage"] = f"error: {exc.strerror}"
    ok = all(v == "ok" for v in checks.values())
    response.status_code = 200 if ok else 503
    return {"status": "ready" if ok else "degraded", "checks": checks}


# ----------------------------------------------------------------------------- dashboard
@router.get("/dashboard/summary", dependencies=[Depends(require_viewer)])
def dashboard(request: Request, db: Session = Depends(get_db)) -> dict:
    s = request.app.state.settings
    now = utcnow()
    counts = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    waiting = db.scalar(select(func.count()).select_from(Job).where(Job.status == "queued")) or 0
    assets_total = db.scalar(select(func.count()).select_from(Asset)) or 0
    by_review = dict(db.execute(select(Asset.review_status, func.count()).group_by(Asset.review_status)).all())

    workers = db.scalars(select(Worker)).all()
    online = [w for w in workers if worker_online(w, s, now)]
    cpu = [w.telemetry.get("cpu_percent") for w in online if w.telemetry.get("cpu_percent") is not None]
    ram_used = sum(w.telemetry.get("ram_used_mb", 0) for w in online)
    ram_total = sum(w.telemetry.get("ram_total_mb", 0) for w in online)
    gpus = [g for w in online for g in (w.telemetry.get("gpus") or [])]
    gpu_util = [g["utilization_percent"] for g in gpus if g.get("utilization_percent") is not None]
    vram_used = sum(g.get("vram_used_mb") or 0 for g in gpus)
    vram_total = sum(g.get("vram_total_mb") or 0 for g in gpus)

    total, free = request.app.state.storage.free_bytes()
    used_assets = request.app.state.storage.used_bytes()

    # processing history: finished jobs per hour for the last 24h (real rows, grouped in python for DB portability)
    since = now - timedelta(hours=24)
    finished = db.execute(select(Job.finished_at, Job.status, Job.started_at).where(
        Job.finished_at.is_not(None), Job.finished_at >= since)).all()
    buckets: dict[str, dict[str, int]] = {}
    for i in range(24):
        h = (now - timedelta(hours=23 - i)).replace(minute=0, second=0, microsecond=0)
        buckets[h.isoformat()] = {"succeeded": 0, "failed": 0, "cancelled": 0}
    for fin, st, _ in finished:
        key = fin.replace(minute=0, second=0, microsecond=0).isoformat()
        if key in buckets and st in buckets[key]:
            buckets[key][st] += 1
    durations = [(f - st).total_seconds() for f, _, st in finished if st and f]
    return {
        "jobs": {"running": counts.get("running", 0), "queued": waiting, "succeeded": counts.get("succeeded", 0),
                 "failed": counts.get("failed", 0), "cancelled": counts.get("cancelled", 0),
                 "paused": bool(get_setting(db, "queue_paused", False))},
        "assets": {"total": assets_total, "by_review": by_review},
        "workers": {"total": len(workers), "online": len(online),
                    "busy": sum(1 for w in online if w.telemetry.get("active_jobs", 0))},
        "resources": {
            "cpu_percent": round(sum(cpu) / len(cpu), 1) if cpu else None,
            "ram_used_mb": ram_used or None, "ram_total_mb": ram_total or None,
            "gpu_percent": round(sum(gpu_util) / len(gpu_util), 1) if gpu_util else None,
            "vram_used_mb": vram_used if vram_total else None, "vram_total_mb": vram_total or None,
            "gpu_count": len(gpus),
        },
        "storage": {"total_bytes": total, "free_bytes": free, "assets_bytes": used_assets},
        "history": [{"hour": k, **v} for k, v in buckets.items()],
        "avg_job_seconds": round(sum(durations) / len(durations), 1) if durations else None,
    }


# ----------------------------------------------------------------------------- catalogs
@router.get("/generators", dependencies=[Depends(require_viewer)])
def generators() -> list[dict]:
    from assetforge_procedural.building import PRESETS

    return [{
        "id": GENERATOR_ID, "version": GENERATOR_VERSION, "kind": "procedural", "requires": ["cpu"],
        "title": "Procedural buildings", "categories": sorted(PRESETS), "palettes": list_palettes(),
        "budgets": {k: list(v) for k, v in CATEGORY_BUDGETS.items() if k in PRESETS},
        "quality_profiles": {k.value: v for k, v in QUALITY_PROFILES.items()},
        "param_schema": BuildingParams.model_json_schema(),
        "formats": {"glb": "always", "blend": "needs Blender worker", "fbx": "needs Blender worker"},
    }]


@router.post("/plan", dependencies=[Depends(require_viewer)])
def plan_from_text(body: PlanIn, request: Request) -> dict:
    """Text description -> validated generator parameters (local LLM if configured, deterministic rules otherwise)."""
    from assetforge_procedural import plan

    s = request.app.state.settings
    use = body.use_llm and bool(s.llm_url and s.llm_model)
    r = plan(body.description, s.llm_url if use else None, s.llm_model if use else None)
    return {"params": r.params, "name": r.name, "source": r.source, "confidence": r.confidence, "matched": r.matched,
            "notes": r.notes, "llm_configured": bool(s.llm_url and s.llm_model)}


@router.get("/models", dependencies=[Depends(require_viewer)])
def models(request: Request, db: Session = Depends(get_db)) -> dict:
    """AI models installed on workers (reported through capabilities). Empty until Milestone 2 workers exist."""
    out = []
    for w in db.scalars(select(Worker)):
        for m in (w.capabilities or {}).get("models", []):
            out.append({"worker": w.name, **m})
    return {"items": out, "note": "AI providers (image/image-to-3D) arrive with the GPU workers (Milestone 2)."}


# ----------------------------------------------------------------------------- presets & art profiles
@router.get("/presets", dependencies=[Depends(require_viewer)])
def list_presets(db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": p.id, "name": p.name, "data": p.data, "created_at": iso(p.created_at)}
            for p in db.scalars(select(Preset).order_by(Preset.name))]


@router.post("/presets", status_code=201)
def save_preset(body: PresetIn, user: User = Depends(require_operator), db: Session = Depends(get_db)) -> dict:
    row = db.execute(select(Preset).where(Preset.name == body.name)).scalar_one_or_none()
    if row is None:
        row = Preset(name=body.name, data=body.data)
        db.add(row)
    else:
        row.data = body.data
    audit(db, user.username, "preset.save", "preset", body.name)
    db.commit()
    return {"id": row.id, "name": row.name, "data": row.data}


@router.delete("/presets/{preset_id}", status_code=204)
def delete_preset(preset_id: str, user: User = Depends(require_operator), db: Session = Depends(get_db)) -> Response:
    row = db.get(Preset, preset_id)
    if not row:
        raise HTTPException(404, "preset not found")
    db.delete(row)
    audit(db, user.username, "preset.delete", "preset", row.name)
    db.commit()
    return Response(status_code=204)


@router.get("/art-profiles", dependencies=[Depends(require_viewer)])
def list_art_profiles(db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": p.id, "name": p.name, "description": p.description, "data": p.data}
            for p in db.scalars(select(ArtProfile).order_by(ArtProfile.name))]


@router.post("/art-profiles", status_code=201)
def save_art_profile(body: ArtProfileIn, user: User = Depends(require_operator), db: Session = Depends(get_db)) -> dict:
    row = db.execute(select(ArtProfile).where(ArtProfile.name == body.name)).scalar_one_or_none()
    if row is None:
        row = ArtProfile(name=body.name, description=body.description, data=body.data)
        db.add(row)
    else:
        row.description, row.data = body.description, body.data
    audit(db, user.username, "art_profile.save", "art_profile", body.name)
    db.commit()
    return {"id": row.id, "name": row.name}


# ----------------------------------------------------------------------------- audit
@router.get("/audit", dependencies=[Depends(require_admin)])
def audit_log(db: Session = Depends(get_db), limit: int = 100) -> list[dict]:
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 500))).all()
    return [{"id": r.id, "ts": iso(r.ts), "actor": r.actor, "action": r.action, "entity": r.entity,
             "entity_id": r.entity_id, "detail": r.detail, "ip": r.ip} for r in rows]


# ----------------------------------------------------------------------------- real-time events (SSE)
@router.get("/events")
async def events(request: Request, last_event_id: int | None = Header(default=None, alias="Last-Event-ID"),
                 _: User = Depends(user_or_download_token)):
    """Server-Sent Events. Events are read from the database, so this works across API replicas."""
    db_ = request.app.state.db

    def fetch(after: int | None) -> tuple[list[Event], int]:
        with db_.session() as s:
            if after is None:
                return [], s.scalar(select(func.coalesce(func.max(Event.id), 0))) or 0
            rows = s.scalars(select(Event).where(Event.id > after).order_by(Event.id).limit(200)).all()
            return list(rows), after

    async def gen():
        _, last = await run_in_threadpool(fetch, None)
        if last_event_id is not None:
            last = last_event_id
        idle = 0
        yield "retry: 3000\n\n"
        while not await request.is_disconnected():
            rows, _ = await run_in_threadpool(fetch, last)
            for r in rows:
                last = r.id
                payload = json.dumps({"id": r.id, "ts": iso(r.ts), "type": r.type, "entity_id": r.entity_id, **r.data})
                yield f"id: {r.id}\nevent: {r.type}\ndata: {payload}\n\n"
            idle = 0 if rows else idle + 1
            if idle and idle % 15 == 0:
                yield ": keepalive\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

