"""CPU-only image-to-3D providers (Stable Fast 3D, TripoSR) for AssetForge."""

from .client import CpuProvider, CpuResult, ProviderCancelled, ProviderError, parse_providers_env
from .registry import DEPENDENCY_LICENSES, PROVIDERS, ProviderSpec

__all__ = ["DEPENDENCY_LICENSES", "PROVIDERS", "CpuProvider", "CpuResult", "ProviderCancelled", "ProviderError", "ProviderSpec", "parse_providers_env"]
