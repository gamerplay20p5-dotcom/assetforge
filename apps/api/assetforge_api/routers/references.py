"""Reference images for image-to-3D jobs (validated, re-encoded, size-limited)."""

from __future__ import annotations

import hashlib
import io
import re
import tempfile
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError

from ..models import User, Worker
from ..security import current_worker, get_db, require_operator, user_or_download_token

router = APIRouter(prefix="/references", tags=["references"])
worker_router = APIRouter(prefix="/worker/references", tags=["worker-protocol"])
_ID = re.compile(r"^ref_[0-9a-f]{12}$")
Image.MAX_IMAGE_PIXELS = 40_000_000  # decompression-bomb guard


def reference_path(request: Request, ref_id: str):
    if not _ID.match(ref_id):
        raise HTTPException(422, "invalid reference id")
    p = request.app.state.storage.root / "references" / f"{ref_id}.png"
    if not p.is_file():
        raise HTTPException(404, "reference not found")
    return p


async def _decode_upload(request: Request, file: UploadFile) -> tuple[bytes, tuple[int, int]]:
    limit = request.app.state.settings.max_reference_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"image larger than {request.app.state.settings.max_reference_mb} MB")
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format not in ("PNG", "JPEG", "WEBP"):
                raise HTTPException(422, f"unsupported image format {im.format}; use PNG, JPEG or WEBP")
            im = ImageOps.exif_transpose(im)
            w, h = im.size
            if max(w, h) > 4096 or min(w, h) < 64:
                raise HTTPException(422, f"image size {w}x{h} outside 64..4096 px")
            im.load()
            clean = im.convert("RGBA" if "A" in im.getbands() else "RGB")  # re-encoding drops EXIF/metadata/payloads
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "file is not a valid image") from exc
    buf = io.BytesIO()
    clean.save(buf, "PNG")
    return buf.getvalue(), (w, h)


@router.post("", status_code=201)
async def upload_reference(request: Request, file: UploadFile, user: User = Depends(require_operator)) -> dict:
    batch = await _store(request, [file], user)
    item = batch[0]
    del item["filename"]
    return item


async def _store(request: Request, files: list[UploadFile], user: User) -> list[dict]:
    d = request.app.state.storage.root / "references"
    d.mkdir(exist_ok=True)
    items = []
    with tempfile.TemporaryDirectory(prefix=".batch-", dir=d) as temporary:
        staging = d.joinpath(temporary)
        for file in files:
            data, (w, h) = await _decode_upload(request, file)
            ref_id = f"ref_{uuid.uuid4().hex[:12]}"
            (staging / f"{ref_id}.png").write_bytes(data)
            items.append({"id": ref_id, "width": w, "height": h, "sha256": hashlib.sha256(data).hexdigest(),
                          "filename": file.filename, "uploaded_by": user.username})
        for item in items:
            filename = f"{item['id']}.png"
            (staging / filename).replace(d / filename)
    return items


@router.post("/batch", status_code=201)
async def upload_reference_batch(request: Request, files: list[UploadFile], user: User = Depends(require_operator)) -> dict:
    settings = request.app.state.settings
    if not files or len(files) > settings.max_batch_jobs * 4:
        raise HTTPException(422, "invalid reference batch size")
    if sum(file.size or 0 for file in files) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, "reference batch exceeds the upload limit")
    return {"items": await _store(request, files, user)}


@router.get("/{ref_id}")
def get_reference(ref_id: str, request: Request, _: User = Depends(user_or_download_token)):
    return FileResponse(reference_path(request, ref_id), media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


@worker_router.get("/{ref_id}")
def worker_get_reference(ref_id: str, request: Request, _: Worker = Depends(current_worker)):
    return FileResponse(reference_path(request, ref_id), media_type="image/png")


_ = get_db
