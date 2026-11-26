"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, select

from .config import Settings, get_settings
from .db import Database, utcnow
from .models import ArtProfile, EnrollmentToken, Event, User
from .routers import assets, auth, jobs, references, system, workers
from .scheduler import reap
from .security import LoginThrottle, hash_password, hash_token
from .storage import Storage

log = logging.getLogger("assetforge.api")

DEFAULT_ART_PROFILE = {
    "name": "Premium Stylized",
    "description": "Premium Stylized Low/Mid Poly: modular facades with real openings, trim details, harmonious "
                   "palettes, tiling detail textures. Reference quality: professional urban kits (no copied assets).",
    "data": {"id": "premium-stylized-v1", "styles": ["modern", "classic", "mediterranean", "nordic", "industrial"],
             "default_quality_profile": "stylized_standard", "texture_resolution": 512},
}


def bootstrap(db: Database, settings: Settings) -> None:
    db.create_all()
    with db.session() as s:
        if s.scalar(select(User.id).limit(1)) is None:
            password = settings.admin_password
            if not password:
                if settings.is_production:
                    raise RuntimeError("ASSETFORGE_ADMIN_PASSWORD must be set on first start in production")
                password = "admin-dev-password"
                log.warning("development mode: admin user created with the default dev password")
            s.add(User(username=settings.admin_username, password_hash=hash_password(password), role="admin"))
        if s.execute(select(ArtProfile).where(ArtProfile.name == DEFAULT_ART_PROFILE["name"])).scalar_one_or_none() is None:
            s.add(ArtProfile(**DEFAULT_ART_PROFILE))
        for raw in filter(None, (t.strip() for t in settings.bootstrap_enrollment_tokens.split(","))):
            if len(raw) < 24:
                raise RuntimeError("ASSETFORGE_BOOTSTRAP_ENROLLMENT_TOKENS entries must have at least 24 characters")
            h = hash_token(raw)
            if s.execute(select(EnrollmentToken).where(EnrollmentToken.token_hash == h)).scalar_one_or_none() is None:
                s.add(EnrollmentToken(token_hash=h, label="bootstrap", created_by="bootstrap", expires_at=utcnow() + timedelta(days=30)))
        s.commit()


async def reaper_loop(app: FastAPI) -> None:
    settings: Settings = app.state.settings
    grace_until = utcnow() + timedelta(seconds=settings.lease_seconds)  # let workers re-attach after an API restart
    last_prune = utcnow()
    while True:
        try:
            now = utcnow()

            def work() -> None:
                with app.state.db.session() as s:
                    reap(s, settings, now, allow_abandon=now >= grace_until)

            await asyncio.get_running_loop().run_in_executor(None, work)
            if (now - last_prune).total_seconds() > 3600:
                last_prune = now
                with app.state.db.session() as s:
                    s.execute(delete(Event).where(Event.ts < now - timedelta(days=2)))
                    s.commit()
        except Exception:  # noqa: BLE001 - the loop must survive transient DB errors
            log.exception("reaper iteration failed")
        await asyncio.sleep(settings.reaper_interval_seconds)


def create_app(settings: Settings | None = None, *, start_reaper: bool = True) -> FastAPI:
    settings = settings or get_settings()
    db = Database(settings.database_url)
    secret = settings.resolved_secret()
    bootstrap(db, settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(reaper_loop(app)) if start_reaper else None
        yield
        if task:
            task.cancel()
        db.dispose()

    app = FastAPI(title="AssetForge API", version="0.1.0", lifespan=lifespan,
                  description="Self-hosted distributed game asset generation. Integration API for the dashboard, "
                              "workers and AI agents (no arbitrary code or shell execution is exposed).",
                  openapi_url="/api/openapi.json", docs_url="/api/docs", redoc_url=None)
    app.state.settings = settings
    app.state.db = db
    app.state.secret = secret
    app.state.storage = Storage(settings.storage_root)
    app.state.throttle = LoginThrottle(settings.login_max_failures)

    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                           allow_methods=["*"], allow_headers=["*"])
    for r in (auth.router, workers.admin_router, workers.worker_router, jobs.router, assets.router, references.router,
              references.worker_router, system.router):
        app.include_router(r, prefix="/api/v1")

    if settings.dashboard_dir and settings.dashboard_dir.is_dir():
        app.mount("/assets-ui", StaticFiles(directory=settings.dashboard_dir / "assets"), name="ui-assets") \
            if (settings.dashboard_dir / "assets").is_dir() else None
        index = settings.dashboard_dir / "index.html"

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            candidate = (settings.dashboard_dir / full_path).resolve()
            if full_path and settings.dashboard_dir.resolve() in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(index)

    return app
