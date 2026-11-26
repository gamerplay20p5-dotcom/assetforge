"""Authentication and user management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import User
from ..schemas import LoginIn, TokenOut, UserCreate
from ..security import (
    create_jwt,
    current_user,
    get_db,
    hash_password,
    require_admin,
    verify_password,
)
from ..services import audit

router = APIRouter(prefix="/auth", tags=["auth"])

# Verifying against a dummy hash keeps response time similar for unknown users.
_DUMMY = hash_password("not-a-real-password")


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)) -> TokenOut:
    ip = request.client.host if request.client else ""
    throttle = request.app.state.throttle
    key = f"{body.username.lower()}|{ip}"
    if throttle.blocked(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many failed logins; try again later")
    user = db.execute(select(User).where(User.username == body.username)).scalar_one_or_none()
    ok = verify_password(body.password, user.password_hash if user else _DUMMY)
    if not user or not ok or user.disabled:
        throttle.fail(key)
        audit(db, body.username[:64], "login.failed", ip=ip)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    throttle.ok(key)
    s = request.app.state.settings
    audit(db, user.username, "login", ip=ip)
    db.commit()
    seconds = s.access_token_minutes * 60
    return TokenOut(access_token=create_jwt(request.app.state.secret, user.username, user.role, seconds=seconds),
                    role=user.role, expires_in=seconds)


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"username": user.username, "role": user.role}


@router.post("/download-token")
def download_token(request: Request, user: User = Depends(current_user)) -> dict:
    """Short-lived token for GET-only endpoints used where headers are impossible (<img>, WebGL loaders, SSE)."""
    secs = request.app.state.settings.download_token_seconds
    return {"token": create_jwt(request.app.state.secret, user.username, user.role, seconds=secs, typ="download"),
            "expires_in": secs}


@router.get("/users", dependencies=[Depends(require_admin)])
def list_users(db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": u.id, "username": u.username, "role": u.role, "disabled": u.disabled}
            for u in db.scalars(select(User).order_by(User.username))]


@router.post("/users", status_code=201)
def create_user(body: UserCreate, request: Request, admin: User = Depends(require_admin),
                db: Session = Depends(get_db)) -> dict:
    if db.execute(select(User).where(User.username == body.username)).scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "username already exists")
    user = User(username=body.username, password_hash=hash_password(body.password), role=body.role)
    db.add(user)
    audit(db, admin.username, "user.create", "user", body.username, role=body.role)
    db.commit()
    return {"id": user.id, "username": user.username, "role": user.role}
