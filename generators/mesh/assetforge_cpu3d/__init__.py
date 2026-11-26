"""CPU-only image-to-3D providers (Stable Fast 3D, TripoSR) for AssetForge.

The client (needs httpx, used by the worker) is imported lazily so the provider containers, which only run the server, don't need it.
"""

from __future__ import annotations

from .registry import DEPENDENCY_LICENSES, PROVIDERS, ProviderSpec

_CLIENT_NAMES = ("CpuProvider", "CpuResult", "ProviderCancelled", "ProviderError", "parse_providers_env")
__all__ = ["DEPENDENCY_LICENSES", "PROVIDERS", "ProviderSpec", *_CLIENT_NAMES]


def __getattr__(name: str):
    if name in _CLIENT_NAMES:
        from . import client

        return getattr(client, name)
    raise AttributeError(name)
