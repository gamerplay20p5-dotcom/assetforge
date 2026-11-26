"""Stand-in for the CLI of a CPU provider (PROVIDER_CMD_OVERRIDE). Usage: provider_stub.py <image> <out_dir>

Writes <out_dir>/0/mesh.glb copied from $STUB_GLB. Behaviour switches (env): STUB_SLEEP seconds, STUB_FAIL=1 always fail,
STUB_FAIL_ONCE=<marker file> fail the first time only, STUB_ALLOC_MB allocate that much memory while sleeping.
This is NOT a model: it only exercises the service plumbing (jobs, cancel, timeout, metrics)."""

import os
import shutil
import sys
import time
from pathlib import Path

image, out = Path(sys.argv[1]), Path(sys.argv[2])
print("stub: start", image.name, flush=True)
hog = bytearray(int(os.environ.get("STUB_ALLOC_MB", "0")) * 2**20)
if hog:
    hog[::4096] = b"x" * len(hog[::4096])  # touch pages so RSS is real
time.sleep(float(os.environ.get("STUB_SLEEP", "0")))
marker = os.environ.get("STUB_FAIL_ONCE")
if os.environ.get("STUB_FAIL") == "1" or (marker and not Path(marker).exists()):
    if marker:
        Path(marker).write_text("failed once")
    print("stub: simulated failure", flush=True)
    sys.exit(3)
(out / "0").mkdir(parents=True, exist_ok=True)
shutil.copyfile(os.environ["STUB_GLB"], out / "0" / "mesh.glb")
print("stub: done", flush=True)
