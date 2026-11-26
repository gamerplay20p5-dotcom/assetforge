"""Filesystem storage with path-traversal protection."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

ALLOWED_EXTENSIONS = {".glb", ".gltf", ".blend", ".fbx", ".png", ".json", ".zip", ".jpg"}
_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class UnsafePath(ValueError):
    pass


def validate_relative(rel: str, max_depth: int = 3) -> str:
    """Accept only simple relative POSIX paths like ``textures/tex_brick.png``."""
    if not rel or "\\" in rel or "\x00" in rel or rel.startswith("/") or ":" in rel:
        raise UnsafePath(f"illegal path {rel!r}")
    parts = rel.split("/")
    if len(parts) > max_depth or any(not _COMPONENT.match(p) or p in (".", "..") or ".." in p for p in parts):
        raise UnsafePath(f"illegal path {rel!r}")
    if Path(parts[-1]).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise UnsafePath(f"extension not allowed: {parts[-1]!r}")
    return rel


def safe_join(base: Path, rel: str) -> Path:
    validate_relative(rel)
    base_r = base.resolve()
    target = (base_r / rel).resolve()
    if base_r != target and base_r not in target.parents:
        raise UnsafePath("path escapes storage root")
    return target


class Storage:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.assets = self.root / "assets"
        self.staging = self.root / "staging"
        self.assets.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _check_id(value: str) -> str:
        if not _ID.match(value):
            raise UnsafePath(f"illegal identifier {value!r}")
        return value

    def staging_dir(self, job_id: str, attempt: int) -> Path:
        d = self.staging / self._check_id(job_id) / f"attempt-{int(attempt)}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def asset_dir(self, asset_id: str, version: int) -> Path:
        return self.assets / self._check_id(asset_id) / f"v{int(version)}"

    def drop_staging(self, job_id: str) -> None:
        shutil.rmtree(self.staging / self._check_id(job_id), ignore_errors=True)

    def free_bytes(self) -> tuple[int, int]:
        u = shutil.disk_usage(self.root)
        return u.total, u.free

    def used_bytes(self) -> int:
        return sum(f.stat().st_size for f in self.assets.rglob("*") if f.is_file())
