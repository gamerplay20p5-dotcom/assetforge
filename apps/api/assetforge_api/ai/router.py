"""Key pool with fail-over: tries the configured keys in priority order and moves to the next one when a key hits its quota, is rejected or the
provider fails. Free-only mode (default ON) never uses a provider without a free tier unless the key is explicitly marked ``allow_paid``.

Per-key RPM/RPD limits are counted from the request history, so they survive restarts; a 429 puts the key in cooldown until the provider says the
quota renews (Gemini's daily quota renews at midnight Pacific time). Answers are cached by (task, prompt version, model, schema, images, prompt).
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import AiCache, AiKey, AiRequest, Setting
from .crypto import decrypt
from .providers import PROVIDERS, AuthError, LlmResult, OutputError, ProviderError, QuotaError, make_provider, pick_model

log = logging.getLogger("assetforge.ai")
DEFAULT_SETTINGS = {"free_only": True, "agent_iterations": 3, "target_score": 8.0}
PACIFIC = ZoneInfo("America/Los_Angeles")


class NoKeyAvailable(Exception):
    def __init__(self, message: str, retry_at: datetime | None) -> None:
        super().__init__(message)
        self.retry_at = retry_at


@dataclass
class AiAnswer:
    data: Any
    provider: str
    model: str
    key_id: str
    cached: bool
    total_tokens: int = 0


def get_ai_settings(db: Session) -> dict[str, Any]:
    row = db.get(Setting, "ai")
    return {**DEFAULT_SETTINGS, **(row.value if row else {})}


def put_ai_settings(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    cur = get_ai_settings(db)
    cur.update({k: v for k, v in values.items() if k in DEFAULT_SETTINGS})
    row = db.get(Setting, "ai")
    if row is None:
        db.add(Setting(key="ai", value=cur))
    else:
        row.value = cur
    db.commit()
    return cur


def is_paid(key: AiKey) -> bool:
    cls = PROVIDERS.get(key.provider)
    return not (cls is not None and cls.free_tier)


def day_start(provider: str, now: datetime) -> datetime:
    """Start of the provider's quota day (Gemini: midnight Pacific; others: midnight UTC), in UTC."""
    tz = PACIFIC if provider == "gemini" else timezone.utc
    local = now.astimezone(tz)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def next_day(provider: str, now: datetime) -> datetime:
    tz = PACIFIC if provider == "gemini" else timezone.utc
    local = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1, minutes=1)
    return local.replace(hour=0, minute=1).astimezone(timezone.utc)


def _aware(d: datetime | None) -> datetime | None:
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


def cache_key(task: str, prompt_version: str, model: str, schema: dict, images: list[tuple[bytes, str]], prompt: str) -> str:
    h = hashlib.sha256()
    for part in (task, prompt_version, model, json.dumps(schema, sort_keys=True), prompt):
        h.update(part.encode())
        h.update(b"\0")
    for b, mime in images:
        h.update(hashlib.sha256(b).digest())
        h.update(mime.encode())
    return h.hexdigest()


