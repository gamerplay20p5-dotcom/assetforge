"""Reference images for image-to-3D jobs (validated, re-encoded, size-limited)."""

from __future__ import annotations

import hashlib
import io
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError

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


@router.post("", status_code=201)
async def upload_reference(request: Request, file: UploadFile, user: User = Depends(require_operator)) -> dict:
    limit = request.app.state.settings.max_reference_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"image larger than {request.app.state.settings.max_reference_mb} MB")
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format not in ("PNG", "JPEG", "WEBP"):
                raise HTTPException(422, f"unsupported image format {im.format}; use PNG, JPEG or WEBP")
            w, h = im.size
            if max(w, h) > 4096 or min(w, h) < 64:
                raise HTTPException(422, f"image size {w}x{h} outside 64..4096 px")
            im.load()
            clean = im.convert("RGBA" if "A" in im.getbands() else "RGB")  # re-encoding drops EXIF/metadata/payloads
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "file is not a valid image") from exc
    buf = io.BytesIO()
    clean.save(buf, "PNG")
    ref_id = f"ref_{uuid.uuid4().hex[:12]}"
    d = request.app.state.storage.root / "references"
    d.mkdir(exist_ok=True)
    (d / f"{ref_id}.png").write_bytes(buf.getvalue())
    return {"id": ref_id, "width": w, "height": h, "sha256": hashlib.sha256(buf.getvalue()).hexdigest(), "uploaded_by": user.username}


@router.get("/{ref_id}")
def get_reference(ref_id: str, request: Request, _: User = Depends(user_or_download_token)):
    return FileResponse(reference_path(request, ref_id), media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


@worker_router.get("/{ref_id}")
def worker_get_reference(ref_id: str, request: Request, _: Worker = Depends(current_worker)):
    return FileResponse(reference_path(request, ref_id), media_type="image/png")


_ = get_db
