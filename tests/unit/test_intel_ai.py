import hashlib
import json

import httpx
import pytest
from assetforge_contract import AiParams, JobCreate, QualityProfile
from assetforge_intel_ai import ComfyCancelled, ComfyClient, ComfyError, IntelAIProvider, ModelStore, VramMonitor, required_specs, target_faces
from assetforge_intel_ai.models import FILE_LICENSES, ModelSpec
from assetforge_intel_ai.presets import PresetError, apply_settings, load_preset, normalize_model_names, set_node_input, text_to_image_workflow
from PIL import Image
from pydantic import ValidationError
from support.fake_comfy import FakeComfy


@pytest.fixture
def fake(tmp_path):
    glb = tmp_path / "fake.glb"
    glb.write_bytes(b"glTF-not-a-real-model")
    png = tmp_path / "fake.png"
    Image.new("RGB", (64, 64), "white").save(png)
    f = FakeComfy(glb, png)
    yield f
    f.close()


# ----------------------------------------------------------------------------- vendored Intel presets
def test_vendored_presets_load_and_match_what_we_rely_on():
    p = load_preset("pixel3d-trellis")
    assert p.name == "Pixel3D-Trellis" and "--use-quad-cross-attention" in p.required_comfy_args
    classes = {n["class_type"] for n in p.workflow.values()}
    # Intel's graph already contains the retopology/detail-preservation nodes we reuse instead of re-implementing
    assert {"RemeshMesh", "DecimateMesh", "UnwrapMesh", "BakeNormalMapFromMesh", "BakeAmbientOcclusion", "SaveGLB"} <= classes
    assert not p.raw["requiredCustomNodes"]  # native ComfyUI nodes only
    for label in ("Input Image", "Base Steps", "Use TRELLIS.2", "Remove Background", "Texture Resolution", "Target Face Count"):
        assert p.setting(label)["nodeTitle"]


def test_apply_settings_injects_by_node_title_without_mutating_the_preset():
    p = load_preset("pixel3d-trellis")
    before = json.dumps(p.workflow, sort_keys=True)
    wf = apply_settings(p, {"Target Face Count": 1234, "Base Steps": 7, "Use TRELLIS.2": True})
    s = p.setting("Target Face Count")
    assert any(n["inputs"].get(s["nodeInput"]) == 1234 for n in wf.values())
    assert json.dumps(p.workflow, sort_keys=True) == before
    with pytest.raises(PresetError):
        apply_settings(p, {"Nonexistent": 1})
    with pytest.raises(PresetError):
        set_node_input(wf, "No Such Node", "x", 1)


def test_model_paths_are_normalised_for_linux():
    wf = normalize_model_names(load_preset("pixel3d-trellis").workflow.copy())
    assert not any("\\" in json.dumps(v) for v in wf.values())


def test_text_to_image_workflow_drops_safety_checker_and_stays_valid():
    wf = text_to_image_workflow(load_preset("z-image"), "a hospital", "", 768, 768, 5, steps=9)
    classes = {n["class_type"] for n in wf.values()}
    assert "SafetyChecker" not in classes and "CM_FloatBinaryOperation" not in classes
    save = next(n for n in wf.values() if n["class_type"] == "SaveImage")
    src = save["inputs"]["images"][0]
    assert wf[src]["class_type"] == "VAEDecode"  # SaveImage re-wired straight to the decoder
    assert next(n for n in wf.values() if n["class_type"] == "EmptySD3LatentImage")["inputs"]["width"] == 768
    for n in wf.values():  # no dangling links
        for v in n["inputs"].values():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                assert v[0] in wf


# ----------------------------------------------------------------------------- client / provider
def test_provider_health_reports_real_state(fake, tmp_path):
    prov = IntelAIProvider(fake.url, models_dir=tmp_path / "models")
    h = prov.health()
    assert h.reachable and h.xpu_devices and h.xpu_devices[0]["vram_total_mb"] == 8192
    assert len(h.models_missing) == len(required_specs()) and not h.ready  # nothing downloaded yet
    down = IntelAIProvider("http://127.0.0.1:9", models_dir=tmp_path).health()
    assert not down.reachable and down.errors


def test_image_to_3d_roundtrip_injects_profile_and_monitors_vram(fake, tmp_path):
    ref = tmp_path / "ref.png"
    Image.new("RGB", (128, 128), "gray").save(ref)
    prov = IntelAIProvider(fake.url, models_dir=tmp_path / "m")
    res = prov.image_to_3d(ref, tmp_path / "out.glb", profile=QualityProfile.stylized_detailed, target_faces=9000, seed=77)
    assert res.path.read_bytes() == fake.glb.read_bytes() and res.peak_vram_mb and res.peak_vram_mb < 8192
    assert fake.uploads and fake.interrupts == 0
    wf = fake.prompts[-1]
    assert any(n["inputs"].get("target_face_count") == 9000 for n in wf.values() if n["class_type"] == "DecimateMesh")
    assert next(n for n in wf.values() if n["class_type"] == "RemeshMesh")["inputs"]["resolution"] == 640  # detailed profile
    assert all(n["inputs"]["seed"] == 77 for n in wf.values() if n["class_type"] == "KSampler")
    assert len(res.workflow_sha) == 64


