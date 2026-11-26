#!/usr/bin/env python3
"""Benchmark e comparação visual do pipeline generativo neste node (medidas reais, nada pré-calculado).

    python3 scripts/intel_ai/benchmark_ai.py --out bench_ai --from-procedural 4 --profiles prototype stylized_standard
    python3 scripts/intel_ai/benchmark_ai.py --out bench_ai --images ./referencias --profiles stylized_standard

--from-procedural N gera N edifícios procedurais, usa a miniatura de cada um como imagem de referência e compara o
resultado da IA com o original procedural (folha "referência | IA | procedural"). Saídas: results.json, results.md e
comparison_<perfil>.png. Requer ComfyUI no ar e nó validado (validate_node.py).
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import tempfile
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # consoles Windows (cp1252)
ROOT = Path(__file__).resolve().parents[2]
for d in ("workers/cpu", "generators/procedural", "generators/intel_ai", "pipeline/export", "pipeline/validation", "pipeline/optimization", "packages/asset-contract"):
    sys.path.insert(0, str(ROOT / d))

from assetforge_export.ai_pipeline import run_ai_job  # noqa: E402
from assetforge_export.pipeline import find_blender, run_building_job  # noqa: E402
from assetforge_intel_ai import IntelAIProvider  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

CATS = ["house", "commercial", "school", "hospital", "apartment", "government"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    ap.add_argument("--models-dir", type=Path, default=Path.home() / "assetforge-ai" / "ComfyUI" / "models")
    ap.add_argument("--images", type=Path)
    ap.add_argument("--from-procedural", type=int, default=0)
    ap.add_argument("--profiles", nargs="+", default=["stylized_standard"])
    ap.add_argument("--blender", default=None)
    args = ap.parse_args()
    blender = args.blender or find_blender()
    if not blender:
        print("Blender não encontrado (--blender)", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    prov = IntelAIProvider(args.comfy_url, models_dir=args.models_dir)
    health = prov.health()
    if not health.ready:
        print("node não está pronto:", health.as_dict(), file=sys.stderr)
        return 2

    refs: list[tuple[str, Path, Path | None, str]] = []  # name, reference, procedural thumbnail, category
    tmp = Path(tempfile.mkdtemp(prefix="afbench-ai-"))
    for i in range(args.from_procedural):
        cat = CATS[i % len(CATS)]
        wd = tmp / f"proc{i}"
        run_building_job(dict(asset_id=f"ast_p{i}", name=f"proc {i}", version=1, job_id="p", formats=["glb"], params=dict(category=cat, style="classic", seed=i + 1, detail=2)),
                         wd, lambda e: None, engine="auto", blender_bin=blender)
        refs.append((f"{cat}-{i + 1}", wd / "out" / "thumbnail.png", wd / "out" / "thumbnail.png", cat))
    if args.images:
        refs += [(p.stem, p, None, "prop") for p in sorted(args.images.glob("*")) if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
    rows: list[dict] = []
    for profile in args.profiles:
        sheet_tiles = []
        for name, ref, proc, cat in refs:
            wd = tmp / f"ai-{profile}-{name}"
            job = {"job_id": "b", "asset_id": "ast_bench", "name": name, "version": 1, "job_type": "ai.image_to_3d", "quality_profile": profile,
                   "formats": ["glb"], "reference_path": str(ref), "thumbnail_size": 384, "thumbnail_samples": 12,
                   "params": {"category": cat, "reference_id": "ref_000000000000", "target_size_m": 8.0, "lod_ratios": [0.5, 0.25, 0.1]}}
            t0 = time.monotonic()
            try:
                res = run_ai_job(job, wd, lambda e: None, prov, blender_bin=blender)
                m = res["manifest"]
                st = m["generation_params"]["ai"]["stages"]["image_to_3d"]
                rows.append({"profile": profile, "name": name, "ok": True, "seconds": round(time.monotonic() - t0, 1), "gen_seconds": st["seconds"],
                             "peak_vram_mb": st["peak_vram_mb"], "vram_total_mb": st["vram_total_mb"], "triangles_lods": [x["triangles"] for x in m["lods"]],
                             "raw_triangles": m["generation_params"]["raw_triangles"], "warnings": [c["name"] for c in res["validation"]["checks"] if c["status"] == "warn"]})
                tiles = [Image.open(ref).convert("RGB").resize((384, 384)), Image.open(wd / "out" / "thumbnail.png").convert("RGB").resize((384, 384))]
                tiles += [Image.open(proc).convert("RGB").resize((384, 384))] if proc else []
                sheet_tiles.append((name, tiles))
            except Exception as exc:  # noqa: BLE001
                rows.append({"profile": profile, "name": name, "ok": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
            print(rows[-1])
        if sheet_tiles:
            cols = max(len(t) for _, t in sheet_tiles)
            sheet = Image.new("RGB", (384 * cols, 408 * len(sheet_tiles)), "white")
            d = ImageDraw.Draw(sheet)
            for r, (name, tiles) in enumerate(sheet_tiles):
                for c, t in enumerate(tiles):
                    sheet.paste(t, (c * 384, r * 408 + 24))
                d.text((6, r * 408 + 6), f"{name}  |  referência  →  IA ({profile})" + ("  →  procedural" if cols == 3 else ""), fill="black")
            sheet.save(args.out / f"comparison_{profile}.png")
    summary = {"machine": platform.node(), "gpu": [g["name"] for g in health.xpu_devices], "rows": rows}
    (args.out / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    md = ["| perfil | asset | ok | s total | s IA | pico VRAM (MB) | tris LOD0..N | avisos |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['profile']} | {r['name']} | {'✅' if r['ok'] else '❌ ' + r.get('error', '')[:60]} | {r.get('seconds', '')} | {r.get('gen_seconds', '')} | {r.get('peak_vram_mb', '')}/{r.get('vram_total_mb', '')} | {r.get('triangles_lods', '')} | {','.join(r.get('warnings', []))} |")
    (args.out / "results.md").write_text("\n".join(md), encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    print("\n".join(md))
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