class AiRouter:
    def __init__(self, db: Session, secret: str, factory: Callable[[str, str, str], Any] = make_provider) -> None:
        self.db, self.secret, self.factory = db, secret, factory

    # ------------------------------------------------------------------ bookkeeping
    def _record(self, key: AiKey | None, model: str, task: str, job_id: str, status: str, res: LlmResult | None = None, error: str = "") -> None:
        self.db.add(AiRequest(key_id=key.id if key else "", provider=key.provider if key else "", model=model, task=task, job_id=job_id, status=status,
                              prompt_tokens=res.prompt_tokens if res else 0, output_tokens=res.output_tokens if res else 0,
                              total_tokens=res.total_tokens if res else 0, latency_ms=res.latency_ms if res else 0, error=error[:400]))
        self.db.commit()

    def usage(self, key: AiKey, now: datetime | None = None) -> dict[str, int]:
        now = now or utcnow()
        q = select(func.count(AiRequest.id), func.coalesce(func.sum(AiRequest.total_tokens), 0)).where(
            AiRequest.key_id == key.id, AiRequest.status.in_(("ok", "error", "quota")))
        minute = self.db.execute(q.where(AiRequest.ts >= now - timedelta(seconds=60))).one()
        day = self.db.execute(q.where(AiRequest.ts >= day_start(key.provider, now))).one()
        return {"rpm": int(minute[0]), "rpd": int(day[0]), "tokens_today": int(day[1])}

    def candidates(self, now: datetime | None = None) -> tuple[list[AiKey], list[str], datetime | None]:
        """Usable keys in order, why the others were skipped, and the earliest moment a skipped one becomes usable again."""
        now = now or utcnow()
        free_only = bool(get_ai_settings(self.db)["free_only"])
        keys = self.db.execute(select(AiKey).where(AiKey.enabled.is_(True)).order_by(AiKey.priority, AiKey.created_at)).scalars().all()
        ok, why, soonest = [], [], None

        def later(t: datetime) -> None:
            nonlocal soonest
            soonest = t if soonest is None or t < soonest else soonest

        for k in keys:
            label = f"{k.provider}:{k.label or k.id}"
            if free_only and is_paid(k) and not k.allow_paid:
                why.append(f"{label}: paid provider blocked by free-only mode")
                continue
            cd = _aware(k.cooldown_until)
            if cd and cd > now:
                why.append(f"{label}: cooling down until {cd.isoformat()}")
                later(cd)
                continue
            u = self.usage(k, now)
            if k.rpd_limit and u["rpd"] >= k.rpd_limit:
                why.append(f"{label}: daily limit {k.rpd_limit} reached")
                later(next_day(k.provider, now))
                continue
            if k.rpm_limit and u["rpm"] >= k.rpm_limit:
                why.append(f"{label}: per-minute limit {k.rpm_limit} reached")
                later(now + timedelta(seconds=61))
                continue
            ok.append(k)
        return ok, why, soonest

    def provider_for(self, key: AiKey) -> Any:
        return self.factory(key.provider, decrypt(self.secret, key.key_enc), key.base_url)

    def _model(self, key: AiKey, prov: Any) -> str:
        if key.model:
            return key.model
        m = pick_model(key.provider, [x["name"] for x in prov.list_models()])
        if not m:
            raise ProviderError("no known vision model is available for this key; choose one in the panel")
        key.model = m
        self.db.commit()
        return m

    # ------------------------------------------------------------------ the call
    def generate_json(self, task: str, system: str, prompt: str, images: list[tuple[bytes, str]], schema: dict, prompt_version: str,
                      job_id: str = "", use_cache: bool = True) -> AiAnswer:
        now = utcnow()
        if use_cache and (cached := self._cached_answer(task, system, prompt, images, schema, prompt_version, job_id)) is not None:
            return cached  # a cache hit needs no provider call, so it is served even when every key is at its limit
        keys, why, soonest = self.candidates(now)
        errors = list(why)
        for key in keys:
            try:
                prov = self.provider_for(key)
                model = self._model(key, prov)
                if use_cache and (hit := self._cache_get(cache_key(task, prompt_version, model, schema, images, prompt))) is not None:
                    self._record(key, model, task, job_id, "cache")
                    return AiAnswer(hit, key.provider, model, key.id, True)
                res = prov.generate_json(model, system, prompt, images, schema)
            except ValueError as exc:  # key cannot be decrypted (server secret changed)
                key.enabled, key.last_error = False, str(exc)[:400]
                self.db.commit()
                errors.append(f"{key.provider}:{key.label or key.id}: {exc}")
                continue
            except QuotaError as exc:
                until = next_day(key.provider, now) if exc.daily else now + timedelta(seconds=max(exc.retry_after_s or 60.0, 5.0))
                key.cooldown_until, key.last_error = until, str(exc)[:400]
                self._record(key, key.model, task, job_id, "quota", error=str(exc))
                errors.append(f"{key.provider}:{key.label or key.id}: quota ({'daily' if exc.daily else 'rate'}) until {until.isoformat()}")
                soonest = until if soonest is None or until < soonest else soonest
                continue
            except AuthError as exc:
                key.cooldown_until, key.last_error = now + timedelta(hours=6), str(exc)[:400]
                self._record(key, key.model, task, job_id, "auth", error=str(exc))
                errors.append(f"{key.provider}:{key.label or key.id}: key rejected")
                continue
            except OutputError as exc:
                self._record(key, key.model, task, job_id, "error", error=str(exc))
                errors.append(f"{key.provider}:{key.label or key.id}: {exc}")
                continue
            except ProviderError as exc:
                key.cooldown_until, key.last_error = now + timedelta(seconds=30), str(exc)[:400]
                self._record(key, key.model, task, job_id, "error", error=str(exc))
                errors.append(f"{key.provider}:{key.label or key.id}: {exc}")
                continue
            key.last_error = ""
            self._record(key, model, task, job_id, "ok", res)
            if use_cache:
                self._cache_put(cache_key(task, prompt_version, model, schema, images, prompt), model, task, prompt_version, res.data)
            return AiAnswer(res.data, key.provider, model, key.id, False, res.total_tokens)
        if not errors:
            errors.append("no AI key is configured (add one in Configurações → IA na nuvem)")
        raise NoKeyAvailable("; ".join(errors), soonest)

    def _cached_answer(self, task: str, system: str, prompt: str, images: list[tuple[bytes, str]], schema: dict, prompt_version: str,
                       job_id: str) -> AiAnswer | None:
        free_only = bool(get_ai_settings(self.db)["free_only"])
        keys = self.db.execute(select(AiKey).where(AiKey.enabled.is_(True), AiKey.model != "").order_by(AiKey.priority, AiKey.created_at)).scalars()
        for key in keys:
            if free_only and is_paid(key) and not key.allow_paid:
                continue
            hit = self._cache_get(cache_key(task, prompt_version, key.model, schema, images, prompt))
            if hit is not None:
                self._record(key, key.model, task, job_id, "cache")
                return AiAnswer(hit, key.provider, key.model, key.id, True)
        return None

    def _cache_get(self, k: str) -> Any:
        row = self.db.get(AiCache, k)
        if row is None:
            return None
        row.hits += 1
        self.db.commit()
        return row.response.get("data")

    def _cache_put(self, k: str, model: str, task: str, version: str, data: Any) -> None:
        row = self.db.get(AiCache, k)
        if row is None:
            self.db.add(AiCache(key=k, model=model, task=task, prompt_version=version, response={"data": data}))
        else:
            row.response = {"data": data}
        self.db.commit()
