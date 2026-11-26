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
import threading
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


class HostSampler:
    """Mede, durante a geração, o pico de RAM do host, de CPU e a maior temperatura exposta pelo kernel (hwmon)."""

    def __init__(self, interval: float = 2.0) -> None:
        import psutil

        self.psutil, self.interval = psutil, interval
        self.peak_ram_mb = 0
        self.peak_cpu = 0.0
        self.peak_temp_c: float | None = None
        self.samples = 0
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.samples += 1
            self.peak_ram_mb = max(self.peak_ram_mb, int(self.psutil.virtual_memory().used / 2**20))
            self.peak_cpu = max(self.peak_cpu, self.psutil.cpu_percent(interval=None))
            try:
                temps = [t.current for entries in self.psutil.sensors_temperatures().values() for t in entries if t.current]
                if temps:
                    self.peak_temp_c = max(self.peak_temp_c or 0.0, max(temps))
            except (AttributeError, OSError):
                pass
            self._stop.wait(self.interval)

    def __enter__(self) -> "HostSampler":
        self._t.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._t.join(timeout=5)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", type=Path, required=True)
    ap.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    ap.add_argument("--models-dir", type=Path, default=Path.home() / "assetforge-ai" / "ComfyUI" / "models")
    ap.add_argument("--image", type=Path, help="usa esta imagem de referência em vez de gerar uma por texto")
    ap.add_argument("--prompt", default="a two-story stylized house with gable roof, brick walls and wooden door")
    ap.add_argument("--blender", default=None)
    ap.add_argument("--repeat", type=int, default=1, help="repete a geração N vezes para medir estabilidade")
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

    runs: list[dict] = []
    for attempt in range(1, max(1, args.repeat) + 1):
        work = Path(tempfile.mkdtemp(prefix="af-validate-"))
        run: dict = {"attempt": attempt, "ok": False}
        try:
            job = {"job_id": "validate", "asset_id": "ast_validate", "name": "Validação do node", "version": 1,
                   "job_type": "ai.image_to_3d" if args.image else "ai.text_to_3d", "quality_profile": "stylized_standard",
                   "formats": ["glb", "fbx"], "thumbnail_size": 384, "thumbnail_samples": 8,
                   "params": {"category": "house", "prompt": args.prompt, "target_size_m": 8.0, "seed": 7 + attempt, "lod_ratios": [0.5, 0.25],
                              "reference_id": "ref_000000000000" if args.image else None}}
            if args.image:
                job["reference_path"] = str(args.image)
            job["params"] = {k: v for k, v in job["params"].items() if v is not None}
            t0 = time.monotonic()
            with HostSampler() as host:
                result = run_ai_job(job, work, lambda e: print(" ", e.get("name") or e.get("message", "")[:100], e.get("status", ""), flush=True), prov, blender_bin=blender)
            m = result["manifest"]
            ai = m["generation_params"]["ai"]["stages"]
            run.update(ok=bool(result["validation"]["passed"]) and m["triangle_count"] > 0, seconds=round(time.monotonic() - t0, 1),
                       stages=ai, triangles=[x["triangles"] for x in m["lods"]], dimensions_m=m["dimensions_m"],
                       materials=len(m["materials"]), textured=any(x["texture"] for x in m["materials"]),
                       peak_vram_mb=max((st.get("peak_vram_mb") or 0) for st in ai.values()),
                       vram_total_mb=max((st.get("vram_total_mb") or 0) for st in ai.values()),
                       peak_host_ram_mb=host.peak_ram_mb, peak_host_cpu_percent=host.peak_cpu, peak_temp_c=host.peak_temp_c,
                       validation_warnings=[c for c in result["validation"]["checks"] if c["status"] == "warn"])
            if run["ok"] and not run["textured"]:
                run["ok"], run["error"] = False, "o GLB gerado não tem textura"
            keep = ROOT / "validation_reports"
            keep.mkdir(exist_ok=True)
            for f in ("thumbnail.png", "concept.png"):
                if (work / "out" / f).is_file():
                    shutil.copy(work / "out" / f, keep / f"{platform.node()}_run{attempt}_{f}")
        except Exception as exc:  # noqa: BLE001
            run["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            shutil.rmtree(work, ignore_errors=True)
        runs.append(run)
        print(f"execução {attempt}/{args.repeat}: {'ok' if run['ok'] else 'FALHOU'} {run.get('error', '')}")
        if not run["ok"]:
            break  # não insiste em uma GPU que já falhou (evita travar o nó)
    best = runs[-1]
    report.update(ok=all(r["ok"] for r in runs) and len(runs) == max(1, args.repeat), runs=runs,
                  seconds=best.get("seconds"), peak_vram_mb=max((r.get("peak_vram_mb") or 0) for r in runs),
                  vram_total_mb=best.get("vram_total_mb"), peak_host_ram_mb=max((r.get("peak_host_ram_mb") or 0) for r in runs),
                  peak_temp_c=max((r.get("peak_temp_c") or 0) for r in runs) or None, error=best.get("error"),
                  stability=f"{sum(r['ok'] for r in runs)}/{max(1, args.repeat)} execuções ok")
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
