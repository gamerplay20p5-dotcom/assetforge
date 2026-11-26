"""Image -> house description with the local vision model (Qwen2.5-VL on CPU, separate container).

The API only forwards a validated reference image to the internal vision service and validates what comes back against a strict schema.
Nothing the model writes is executed: it can only fill the fields of :class:`HouseDescription`.
"""

from __future__ import annotations

import logging
import re
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


def _ref_size(request: Request, job: dict[str, Any]) -> tuple[int, int] | None:
    """Pixel size of the image of an analysis (remembered in memory when it was submitted; lost on API restart, then simply unknown)."""
    return getattr(request.app.state, "vision_sizes", {}).get(job.get("id"))


def _services(request: Request) -> list[str]:
    urls = [u.strip().rstrip("/") for u in request.app.state.settings.vlm_url.split(",") if u.strip()]
    if not urls:
        raise HTTPException(503, "the vision service is not enabled on this server (ASSETFORGE_VLM_URL is empty)")
    return urls


def _auth(request: Request) -> dict[str, str]:
    t = request.app.state.settings.vlm_token
    return {"Authorization": f"Bearer {t}"} if t else {}


def _pick(request: Request) -> tuple[int, str]:
    """First service (in the configured order) that answers /health with ready=true; the order lets a GPU box go first with the CPU one as backup."""
    for i, u in enumerate(_services(request)):
        try:
            h = httpx.get(f"{u}/health", timeout=3).json()
            if h.get("ready"):
                return i, u
        except (httpx.HTTPError, ValueError):
            continue
    raise HTTPException(503, "no vision service is ready (check the GPU box and the CPU container)")


def _describe_result(answer: str, image_size: tuple[int, int] | None = None) -> dict[str, Any]:
    """Validate the raw model answer; on failure keep the answer so the person can still start from defaults."""
    try:
        raw = extract_json(answer)
        analysis = parse_analysis(raw)
        out: dict[str, Any] = dict(valid=True, category=analysis.category, subject=analysis.subject, isolated_object=analysis.isolated_object,
                                   route=route(analysis, image_size))
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
    if not request.app.state.settings.vlm_url:
        return dict(enabled=False, reason="serviço de visão não habilitado neste servidor")
    services = []
    for i, u in enumerate(_services(request)):
        try:
            h = httpx.get(f"{u}/health", timeout=3).json()
            services.append(dict(index=i, ready=bool(h.get("ready")), device=h.get("device", "cpu"), model=h.get("model"), loaded=bool(h.get("loaded")), pending=h.get("pending", 0)))
        except (httpx.HTTPError, ValueError) as exc:
            services.append(dict(index=i, ready=False, error=type(exc).__name__))
    chosen = next((x for x in services if x["ready"]), None)
    if chosen is None:
        return dict(enabled=True, ready=False, services=services, reason="nenhum serviço de visão está disponível (GPU e CPU)")
    return dict(enabled=True, ready=True, loaded=chosen["loaded"], model=chosen["model"], device=chosen["device"], pending=chosen["pending"], services=services, reason=None)


@router.post("/describe", status_code=202)
def describe(body: DescribeIn, request: Request, user: User = Depends(require_operator)) -> dict[str, Any]:
    idx, url = _pick(request)
    png = reference_path(request, body.reference_id).read_bytes()
    try:
        r = httpx.post(f"{url}/describe?task=analysis", content=png, headers={"Content-Type": "application/octet-stream", **_auth(request)}, timeout=30)
    except httpx.HTTPError as exc:
        raise HTTPException(503, f"vision service unreachable: {type(exc).__name__}") from exc
    if r.status_code != 202:
        raise HTTPException(502 if r.status_code >= 500 else r.status_code, r.json().get("error", "vision service refused the image"))
    from PIL import Image

    with Image.open(reference_path(request, body.reference_id)) as im:
        sizes = request.app.state.__dict__.setdefault("vision_sizes", {})
        sizes[f"{idx}.{r.json()['id']}"] = im.size
        for k in list(sizes)[:-200]:  # keep it small
            sizes.pop(k, None)
    log.info("vision analysis started by %s for %s", user.username, body.reference_id)
    return {"id": f"{idx}.{r.json()['id']}", "status": "queued"}  # "<service index>.<service job id>": the status must ask the same service


@router.get("/describe/{job_id}", dependencies=[Depends(require_viewer)])
def describe_status(job_id: str, request: Request) -> dict[str, Any]:
    m = re.fullmatch(r"(\d)\.(vis_[0-9a-f]{12})", job_id)
    if not m:
        raise HTTPException(422, "invalid analysis id")
    services = _services(request)
    if int(m.group(1)) >= len(services):
        raise HTTPException(404, "analysis not found")
    url, svc_id = services[int(m.group(1))], m.group(2)
    try:
        r = httpx.get(f"{url}/jobs/{svc_id}", headers=_auth(request), timeout=10)
    except httpx.HTTPError as exc:
        raise HTTPException(503, f"vision service unreachable: {type(exc).__name__}") from exc
    if r.status_code == 404:
        raise HTTPException(404, "analysis not found (the vision service may have restarted)")
    j = r.json()
    j["id"] = job_id  # the service knows its own id; the API id also carries the service index
    out: dict[str, Any] = dict(id=job_id, status=j["status"], started=j.get("started"), finished=j.get("finished"), error=j.get("error"))
    if j["status"] == "succeeded":
        res = j["result"]
        out.update(seconds=res.get("seconds"), new_tokens=res.get("new_tokens"), raw_answer=res["answer"], **_describe_result(res["answer"], _ref_size(request, j)))
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
