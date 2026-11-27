"""Cloud AI (Gemini / Grok) administration and the worker proxy.

* Keys are only ever written (``POST``) and are stored encrypted; responses carry a masked hint, never the key.
* Workers never see a key: they call ``POST /worker/jobs/{id}/ai`` with their lease, the API builds the prompt from versioned templates, calls the
  key pool (fail-over between keys/providers) and returns the validated JSON. Nothing the model returns is executed.
"""

from __future__ import annotations

import base64
import binascii
import re
from datetime import timedelta
from typing import Any, Literal

from assetforge_vision import llm_spec
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ai.crypto import encrypt, hint
from ..ai.providers import PROVIDERS, ProviderError, make_provider, pick_model
from ..ai.router import AiRouter, NoKeyAvailable, _aware, day_start, get_ai_settings, is_paid, put_ai_settings
from ..db import utcnow
from ..models import AiKey, AiRequest, User, Worker
from ..security import current_worker, get_db, require_admin, require_viewer
from ..services import audit
from .references import reference_path
from .workers import _lease_job

router = APIRouter(prefix="/ai", tags=["cloud-ai"])
worker_router = APIRouter(prefix="/worker", tags=["worker-protocol"])
Provider = Literal["gemini", "grok"]
_URL = re.compile(r"^https?://[\w.\-:\[\]]+(/[\w.\-/]*)?$")
MAX_IMAGES = 10


def _key_out(r: AiRouter, k: AiKey) -> dict[str, Any]:
    u = r.usage(k)
    cd = _aware(k.cooldown_until)
    return {"id": k.id, "provider": k.provider, "label": k.label, "key_hint": k.key_hint, "model": k.model, "priority": k.priority, "enabled": k.enabled,
            "allow_paid": k.allow_paid, "paid": is_paid(k), "rpm_limit": k.rpm_limit, "rpd_limit": k.rpd_limit,
            "cooldown_until": cd.isoformat() if cd and cd > utcnow() else None,
            "last_error": k.last_error, "custom_endpoint": bool(k.base_url), "usage": u, "created_at": k.created_at.isoformat()}


def _router(request: Request, db: Session) -> AiRouter:
    return AiRouter(db, request.app.state.secret)


class KeyIn(BaseModel):
    provider: Provider
    api_key: str = Field(min_length=8, max_length=400)
    label: str = Field(default="", max_length=80)
    model: str = Field(default="", max_length=120, pattern=r"^[\w.\-/]*$")
    priority: int = Field(default=100, ge=0, le=10000)
    rpm_limit: int = Field(default=5, ge=0, le=10000)
    rpd_limit: int = Field(default=100, ge=0, le=1000000)
    allow_paid: bool = False
    base_url: str = Field(default="", max_length=200)

    @field_validator("api_key")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if any(c.isspace() for c in v):
            raise ValueError("the API key must not contain spaces")
        return v

    @field_validator("base_url")
    @classmethod
    def _url(cls, v: str) -> str:
        if v and not _URL.match(v):
            raise ValueError("invalid base URL")
        return v


class KeyPatch(BaseModel):
    label: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=120, pattern=r"^[\w.\-/]*$")
    priority: int | None = Field(default=None, ge=0, le=10000)
    rpm_limit: int | None = Field(default=None, ge=0, le=10000)
    rpd_limit: int | None = Field(default=None, ge=0, le=1000000)
    enabled: bool | None = None
    allow_paid: bool | None = None
    clear_cooldown: bool = False


class ProbeIn(BaseModel):
    provider: Provider
    api_key: str = Field(min_length=8, max_length=400)
    base_url: str = Field(default="", max_length=200)


class SettingsIn(BaseModel):
    free_only: bool | None = None
    agent_iterations: int | None = Field(default=None, ge=0, le=5)
    target_score: float | None = Field(default=None, ge=0, le=10)


def _list_models(provider: str, api_key: str, base_url: str) -> list[dict]:
    try:
        return make_provider(provider, api_key, base_url).list_models()
    except ProviderError as exc:
        raise HTTPException(400, f"the provider rejected the request: {exc}") from exc


# ============================================================================================ admin
@router.get("/settings", dependencies=[Depends(require_viewer)])
def read_settings(db: Session = Depends(get_db)) -> dict:
    return {**get_ai_settings(db), "providers": {k: {"free_tier": v.free_tier} for k, v in PROVIDERS.items()},
            "data_notice": "Imagens enviadas ao nível gratuito da API Gemini podem ser usadas pelo Google para melhorar seus produtos."}


