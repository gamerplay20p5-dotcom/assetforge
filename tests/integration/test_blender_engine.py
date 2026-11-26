"""Runs the real Blender headless export. Skipped automatically when no Blender executable is available."""

import os
import shutil
from pathlib import Path

import pytest
from assetforge_export.pipeline import run_building_job
from assetforge_validation import validate_glb

ROOT = Path(__file__).resolve().parents[2]


def _blender() -> str | None:
    cand = os.environ.get("BLENDER_BIN")
    if cand and Path(cand).is_file():
        return cand
    local = next((ROOT / ".tools" / "blender").glob("*/blender.exe"), None) or next((ROOT / ".tools" / "blender").glob("*/blender"), None)
    return str(local) if local else shutil.which("blender")


pytestmark = pytest.mark.blender


@pytest.fixture(scope="module")
def blender():
    b = _blender()
    if not b:
        pytest.skip("no Blender executable (set BLENDER_BIN)")
    return b


def test_blender_exports_blend_glb_fbx_and_thumbnail(blender, tmp_path):
    events = []
    job = dict(asset_id="ast_blender01", name="Blender House", version=1, job_id="j", quality_profile="stylized_standard",
               formats=["glb", "blend", "fbx"], params=dict(category="house", style="mediterranean", seed=9, detail=2, texture_resolution=256),
               thumbnail_size=256, thumbnail_samples=8)
    result = run_building_job(job, tmp_path, events.append, engine="blender", blender_bin=blender, threads=2)
    out = tmp_path / "out"
    assert result["engine"] == "blender" and result["validation"]["passed"]
    for name in ("model.glb", "model.blend", "model.fbx", "thumbnail.png", "manifest.json"):
        assert (out / name).stat().st_size > 1000, name
    assert (out / "model.fbx").read_bytes()[:20].startswith(b"Kaydara FBX Binary")
    assert (out / "model.blend").read_bytes()[:7] in (b"BLENDER", b"\x28\xb5\x2f\xfd\x04\x58"[:7]) or (out / "model.blend").stat().st_size > 1000
    report = validate_glb(out / "model.glb", expected_triangles=result["triangle_count"])
    assert report.passed, report.errors
    stages = [(e["name"], e["status"]) for e in events if e["type"] == "stage"]
    assert ("export", "done") in stages and ("thumbnail", "done") in stages


def test_blend_format_without_blender_is_refused_honestly(tmp_path):
    from assetforge_export.pipeline import PipelineError

    job = dict(asset_id="ast_x", name="x", version=1, job_id="j", formats=["glb", "fbx"], params=dict(category="house"))
    with pytest.raises(PipelineError, match="Blender"):
        run_building_job(job, tmp_path, lambda e: None, engine="trimesh")
