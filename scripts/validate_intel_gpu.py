#!/usr/bin/env python3
"""Intel GPU / OpenVINO validation harness (Milestone 2 groundwork).

What it does TODAY: enumerates the devices OpenVINO and PyTorch can see and, if OpenVINO is installed, compiles and
runs a tiny real model on every device (a 1-layer convolution) to prove the device executes work.
What it deliberately does NOT do: declare Stable Diffusion / SDXL / image-to-3D "compatible". That requires running the
actual model on the node (planned in Milestone 2) and recording the result in docs/HARDWARE_COMPATIBILITY.md.

    pip install openvino      # on the node, in a venv - this script never installs anything
    python scripts/validate_intel_gpu.py [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
import time


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    out: dict = {"openvino": None, "devices": {}, "torch_xpu": None, "validated": []}
    try:
        import numpy as np
        import openvino as ov
        import openvino.runtime.opset13 as ops

        core = ov.Core()
        out["openvino"] = ov.__version__
        param = ops.parameter([1, 3, 64, 64], np.float32, name="x")
        weights = ops.constant(np.random.default_rng(0).standard_normal((8, 3, 3, 3)).astype(np.float32))
        model = ov.Model([ops.convolution(param, weights, [1, 1], [1, 1], [1, 1], [1, 1])], [param], "probe")
        for dev in core.available_devices:
            name = core.get_property(dev, "FULL_DEVICE_NAME")
            entry: dict = {"name": name, "ran_probe_model": False}
            try:
                compiled = core.compile_model(model, dev)
                x = np.random.default_rng(1).standard_normal((1, 3, 64, 64)).astype(np.float32)
                compiled([x])
                t0 = time.perf_counter()
                for _ in range(20):
                    compiled([x])
                entry.update(ran_probe_model=True, ms_per_inference=round((time.perf_counter() - t0) / 20 * 1000, 3))
            except Exception as exc:  # noqa: BLE001
                entry["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            out["devices"][dev] = entry
    except ImportError:
        out["openvino"] = "not installed"
    try:
        import torch

        out["torch_xpu"] = {"torch": torch.__version__, "xpu_available": bool(getattr(torch, "xpu", None) and torch.xpu.is_available())}
        if out["torch_xpu"]["xpu_available"]:
            out["torch_xpu"]["devices"] = [torch.xpu.get_device_name(i) for i in range(torch.xpu.device_count())]
    except ImportError:
        out["torch_xpu"] = "not installed"
    out["note"] = "Probe-model success shows the device executes OpenVINO graphs. It is NOT proof that SD/SDXL or image-to-3D models work."
    print(json.dumps(out, indent=2) if args.json else json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
