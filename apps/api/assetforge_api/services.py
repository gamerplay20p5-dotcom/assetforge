"""Small cross-cutting helpers: events, audit log, settings."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditLog, Event, Setting


def emit_event(db: Session, type_: str, entity_id: str = "", **data) -> None:
    db.add(Event(type=type_, entity_id=entity_id, data=data))


def audit(db: Session, actor: str, action: str, entity: str = "", entity_id: str = "", ip: str = "", **detail) -> None:
    db.add(AuditLog(actor=actor, action=action, entity=entity, entity_id=entity_id, detail=detail, ip=ip))


def get_setting(db: Session, key: str, default=None):
    row = db.get(Setting, key)
    return row.value.get("v", default) if row else default


def set_setting(db: Session, key: str, value) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value={"v": value}))
    else:
        row.value = {"v": value}
