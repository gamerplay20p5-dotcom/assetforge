"""Starts a REAL local AssetForge stack for end-to-end tests: API (+ built dashboard) and one CPU worker.

Used by Playwright (`apps/dashboard/playwright.config.ts`) and runnable by hand:
    python tests/e2e/stack.py [--port 8130] [--blender /path/to/blender]
Everything lives in a temporary directory that is removed on exit. No Docker needed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
PKG_DIRS = ["apps/api", "workers/cpu", "generators/procedural", "pipeline/validation", "pipeline/optimization",
            "pipeline/export", "packages/asset-contract"]
ADMIN_PASSWORD = "e2e-admin-password"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8130)
    ap.add_argument("--blender", default=os.environ.get("BLENDER_BIN", ""))
    ap.add_argument("--engine", default="auto")
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="assetforge-e2e-"))
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(ROOT / d) for d in PKG_DIRS), "PYTHONUNBUFFERED": "1",
           "ASSETFORGE_ENV": "test", "ASSETFORGE_DATABASE_URL": f"sqlite:///{(tmp / 'db.sqlite3').as_posix()}",
           "ASSETFORGE_STORAGE_ROOT": str(tmp / "storage"), "ASSETFORGE_ADMIN_PASSWORD": ADMIN_PASSWORD,
           "ASSETFORGE_SECRET_KEY": "e2e-secret-key-0123456789-0123456789", "ASSETFORGE_DASHBOARD_DIR": str(ROOT / "apps/dashboard/dist"),
           "ASSETFORGE_LEASE_SECONDS": "30"}
    if args.blender:
        env["BLENDER_BIN"] = args.blender
    procs: list[subprocess.Popen] = []

    def stop(*_: object) -> None:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
        shutil.rmtree(tmp, ignore_errors=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    base = f"http://127.0.0.1:{args.port}"
    procs.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "assetforge_api.main:create_app", "--factory", "--port", str(args.port),
                                   "--log-level", "warning"], env=env, cwd=ROOT))
    for _ in range(60):
        try:
            if httpx.get(f"{base}/api/v1/health/ready", timeout=2).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.5)
    else:
        print("API did not become ready", file=sys.stderr)
        stop()
    token = httpx.post(f"{base}/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}).json()["access_token"]
    enr = httpx.post(f"{base}/api/v1/workers/enrollment-tokens", json={"label": "e2e"}, headers={"Authorization": f"Bearer {token}"}).json()["token"]
    wenv = {**env, "ASSETFORGE_SERVER_URL": base, "ASSETFORGE_ENROLLMENT_TOKEN": enr, "ASSETFORGE_WORKER_NAME": "e2e-cpu",
            "ASSETFORGE_WORKER_STATE_DIR": str(tmp / "worker"), "ASSETFORGE_WORKER_ENGINE": args.engine,
            "ASSETFORGE_WORKER_POLL_SECONDS": "1"}
    procs.append(subprocess.Popen([sys.executable, "-m", "assetforge_worker"], env=wenv, cwd=ROOT))
    print(f"stack ready at {base} (admin password: {ADMIN_PASSWORD})", flush=True)
    while all(p.poll() is None for p in procs):
        time.sleep(1)
    stop()
    return 1


if __name__ == "__main__":
    sys.exit(main())