@router.put("/settings")
def write_settings(body: SettingsIn, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    vals = body.model_dump(exclude_none=True)
    audit(db, admin.username, "ai.settings", "ai", "", request.client.host if request.client else "", **vals)
    return put_ai_settings(db, vals)


@router.get("/keys", dependencies=[Depends(require_admin)])
def list_keys(request: Request, db: Session = Depends(get_db)) -> list[dict]:
    r = _router(request, db)
    return [_key_out(r, k) for k in db.execute(select(AiKey).order_by(AiKey.priority, AiKey.created_at)).scalars()]


@router.post("/models", dependencies=[Depends(require_admin)])
async def probe_models(body: ProbeIn) -> dict:
    """Test a key BEFORE saving it and list the models it can use."""
    models = await run_in_threadpool(_list_models, body.provider, body.api_key.strip(), body.base_url)
    names = [m["name"] for m in models]
    return {"ok": True, "models": models, "suggested": pick_model(body.provider, names)}


@router.post("/keys", status_code=201)
async def add_key(body: KeyIn, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    models = await run_in_threadpool(_list_models, body.provider, body.api_key, body.base_url)  # never store a key that does not work
    names = [m["name"] for m in models]
    model = body.model or pick_model(body.provider, names) or ""
    if body.model and names and body.model not in names:
        raise HTTPException(422, f"model {body.model!r} is not available for this key")
    k = AiKey(provider=body.provider, label=body.label, key_enc=encrypt(request.app.state.secret, body.api_key), key_hint=hint(body.api_key), model=model,
              priority=body.priority, rpm_limit=body.rpm_limit, rpd_limit=body.rpd_limit, allow_paid=body.allow_paid, base_url=body.base_url)
    db.add(k)
    audit(db, admin.username, "ai.key.add", "ai_key", k.id, request.client.host if request.client else "", provider=body.provider, hint=k.key_hint)
    db.commit()
    return _key_out(_router(request, db), k)


def _get_key(db: Session, key_id: str) -> AiKey:
    k = db.get(AiKey, key_id)
    if k is None:
        raise HTTPException(404, "key not found")
    return k


@router.patch("/keys/{key_id}")
def patch_key(key_id: str, body: KeyPatch, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    k = _get_key(db, key_id)
    for f in ("label", "model", "priority", "rpm_limit", "rpd_limit", "enabled", "allow_paid"):
        v = getattr(body, f)
        if v is not None:
            setattr(k, f, v)
    if body.clear_cooldown:
        k.cooldown_until, k.last_error = None, ""
    audit(db, admin.username, "ai.key.patch", "ai_key", k.id, request.client.host if request.client else "", **body.model_dump(exclude_none=True))
    db.commit()
    return _key_out(_router(request, db), k)


@router.delete("/keys/{key_id}", status_code=204)
def delete_key(key_id: str, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> Response:
    k = _get_key(db, key_id)
    db.delete(k)
    audit(db, admin.username, "ai.key.delete", "ai_key", key_id, request.client.host if request.client else "")
    db.commit()
    return Response(status_code=204)


@router.post("/keys/{key_id}/test", dependencies=[Depends(require_admin)])
async def test_key(key_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    k = _get_key(db, key_id)
    r = _router(request, db)
    try:
        prov = r.provider_for(k)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        models = await run_in_threadpool(prov.list_models)
    except ProviderError as exc:
        k.last_error = str(exc)[:400]
        db.commit()
        return {"ok": False, "error": str(exc)[:400]}
    k.last_error = ""
    db.commit()
    names = [m["name"] for m in models]
    return {"ok": True, "models": models, "model_available": (not k.model) or k.model in names, "suggested": pick_model(k.provider, names)}


@router.get("/usage", dependencies=[Depends(require_viewer)])
def usage(db: Session = Depends(get_db)) -> dict:
    now = utcnow()
    since = min(day_start("gemini", now), day_start("grok", now))
    rows = db.execute(select(AiRequest.provider, AiRequest.status, func.count(AiRequest.id), func.coalesce(func.sum(AiRequest.total_tokens), 0))
                      .where(AiRequest.ts >= since).group_by(AiRequest.provider, AiRequest.status)).all()
    week = db.execute(select(func.count(AiRequest.id), func.coalesce(func.sum(AiRequest.total_tokens), 0))
                      .where(AiRequest.ts >= now - timedelta(days=7), AiRequest.status == "ok")).one()
    return {"today": [{"provider": p, "status": s, "requests": int(n), "tokens": int(t)} for p, s, n, t in rows],
            "week": {"requests": int(week[0]), "tokens": int(week[1])}}


@router.get("/requests", dependencies=[Depends(require_viewer)])
def history(limit: int = 50, job_id: str = "", db: Session = Depends(get_db)) -> list[dict]:
    q = select(AiRequest).order_by(AiRequest.id.desc()).limit(max(1, min(limit, 500)))
    if job_id:
        q = q.where(AiRequest.job_id == job_id)
    return [{"id": x.id, "ts": x.ts.isoformat(), "key_id": x.key_id, "provider": x.provider, "model": x.model, "task": x.task, "job_id": x.job_id,
             "status": x.status, "prompt_tokens": x.prompt_tokens, "output_tokens": x.output_tokens, "total_tokens": x.total_tokens,
             "latency_ms": x.latency_ms, "error": x.error} for x in db.execute(q).scalars()]


@router.get("/status", dependencies=[Depends(require_viewer)])
def status(request: Request, db: Session = Depends(get_db)) -> dict:
    """For the Studio: is at least one key usable right now (without revealing anything about the keys)?"""
    keys, why, soonest = _router(request, db).candidates()
    total = db.execute(select(func.count(AiKey.id))).scalar_one()
    return {"configured": total > 0, "available": len(keys), "next_available_at": soonest.isoformat() if soonest else None, "blocked": why[:10],
            **{k: v for k, v in get_ai_settings(db).items()}}


# ============================================================================================ worker proxy
class WorkerAiIn(BaseModel):
    lease_token: str
    task: Literal["spec", "critique"]
    reference_ids: list[str] = Field(min_length=1, max_length=4)
    renders_b64: list[str] = Field(default_factory=list, max_length=6)  # PNG/JPEG renders of the current model (critique)
    category_hint: str = Field(default="", max_length=40)
    validation_error: str = Field(default="", max_length=2000)
    previous: dict | None = None
    spec: dict | None = None
    iteration: int = Field(default=0, ge=0, le=20)


def _decode_image(b64: str, limit: int) -> tuple[bytes, str]:
    try:
        data = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, "invalid base64 image") from exc
    if len(data) > limit:
        raise HTTPException(413, "render image too large")
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return data, "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return data, "image/jpeg"
    raise HTTPException(422, "renders must be PNG or JPEG")


@worker_router.post("/jobs/{job_id}/ai")
async def worker_ai(job_id: str, body: WorkerAiIn, request: Request, worker: Worker = Depends(current_worker), db: Session = Depends(get_db)):
    job = _lease_job(db, job_id, worker, body.lease_token)
    if job.job_type != "agent.building":
        raise HTTPException(403, "this job type may not call the cloud AI")
    limit = request.app.state.settings.max_reference_mb * 1024 * 1024
    refs = [(reference_path(request, r).read_bytes(), "image/png") for r in body.reference_ids]
    if body.task == "spec":
        images = refs
        prompt = llm_spec.spec_prompt(len(refs), body.category_hint, body.validation_error, body.previous)
        schema = llm_spec.SPEC_SCHEMA
    else:
        if not body.renders_b64 or body.spec is None:
            raise HTTPException(422, "critique needs renders_b64 and spec")
        renders = [_decode_image(b, limit) for b in body.renders_b64]
        images = refs + renders
        prompt = llm_spec.critique_prompt(len(refs), len(renders), body.spec, body.iteration)
        schema = llm_spec.CRITIQUE_SCHEMA
    if len(images) > MAX_IMAGES:
        raise HTTPException(422, "too many images")
    r = _router(request, db)
    try:
        ans = await run_in_threadpool(r.generate_json, body.task, llm_spec.SYSTEM, prompt, images, schema, llm_spec.PROMPT_VERSION, job_id)
    except NoKeyAvailable as exc:
        wait = max(30.0, (exc.retry_at - utcnow()).total_seconds()) if exc.retry_at else None
        return JSONResponse(status_code=429, content={"detail": str(exc)[:1500], "retry_after_s": wait})
    return {"data": ans.data, "provider": ans.provider, "model": ans.model, "cached": ans.cached, "total_tokens": ans.total_tokens}
