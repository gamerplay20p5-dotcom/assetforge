"""Client used by the AssetForge worker to talk to a CPU image-to-3D provider container."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import httpx

from .registry import DEPENDENCY_LICENSES, PROVIDERS


class ProviderError(Exception):
    pass


class ProviderCancelled(ProviderError):
    pass


@dataclass
class CpuResult:
    path: Path
    seconds: float
    provider: str
    job_id: str
    peak_ram_mb: int
    peak_cpu_percent: float
    info: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)


class CpuProvider:
    """Same role as IntelAIProvider, for the CPU-only containers (sf3d, triposr)."""

    kind = "cpu3d"

    def __init__(self, name: str, url: str, client: httpx.Client | None = None) -> None:
        if name not in PROVIDERS:
            raise ValueError(f"unknown provider {name!r}")
        self.name, self.base = name, url.rstrip("/")
        self.http = client or httpx.Client(timeout=httpx.Timeout(30.0, read=300.0))
        self.spec = PROVIDERS[name]

    # ------------------------------------------------------------------ info
    def health(self) -> dict:
        try:
            r = self.http.get(f"{self.base}/health")
            r.raise_for_status()
            return {"reachable": True, **r.json()}
        except (httpx.HTTPError, ValueError) as exc:
            return {"reachable": False, "ready": False, "reason": f"provider unreachable: {type(exc).__name__}"}

    def stats(self) -> dict:
        try:
            return self.http.get(f"{self.base}/stats").json()
        except (httpx.HTTPError, ValueError):
            return {}

    def provenance(self) -> dict[str, str]:
        return {"provider": f"cpu3d:{self.name}", "upstream": f"https://github.com/{self.spec.repo}", "upstream_commit": self.spec.commit,
                "weights": self.spec.weights_repo, "device": "cpu (torch CPU, no CUDA/XPU)"}

    def license_summary(self) -> str:
        return (f"{self.spec.title}: código {self.spec.code_license}; pesos {self.spec.weights_license}. {self.spec.commercial} "
                f"Dependências: " + "; ".join(f"{k}: {v}" for k, v in DEPENDENCY_LICENSES.items()))

    def model_name(self) -> str:
        return self.name

    # ------------------------------------------------------------------ generation
    def cancel_tag(self, tag: str) -> None:
        try:
            self.http.post(f"{self.base}/v1/cancel?tag={quote(tag)}")
        except httpx.HTTPError:
            pass

    def image_to_3d(self, image: Path, dest: Path, *, params: dict, tag: str = "", timeout: float = 3600.0, poll: float = 3.0,
                    should_cancel: Callable[[], bool] | None = None) -> CpuResult:
        r = self.http.post(f"{self.base}/v1/jobs?params={quote(json.dumps(params))}&tag={quote(tag)}", content=image.read_bytes(),
                           headers={"Content-Type": "application/octet-stream"})
        if r.status_code != 202:
            raise ProviderError(f"provider rejected the job ({r.status_code}): {r.text[:300]}")
        jid = r.json()["id"]
        start = time.monotonic()
        while True:
            if should_cancel and should_cancel():
                self.http.post(f"{self.base}/v1/jobs/{jid}/cancel")
                raise ProviderCancelled("cancelled")
            j = self.http.get(f"{self.base}/v1/jobs/{jid}").json()
            if j["status"] == "succeeded":
                break
            if j["status"] in ("failed", "cancelled"):
                tail = " | ".join(j.get("log_tail", [])[-4:])
                raise ProviderError(f"provider job {j['status']}: {j.get('error') or ''} {tail}"[:600])
            if time.monotonic() - start > timeout:
                self.http.post(f"{self.base}/v1/jobs/{jid}/cancel")
                raise ProviderError(f"timed out after {timeout:.0f}s waiting for {self.name}")
            time.sleep(poll)
        res = self.http.get(f"{self.base}/v1/jobs/{jid}/result")
        if res.status_code != 200 or not res.content.startswith(b"glTF"):
            raise ProviderError("provider returned an invalid GLB")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(res.content)
        m = j["metrics"]
        return CpuResult(dest, float(m.get("seconds") or time.monotonic() - start), self.name, jid, int(m.get("peak_rss_mb", 0)),
                         float(m.get("peak_cpu_percent", 0.0)), j.get("info", {}), params)
