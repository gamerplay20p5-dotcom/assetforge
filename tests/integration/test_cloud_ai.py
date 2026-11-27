"""Cloud AI (Gemini / Grok): key pool, fail-over, quotas, cache, free-only mode and the worker proxy.

The providers are exercised through their real clients (the official ``google-genai`` SDK, and httpx for xAI) against local stub servers that
speak the same REST protocol, selected by the key's ``base_url``. No real key and no network access are needed.
"""

from __future__ import annotations

import io
import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from assetforge_api.ai.crypto import decrypt, encrypt
from assetforge_api.ai.providers import _gemini_retry_info
from assetforge_api.ai.router import day_start, next_day
from assetforge_api.models import AiKey, Job
from PIL import Image

API = "/api/v1"
SPEC = {"name": "casa teste", "category": "house", "wall_kind": "stucco", "roof_kind": "shingles", "palette": {
    "wall": "#E8D1AC", "trim": "#EFE1C6", "roof": "#5A5F66", "door": "#3A3E44", "frame": "#3A3E44"},
    "wings": [{"name": "main", "w": 8.0, "d": 6.0, "floors": 2, "fh": 2.9, "roof": "gable", "door_side": "front"}], "features": []}


class Stub(BaseHTTPRequestHandler):
    """Gemini (models.list / generateContent) and xAI (OpenAI chat completions) in one stub; the API key picks the behaviour."""

    calls: list[tuple[str, str]] = []
    answer: dict = {}

    def log_message(self, *a):
        pass

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _key(self) -> str:
        return self.headers.get("x-goog-api-key") or (self.headers.get("Authorization") or "").removeprefix("Bearer ")

    def _fault(self, key: str) -> bool:
        if "quota" in key:
            daily = "daily" in key
            self._send(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "quota exceeded", "details": [
                {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
                    {"quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
                     "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier" if daily else "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]},
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "17s"}]}})
            return True
        if "bad" in key:
            self._send(403, {"error": {"code": 403, "status": "PERMISSION_DENIED", "message": "API key not valid"}})
            return True
        return False

    def do_GET(self):  # noqa: N802
        key = self._key()
        Stub.calls.append(("list", key))
        if "bad" in key:
            self._fault(key)
        elif self.headers.get("x-goog-api-key"):  # Gemini (the SDK picks the API version; the auth header identifies it)
            self._send(200, {"models": [{"name": "models/gemini-2.5-flash", "displayName": "Gemini 2.5 Flash", "supportedGenerationMethods": ["generateContent"]},
                                        {"name": "models/gemini-3.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
                                        {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]}]})
        elif self.path.endswith("/models"):
            self._send(200, {"data": [{"id": "grok-4"}]})
        else:
            self._send(404, {})

    def do_POST(self):  # noqa: N802
        key = self._key()
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Stub.calls.append(("gen", key))
        if self._fault(key):
            return
        text = json.dumps(Stub.answer)
        if ":generateContent" in self.path:
            parts = body["contents"][0]["parts"]
            assert any("inlineData" in p or "inline_data" in p for p in parts), "images must be sent inline"
            assert body["generationConfig"]["responseMimeType"] == "application/json" and "responseJsonSchema" in body["generationConfig"]
            self._send(200, {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}],
                             "usageMetadata": {"promptTokenCount": 1200, "candidatesTokenCount": 300, "totalTokenCount": 1500}})
        elif self.path.endswith("/chat/completions"):
            assert body["response_format"]["type"] == "json_schema"
            self._send(200, {"choices": [{"message": {"role": "assistant", "content": text}}], "usage": {"prompt_tokens": 900, "completion_tokens": 200,
                                                                                                      "total_tokens": 1100}})
        else:
            self._send(404, {})


@pytest.fixture
def stub():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    Stub.calls, Stub.answer = [], SPEC
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def _key(client, admin, stub, provider="gemini", api_key="AIzaGOODKEY0001", **over):
    body = {"provider": provider, "api_key": api_key, "label": api_key[-6:], "base_url": stub if provider == "gemini" else stub + "/v1", **over}
    r = client.post(f"{API}/ai/keys", headers=admin, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _ref(client, admin) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, "PNG")
    return client.post(f"{API}/references", headers=admin, files={"file": ("a.png", buf.getvalue(), "image/png")}).json()["id"]


def _agent_lease(client, admin, make_worker):
    ref = _ref(client, admin)
    r = client.post(f"{API}/jobs", headers=admin, json={"name": "agente", "job_type": "agent.building", "params": {"reference_ids": [ref]}})
    assert r.status_code == 201, r.text
    w = make_worker(features=("procedural.building", "trimesh", "blender", "agent.building"))
    lease = w.lease()
    assert lease and lease["job_id"] == r.json()["id"]
    return w, lease, ref


def _ask(w, lease, ref, **extra):
    return w.client.post(f"{API}/worker/jobs/{lease['job_id']}/ai", headers=w.headers,
                         json={"lease_token": lease["lease_token"], "task": "spec", "reference_ids": [ref], **extra})


