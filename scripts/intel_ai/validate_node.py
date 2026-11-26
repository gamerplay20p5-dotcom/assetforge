#!/usr/bin/env python3
"""Valida UM node: roda de verdade texto→imagem→3D no ComfyUI local e só então registra "validado".

    python3 scripts/intel_ai/validate_node.py --state-dir ~/assetforge-worker-state [--comfy-url http://127.0.0.1:8188]
        [--models-dir ~/assetforge-ai/ComfyUI/models] [--image ref.png] [--blender /caminho/blender] [--dry-run]

Critérios (todos reais): ComfyUI acessível com dispositivo de GPU; modelos presentes; texto→imagem produz PNG; imagem→3D
produz GLB; o GLB re-lido tem triângulos > 0 e material com textura; pós-processamento no Blender gera LOD0..N dentro do
orçamento; pico de VRAM medido. Só se TUDO passar é escrito <state-dir>/ai_validated.json (ok=true), que libera os
recursos ai.* no worker. Em caso de falha grava o relatório (ok=false) com a causa e NÃO libera nada.
O relatório vira evidência para docs/HARDWARE_COMPATIBILITY.md (cole o JSON de saída lá).
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # consoles Windows (cp1252)
ROOT = Path(__file__).resolve().parents[2]
for d in ("workers/cpu", "generators/procedural", "generators/intel_ai", "pipeline/export", "pipeline/validation",
          "pipeline/optimization", "packages/asset-contract"):
    sys.path.insert(0, str(ROOT / d))

from assetforge_export.ai_pipeline import run_ai_job  # noqa: E402
from assetforge_export.pipeline import find_blender  # noqa: E402
from assetforge_intel_ai import ComfyClient, IntelAIProvider  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", type=Path, required=True)
    ap.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    ap.add_argument("--models-dir", type=Path, default=Path.home() / "assetforge-ai" / "ComfyUI" / "models")
    ap.add_argument("--image", type=Path, help="usa esta imagem de referência em vez de gerar uma por texto")
    ap.add_argument("--prompt", default="a two-story stylized house with gable roof, brick walls and wooden door")
    ap.add_argument("--blender", default=None)
    ap.add_argument("--dry-run", action="store_true", help="não grava ai_validated.json")
    args = ap.parse_args()

    prov = IntelAIProvider(args.comfy_url, models_dir=args.models_dir)
    health = prov.health()
    stats = {}
    try:
        stats = ComfyClient(args.comfy_url).system_stats()
    except Exception:  # noqa: BLE001
        pass
    gpu = (health.xpu_devices[0]["name"] if health.xpu_devices else None)
    report: dict = {"ok": False, "preset": "pixel3d-trellis", "gpu": gpu, "date": datetime.now(UTC).isoformat(),
                    "host": platform.node(), "health": health.as_dict(), "system": stats.get("system", {}),
                    "provenance": prov.provenance()}
    print(json.dumps(health.as_dict(), indent=2, ensure_ascii=False))
    blender = args.blender or find_blender()
    if not health.reachable or not health.xpu_devices or health.models_missing or not blender:
        report["error"] = "pré-requisitos ausentes: " + ("; ".join(health.errors + (["Blender não encontrado"] if not blender else []) + health.models_missing[:3]))
        return _finish(args, report, 2)

    work = Path(tempfile.mkdtemp(prefix="af-validate-"))
    try:
        job = {"job_id": "validate", "asset_id": "ast_validate", "name": "Validação do node", "version": 1,
               "job_type": "ai.image_to_3d" if args.image else "ai.text_to_3d", "quality_profile": "stylized_standard",
               "formats": ["glb", "fbx"], "thumbnail_size": 384, "thumbnail_samples": 8,
               "params": {"category": "house", "prompt": args.prompt, "target_size_m": 8.0, "seed": 7, "lod_ratios": [0.5, 0.25],
                          "reference_id": "ref_000000000000" if args.image else None}}
        if args.image:
            job["reference_path"] = str(args.image)
        job["params"] = {k: v for k, v in job["params"].items() if v is not None}
        t0 = time.monotonic()
        events: list[dict] = []
        result = run_ai_job(job, work, lambda e: (events.append(e), print(" ", e.get("name") or e.get("message", "")[:100], e.get("status", ""))), prov, blender_bin=blender)
        m = result["manifest"]
        ai = m["generation_params"]["ai"]["stages"]
        report.update(ok=bool(result["validation"]["passed"]) and m["triangle_count"] > 0, seconds=round(time.monotonic() - t0, 1),
                      stages=ai, triangles=[x["triangles"] for x in m["lods"]], dimensions_m=m["dimensions_m"],
                      materials=len(m["materials"]), textured=any(x["texture"] for x in m["materials"]),
                      peak_vram_mb=max((s.get("peak_vram_mb") or 0) for s in ai.values()),
                      vram_total_mb=max((s.get("vram_total_mb") or 0) for s in ai.values()),
                      validation_warnings=[c for c in result["validation"]["checks"] if c["status"] == "warn"])
        if report["ok"] and not report["textured"]:
            report["ok"], report["error"] = False, "o GLB gerado não tem textura"
        keep = ROOT / "validation_reports"
        keep.mkdir(exist_ok=True)
        for f in ("thumbnail.png", "concept.png"):
            if (work / "out" / f).is_file():
                shutil.copy(work / "out" / f, keep / f"{platform.node()}_{f}")
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return _finish(args, report, 0 if report["ok"] else 1)


def _finish(args: argparse.Namespace, report: dict, code: int) -> int:
    print("\n=== RELATÓRIO ===")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    out = ROOT / "validation_reports"
    out.mkdir(exist_ok=True)
    (out / f"{platform.node()}_{datetime.now():%Y%m%d-%H%M%S}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if not args.dry_run:
        args.state_dir.mkdir(parents=True, exist_ok=True)
        f = args.state_dir / "ai_validated.json"
        try:
            old = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            old = []
        f.write_text(json.dumps([r for r in old if r.get("gpu") != report["gpu"]] + [{k: report.get(k) for k in ("ok", "preset", "gpu", "date", "host", "seconds", "peak_vram_mb", "vram_total_mb", "error")}], indent=2), encoding="utf-8")
        print(f"\nregistro gravado em {f} (ok={report['ok']})")
    print("\nRESULTADO:", "VALIDADO — recursos ai.* liberados no worker" if report["ok"] else "NÃO VALIDADO — nada foi liberado")
    return code


if __name__ == "__main__":
    sys.exit(main())
