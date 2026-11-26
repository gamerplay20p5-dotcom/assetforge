#!/usr/bin/env python3
"""Benchmark REAL dos providers CPU (Stable Fast 3D e TripoSR) com as SUAS imagens de referência, com comparação visual.

    (no container, via scripts/intel_ai/docker_tasks.sh cpu3d-benchmark ./minhas_referencias stylized_standard)
    python scripts/cpu3d/benchmark_cpu3d.py --images /refs --out /bench --profiles stylized_standard prototype [--providers sf3d triposr]

Para cada imagem x provider x perfil roda o pipeline COMPLETO (provider -> Blender: escala/pivo, reducao de poligonos, LODs, FBX/BLEND,
miniaturas) e mede tempo, pico de RAM/CPU do provider, pico de RAM/temperatura do host. Gera results.json, results.md e
comparison_<perfil>.png (linhas = imagens; colunas = referencia | cada provider ANTES da otimizacao | DEPOIS). Nada e estimado.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
import tempfile
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[2]
for d in ("workers/cpu", "generators/procedural", "generators/intel_ai", "generators/mesh", "pipeline/export", "pipeline/validation",
          "pipeline/optimization", "packages/asset-contract"):
    sys.path.insert(0, str(ROOT / d))

from assetforge_cpu3d import CpuProvider, parse_providers_env  # noqa: E402
from assetforge_export.ai_pipeline import run_ai_job  # noqa: E402
from assetforge_export.hostmon import HostSampler  # noqa: E402
from assetforge_export.pipeline import find_blender  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--profiles", nargs="+", default=["stylized_standard"])
    ap.add_argument("--providers", nargs="+", default=["sf3d", "triposr"])
    ap.add_argument("--category", default="prop")
    ap.add_argument("--size-m", type=float, default=3.0)
    ap.add_argument("--max-triangles", type=int, default=None)
    ap.add_argument("--blender", default=None)
    args = ap.parse_args()
    blender = args.blender or find_blender()
    urls = parse_providers_env(os.environ.get("ASSETFORGE_CPU3D_PROVIDERS", ""))
    if not blender:
        print("Blender nao encontrado", file=sys.stderr)
        return 2
    provs: dict[str, CpuProvider] = {}
    for n in args.providers:
        if n not in urls:
            print(f"[{n}] nao configurado em ASSETFORGE_CPU3D_PROVIDERS - ignorado")
            continue
        p = CpuProvider(n, urls[n])
        h = p.health()
        if h.get("ready"):
            provs[n] = p
        else:
            print(f"[{n}] NAO pronto: {h.get('reason')} - ignorado")
    if not provs:
        print("nenhum provider pronto", file=sys.stderr)
        return 2
    images = sorted(p for p in args.images.glob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))
    args.out.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    tmp = Path(tempfile.mkdtemp(prefix="afcpu3d-"))
    for profile in args.profiles:
        sheet: list[tuple[str, Path, dict[str, tuple[Path | None, Path | None]]]] = []
        for img in images:
            cells: dict[str, tuple[Path | None, Path | None]] = {}
            for name, prov in provs.items():
                wd = tmp / f"{img.stem}-{name}-{profile}"
                params = {"provider": name, "category": args.category, "reference_id": "ref_000000000000", "target_size_m": args.size_m,
                          "lod_ratios": [0.5, 0.25, 0.1]}
                if args.max_triangles:
                    params["max_triangles"] = args.max_triangles
                job = {"job_id": f"bench-{img.stem}-{name}", "asset_id": "ast_bench", "name": img.stem, "version": 1, "job_type": "ai.image_to_3d",
                       "quality_profile": profile, "formats": ["glb", "fbx", "blend"], "reference_path": str(img), "thumbnail_size": 384,
                       "thumbnail_samples": 12, "params": params}
                t0 = time.monotonic()
                row: dict = {"profile": profile, "image": img.name, "provider": name}
                try:
                    with HostSampler() as host:
                        res = run_ai_job(job, wd, lambda e: None, prov, blender_bin=blender, threads=4)
                    m = res["manifest"]
                    st = m["generation_params"]["ai"]["stages"]["image_to_3d"]
                    keep = args.out / img.stem / f"{name}_{profile}"
                    keep.mkdir(parents=True, exist_ok=True)
                    for f in res["files"]:
                        if f["format"] in ("glb", "fbx", "blend", "png") and "/" not in f["name"]:
                            shutil.copyfile(wd / "out" / f["name"], keep / f["name"])
                    row.update(ok=True, total_seconds=round(time.monotonic() - t0, 1), provider_seconds=st["seconds"],
                               provider_peak_ram_mb=st["peak_ram_mb"], provider_peak_cpu_percent=st["peak_cpu_percent"],
                               host_peak_ram_mb=host.peak_ram_mb, host_peak_temp_c=host.peak_temp_c, color=st["color"],
                               bake_fallback=st.get("bake_fallback"), raw_triangles=m["generation_params"]["raw_triangles"],
                               lod_triangles=[x["triangles"] for x in m["lods"]], materials=len(m["materials"]),
                               warnings=[c["name"] for c in res["validation"]["checks"] if c["status"] == "warn"])
                    cells[name] = (wd / "out" / "preview_raw.png", wd / "out" / "thumbnail.png")
                except Exception as exc:  # noqa: BLE001
                    row.update(ok=False, error=f"{type(exc).__name__}: {str(exc)[:300]}")
                    cells[name] = (None, None)
                rows.append(row)
                print(row, flush=True)
            sheet.append((img.stem, img, cells))
        if sheet:
            cols, tile = 1 + 2 * len(provs), 320
            im = Image.new("RGB", (tile * cols, (tile + 22) * len(sheet) + 22), "white")
            d = ImageDraw.Draw(im)
            heads = ["referencia"] + [f"{n} {w}" for n in provs for w in ("ANTES (bruto)", "DEPOIS (otimizado)")]
            for c, h in enumerate(heads):
                d.text((c * tile + 6, 4), f"{h} | {profile}", fill="black")
            for r, (stem, ref, cells) in enumerate(sheet):
                y = 22 + r * (tile + 22)
                im.paste(Image.open(ref).convert("RGB").resize((tile, tile)), (0, y))
                c = 1
                for n in provs:
                    for k in cells.get(n, (None, None)):
                        if k and Path(k).is_file():
                            im.paste(Image.open(k).convert("RGB").resize((tile, tile)), (c * tile, y))
                        c += 1
                d.text((6, y + tile + 4), stem, fill="black")
            im.save(args.out / f"comparison_{profile}.png")
    (args.out / "results.json").write_text(json.dumps({"machine": platform.node(), "rows": rows}, indent=2), encoding="utf-8")
    md = ["| perfil | imagem | provider | ok | s total | s provider | RAM pico MB | CPU pico % | cor | tris bruto -> LODs | avisos |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        status = "ok" if r["ok"] else "FALHOU " + r.get("error", "")[:70]
        md.append(f"| {r['profile']} | {r['image']} | {r['provider']} | {status} | {r.get('total_seconds', '')} | {r.get('provider_seconds', '')} | "
                  f"{r.get('provider_peak_ram_mb', '')} | {r.get('provider_peak_cpu_percent', '')} | {r.get('color', '')} | "
                  f"{r.get('raw_triangles', '')} -> {r.get('lod_triangles', '')} | {','.join(r.get('warnings', []))} |")
    (args.out / "results.md").write_text("\n".join(md), encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    print("\n".join(md))
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