def test_text_to_image_prompt_gets_art_direction_suffix(fake, tmp_path):
    prov = IntelAIProvider(fake.url, models_dir=tmp_path)
    prov.text_to_image("modern hospital", tmp_path / "c.png", seed=3)
    text = next(n for n in fake.prompts[-1].values() if n["class_type"] == "CLIPTextEncode")["inputs"]["text"]
    assert text.startswith("modern hospital") and "premium stylized" in text


def test_comfy_errors_and_cancellation(tmp_path, fake):
    fake.fail_with = "OutOfMemoryError: XPU out of memory"
    prov = IntelAIProvider(fake.url, models_dir=tmp_path)
    with pytest.raises(ComfyError, match="XPU out of memory"):
        prov.text_to_image("x", tmp_path / "c.png")
    fake.fail_with = None
    with pytest.raises(ComfyCancelled):
        prov.text_to_image("x", tmp_path / "c.png", should_cancel=lambda: True)
    assert fake.interrupts == 1  # cancellation interrupts the backend, not just our process


def test_vram_monitor_keeps_peak(fake):
    with VramMonitor(ComfyClient(fake.url), interval=0.05) as m:
        fake.prompts.append({})  # raises the fake's reported usage
        import time

        time.sleep(0.2)
    assert m.samples >= 2 and m.total_mb == 8192 and m.peak_used_mb >= int(8192 * 0.45)


# ----------------------------------------------------------------------------- profiles / contract
def test_target_faces_follow_contract_budget_and_override():
    assert target_faces("house", QualityProfile.stylized_standard, None) == int(4000 * 0.9)
    assert target_faces("house", QualityProfile.stylized_standard, 1000) == 900
    assert target_faces("tree", QualityProfile.high_quality, None) > target_faces("tree", QualityProfile.prototype, None)


def test_ai_job_contract_validation():
    ok = JobCreate(name="t", job_type="ai.text_to_3d", params={"prompt": "a school", "category": "school", "provider": "intel"})
    assert ok.params["lod_ratios"] == [0.5, 0.25, 0.1] and ok.category == "school"
    with pytest.raises(ValidationError):
        JobCreate(name="t", job_type="ai.text_to_3d", params={"provider": "intel"})
    with pytest.raises(ValidationError, match="text-to-image"):
        JobCreate(name="t", job_type="ai.text_to_3d", params={"prompt": "a school"})  # CPU providers have no text-to-image
    with pytest.raises(ValidationError):
        JobCreate(name="t", job_type="ai.image_to_3d", params={"prompt": "x"})
    with pytest.raises(ValidationError):
        AiParams(lod_ratios=[0.1, 0.5])
    with pytest.raises(ValidationError):
        AiParams(category="castle")
    with pytest.raises(ValidationError):
        AiParams(reference_id="../../etc/passwd")
    assert JobCreate(name="b", params={"category": "house"}).params["category"] == "house"  # procedural unchanged


# ----------------------------------------------------------------------------- model store
def _store(tmp_path, content: bytes, sha: str | None):
    spec = ModelSpec("diffusion_models", "Comfy-Org/Fake", "diffusion_models/m.safetensors", "t")

    def handler(req: httpx.Request) -> httpx.Response:
        if "/api/models/" in req.url.path:
            return httpx.Response(200, json=[{"path": spec.path, "size": len(content), "lfs": {"oid": sha} if sha else {}}])
        rng = req.headers.get("range")
        if rng:
            start = int(rng.split("=")[1].split("-")[0])
            return httpx.Response(206, content=content[start:])
        return httpx.Response(200, content=content)

    return spec, ModelStore(tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True))


def test_model_download_verifies_sha_and_layout(tmp_path):
    data = b"x" * 5000
    spec, store = _store(tmp_path, data, hashlib.sha256(data).hexdigest())
    p = store.download(spec)
    assert p == tmp_path / "diffusion_models" / "Comfy-Org---Fake" / "diffusion_models" / "m.safetensors"  # AIPG-compatible layout
    assert store.verify(spec) and not store.missing([spec]) and store.status([spec])[0]["verified"]
    p.write_bytes(b"corrupt")
    assert not store.verify(spec)


def test_model_download_rejects_wrong_hash_and_resumes(tmp_path):
    data = b"y" * 4000
    spec, bad = _store(tmp_path, data, "0" * 64)
    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        bad.download(spec)
    assert not spec.local_path(tmp_path).exists() and not spec.local_path(tmp_path).with_name("m.safetensors.part").exists()
    spec, good = _store(tmp_path, data, hashlib.sha256(data).hexdigest())
    part = spec.local_path(tmp_path).with_name("m.safetensors.part")
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(data[:1500])  # interrupted earlier
    good.download(spec)
    assert spec.local_path(tmp_path).read_bytes() == data


def test_every_required_model_has_a_license_and_brazil_review_flags():
    specs = required_specs()
    assert len(specs) >= 9
    for s in specs:
        info = s.license_info
        assert info["license"] != "DESCONHECIDA", s.key
    dino = next(s for s in specs if s.path in FILE_LICENSES)
    assert dino.license_info["commercial_br"] == "verify"  # honest: needs human confirmation
