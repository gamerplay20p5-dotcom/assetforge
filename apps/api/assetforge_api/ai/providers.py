"""Thin adapters over the official SDK (Gemini: google-genai) and an OpenAI-compatible HTTP API (Grok / xAI).

Both expose the same three operations: list models, test the key, and generate JSON constrained by a JSON Schema from text + images.
Errors are normalised: :class:`QuotaError` (HTTP 429, with the wait and whether it is a daily quota), :class:`AuthError` (401/403) and
:class:`ProviderError` (anything else). The key is only held in memory for the duration of a call and never logged.
"""

from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx


class ProviderError(Exception):
    pass


class AuthError(ProviderError):
    pass


class OutputError(ProviderError):
    """The call worked but the answer is unusable (empty / not JSON). Not the key's fault: no cooldown."""


class QuotaError(ProviderError):
    def __init__(self, message: str, retry_after_s: float | None = None, daily: bool = False) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s
        self.daily = daily


@dataclass
class LlmResult:
    data: Any
    text: str
    model: str
    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0


def _parse_json(text: str | None) -> Any:
    if not text:
        raise OutputError("the model returned an empty answer")
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError as exc:
        raise OutputError(f"the model did not return valid JSON: {exc}") from exc


# ------------------------------------------------------------------------------------------------------------ Gemini
class GeminiProvider:
    kind = "gemini"
    free_tier = True  # the Gemini API has a free tier; whether THIS key is free depends on billing of its Google project

    def __init__(self, api_key: str, base_url: str = "", timeout_s: float = 180.0) -> None:
        from google import genai
        from google.genai import types

        self._types = types
        opts = types.HttpOptions(timeout=int(timeout_s * 1000), **({"base_url": base_url} if base_url else {}))
        self.client = genai.Client(api_key=api_key, http_options=opts)

    def _wrap(self, exc: Exception) -> ProviderError:
        from google.genai import errors

        if isinstance(exc, errors.APIError):
            code = getattr(exc, "code", 0) or 0
            msg = f"{code} {getattr(exc, 'status', '')}: {str(getattr(exc, 'message', '') or exc)[:300]}"
            if code == 429:
                retry, daily = _gemini_retry_info(getattr(exc, "details", None))
                return QuotaError(msg, retry, daily)
            if code in (401, 403):
                return AuthError(msg)
            return ProviderError(msg)
        return ProviderError(f"{type(exc).__name__}: {str(exc)[:300]}")

    def list_models(self) -> list[dict]:
        try:
            out = []
            for m in self.client.models.list():
                actions = list(getattr(m, "supported_actions", None) or [])
                if actions and "generateContent" not in actions:
                    continue
                name = (m.name or "").removeprefix("models/")
                out.append({"name": name, "display": getattr(m, "display_name", "") or name, "input_token_limit": getattr(m, "input_token_limit", None)})
            return out
        except Exception as exc:  # noqa: BLE001
            raise self._wrap(exc) from exc

    def generate_json(self, model: str, system: str, prompt: str, images: list[tuple[bytes, str]], schema: dict) -> LlmResult:
        t = self._types
        parts = [t.Part.from_bytes(data=b, mime_type=mime) for b, mime in images] + [prompt]
        cfg = t.GenerateContentConfig(system_instruction=system, response_mime_type="application/json", response_json_schema=schema, temperature=0.2)
        t0 = time.monotonic()
        try:
            r = self.client.models.generate_content(model=model, contents=parts, config=cfg)
        except Exception as exc:  # noqa: BLE001
            raise self._wrap(exc) from exc
        u = getattr(r, "usage_metadata", None)
        return LlmResult(_parse_json(r.text), r.text or "", model, int(getattr(u, "prompt_token_count", 0) or 0), int(getattr(u, "candidates_token_count", 0) or 0),
                         int(getattr(u, "total_token_count", 0) or 0), int((time.monotonic() - t0) * 1000))


