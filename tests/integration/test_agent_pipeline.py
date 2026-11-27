"""agent.building end to end with a scripted AI (no network): spec -> validation retry -> build -> real Blender review renders -> critique ->
corrected spec -> best spec exported by the normal building pipeline."""

from __future__ import annotations

import base64
import copy
import json

import pytest
from assetforge_export.agent_pipeline import QuotaWait, run_agent_job
from assetforge_export.pipeline import PipelineError

from test_blender_engine import _blender

pytestmark = pytest.mark.blender

SPEC = {"name": "sobrado", "category": "house", "wall_kind": "stucco", "roof_kind": "shingles", "ground": False,
        "palette": {"wall": "#E8D1AC", "trim": "#EFE1C6", "roof": "#5A5F66", "door": "#3A3E44", "frame": "#3A3E44"},
        "wings": [{"name": "main", "w": 8.0, "d": 6.0, "floors": 1, "fh": 2.9, "roof": "gable", "ridge": "x", "pitch": 30, "door_side": "front",
                   "window": {"w": 1.0, "h": 1.2, "sill": 0.9, "mullions_x": 2, "mullions_y": 2}}],
        "features": []}


@pytest.fixture(scope="module")
def blender():
    b = _blender()
    if not b:
        pytest.skip("no Blender executable (set BLENDER_BIN)")
    return b


def _job(**params):
    return dict(asset_id="ast_agent0001", name="Agente", version=1, job_id="job_agent", job_type="agent.building", quality_profile="stylized_standard",
                formats=["glb"], thumbnail_size=256, thumbnail_samples=8,
                params={"reference_ids": ["ref_0123456789ab"], "max_iterations": 2, "target_score": 8.0, "texture_resolution": 512, **params})


def test_agent_loop_validates_critiques_corrects_and_exports_the_best_spec(blender, tmp_path):
    calls: list[dict] = []
    better = copy.deepcopy(SPEC)
    better["wings"][0]["floors"] = 2

    def ai(body: dict) -> dict:
        calls.append(body)
        if body["task"] == "spec":
            if not body.get("validation_error"):  # first answer is invalid on purpose: the validator error must be sent back
                bad = copy.deepcopy(SPEC)
                bad["wings"][0]["floors"] = 0
                return {"data": bad, "provider": "fake", "model": "m"}
            return {"data": SPEC, "provider": "fake", "model": "m"}
        imgs = [base64.b64decode(b) for b in body["renders_b64"]]
        assert len(imgs) == 3 and all(i[:4] == b"\x89PNG" for i in imgs)  # real renders of the current model
        if body["iteration"] == 0:
            return {"data": {"score": 5.0, "issues": ["the reference has two storeys"], "spec": better}, "provider": "fake", "model": "m"}
        return {"data": {"score": 8.5, "issues": [], "spec": better}, "provider": "fake", "model": "m"}

    events: list[dict] = []
    result = run_agent_job(_job(), tmp_path, events.append, ai, blender_bin=blender, threads=2)
    tasks = [(c["task"], bool(c.get("validation_error"))) for c in calls]
    assert tasks == [("spec", False), ("spec", True), ("critique", False), ("critique", False)]
    assert "floors" in calls[1]["validation_error"]
    names = {f["name"] for f in result["files"]}
    assert {"model.glb", "thumbnail.png", "agent/history.json", "agent/iter0/view_front_left.png", "agent/iter1/view_aerial.png"} <= names
    hist = json.loads((tmp_path / "out" / "agent" / "history.json").read_text(encoding="utf-8"))
    assert [r["score"] for r in hist["rounds"]] == [5.0, 8.5] and hist["best_score"] == 8.5
    assert hist["rounds"][1]["spec"]["wings"][0]["floors"] == 2  # the corrected (better scored) spec is the one exported
    assert result["validation"]["passed"] and result["validation"]["metrics"]["agent_best_score"] == 8.5
    assert result["manifest"]["triangle_count"] > hist["rounds"][0]["triangles"]


def test_agent_gives_up_on_specs_that_never_validate(blender, tmp_path):
    def ai(body: dict) -> dict:
        return {"data": {**SPEC, "wings": [{**SPEC["wings"][0], "floors": 0}]}}

    with pytest.raises(PipelineError, match="valid specification"):
        run_agent_job(_job(), tmp_path, lambda e: None, ai, blender_bin=blender)


def test_quota_exhaustion_is_reported_for_requeue(blender, tmp_path):
    def ai(body: dict) -> dict:
        raise QuotaWait("cota", 3600.0)

    with pytest.raises(QuotaWait) as exc:
        run_agent_job(_job(), tmp_path, lambda e: None, ai, blender_bin=blender)
    assert exc.value.retry_after_s == 3600.0
