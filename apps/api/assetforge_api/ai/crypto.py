"""Encryption at rest for provider API keys (Fernet; the key is derived from the server secret, so a DB dump alone does not reveal them)."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


def _fernet(secret: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("assetforge-ai-keys:" + secret).encode()).digest()))


def encrypt(secret: str, plain: str) -> str:
    return _fernet(secret).encrypt(plain.encode()).decode()


def decrypt(secret: str, token: str) -> str:
    try:
        return _fernet(secret).decrypt(token.encode()).decode()
    except InvalidToken as exc:  # the server secret changed: the stored keys cannot be used and must be entered again
        raise ValueError("this API key was encrypted with another server secret; enter it again") from exc


def hint(key: str) -> str:
    return "…" + key[-4:] if len(key) >= 8 else "…"
