import json
from datetime import datetime, time

import httpx
import pytest
from assetforge_api.security import LoginThrottle, create_jwt, decode_jwt, hash_password, verify_password
from assetforge_api.storage import Storage, UnsafePath, safe_join, validate_relative
from assetforge_procedural import plan_with_llm, plan_with_rules
from assetforge_procedural.planner import plan
from assetforge_worker.policy import in_active_hours, lease_gate, parse_active_hours
from assetforge_worker.resources import detect_gpus
from jwt import ExpiredSignatureError


# ----------------------------------------------------------------------------- planner
def test_planner_hospital_example_from_brief():
    r = plan_with_rules("um hospital moderno de cinco andares")
    assert r.params == {"category": "hospital", "style": "modern", "floors": 5}
    assert r.source == "rules" and r.confidence > 0.5


@pytest.mark.parametrize("text,expected", [
    ("casa clássica de tijolo com garagem, telhado de duas águas", {"category": "house", "style": "classic", "garage": True, "roof": "gable"}),
    ("a modern five-story hospital without balconies", {"category": "hospital", "floors": 5, "balconies": False}),
    ("arranha-céu de 30 andares", {"category": "skyscraper", "floors": 30}),
    ("galpão 60 x 30 m desgastado", {"category": "warehouse", "width": 60.0, "depth": 30.0, "wear": 0.7}),
])
def test_planner_rules(text, expected):
    params = plan_with_rules(text).params
    for k, v in expected.items():
        assert params[k] == v


def test_planner_unknown_text_is_flagged_not_invented():
    r = plan_with_rules("blablabla")
    assert r.params == {"category": "house"} and r.confidence < 0.2 and r.notes


def _llm_client(answer: str, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["format"]["title"] == "BuildingParams" and body["options"]["temperature"] == 0
        return httpx.Response(status, json={"message": {"content": answer}})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_llm_planner_accepts_schema_valid_answer():
    r = plan_with_llm("hospital", "http://llm", "m", client=_llm_client('{"category":"hospital","floors":5}'))
    assert r.source == "llm" and r.params["floors"] == 5


@pytest.mark.parametrize("answer", ['{"category":"hospital","exec":"rm -rf /"}', '{"floors": 9999}', "not json"])
def test_llm_planner_rejects_unsafe_or_invalid_answers(answer):
    with pytest.raises(ValueError):
        plan_with_llm("x", "http://llm", "m", client=_llm_client(answer))


def test_plan_falls_back_to_rules_when_llm_unreachable():
    r = plan("hospital moderno de 5 andares", "http://127.0.0.1:9", "m")
    assert r.source == "rules" and any("LLM" in n for n in r.notes)


# ----------------------------------------------------------------------------- worker policy
def test_active_hours_cross_midnight():
    w = parse_active_hours("22:00-07:00")
    assert in_active_hours(w, datetime(2026, 1, 1, 23, 30)) and in_active_hours(w, datetime(2026, 1, 1, 3, 0))
    assert not in_active_hours(w, datetime(2026, 1, 1, 12, 0))
    assert in_active_hours([], datetime(2026, 1, 1, 12, 0))
    with pytest.raises(ValueError):
        parse_active_hours("nonsense")


def test_lease_gate_reasons():
    noon = datetime(2026, 1, 1, 12, 0)
    base = dict(windows=[], now=noon, max_host_cpu_percent=0, host_cpu_avg=None, yield_patterns=[], running_processes=[])
    assert lease_gate(**base) is None
    assert "janela" in lease_gate(**{**base, "windows": [(time(22), time(7))]})
    assert "host ocupado" in lease_gate(**{**base, "max_host_cpu_percent": 50, "host_cpu_avg": 80})
    assert lease_gate(**{**base, "max_host_cpu_percent": 50, "host_cpu_avg": 20}) is None
    reason = lease_gate(**{**base, "yield_patterns": ["ai-stream-clipper"], "running_processes": ["python AI-Stream-Clipper --run"]})
    assert reason and "ai-stream-clipper" in reason


def test_gpu_detection_never_invents_values():
    for g in detect_gpus():  # may be empty on CI; when present, unmeasured fields must be None
        assert g["vendor"] == "Intel" and g["utilization_percent"] is None and g["vram_used_mb"] is None


# ----------------------------------------------------------------------------- security helpers
def test_password_hashing_and_jwt(tmp_path):
    h = hash_password("correct horse battery")
    assert verify_password("correct horse battery", h) and not verify_password("wrong", h)
    assert not verify_password("x", "garbage")
    tok = create_jwt("s" * 32, "alice", "admin", seconds=60)
    assert decode_jwt("s" * 32, tok)["sub"] == "alice"
    with pytest.raises(ExpiredSignatureError):
        decode_jwt("s" * 32, create_jwt("s" * 32, "alice", "admin", seconds=-5))


def test_login_throttle():
    t = LoginThrottle(3)
    for _ in range(3):
        t.fail("k")
    assert t.blocked("k")
    t.ok("k")
    assert not t.blocked("k")


@pytest.mark.parametrize("bad", ["../x.glb", "/etc/passwd.glb", "a/../../b.glb", "a\\b.glb", "x.exe", "a/b/c/d/e.glb", ".hidden.png", "C:/x.png", "a//b.png", ""])
def test_unsafe_paths_rejected(bad):
    with pytest.raises(UnsafePath):
        validate_relative(bad)


def test_safe_join_stays_inside(tmp_path):
    assert safe_join(tmp_path, "textures/tex_brick_512.png").is_relative_to(tmp_path.resolve())
    with pytest.raises(UnsafePath):
        safe_join(tmp_path, "../escape.png")
    with pytest.raises(UnsafePath):
        Storage(tmp_path).asset_dir("../evil", 1)