# ---------------------------------------------------------------------------------------------------------- unit
def test_key_encryption_roundtrip_and_secret_change():
    tok = encrypt("s" * 40, "AIzaSECRET")
    assert "AIzaSECRET" not in tok and decrypt("s" * 40, tok) == "AIzaSECRET"
    with pytest.raises(ValueError):
        decrypt("other" * 10, tok)


def test_quota_details_and_pacific_day():
    retry, daily = _gemini_retry_info({"error": {"details": [{"retryDelay": "33s"}, {"violations": [{"quotaId": "GenerateRequestsPerDayPerProject"}]}]}})
    assert retry == 33.0 and daily
    now = datetime(2026, 11, 26, 9, 0, tzinfo=timezone.utc)  # 01:00 in Los Angeles (PST, UTC-8)
    assert day_start("gemini", now) == datetime(2026, 11, 26, 8, 0, tzinfo=timezone.utc)
    assert next_day("gemini", now) == datetime(2026, 11, 27, 8, 1, tzinfo=timezone.utc)
    assert day_start("grok", now) == datetime(2026, 11, 26, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------------------------------------- admin
def test_keys_are_tested_before_saving_stored_encrypted_and_never_returned(app, client, admin, stub):
    probe = client.post(f"{API}/ai/models", headers=admin, json={"provider": "gemini", "api_key": "AIzaGOODKEY0001", "base_url": stub}).json()
    assert probe["ok"] and probe["suggested"] == "gemini-3.5-flash-lite"
    assert [m["name"] for m in probe["models"]] == ["gemini-2.5-flash", "gemini-3.5-flash-lite"]  # embedding-only models are hidden
    bad = client.post(f"{API}/ai/keys", headers=admin, json={"provider": "gemini", "api_key": "AIzabadKEY00001", "base_url": stub})
    assert bad.status_code == 400  # a key that does not work is never stored
    k = _key(client, admin, stub)
    assert k["model"] == "gemini-3.5-flash-lite" and k["key_hint"] == "…0001" and "api_key" not in k and "key_enc" not in k
    listing = client.get(f"{API}/ai/keys", headers=admin)
    assert "AIzaGOODKEY0001" not in listing.text and "key_enc" not in listing.text
    with app.state.db.session() as db:
        row = db.get(AiKey, k["id"])
        assert "AIzaGOODKEY0001" not in row.key_enc
    assert client.post(f"{API}/ai/keys/{k['id']}/test", headers=admin).json()["ok"]
    assert client.patch(f"{API}/ai/keys/{k['id']}", headers=admin, json={"priority": 5, "rpm_limit": 2}).json()["priority"] == 5
    assert client.delete(f"{API}/ai/keys/{k['id']}", headers=admin).status_code == 204
    assert client.get(f"{API}/ai/keys", headers=admin).json() == []


def test_keys_admin_requires_admin(client, admin):
    client.post(f"{API}/auth/users", headers=admin, json={"username": "oper", "password": "operator-pass-1", "role": "operator"})
    r = client.post(f"{API}/auth/login", json={"username": "oper", "password": "operator-pass-1"})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get(f"{API}/ai/keys", headers=h).status_code == 403
    assert client.post(f"{API}/ai/keys", headers=h, json={"provider": "gemini", "api_key": "AIzaGOODKEY0001"}).status_code == 403


# ---------------------------------------------------------------------------------------------------------- pool
def test_failover_to_the_next_key_when_one_is_out_of_quota(app, client, admin, stub, make_worker):
    q = _key(client, admin, stub, api_key="AIzaquotaKEY001", priority=1)
    ok = _key(client, admin, stub, api_key="AIzaGOODKEY0002", priority=2)
    w, lease, ref = _agent_lease(client, admin, make_worker)
    r = _ask(w, lease, ref)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["wings"][0]["name"] == "main" and r.json()["cached"] is False and r.json()["total_tokens"] == 1500
    keys = {k["id"]: k for k in client.get(f"{API}/ai/keys", headers=admin).json()}
    assert keys[q["id"]]["cooldown_until"] and not keys[ok["id"]]["cooldown_until"]  # rate quota: ~17 s cooldown
    before = [c for c in Stub.calls if c == ("gen", "AIzaquotaKEY001")]
    assert _ask(w, lease, ref, category_hint="apartment").status_code == 200
    assert [c for c in Stub.calls if c == ("gen", "AIzaquotaKEY001")] == before  # the cooling key is skipped
    hist = client.get(f"{API}/ai/requests", headers=admin).json()
    assert {h["status"] for h in hist} == {"ok", "quota"} and all("AIza" not in json.dumps(h) for h in hist)


def test_daily_quota_cools_until_pacific_midnight_and_job_waits(app, client, admin, stub, make_worker):
    k = _key(client, admin, stub, api_key="AIzaquotadaily1")
    w, lease, ref = _agent_lease(client, admin, make_worker)
    r = _ask(w, lease, ref)
    assert r.status_code == 429 and r.json()["retry_after_s"] > 60
    cd = datetime.fromisoformat(client.get(f"{API}/ai/keys", headers=admin).json()[0]["cooldown_until"])
    assert cd == next_day("gemini", datetime.now(timezone.utc)) or abs((cd - next_day("gemini", datetime.now(timezone.utc))).total_seconds()) < 5
    # the worker hands the job back without using an attempt: it resumes automatically after the wait
    f = client.post(f"{API}/worker/jobs/{lease['job_id']}/fail", headers=w.headers,
                    json={"lease_token": lease["lease_token"], "error": "cota", "retryable": True, "quota_wait_s": 3600})
    assert f.json()["status"] == "queued"
    with app.state.db.session() as db:
        job = db.get(Job, lease["job_id"])
        assert job.max_attempts == 3 and job.not_before is not None
    assert k["id"]


def test_rpm_limit_and_cache(client, admin, stub, make_worker):
    _key(client, admin, stub, api_key="AIzaGOODKEY0003", rpm_limit=1)
    w, lease, ref = _agent_lease(client, admin, make_worker)
    assert _ask(w, lease, ref).status_code == 200
    n = len(Stub.calls)
    again = _ask(w, lease, ref)  # identical request: served from the cache, no provider call, does not count toward the limit
    assert again.status_code == 200 and again.json()["cached"] is True and len(Stub.calls) == n
    other = _ask(w, lease, ref, category_hint="school")  # new prompt, but the per-minute limit (1) is used up
    assert other.status_code == 429 and 30 <= other.json()["retry_after_s"] <= 62


def test_free_only_blocks_paid_grok_until_allowed(client, admin, stub, make_worker):
    g = _key(client, admin, stub, provider="grok", api_key="xai-GOODKEY0004")
    assert g["paid"] and g["model"] == "grok-4"
    w, lease, ref = _agent_lease(client, admin, make_worker)
    r = _ask(w, lease, ref)
    assert r.status_code == 429 and "free-only" in r.json()["detail"]
    client.patch(f"{API}/ai/keys/{g['id']}", headers=admin, json={"allow_paid": True})
    ok = _ask(w, lease, ref)
    assert ok.status_code == 200 and ok.json()["provider"] == "grok" and ok.json()["data"]["name"] == "casa teste"


def test_rejected_key_fails_over_and_status_hides_keys(client, admin, stub, make_worker, app):
    k = _key(client, admin, stub, api_key="AIzaGOODKEY0005", priority=1)
    _key(client, admin, stub, api_key="AIzaGOODKEY0006", priority=2)
    with app.state.db.session() as db:  # the key was revoked at Google after being saved
        db.get(AiKey, k["id"]).key_enc = encrypt("k" * 40, "AIzabadREVOKED1")
        db.commit()
    w, lease, ref = _agent_lease(client, admin, make_worker)
    assert _ask(w, lease, ref).status_code == 200
    st = client.get(f"{API}/ai/status", headers=admin).json()
    assert st["configured"] and st["available"] == 1 and "AIza" not in json.dumps(st)


# ---------------------------------------------------------------------------------------------------------- proxy rules
def test_proxy_needs_the_lease_and_an_agent_job(client, admin, stub, make_worker, job_body):
    _key(client, admin, stub)
    w, lease, ref = _agent_lease(client, admin, make_worker)
    assert _ask(w, {**lease, "lease_token": "wrong"}, ref).status_code == 409
    client.post(f"{API}/jobs", headers=admin, json=job_body())
    w2 = make_worker()
    l2 = w2.lease()
    assert _ask(w2, l2, ref).status_code == 403  # a normal building job may not spend AI quota
    bad = w.client.post(f"{API}/worker/jobs/{lease['job_id']}/ai", headers=w.headers,
                        json={"lease_token": lease["lease_token"], "task": "critique", "reference_ids": [ref], "spec": SPEC, "renders_b64": ["bm90IGFuIGltYWdl"]})
    assert bad.status_code == 422  # renders must be real PNG/JPEG


def test_agent_job_defaults_come_from_panel_settings(client, admin):
    client.put(f"{API}/ai/settings", headers=admin, json={"agent_iterations": 1, "target_score": 7.5})
    ref = _ref(client, admin)
    j = client.post(f"{API}/jobs", headers=admin, json={"name": "a", "job_type": "agent.building", "params": {"reference_ids": [ref]}}).json()
    assert j["params"]["max_iterations"] == 1 and j["params"]["target_score"] == 7.5
    s = client.get(f"{API}/ai/settings", headers=admin).json()
    assert s["free_only"] is True and "Google" in s["data_notice"]
    missing = client.post(f"{API}/jobs", headers=admin, json={"name": "a", "job_type": "agent.building", "params": {"reference_ids": ["ref_000000000000"]}})
    assert missing.status_code == 404
    _ = timedelta
