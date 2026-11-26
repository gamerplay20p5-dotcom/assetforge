"""One-shot task (inside the provider image): download weights into the persistent cache and run a REAL warm-up inference.

    python -m assetforge_cpu3d.download            # PROVIDER_NAME=sf3d|triposr, HF_TOKEN needed for sf3d (gated)

Downloading is explicit (operator action). Afterwards the service can run with HF_HUB_OFFLINE=1. The warm-up generates a mesh
from the example image shipped in the upstream repo, so it also fills the secondary caches (DINOv2/CLIP/u2net) and proves the
provider works on this machine.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from . import adapters
from .registry import PROVIDERS


def main() -> int:
    name = os.environ["PROVIDER_NAME"]
    spec = PROVIDERS[name]
    hf_home = Path(os.environ.get("HF_HOME", "/models/hf"))
    token = os.environ.get("HF_TOKEN") or None
    if spec.weights_gated and not token and not adapters.weights_ready(name, hf_home)[0]:
        print(f"{spec.weights_repo} é 'gated': aceite a licença em https://huggingface.co/{spec.weights_repo} com a sua conta e passe HF_TOKEN.", file=sys.stderr)
        return 2
    from huggingface_hub import snapshot_download

    t0 = time.time()
    path = snapshot_download(spec.weights_repo, token=token, cache_dir=str(hf_home / "hub"))
    print(f"pesos em {path} ({time.time() - t0:.0f}s)")
    example = Path({"sf3d": adapters.SF3D_DIR / "demo_files/examples/chair1.png", "triposr": adapters.TRIPOSR_DIR / "examples/chair.png"}[name])
    from .server import Service

    svc = Service(name, Path("/tmp/cpu3d-warmup"), hf_home, int(os.environ.get("PROVIDER_THREADS", "8")), 1, float(os.environ.get("PROVIDER_JOB_TIMEOUT", "3600")))
    job = svc.submit(example.read_bytes(), {"texture_resolution": 512, "mc_resolution": 192})
    while job.status in ("queued", "running"):
        time.sleep(2)
    print("warm-up:", job.status, job.error or "", job.metrics, job.info)
    for line in list(job.log)[-8:]:
        print("  |", line)
    return 0 if job.status == "succeeded" else 1


if __name__ == "__main__":
    sys.exit(main())
