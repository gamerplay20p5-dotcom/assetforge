"""Supervised subprocess execution: hard timeout, cooperative cancellation, streamed output."""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path


class JobCancelled(Exception):
    """Raised when the server asked the job to stop."""


class SubprocessTimeout(Exception):
    pass


class SubprocessFailed(Exception):
    def __init__(self, code: int, tail: str) -> None:
        super().__init__(f"process exited with code {code}: {tail[-400:]}")
        self.code = code
        self.tail = tail


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False)
        else:
            import signal

            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:  # noqa: BLE001
        proc.kill()


def run_supervised(cmd: Sequence[str], *, timeout: float, on_line: Callable[[str], None] | None = None,
                   should_cancel: Callable[[], bool] | None = None, cwd: Path | None = None,
                   env: dict[str, str] | None = None) -> str:
    """Run ``cmd`` (never through a shell). Returns the combined output; raises on failure/timeout/cancel."""
    kwargs: dict = {}
    if os.name != "nt":
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(list(cmd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", cwd=str(cwd) if cwd else None, env=env, **kwargs)
    lines: queue.Queue[str | None] = queue.Queue()

    def reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.put(line.rstrip("\n"))
        lines.put(None)

    threading.Thread(target=reader, daemon=True).start()
    start = time.monotonic()
    collected: list[str] = []
    done = False
    while not done:
        try:
            item = lines.get(timeout=0.2)
            if item is None:
                done = True
            else:
                collected.append(item)
                if len(collected) > 4000:
                    del collected[:1000]
                if on_line:
                    on_line(item)
        except queue.Empty:
            pass
        if should_cancel and should_cancel():
            _kill_tree(proc)
            proc.wait()
            raise JobCancelled()
        if time.monotonic() - start > timeout:
            _kill_tree(proc)
            proc.wait()
            raise SubprocessTimeout(f"timed out after {timeout:.0f}s")
    code = proc.wait()
    output = "\n".join(collected)
    if code != 0:
        raise SubprocessFailed(code, output)
    return output
