"""Vision endpoints against a stub of the vision service (a real HTTP server speaking the same protocol), plus the description -> kit job path."""

import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from assetforge_api.main import create_app
from fastapi.testclient import TestClient
from PIL import Image

from conftest import ADMIN_PW, make_settings

API = "/api/v1"
ANSWER = json.dumps(dict(floors=2, roof_type="hip", roof_color="dark_gray", wall_material="brick", wall_color="brick_red", lower_wall_material="none",
                         lower_wall_color="none", trim_color="cream", door_color="orange", door_position="right", windows_front_per_floor=[1, 2],
                         porch="portico", garage=False, garage_side="none", chimney=False, volumes="single", bay_window=True))


class StubVlm(BaseHTTPRequestHandler):
    answer = f"```json\n{ANSWER}\n```"

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            body = {"ready": True, "loaded": False, "model": "stub", "pending": 0}
        elif self.path.startswith("/jobs/vis_ok"):
            body = {"id": "vis_ok", "status": "succeeded", "started": 1, "finished": 2, "error": None,
                    "result": {"answer": self.answer, "seconds": 1.5, "new_tokens": 90}}
        elif self.path.startswith("/jobs/vis_run"):
            body = {"id": "vis_run", "status": "running", "started": 1, "finished": None, "error": None, "result": None}
        else:
            self.send_response(404)
            self.end_headers()
            return
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):  # noqa: N802
        n = int(self.headers["Content-Length"])
        assert self.rfile.read(n)[:4] == b"\x89PNG"
        data = json.dumps({"id": "vis_ok"}).encode()
        self.send_response(202)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.fixture
def vlm_client(tmp_path):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), StubVlm)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    app = create_app(make_settings(tmp_path, vlm_url=f"http://127.0.0.1:{srv.server_port}"), start_reaper=False)
    with TestClient(app) as c:
        yield c
    srv.shutdown()


def _login(c):
    r = c.post(f"{API}/auth/login", json={"username": "admin", "password": ADMIN_PW})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _ref(c, h):
    buf = io.BytesIO()
    Image.new("RGB", (128, 128), "white").save(buf, "PNG")
    return c.post(f"{API}/references", headers=h, files={"file": ("a.png", buf.getvalue(), "image/png")}).json()["id"]


def test_status_reports_the_service_or_that_it_is_disabled(client, admin, vlm_client):
    assert client.get(f"{API}/vision/status", headers=admin).json()["enabled"] is False
    h = _login(vlm_client)
    s = vlm_client.get(f"{API}/vision/status", headers=h).json()
    assert s["enabled"] and s["ready"] and s["model"] == "stub"
    assert client.post(f"{API}/vision/describe", headers=admin, json={"reference_id": "ref_000000000000"}).status_code == 503


def test_describe_validates_the_model_answer_and_picks_a_base_house(vlm_client):
    h = _login(vlm_client)
    ref = _ref(vlm_client, h)
    start = vlm_client.post(f"{API}/vision/describe", headers=h, json={"reference_id": ref})
    assert start.status_code == 202 and start.json()["id"] == "vis_ok"
    r = vlm_client.get(f"{API}/vision/describe/vis_ok", headers=h).json()
    assert r["status"] == "succeeded" and r["valid"] and r["description"]["roof_type"] == "hip" and r["base"] == "ref05"
    assert vlm_client.get(f"{API}/vision/describe/vis_run", headers=h).json()["status"] == "running"
    assert vlm_client.get(f"{API}/vision/describe/not_an_id", headers=h).status_code == 422
    assert vlm_client.post(f"{API}/vision/describe", headers=h, json={"reference_id": "../etc"}).status_code == 422


def test_invalid_model_answer_is_reported_not_trusted(vlm_client, monkeypatch):
    h = _login(vlm_client)
    monkeypatch.setattr(StubVlm, "answer", '{"floors": 9, "roof_type": "dome"}')
    r = vlm_client.get(f"{API}/vision/describe/vis_ok", headers=h).json()
    assert r["status"] == "succeeded" and r["valid"] is False and r["error"]
    assert "description" not in r  # nothing from an invalid answer is trusted


def test_preview_and_job_creation_validate_the_description(vlm_client):
    h = _login(vlm_client)
    desc = json.loads(ANSWER)
    p = vlm_client.post(f"{API}/vision/preview", headers=h, json={"description": desc}).json()
    assert p["valid"] and p["base"] == "ref05"
    assert vlm_client.post(f"{API}/vision/preview", headers=h, json={"description": {**desc, "wall_color": "magenta"}}).status_code == 422
    ok = vlm_client.post(f"{API}/jobs", headers=h, json={"name": "casa", "quality_profile": "stylized_detailed", "formats": ["glb"],
                                                           "params": {"category": "house", "house_description": desc, "construction_stage": 6}})
    assert ok.status_code == 201, ok.text
    bad = vlm_client.post(f"{API}/jobs", headers=h, json={"name": "casa", "params": {"category": "house", "house_description": {**desc, "floors": 7}}})
    assert bad.status_code == 422