def _gemini_retry_info(details: Any) -> tuple[float | None, bool]:
    """Read google.rpc.RetryInfo (retryDelay) and QuotaFailure (is it a per-day quota?) from a 429 body."""
    retry, daily = None, False
    try:
        items = details.get("error", {}).get("details", []) if isinstance(details, dict) else (details or [])
        for d in items:
            if "retryDelay" in d:
                m = re.match(r"([\d.]+)s", str(d["retryDelay"]))
                retry = float(m.group(1)) if m else None
            for v in d.get("violations", []) or []:
                if "PerDay" in str(v.get("quotaId", "")) or "per_day" in str(v.get("quotaMetric", "")).lower():
                    daily = True
    except (AttributeError, TypeError):
        pass
    return retry, daily


# ------------------------------------------------------------------------------------------------------------- Grok
class GrokProvider:
    """xAI's API is OpenAI compatible (chat completions with image_url parts and json_schema response format). It has no free tier."""

    kind = "grok"
    free_tier = False

    def __init__(self, api_key: str, base_url: str = "", timeout_s: float = 180.0) -> None:
        self.base = (base_url or "https://api.x.ai/v1").rstrip("/")
        self.http = httpx.Client(timeout=timeout_s, headers={"Authorization": f"Bearer {api_key}"})

    def _check(self, r: httpx.Response) -> None:
        if r.status_code == 429:
            ra = r.headers.get("retry-after")
            raise QuotaError(f"429: {r.text[:200]}", float(ra) if ra and ra.replace(".", "", 1).isdigit() else None, False)
        if r.status_code in (401, 403):
            raise AuthError(f"{r.status_code}: {r.text[:200]}")
        if r.status_code >= 400:
            raise ProviderError(f"{r.status_code}: {r.text[:300]}")

    def list_models(self) -> list[dict]:
        try:
            r = self.http.get(f"{self.base}/models")
        except httpx.HTTPError as exc:
            raise ProviderError(f"{type(exc).__name__}") from exc
        self._check(r)
        return [{"name": m.get("id", ""), "display": m.get("id", ""), "input_token_limit": None} for m in r.json().get("data", [])]

    def generate_json(self, model: str, system: str, prompt: str, images: list[tuple[bytes, str]], schema: dict) -> LlmResult:
        content: list[dict] = [{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(b).decode()}"}} for b, mime in images]
        content.append({"type": "text", "text": prompt})
        body = {"model": model, "temperature": 0.2, "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
                "response_format": {"type": "json_schema", "json_schema": {"name": "assetforge", "schema": schema}}}
        t0 = time.monotonic()
        try:
            r = self.http.post(f"{self.base}/chat/completions", json=body)
        except httpx.HTTPError as exc:
            raise ProviderError(f"{type(exc).__name__}") from exc
        self._check(r)
        j = r.json()
        text = (j.get("choices") or [{}])[0].get("message", {}).get("content", "")
        u = j.get("usage") or {}
        return LlmResult(_parse_json(text), text, model, int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0)), int(u.get("total_tokens", 0)),
                         int((time.monotonic() - t0) * 1000))


PROVIDERS = {"gemini": GeminiProvider, "grok": GrokProvider}
MODEL_PREFERENCE = {  # tried in this order when a key has no model chosen; only names the key really lists are used
    # gemini-3.5-flash-lite first: the model the user's HTS bot already uses successfully with the same kind of free key
    "gemini": ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"],
    "grok": ["grok-4", "grok-4-fast", "grok-2-vision"],
}


def make_provider(kind: str, api_key: str, base_url: str = ""):  # noqa: ANN201
    if kind not in PROVIDERS:
        raise ValueError(f"unknown provider {kind!r}")
    return PROVIDERS[kind](api_key, base_url)


def pick_model(kind: str, available: list[str]) -> str | None:
    for m in MODEL_PREFERENCE.get(kind, []):
        if m in available:
            return m
    return None
