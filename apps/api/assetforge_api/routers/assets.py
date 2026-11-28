"""Asset library: search, detail, review, versions, downloads."""

from __future__ import annotations

import mimetypes
import io
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from assetforge_vision import compare
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from ..ai.router import AiRejected, AiRouter, NoKeyAvailable
from ..models import Asset, AssetVersion, Job, User
from ..schemas import AssetDeleteRequest, AssetPatch, DownloadRequest, asset_out
from ..security import get_db, require_operator, require_viewer, user_or_download_token
from ..services import audit, emit_event
from ..storage import UnsafePath, safe_join
from .references import reference_path
from .ai import _decode_image

router = APIRouter(prefix="/assets", tags=["assets"])

MEDIA = {".glb": "model/gltf-binary", ".png": "image/png", ".json": "application/json", ".zip": "application/zip",
         ".blend": "application/octet-stream", ".fbx": "application/octet-stream"}


@router.get("", dependencies=[Depends(require_viewer)])
def list_assets(db: Session = Depends(get_db), q: str | None = None, category: str | None = None,
                tag: str | None = None, review_status: str | None = None, favorite: bool | None = None,
                sort: str = Query("-created_at", pattern=r"^-?(created_at|name|triangle_count|updated_at)$"),
                limit: int = Query(60, ge=1, le=500), offset: int = Query(0, ge=0)) -> dict:
    stmt = select(Asset)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Asset.name.ilike(like), Asset.id.ilike(like), Asset.category.ilike(like)))
    if category:
        stmt = stmt.where(Asset.category == category)
    if review_status:
        stmt = stmt.where(Asset.review_status == review_status)
    if favorite is not None:
        stmt = stmt.where(Asset.favorite.is_(favorite))
    items = db.scalars(stmt).all()
    if tag:
        items = [a for a in items if tag in (a.tags or [])]
    desc = sort.startswith("-")
    key = sort.lstrip("-")
    if key == "triangle_count":
        keyfn = lambda a: asset_out(a)["triangle_count"]  # noqa: E731
    else:
        keyfn = lambda a: getattr(a, key)  # noqa: E731
    items.sort(key=keyfn, reverse=desc)
    total = len(items)
    page = items[offset: offset + limit]
    facets_cat = dict(db.execute(select(Asset.category, func.count()).group_by(Asset.category)).all())
    return {"total": total, "items": [asset_out(a) for a in page], "facets": {"category": facets_cat}}


@router.get("/{asset_id}", dependencies=[Depends(require_viewer)])
def get_asset(asset_id: str, version: int | None = None, db: Session = Depends(get_db)) -> dict:
    a = db.get(Asset, asset_id)
    if not a:
        raise HTTPException(404, "asset not found")
    v = None
    if version is not None:
        v = next((x for x in a.versions if x.version == version), None)
        if v is None:
            raise HTTPException(404, "version not found")
    return asset_out(a, v, detail=True)


@router.patch("/{asset_id}")
def patch_asset(asset_id: str, body: AssetPatch, version: int | None = None, user: User = Depends(require_operator),
                db: Session = Depends(get_db)) -> dict:
    a = db.scalar(select(Asset).where(Asset.id == asset_id).with_for_update())
    if not a:
        raise HTTPException(404, "asset not found")
    changes = body.model_dump(exclude_none=True)
    selected = None
    if "review_status" in changes:
        selected = _version(db, asset_id, version, lock=True)
        selected.manifest = {**selected.manifest, "art_review": {
            "status": changes["review_status"], "reviewed_by": user.username,
        }}
        if selected.version != a.current_version:
            changes = {k: v for k, v in changes.items() if k != "review_status"}
    for k, v in changes.items():
        if k == "tags":
            v = sorted({t.strip()[:40] for t in v if t.strip()})
        setattr(a, k, v)
    audit(db, user.username, "asset.update", "asset", a.id, version=version or a.current_version,
          **{k: (v if k != "tags" else len(v)) for k, v in body.model_dump(exclude_none=True).items()})
    emit_event(db, "asset.updated", a.id, **{k: v for k, v in changes.items() if k != "tags"})
    db.commit()
    return asset_out(a, selected)


