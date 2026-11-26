"""HTTP client for the AssetForge worker protocol with retries and exponential backoff."""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

import httpx

log = logging.getLogger("assetforge.worker")


class LeaseLost(Exception):
    """The server no longer considers this worker the owner of the job (HTTP 409)."""


class AuthFailed(Exception):
    pass


class ServerClient:
    def __init__(self, base_url: str, token: str | None = None, timeout: float = 30.0) -> None:
        self.base = base_url.rstrip("/") + "/api/v1"
        self.token = token
        self.http = httpx.Client(timeout=httpx.Timeout(timeout, read=120.0))

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def request(self, method: str, path: str, *, retries: int = 3, **kw) -> httpx.Response:
        delay = 1.0
        extra_headers = kw.pop("headers", {})
        for attempt in range(retries + 1):
            try:
                resp = self.http.request(method, self.base + path, headers={**self._headers, **extra_headers}, **kw)
            except httpx.TransportError as exc:
                if attempt == retries:
                    raise
                log.warning("server unreachable (%s); retry in %.0fs", type(exc).__name__, delay)
                time.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            if resp.status_code == 409:
                raise LeaseLost(resp.text)
            if resp.status_code == 401 and self.token:
                raise AuthFailed(resp.text)
            if resp.status_code >= 500 and attempt < retries:
                time.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            return resp
        raise RuntimeError("unreachable")

    def register(self, payload: dict) -> dict:
        r = self.request("POST", "/worker/register", json=payload)
        r.raise_for_status()
        return r.json()

    def heartbeat(self, payload: dict) -> dict:
        r = self.request("POST", "/worker/heartbeat", json=payload, retries=1)
        r.raise_for_status()
        return r.json()

    def lease(self) -> dict | None:
        r = self.request("POST", "/worker/lease", retries=1)
        if r.status_code == 204:
            return None
        r.raise_for_status()
        return r.json()

    def events(self, job_id: str, token: str, events: list[dict], plan: list[dict] | None = None) -> dict:
        body: dict = {"lease_token": token, "events": events}
        if plan is not None:
            body["plan"] = plan
        r = self.request("POST", f"/worker/jobs/{job_id}/events", json=body)
        r.raise_for_status()
        return r.json()

    def upload(self, job_id: str, token: str, rel: str, path: Path, attempts: int = 3) -> None:
        """Streamed PUT with SHA-256 header; the body generator is rebuilt for every attempt."""
        for n in range(attempts):
            try:
                self._upload_once(job_id, token, rel, path)
                return
            except httpx.TransportError:
                if n == attempts - 1:
                    raise
                time.sleep(2 ** n)

    def _upload_once(self, job_id: str, token: str, rel: str, path: Path) -> None:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)

        def body():
            with path.open("rb") as fh:
                while chunk := fh.read(1 << 20):
                    yield chunk

        r = self.request("PUT", f"/worker/jobs/{job_id}/artifacts/{rel}", content=body(),
                         headers={"X-Lease-Token": token, "X-SHA256": h.hexdigest(),
                                  "Content-Type": "application/octet-stream"}, retries=0)
        if r.status_code >= 400:
            raise RuntimeError(f"upload of {rel} rejected: {r.status_code} {r.text[:200]}")

    def download_reference(self, ref_id: str, dest: Path) -> None:
        r = self.request("GET", f"/worker/references/{ref_id}")
        if r.status_code != 200:
            raise RuntimeError(f"reference {ref_id} unavailable: {r.status_code}")
        dest.write_bytes(r.content)

    def complete(self, job_id: str, token: str, result: dict) -> dict:
        r = self.request("POST", f"/worker/jobs/{job_id}/complete", json={"lease_token": token, "result": result})
        if r.status_code >= 400:
            raise RuntimeError(f"server rejected the result: {r.status_code} {r.text[:500]}")
        return r.json()

    def fail(self, job_id: str, token: str, error: str, retryable: bool) -> None:
        self.request("POST", f"/worker/jobs/{job_id}/fail",
                     json={"lease_token": token, "error": error[:3900], "retryable": retryable})

    def cancelled(self, job_id: str, token: str) -> None:
        self.request("POST", f"/worker/jobs/{job_id}/cancelled", json={"lease_token": token})
