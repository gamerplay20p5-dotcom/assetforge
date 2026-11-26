"""ORM models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, JSONType, UTCDateTime, utcnow


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}" if prefix else uuid.uuid4().hex


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("usr_"))
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16), default="admin")  # admin | operator | viewer
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class EnrollmentToken(Base):
    """One-time token that lets a worker register itself (admin generates, worker consumes)."""

    __tablename__ = "enrollment_tokens"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("enr_"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(120), default="")
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    used_by_worker_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Worker(Base):
    __tablename__ = "workers"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("wrk_"))
    name: Mapped[str] = mapped_column(String(120), unique=True)
    kind: Mapped[str] = mapped_column(String(16), default="cpu")  # cpu | intel | hybrid
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    address: Mapped[str] = mapped_column(String(64), default="")
    hostname: Mapped[str] = mapped_column(String(120), default="")
    version: Mapped[str] = mapped_column(String(32), default="")
    state: Mapped[str] = mapped_column(String(16), default="enabled")  # enabled | disabled | maintenance
    capabilities: Mapped[dict] = mapped_column(JSONType, default=dict)
    limits: Mapped[dict] = mapped_column(JSONType, default=dict)
    telemetry: Mapped[dict] = mapped_column(JSONType, default=dict)
    last_heartbeat: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    registered_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    jobs_succeeded: Mapped[int] = mapped_column(Integer, default=0)
    jobs_failed: Mapped[int] = mapped_column(Integer, default=0)


class Batch(Base):
    __tablename__ = "batches"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("bat_"))
    name: Mapped[str] = mapped_column(String(160))
    spec: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    jobs: Mapped[list[Job]] = relationship(back_populates="batch")


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("job_"))
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("batches.id"), nullable=True, index=True)
    asset_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(160))
    job_type: Mapped[str] = mapped_column(String(64), default="procedural.building")
    params: Mapped[dict] = mapped_column(JSONType, default=dict)
    quality_profile: Mapped[str] = mapped_column(String(32), default="stylized_standard")
    triangle_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    formats: Mapped[list] = mapped_column(JSONType, default=list)
    tags: Mapped[list] = mapped_column(JSONType, default=list)
    art_profile_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    category: Mapped[str] = mapped_column(String(48), default="")

    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    requirements: Mapped[dict] = mapped_column(JSONType, default=dict)
    pinned_worker_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    not_before: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    depends_on: Mapped[list] = mapped_column(JSONType, default=list)
    has_deps: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    retry_of: Mapped[str | None] = mapped_column(String(32), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)

    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    worker_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    asset_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    plan: Mapped[list] = mapped_column(JSONType, default=list)  # [{name, weight}]
    stages: Mapped[dict] = mapped_column(JSONType, default=dict)  # name -> {status, started_at, finished_at, detail}
    current_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    result: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    batch: Mapped[Batch | None] = relationship(back_populates="jobs")
    attempt_rows: Mapped[list[JobAttempt]] = relationship(back_populates="job", order_by="JobAttempt.attempt_no")

    __table_args__ = (Index("ix_jobs_dispatch", "status", "priority", "created_at"),)


class JobAttempt(Base):
    __tablename__ = "job_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer)
    worker_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), default="running")  # running|succeeded|failed|cancelled|abandoned
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    job: Mapped[Job] = relationship(back_populates="attempt_rows")
    __table_args__ = (UniqueConstraint("job_id", "attempt_no"),)


class JobLog(Base):
    __tablename__ = "job_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer, default=0)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    level: Mapped[str] = mapped_column(String(10), default="info")
    source: Mapped[str] = mapped_column(String(16), default="worker")  # worker | server
    message: Mapped[str] = mapped_column(Text)


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    category: Mapped[str] = mapped_column(String(48), index=True, default="")
    tags: Mapped[list] = mapped_column(JSONType, default=list)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    review_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|approved|rejected
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    art_profile: Mapped[str] = mapped_column(String(64), default="")
    generator_id: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    versions: Mapped[list[AssetVersion]] = relationship(back_populates="asset", order_by="AssetVersion.version")


class AssetVersion(Base):
    __tablename__ = "asset_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    job_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    files: Mapped[list] = mapped_column(JSONType, default=list)
    manifest: Mapped[dict] = mapped_column(JSONType, default=dict)
    validation: Mapped[dict] = mapped_column(JSONType, default=dict)
    triangle_count: Mapped[int] = mapped_column(Integer, default=0)
    engine: Mapped[str] = mapped_column(String(24), default="")
    note: Mapped[str] = mapped_column(String(240), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    asset: Mapped[Asset] = relationship(back_populates="versions")
    __table_args__ = (UniqueConstraint("asset_id", "version"),)


class ArtProfile(Base):
    __tablename__ = "art_profiles"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("art_"))
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Preset(Base):
    __tablename__ = "presets"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("pre_"))
    name: Mapped[str] = mapped_column(String(120), unique=True)
    data: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    type: Mapped[str] = mapped_column(String(48))
    entity_id: Mapped[str] = mapped_column(String(48), default="")
    data: Mapped[dict] = mapped_column(JSONType, default=dict)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(48), default="")
    entity_id: Mapped[str] = mapped_column(String(48), default="")
    detail: Mapped[dict] = mapped_column(JSONType, default=dict)
    ip: Mapped[str] = mapped_column(String(64), default="")


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONType, default=dict)
