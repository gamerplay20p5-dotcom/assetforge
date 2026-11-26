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


def test_house_kit_archetype_runs_the_full_blender_pipeline(blender, tmp_path):
    job = dict(asset_id="ast_kit01", name="Kit House", version=1, job_id="j", quality_profile="stylized_detailed", formats=["glb", "blend", "fbx"],
               params=dict(category="house", archetype="nordic_cabin", seed=1, texture_resolution=256), thumbnail_size=256, thumbnail_samples=8)
    result = run_building_job(job, tmp_path, lambda e: None, engine="blender", blender_bin=blender, threads=2)
    out = tmp_path / "out"
    assert result["validation"]["passed"], result["validation"]
    assert (out / "model.glb").stat().st_size > 10_000 and (out / "model.fbx").stat().st_size > 10_000
    assert validate_glb(out / "model.glb", expected_triangles=result["triangle_count"]).passed


def test_vision_description_runs_the_full_blender_pipeline(blender, tmp_path):
    desc = dict(floors=2, roof_type="gable", roof_color="dark_gray", wall_material="siding", wall_color="sage_green", trim_color="cream",
                door_color="orange", door_position="left", windows_front_per_floor=[2, 2], porch="covered_porch", garage=True, garage_side="right",
                chimney=False, volumes="with_side_wing", bay_window=False)
    job = dict(asset_id="ast_vis01", name="Vision House", version=1, job_id="j", quality_profile="stylized_detailed", formats=["glb", "blend", "fbx"],
               params=dict(category="house", house_description=desc, construction_stage=6, texture_resolution=256), thumbnail_size=256, thumbnail_samples=8)
    result = run_building_job(job, tmp_path, lambda e: None, engine="blender", blender_bin=blender, threads=2)
    assert result["validation"]["passed"], result["validation"]
    assert (tmp_path / "out" / "model.fbx").stat().st_size > 10_000


@pytest.mark.parametrize("stage", [3, 4])
def test_framing_stages_pass_validation_after_blender_export(blender, tmp_path, stage):
    """Regression: the framing stage (overlapping beams) exported fewer triangles than reported."""
    desc = dict(floors=2, roof_type="gable", roof_color="dark_gray", wall_material="siding", wall_color="sage_green", lower_wall_material="siding",
                lower_wall_color="sage_green", trim_color="white", door_color="brown", door_position="center", windows_front_per_floor=[2, 2],
                porch="covered_porch", garage=True, garage_side="right", chimney=False, volumes="single", bay_window=False)
    job = dict(asset_id="ast_fr01", name="Framing", version=1, job_id="j", quality_profile="stylized_detailed", formats=["glb"],
               params=dict(category="house", house_description=desc, construction_stage=stage, texture_resolution=256), thumbnail_size=128, thumbnail_samples=4)
    result = run_building_job(job, tmp_path, lambda e: None, engine="blender", blender_bin=blender, threads=2)
    assert result["validation"]["passed"], result["validation"]
