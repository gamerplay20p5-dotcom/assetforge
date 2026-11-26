"""Runtime configuration (environment variables prefixed ``ASSETFORGE_``)."""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ASSETFORGE_", env_file=".env", extra="ignore")

    env: str = "development"  # development | production | test
    database_url: str = "sqlite:///./data/assetforge.sqlite3"
    storage_root: Path = Path("./data/storage")
    secret_key: str = ""
    admin_username: str = "admin"
    admin_password: str = ""
    access_token_minutes: int = 12 * 60
    download_token_seconds: int = 600
    cors_origins: str = ""  # comma separated; empty = same-origin only

    max_upload_mb: int = 256
    max_batch_jobs: int = 1000
    lease_seconds: int = 60
    heartbeat_seconds: int = 10
    worker_offline_seconds: int = 45
    reaper_interval_seconds: float = 5.0
    retry_backoff_seconds: int = 10
    default_max_attempts: int = 3
    enrollment_token_hours: int = 24
    login_max_failures: int = 8

    llm_url: str = ""  # optional local Ollama-compatible server used by the text planner (never a cloud API)
    llm_model: str = ""

    dashboard_dir: Path | None = Field(default=None, description="Serve a built dashboard from this folder")

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    def resolved_secret(self) -> str:
        if self.secret_key:
            return self.secret_key
        if self.is_production:
            raise RuntimeError("ASSETFORGE_SECRET_KEY must be set in production")
        return _ephemeral_secret()


@lru_cache(maxsize=1)
def _ephemeral_secret() -> str:
    return secrets.token_urlsafe(48)


def get_settings() -> Settings:
    return Settings()
