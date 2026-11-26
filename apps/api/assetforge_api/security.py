"""Password hashing, JWTs, API/worker token handling and FastAPI auth dependencies."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta

import jwt
from fastapi import Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import utcnow
from .models import User, Worker

ROLE_RANK = {"viewer": 1, "operator": 2, "admin": 3}


# ----------------------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    n, r, p = 2**14, 8, 1
    digest = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc.hex(), digest)
    except (ValueError, TypeError):
        return False


def hash_token(token: str) -> str:
    """Opaque tokens (workers, enrollment) are stored only as SHA-256 digests."""
    return hashlib.sha256(token.encode()).hexdigest()


def new_token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


# ----------------------------------------------------------------------------- JWT
def create_jwt(secret: str, subject: str, role: str, *, seconds: int, typ: str = "access") -> str:
    now = utcnow()
    payload = {"sub": subject, "role": role, "typ": typ, "iat": now, "exp": now + timedelta(seconds=seconds)}
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_jwt(secret: str, token: str) -> dict:
    return jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["exp", "sub"]})


# ----------------------------------------------------------------------------- login throttling
class LoginThrottle:
    def __init__(self, max_failures: int, window: float = 300.0) -> None:
        self.max = max_failures
        self.window = window
        self._fails: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str) -> deque[float]:
        q = self._fails[key]
        now = time.monotonic()
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def blocked(self, key: str) -> bool:
        return len(self._prune(key)) >= self.max

    def fail(self, key: str) -> None:
        self._prune(key).append(time.monotonic())

    def ok(self, key: str) -> None:
        self._fails.pop(key, None)


# ----------------------------------------------------------------------------- dependencies
def get_db(request: Request):
    db: Session = request.app.state.db.session()
    try:
        yield db
    finally:
        db.close()


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def _user_from_token(request: Request, db: Session, token: str, allowed_types: set[str]) -> User:
    try:
        payload = decode_jwt(request.app.state.secret, token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"}) from exc
    if payload.get("typ") not in allowed_types:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong token type")
    user = db.execute(select(User).where(User.username == payload["sub"])).scalar_one_or_none()
    if user is None or user.disabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown or disabled user")
    return user


def current_user(request: Request, db: Session = Depends(get_db),
                 authorization: str | None = Header(default=None)) -> User:
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token", headers={"WWW-Authenticate": "Bearer"})
    return _user_from_token(request, db, token, {"access"})


def user_or_download_token(request: Request, db: Session = Depends(get_db),
                           authorization: str | None = Header(default=None),
                           token: str | None = Query(default=None, description="short-lived download token")) -> User:
    """Auth for GET endpoints used by <img>, <a download>, EventSource and WebGL loaders (no headers possible)."""
    raw = _bearer(authorization) or token
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing credentials")
    return _user_from_token(request, db, raw, {"access", "download"})


def require_role(minimum: str):
    def dep(user: User = Depends(current_user)) -> User:
        if ROLE_RANK.get(user.role, 0) < ROLE_RANK[minimum]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"requires role {minimum}")
        return user

    return dep


require_viewer = require_role("viewer")
require_operator = require_role("operator")
require_admin = require_role("admin")


def current_worker(db: Session = Depends(get_db), authorization: str | None = Header(default=None)) -> Worker:
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing worker token")
    worker = db.execute(select(Worker).where(Worker.token_hash == hash_token(token))).scalar_one_or_none()
    if worker is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid worker token")
    return worker