def _delete_assets(ids: list[str], request: Request, user: User, db: Session) -> dict:
    """Delete assets (rows and files). An asset that a queued/running job is still producing is skipped, never half-deleted."""
    storage = request.app.state.storage
    deleted: list[str] = []
    skipped: list[dict] = []
    freed = 0
    for aid in dict.fromkeys(ids):
        a = db.get(Asset, aid)
        if a is None:
            skipped.append({"id": aid, "reason": "não encontrado"})
            continue
        busy = db.scalar(select(func.count(Job.id)).where(Job.asset_id == aid, Job.status.in_(("queued", "running", "cancelling"))))
        if busy:
            skipped.append({"id": aid, "name": a.name, "reason": "há uma geração em andamento para este modelo"})
            continue
        name, versions = a.name, len(a.versions)
        try:
            freed += storage.delete_asset(aid)
        except UnsafePath:
            skipped.append({"id": aid, "name": name, "reason": "identificador inválido"})
            continue
        for v in list(a.versions):
            db.delete(v)
        db.delete(a)
        audit(db, user.username, "asset.delete", "asset", aid, name=name, versions=versions)
        emit_event(db, "asset.deleted", aid)
        deleted.append(aid)
    db.commit()
    return {"deleted": deleted, "skipped": skipped, "freed_bytes": freed}


@router.post("/delete")
def delete_assets(body: AssetDeleteRequest, request: Request, user: User = Depends(require_operator), db: Session = Depends(get_db)) -> dict:
    """Delete several assets at once (the Library's 'Apagar selecionados')."""
    return _delete_assets(body.asset_ids, request, user, db)


@router.delete("/{asset_id}")
def delete_asset(asset_id: str, request: Request, user: User = Depends(require_operator), db: Session = Depends(get_db)) -> dict:
    r = _delete_assets([asset_id], request, user, db)
    if not r["deleted"] and r["skipped"] and r["skipped"][0]["reason"] == "não encontrado":
        raise HTTPException(404, "asset not found")
    return r


def _version(db: Session, asset_id: str, version: int | None, *, lock: bool = False) -> AssetVersion:
    a = db.get(Asset, asset_id)
    if not a:
        raise HTTPException(404, "asset not found")
    ver = version if version is not None else a.current_version
    stmt = select(AssetVersion).where(AssetVersion.asset_id == asset_id, AssetVersion.version == ver)
    v = db.scalar(stmt.with_for_update().execution_options(populate_existing=True) if lock else stmt)
    if not v:
        raise HTTPException(404, "version not found")
    return v


class EvaluationIn(BaseModel):
    renders: list[str] = Field(min_length=1, max_length=4)


