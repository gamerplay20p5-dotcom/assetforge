"""Static checks of the single-node Docker deployment (Docker itself is not available here: these catch regressions of the
design rules, they do not prove the containers build or run)."""

import re
from pathlib import Path

import pytest
import yaml
from assetforge_intel_ai.presets import AIPG_COMMIT, COMFYUI_VERSION

ROOT = Path(__file__).resolve().parents[2]
DEP = ROOT / "deployment"
COMPOSE = yaml.safe_load((DEP / "docker-compose.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]
ENV_FILES = {n: (DEP / f"{n}.env.example").read_text(encoding="utf-8") for n in ("standalone", "external-db")}


def test_expected_services_and_profiles():
    assert set(SERVICES) == {"postgres", "api", "worker-cpu", "comfyui", "worker-gpu", "ai-tools", "triposr", "sf3d", "worker-ai", "triposr-setup", "sf3d-setup", "cpu3d-tools", "vlm"}
    assert SERVICES["postgres"]["profiles"] == ["standalone"]
    assert SERVICES["comfyui"]["profiles"] == ["ai"] and SERVICES["worker-gpu"]["profiles"] == ["ai"] and SERVICES["ai-tools"]["profiles"] == ["tools"]
    assert "profiles" not in SERVICES["api"] and "profiles" not in SERVICES["worker-cpu"]  # work with either DB profile and without AI
    assert SERVICES["api"]["depends_on"]["postgres"]["required"] is False  # external-db profile must not need the local postgres


def test_only_the_api_publishes_a_port():
    for name, svc in SERVICES.items():
        assert bool(svc.get("ports")) == (name == "api"), name
    assert SERVICES["comfyui"]["expose"] == ["8188"]  # ComfyUI has no authentication: internal network only


def test_cpu3d_providers_are_cpu_only_internal_and_resource_limited():
    for name in ("triposr", "sf3d"):
        svc = SERVICES[name]
        assert svc["profiles"] == ["cpu3d"] and "devices" not in svc and "ports" not in svc and "expose" not in svc
        assert "cpu3d-models:/models" in svc["volumes"] and svc["cap_drop"] == ["ALL"]
        assert str(svc["cpus"]).startswith("${") and str(svc["mem_limit"]).startswith("${")
        assert "HF_TOKEN" not in svc["environment"]  # the gated-weights token never reaches the long-running services
    assert "HF_TOKEN" in SERVICES["sf3d-setup"]["environment"] and SERVICES["sf3d-setup"]["profiles"] == ["tools"]
    w = SERVICES["worker-ai"]["environment"]
    assert w["ASSETFORGE_CPU3D_PROVIDERS"] == "sf3d=http://sf3d:8080,triposr=http://triposr:8080" and "devices" not in SERVICES["worker-ai"]
    assert SERVICES["worker-gpu"]["environment"]["ASSETFORGE_ENABLE_INTEL_AI"] == "${ASSETFORGE_ENABLE_INTEL_AI:-0}"  # Intel stays opt-in


def test_gpu_via_dri_without_privileged_or_nvidia():
    text = (DEP / "docker-compose.yml").read_text(encoding="utf-8").lower()
    for name in ("comfyui", "worker-gpu", "ai-tools"):
        assert "/dev/dri:/dev/dri" in SERVICES[name]["devices"], name
    for name in ("triposr", "sf3d", "worker-ai", "worker-cpu"):
        assert "devices" not in SERVICES[name], name  # CPU services never touch /dev/dri
    for name, svc in SERVICES.items():
        assert not svc.get("privileged"), name
        assert svc.get("security_opt") == ["no-new-privileges:true"], name
        assert svc.get("cap_drop") == ["ALL"], name
        assert "runtime" not in svc and "gpus" not in svc and "deploy" not in svc, name
    assert not re.search(r"runtime:\s*nvidia|\bgpus:|capabilities:\s*\[gpu\]|image:.*(cuda|nvidia)", text)
    assert "nvidia" not in (DEP / "Dockerfile.comfyui").read_text(encoding="utf-8").lower().replace("sem cuda/nvidia", "")


def test_gpu_worker_is_single_job_and_models_are_readonly_for_services():
    assert SERVICES["worker-gpu"]["environment"]["ASSETFORGE_WORKER_MAX_JOBS"] == 1
    assert "ai-models:/models:ro" in SERVICES["worker-gpu"]["volumes"]
    assert "ai-models:/models" in SERVICES["ai-tools"]["volumes"]  # only the tools job may write models
    assert SERVICES["worker-gpu"]["environment"]["ASSETFORGE_AI_ALLOW_UNVALIDATED"] == "${ASSETFORGE_AI_ALLOW_UNVALIDATED:-0}"


def test_postgres_keeps_only_the_capabilities_its_entrypoint_needs():
    pg = SERVICES["postgres"]
    assert pg["cap_drop"] == ["ALL"] and set(pg["cap_add"]) == {"CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID"}
    assert all("cap_add" not in svc for n, svc in SERVICES.items() if n != "postgres")


def test_persistent_volumes_cover_models_assets_db_and_state():
    assert {"pgdata", "assets", "ai-models", "cpu3d-models", "worker-cpu-state", "worker-gpu-state", "worker-ai-state"} <= set(COMPOSE["volumes"])


def test_resource_limits_are_configurable():
    for name in ("api", "worker-cpu", "comfyui", "worker-gpu", "worker-ai", "triposr", "sf3d"):
        assert str(SERVICES[name]["cpus"]).startswith("${") and str(SERVICES[name]["mem_limit"]).startswith("${"), name


@pytest.mark.parametrize("profile", ["standalone", "external-db"])
def test_env_examples_define_every_required_variable(profile):
    env = ENV_FILES[profile]
    defined = set(re.findall(r"^([A-Z0-9_]+)=", env, flags=re.M))
    raw = (DEP / "docker-compose.yml").read_text(encoding="utf-8")
    required = set(re.findall(r"\$\{([A-Z0-9_]+):\?", raw))
    needed = {v for v in required if not (profile == "external-db" and v == "POSTGRES_PASSWORD")}
    assert needed <= defined, needed - defined
    assert f"COMPOSE_PROFILES={profile}" in env
    assert ("ASSETFORGE_DATABASE_URL=postgresql://" in env) == (profile == "external-db")
    assert "HOST_DO_BANCO" in env or profile == "standalone"  # placeholder, never a real address/password


def test_no_secrets_or_hardcoded_addresses_in_deployment_files():
    for f in list(DEP.glob("*")) + [ROOT / "scripts" / "install_single_node.sh"]:
        t = f.read_text(encoding="utf-8")
        assert not re.search(r"192\.168\.\d+\.\d+", t), f.name


def test_pinned_versions_match_code():
    d = (DEP / "Dockerfile.comfyui").read_text(encoding="utf-8")
    assert f"AIPG_COMMIT={AIPG_COMMIT}" in d and f"COMFY_TAG={COMFYUI_VERSION}" in d
    assert AIPG_COMMIT in (ROOT / "scripts/intel_ai/install_node.sh").read_text(encoding="utf-8")


def test_dockerfile_copy_sources_exist():
    for df in ("Dockerfile.worker", "Dockerfile.central"):
        for m in re.finditer(r"^COPY\s+(?!--from)(\S+)\s", (DEP / df).read_text(encoding="utf-8"), flags=re.M):
            assert (ROOT / m.group(1)).exists(), (df, m.group(1))


def test_vision_service_is_internal_limited_and_offline_by_default():
    v = SERVICES["vlm"]
    assert v["profiles"] == ["vision"] and not v.get("ports")
    assert v["cap_drop"] == ["ALL"] and "no-new-privileges:true" in v["security_opt"]
    assert "cpus" in v and "mem_limit" in v  # never unbounded on a shared server
    assert "HF_HUB_OFFLINE: ${VLM_OFFLINE:-1}" in str(v["environment"]).replace("'", "") or v["environment"]["HF_HUB_OFFLINE"] == "${VLM_OFFLINE:-1}"
    assert "vlm-models" in COMPOSE["volumes"] and v["networks"] == ["internal"]
    assert "ASSETFORGE_VLM_URL" in SERVICES["api"]["environment"]
