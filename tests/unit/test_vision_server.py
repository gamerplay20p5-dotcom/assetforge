"""The vision HTTP service: token, image checks, queue (with a stub engine, no model)."""

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
from assetforge_vision.server import Service, make_handler

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


class StubEngine:
    model_name, quant, device, loaded, idle_unload = "stub", "fp32", "cuda", False, 10**6
    threads, max_side = 1, 640
    last_used = 0.0

    def weights_cached(self):
        return True

    def describe(self, png, task="house"):
        return dict(answer='{"ok": true}', seconds=0.1, load_seconds=0.0, input_tokens=1, new_tokens=1, task=task)


def _req(url, method="GET", data=None, token=None):
    r = urllib.request.Request(url, data=data, method=method, headers={"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@pytest.fixture
def server():
    svc = Service(StubEngine())
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(svc, token="tok"))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_token_is_required_except_for_health(server):
    assert _req(f"{server}/health")[0] == 200 and _req(f"{server}/health")[1]["device"] == "cuda"
    assert _req(f"{server}/describe", "POST", PNG)[0] == 401
    assert _req(f"{server}/describe", "POST", PNG, token="wrong")[0] == 401
    assert _req(f"{server}/jobs/vis_x", token="wrong")[0] == 401


def test_only_images_are_accepted_and_jobs_complete_in_order(server):
    assert _req(f"{server}/describe", "POST", b"#!/bin/sh\nrm -rf /", token="tok")[0] == 415
    assert _req(f"{server}/describe", "POST", b"", token="tok")[0] in (413, 400)
    ids = [_req(f"{server}/describe?task=analysis", "POST", PNG, token="tok")[1]["id"] for _ in range(3)]
    for _ in range(50):
        st = [_req(f"{server}/jobs/{i}", token="tok")[1] for i in ids]
        if all(s["status"] == "succeeded" for s in st):
            break
        time.sleep(0.1)
    assert all(s["status"] == "succeeded" for s in st)
    assert [s["result"]["task"] for s in st] == ["analysis"] * 3
    assert st[0]["finished"] <= st[1]["finished"] <= st[2]["finished"]  # first requested, first served