def evaluation_image(data: bytes) -> tuple[bytes, str]:
    """Normalize submitted renders and references before handing them to the central key pool."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > 16_777_216:
                raise HTTPException(413, "render image too large")
            rgba = image.convert("RGBA")
            rgba.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
            flat = Image.new("RGB", rgba.size, (200, 200, 200))
            flat.paste(rgba, mask=rgba.getchannel("A"))
            out = io.BytesIO()
            flat.save(out, "JPEG", quality=88)
            return out.getvalue(), "image/jpeg"
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "invalid evaluation image") from exc


@router.post("/{asset_id}/versions/{version}/evaluate")
def evaluate(asset_id: str, version: int, body: EvaluationIn, request: Request,
             user: User = Depends(require_operator), db: Session = Depends(get_db)) -> dict:
    selected = _version(db, asset_id, version)
    params = selected.manifest.get("generation_params", {})
    refs = params.get("original_references") or params.get("references") or {}
    front = refs.get("front") or params.get("reference_id") or next(iter(params.get("reference_ids") or []), None)
    settings = request.app.state.settings
    originals = [(name, refs[name]) for name in ("front", "right", "back", "three_quarter") if name in refs]
    if not originals and front:
        originals = [("front", front)]
    if originals:
        images = [evaluation_image(reference_path(request, ref).read_bytes()) for _, ref in originals]
        reference_names = [name for name, _ in originals]
    elif params.get("generated_reference_file") == "reference.png":
        generated = request.app.state.storage.asset_dir(asset_id, selected.version) / "reference.png"
        if not generated.is_file():
            raise HTTPException(410, "a referência gerada está indisponível")
        images = [evaluation_image(generated.read_bytes())]
        reference_names = ["front"]
    else:
        raise HTTPException(422, "esta versão não tem imagem de referência")
    images += [evaluation_image(_decode_image(b, 4 * 1024**2)[0]) for b in body.renders]
    names = [f"captura {i}" for i in range(1, len(body.renders) + 1)]
    model_label = f"{asset_id} v{version}"
    try:
        ans = AiRouter(db, settings.resolved_secret()).generate_json(
            "asset.visual_review", compare.SYSTEM, compare.compare_prompt(
                names, model_label, reference_names=reference_names), images,
            compare.COMPARE_SCHEMA, compare.PROMPT_VERSION, selected.job_id or "", provider="gemini",
        )
    except NoKeyAvailable as exc:
        raise HTTPException(429, "Gemini indisponível no pool central. Confira a cota em IA na nuvem.") from exc
    except AiRejected as exc:
        raise HTTPException(502, "Gemini recusou a avaliação") from exc
    selected = _version(db, asset_id, version, lock=True)
    report = {**compare.clean(ans.data), "provider": ans.provider, "model": ans.model, "cached": ans.cached}
    selected.manifest = {**selected.manifest, "gemini_evaluation": report}
    audit(db, user.username, "asset.evaluate", "asset", asset_id, version=version, model=ans.model)
    db.commit()
    return report


@router.get("/{asset_id}/files/{path:path}")
def get_file(asset_id: str, path: str, request: Request, version: int | None = None,
             download: bool = False, _: User = Depends(user_or_download_token), db: Session = Depends(get_db)):
    v = _version(db, asset_id, version)
    if path not in {f["name"] for f in v.files}:
        raise HTTPException(404, "file not part of this asset version")
    try:
        full = safe_join(request.app.state.storage.asset_dir(asset_id, v.version), path)
    except UnsafePath as exc:
        raise HTTPException(400, str(exc)) from exc
    if not full.is_file():
        raise HTTPException(410, "file is registered but missing on disk")
    media = MEDIA.get(full.suffix.lower()) or mimetypes.guess_type(full.name)[0] or "application/octet-stream"
    headers = {"Cache-Control": "private, max-age=300"}
    return FileResponse(full, media_type=media, headers=headers,
                        filename=f"{asset_id}_v{v.version}_{full.name}" if download else None)


@router.get("/{asset_id}/package")
def get_package(asset_id: str, request: Request, version: int | None = None,
                _: User = Depends(user_or_download_token), db: Session = Depends(get_db)):
    v = _version(db, asset_id, version)
    pkg = next((f["name"] for f in v.files if f["role"] == "package"), None)
    if not pkg:
        raise HTTPException(404, "no package in this version")
    full = safe_join(request.app.state.storage.asset_dir(asset_id, v.version), pkg)
    if not full.is_file():
        raise HTTPException(410, "package missing on disk")
    return FileResponse(full, media_type="application/zip", filename=pkg)


@router.post("/download")
def batch_download(body: DownloadRequest, request: Request, _: User = Depends(require_viewer),
                   db: Session = Depends(get_db)):
    """ZIP with one folder per asset (full package contents, or just the GLB)."""
    storage = request.app.state.storage
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()
    count = 0
    with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as zf:
        for aid in body.asset_ids:
            a = db.get(Asset, aid)
            if not a:
                continue
            v = next((x for x in a.versions if x.version == (body.version or a.current_version)), None)
            if not v:
                continue
            base = storage.asset_dir(aid, v.version)
            for f in v.files:
                if f["role"] == "package":
                    continue
                if body.include == "glb" and f["name"] != "model.glb":
                    continue
                p = safe_join(base, f["name"])
                if p.is_file():
                    zf.write(p, f"{a.name}_{aid}_v{v.version}/{f['name']}")
                    count += 1
    if count == 0:
        Path(tmp.name).unlink(missing_ok=True)
        raise HTTPException(404, "nothing to download")
    return FileResponse(tmp.name, media_type="application/zip", filename="assetforge_assets.zip",
                        background=BackgroundTask(lambda: Path(tmp.name).unlink(missing_ok=True)))
