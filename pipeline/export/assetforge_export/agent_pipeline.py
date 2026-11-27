"""``agent.building``: cloud-AI assisted procedural modelling (analyse -> spec -> validate -> build -> render -> critique -> correct).

The AI (reached ONLY through the API's worker proxy, which owns the keys) writes data in a fixed JSON schema; this module converts it to a
``HouseSpec``, validates it with the generator, builds it, renders review views in Blender and sends them back with the references so the AI
can score the fidelity and return a corrected spec. The best-scored spec is exported with the normal building pipeline (same validation,
textures, LOD, package). Nothing returned by the model is executed.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from assetforge_contract import AgentParams
from assetforge_optimization import clean_mesh
from assetforge_procedural.house import HouseSpec, generate_house
from assetforge_vision import llm_spec

from .glb import render_textures, write_glb
from .pipeline import PipelineError, find_blender, run_building_job

Emit = Callable[[dict], None]
AiCall = Callable[[dict], dict]
AGENT_PLAN: list[tuple[str, float]] = [("ai_spec", 10), ("agent_loop", 45), ("generate_geometry", 4), ("optimize", 2), ("validate_geometry", 2),
                                       ("textures", 5), ("export", 18), ("thumbnail", 7), ("validate_outputs", 3), ("package", 4)]
REVIEW_VIEWS = "front_left,front_right,aerial"
MAX_INLINE_WAIT_S = 90.0  # wait in place for short (per-minute) quota windows; longer waits re-queue the job


class QuotaWait(PipelineError):
    def __init__(self, message: str, retry_after_s: float | None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


def views_script() -> Path:
    env = os.environ.get("ASSETFORGE_REVIEW_VIEWS")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "scripts" / "review" / "blender_views.py"


def proxy_ai_call(emit: Emit) -> AiCall:
    """AI calls through the API (``POST /worker/jobs/{id}/ai``); credentials come from the parent worker via the environment, never disk."""
    url, token, lease = (os.environ.get(k, "") for k in ("ASSETFORGE_AGENT_AI_URL", "ASSETFORGE_AGENT_WORKER_TOKEN", "ASSETFORGE_AGENT_LEASE"))
    if not url or not lease:
        raise PipelineError("this worker was started without the AI proxy settings (agent.building needs a current worker)")
    http = httpx.Client(timeout=300.0, headers={"Authorization": f"Bearer {token}"} if token else {})

    def call(body: dict) -> dict:
        waited = 0.0
        for _ in range(12):
            try:
                r = http.post(url, json={**body, "lease_token": lease})
            except httpx.HTTPError as exc:
                raise PipelineError(f"could not reach the API AI proxy: {type(exc).__name__}") from exc
            if r.status_code == 429:
                j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                wait = j.get("retry_after_s")
                if wait is not None and wait <= MAX_INLINE_WAIT_S and waited + wait <= 4 * MAX_INLINE_WAIT_S:
                    emit({"type": "log", "level": "warning", "message": f"cota de IA esgotada no momento; aguardando {int(wait)} s ({j.get('detail', '')[:200]})"})
                    time.sleep(wait)
                    waited += wait
                    continue
                raise QuotaWait(f"cota de IA indisponível: {j.get('detail', r.text)[:600]}", wait)
            if r.status_code >= 400:
                raise PipelineError(f"AI proxy error {r.status_code}: {r.text[:400]}")
            return r.json()
        raise QuotaWait("cota de IA indisponível (várias esperas seguidas)", 120.0)

    return call


def _validate(llm: dict, seed: int, wear: float | None, stage: int) -> tuple[dict, Any]:
    spec = llm_spec.to_house_spec(llm, seed)
    if wear is not None:
        spec["wear"] = wear
    hs = HouseSpec.from_dict(spec)  # raises ValueError with a readable message
    gen = generate_house(hs, stage)
    if gen.mesh.triangle_count == 0:
        raise ValueError("the specification produced no geometry")
    return spec, gen


def _render(gen: Any, d: Path, blender: str, samples: int = 24, size: int = 640, timeout: float = 600.0) -> list[Path]:
    d.mkdir(parents=True, exist_ok=True)
    mesh, _ = clean_mesh(gen.mesh, normalize_pivot=False)
    tex = render_textures(gen.materials, 512, d / "textures")
    write_glb(d / "model.glb", mesh, gen.materials, tex, "review", {})
    lo, hi = mesh.bounds()
    w, h, dz = float(hi[0] - lo[0]), float(hi[1] - lo[1]), float(hi[2] - lo[2])
    args = [blender, "-b", "-P", str(views_script()), "--", str(d / "model.glb"), str(d / "view"), str(samples), str(size), REVIEW_VIEWS, "plain",
            f"{h:.3f}"] + (["portrait"] if h > 1.3 * max(w, dz) else [])
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
    out = [d / f"view_{v}.png" for v in REVIEW_VIEWS.split(",")]
    missing = [p.name for p in out if not p.is_file()]
    if missing:
        raise PipelineError(f"review render failed (missing {missing})")
    return out


def run_agent_job(job: dict, workdir: Path, emit: Emit, ai: AiCall | None = None, *, blender_bin: str | None = None, threads: int = 2,
                  blender_timeout: float = 900.0, should_cancel: Callable[[], bool] | None = None) -> dict:
    params = AgentParams.model_validate(job["params"])
    ai = ai or proxy_ai_call(emit)
    blender = blender_bin or find_blender()
    if not blender:
        raise PipelineError("agent.building needs Blender for the review renders")
    max_iter = params.max_iterations if params.max_iterations is not None else 2
    target = params.target_score if params.target_score is not None else 8.0
    stage_no = params.construction_stage or 6
    refs = params.reference_ids
    agent_dir = workdir / "agent"
    history: list[dict] = []

    def stage(name: str, status: str, **extra: Any) -> None:
        emit({"type": "stage", "name": name, "status": status, **extra})

    def log(msg: str, level: str = "info") -> None:
        emit({"type": "log", "level": level, "message": msg})

    def ask(body: dict) -> dict:
        r = ai(body)
        log(f"IA: {body['task']} via {r.get('provider')}/{r.get('model')}{' (cache)' if r.get('cached') else ''} tokens={r.get('total_tokens', 0)}")
        return r["data"]

    def valid_spec(llm: dict, what: str) -> tuple[dict, dict, Any]:
        err = ""
        for attempt in range(3):
            if err:
                llm = ask({"task": "spec", "reference_ids": refs, "category_hint": params.category, "validation_error": err, "previous": llm})
            try:
                spec, gen = _validate(llm, params.seed, params.wear, stage_no)
                return llm, spec, gen
            except (ValueError, TypeError, KeyError) as exc:
                err = f"{type(exc).__name__}: {exc}"[:1500]
                log(f"{what}: especificação rejeitada pelo validador (tentativa {attempt + 1}): {err}", "warning")
        raise PipelineError(f"the AI could not produce a valid specification: {err}")

    # 1. first spec -----------------------------------------------------------------------------------------------
    stage("ai_spec", "start")
    llm, spec, gen = valid_spec(ask({"task": "spec", "reference_ids": refs, "category_hint": params.category}), "spec")
    stage("ai_spec", "done", detail=f"{len(spec['wings'])} volumes, {len(spec['features'])} detalhes")

    # 2. render -> critique -> correct --------------------------------------------------------------------------
    stage("agent_loop", "start")
    best: tuple[float, dict, dict] | None = None
    for it in range(max_iter + 1):
        if should_cancel and should_cancel():
            raise PipelineError("cancelled")
        renders = _render(gen, agent_dir / f"iter{it}", blender, timeout=blender_timeout)
        crit = ask({"task": "critique", "reference_ids": refs, "renders_b64": [base64.b64encode(p.read_bytes()).decode() for p in renders],
                    "spec": llm, "iteration": it})
        score = float(crit.get("score", 0.0))
        issues = [str(x)[:300] for x in (crit.get("issues") or [])][:20]
        history.append({"iteration": it, "score": score, "issues": issues, "triangles": gen.mesh.triangle_count, "spec": spec,
                        "renders": [f"agent/iter{it}/{p.name}" for p in renders]})
        log(f"iteração {it}: nota {score:.1f}/10; {'; '.join(issues[:4])}")
        if best is None or score > best[0]:
            best = (score, llm, spec)
        if score >= target or it == max_iter:
            break
        try:
            llm, spec, gen = valid_spec(crit.get("spec") or {}, f"correção {it + 1}")
        except PipelineError as exc:
            log(f"correção descartada: {exc}", "warning")
            break
    assert best is not None
    score, llm, spec = best
    stage("agent_loop", "done", detail=f"melhor nota {score:.1f}/10 em {len(history)} rodada(s)")

    # 3. export the best spec with the normal (validated) building pipeline ------------------------------------
    category = llm_spec.category_of(llm)
    bjob = {**job, "job_type": "procedural.building",
            "params": {"category": category, "seed": params.seed, "house_spec": spec, "construction_stage": params.construction_stage,
                       "texture_resolution": params.texture_resolution, **({"wear": params.wear} if params.wear is not None else {})}}
    result = run_building_job(bjob, workdir, emit, engine="blender", blender_bin=blender, threads=threads, blender_timeout=blender_timeout,
                              should_cancel=should_cancel)
    out = workdir / "out"
    extra = out / "agent"
    extra.mkdir(exist_ok=True)
    (extra / "history.json").write_text(json.dumps({"best_score": score, "target_score": target, "category": category, "rounds": history},
                                                   indent=2), encoding="utf-8")
    from .pipeline import _file_entry

    files = [_file_entry(extra / "history.json", out, "report", "json")]
    for h in history:
        for rel in h["renders"]:
            src = workdir / rel
            dst = out / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
            files.append(_file_entry(dst, out, "preview", "png"))
    result["files"] = result["files"] + [f.model_dump() for f in files]
    result.setdefault("validation", {}).setdefault("metrics", {}).update(agent_best_score=score, agent_rounds=len(history))
    return result
