"""Image -> house description with the local vision model (Qwen2.5-VL on CPU, separate container).

The API only forwards a validated reference image to the internal vision service and validates what comes back against a strict schema.
Nothing the model writes is executed: it can only fill the fields of :class:`HouseDescription`.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from assetforge_vision.kits import route
from assetforge_vision.mapper import description_to_spec, pick_base
from assetforge_vision.schema import DescriptionError, HouseDescription, extract_json, parse_analysis, parse_description
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..models import User
from ..security import require_operator, require_viewer
from .references import reference_path

log = logging.getLogger("assetforge.vision")
router = APIRouter(prefix="/vision", tags=["vision"])

BASE_LABELS = {
    "ref01": "Térrea com varanda (craftsman)", "ref02": "Sobrado de quatro águas", "ref03": "Meios níveis (tijolo + tábuas)",
    "ref04": "Moderna de telhado inclinado", "ref05": "Sobrado de tijolo", "ref06": "Sobrado com varanda e garagem", "bungalow": "Bangalô moderno",
}


def _url(request: Request) -> str:
    url = request.app.state.settings.vlm_url
    if not url:
        raise HTTPException(503, "the vision service is not enabled on this server (ASSETFORGE_VLM_URL is empty)")
    return url.rstrip("/")


def _describe_result(answer: str) -> dict[str, Any]:
    """Validate the raw model answer; on failure keep the answer so the person can still start from defaults."""
    try:
        raw = extract_json(answer)
        analysis = parse_analysis(raw)
        out: dict[str, Any] = dict(valid=True, category=analysis.category, subject=analysis.subject, isolated_object=analysis.isolated_object,
                                   route=route(analysis))
        if analysis.house is not None:
            house_raw = raw.get("house") if isinstance(raw.get("house"), dict) else raw
            base = pick_base(analysis.house)
            out.update(description=analysis.house.to_dict(), base=base, base_label=BASE_LABELS.get(base, base),
                       fields_missing=[k for k in HouseDescription().to_dict() if k not in house_raw])
        return out
    except DescriptionError as exc:
        return dict(valid=False, error=str(exc))


class DescribeIn(BaseModel):
    reference_id: str = Field(pattern=r"^ref_[0-9a-f]{12}$")


class PreviewIn(BaseModel):
    description: dict[str, Any]
    seed: int = Field(default=1, ge=0, le=2**31 - 1)


@router.get("/status", dependencies=[Depends(require_viewer)])
def status(request: Request) -> dict[str, Any]:
    url = request.app.state.settings.vlm_url
    if not url:
        return dict(enabled=False, reason="serviço de visão não habilitado neste servidor")
    try:
        r = httpx.get(f"{url.rstrip('/')}/health", timeout=4)
        h = r.json()
        return dict(enabled=True, ready=bool(h.get("ready")), loaded=bool(h.get("loaded")), model=h.get("model"), pending=h.get("pending", 0),
                    reason=None if h.get("ready") else "pesos do modelo não estão no cache")
    except (httpx.HTTPError, ValueError) as exc:
        return dict(enabled=True, ready=False, reason=f"serviço de visão indisponível ({type(exc).__name__})")


@router.post("/describe", status_code=202)
def describe(body: DescribeIn, request: Request, user: User = Depends(require_operator)) -> dict[str, Any]:
    url = _url(request)
    png = reference_path(request, body.reference_id).read_bytes()
    try:
        r = httpx.post(f"{url}/describe?task=analysis", content=png, headers={"Content-Type": "application/octet-stream"}, timeout=30)
    except httpx.HTTPError as exc:
        raise HTTPException(503, f"vision service unreachable: {type(exc).__name__}") from exc
    if r.status_code != 202:
        raise HTTPException(502 if r.status_code >= 500 else r.status_code, r.json().get("error", "vision service refused the image"))
    log.info("vision analysis started by %s for %s", user.username, body.reference_id)
    return {"id": r.json()["id"], "status": "queued"}


@router.get("/describe/{job_id}", dependencies=[Depends(require_viewer)])
def describe_status(job_id: str, request: Request) -> dict[str, Any]:
    if not job_id.startswith("vis_") or len(job_id) > 32:
        raise HTTPException(422, "invalid analysis id")
    url = _url(request)
    try:
        r = httpx.get(f"{url}/jobs/{job_id}", timeout=10)
    except httpx.HTTPError as exc:
        raise HTTPException(503, f"vision service unreachable: {type(exc).__name__}") from exc
    if r.status_code == 404:
        raise HTTPException(404, "analysis not found (the vision service may have restarted)")
    j = r.json()
    out: dict[str, Any] = dict(id=job_id, status=j["status"], started=j.get("started"), finished=j.get("finished"), error=j.get("error"))
    if j["status"] == "succeeded":
        res = j["result"]
        out.update(seconds=res.get("seconds"), new_tokens=res.get("new_tokens"), raw_answer=res["answer"], **_describe_result(res["answer"]))
    return out


@router.post("/preview", dependencies=[Depends(require_viewer)])
def preview(body: PreviewIn) -> dict[str, Any]:
    """Validate an (edited) description and say which kit house it will be built on."""
    try:
        desc = parse_description(body.description)
        spec = description_to_spec(desc, body.seed)
    except (DescriptionError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    base = pick_base(desc)
    return dict(valid=True, description=desc.to_dict(), base=base, base_label=BASE_LABELS.get(base, base), wings=len(spec.wings), features=[f.type for f in spec.features])
