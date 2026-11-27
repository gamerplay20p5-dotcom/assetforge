#!/usr/bin/env python3
"""Benchmark: cloud AI agent (Gemini / Grok) vs Qwen2.5-VL (local) vs the hand-written kit specs, side by side.

    set GEMINI_API_KEY=...   (read from the environment only; never printed, never written)
    python scripts/ai/benchmark_cloud.py --out reports_out/cloud_bench \
        --case ref01=path/to/ref01.png:ref01 --case tower=images/7.png:ref_tower \
        [--qwen-json reports_out/vlm/Qwen2.5-VL-7B-Instruct.json] [--provider gemini --model gemini-2.5-flash] [--iterations 2] [--judge]

For every case it renders, from the same camera: the reference | the hand-written kit spec (if given) | Qwen's description mapped onto the kit
(if a prediction exists for that case) | the cloud agent's best spec. ``--judge`` also asks the cloud model to score the other two columns with
the same critique prompt (one extra request each). The scores are the model's own opinion: the visual sheet is what decides.
A valid JSON is not counted as quality.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for d in ("apps/api", "generators/procedural", "generators/vision", "pipeline/export", "pipeline/validation", "pipeline/optimization",
          "packages/asset-contract", "generators/mesh", "generators/intel_ai"):
    sys.path.insert(0, str(ROOT / d))

from assetforge_api.ai.providers import make_provider, pick_model  # noqa: E402
from assetforge_export.agent_pipeline import _render, run_agent_job  # noqa: E402
from assetforge_procedural.house import ARCHETYPES, generate_house  # noqa: E402
from assetforge_vision import llm_spec  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

KEY_ENV = {"gemini": "GEMINI_API_KEY", "grok": "XAI_API_KEY"}


def _mime(p: Path) -> str:
    return "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else "image/png"


def _blender() -> str:
    env = os.environ.get("BLENDER_BIN")
    if env:
        return env
    found = next((ROOT / ".tools" / "blender").rglob("blender.exe"), None) or next((ROOT / ".tools" / "blender").rglob("blender"), None)
    if not found:
        sys.exit("Blender not found (set BLENDER_BIN)")
    return str(found)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--case", action="append", required=True, help="name=image[:archetype]")
    ap.add_argument("--qwen-json", type=Path)
    ap.add_argument("--provider", default="gemini", choices=sorted(KEY_ENV))
    ap.add_argument("--model", default="")
    ap.add_argument("--iterations", type=int, default=2)
    ap.add_argument("--target", type=float, default=8.0)
    ap.add_argument("--judge", action="store_true")
    args = ap.parse_args()
    key = os.environ.get(KEY_ENV[args.provider], "")
    if not key:
        sys.exit(f"set {KEY_ENV[args.provider]} in the environment")
    prov = make_provider(args.provider, key)
    model = args.model or pick_model(args.provider, [m["name"] for m in prov.list_models()]) or sys.exit("no known model for this key")
    blender = _blender()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    qwen = {}
    if args.qwen_json:
        qwen = {r["house"]: r for r in json.loads(args.qwen_json.read_text(encoding="utf-8"))["rows"] if r.get("valid")}
    report: list[dict] = []
    tiles: list[list[tuple[str, Path | None, str]]] = []

    for case in args.case:
        name, rest = case.split("=", 1)
        img_s, arch = rest, ""
        head, sep, tail = rest.rpartition(":")  # optional ":archetype" suffix (paths may contain a drive letter)
        if sep and tail in ARCHETYPES:
            img_s, arch = head, tail
        img = Path(img_s).resolve()
        refs = [(img.read_bytes(), _mime(img))]
        d = out / name
        stats = {"calls": 0, "tokens": 0, "seconds": 0.0}

        def ai(body: dict) -> dict:
            if body["task"] == "spec":
                prompt, schema, images = llm_spec.spec_prompt(1, body.get("category_hint", ""), body.get("validation_error", ""), body.get("previous")), \
                    llm_spec.SPEC_SCHEMA, refs
            else:
                import base64

                renders = [(base64.b64decode(b), "image/png") for b in body["renders_b64"]]
                prompt, schema, images = llm_spec.critique_prompt(1, len(renders), body["spec"], body["iteration"]), llm_spec.CRITIQUE_SCHEMA, refs + renders
            t0 = time.monotonic()
            r = prov.generate_json(model, llm_spec.SYSTEM, prompt, images, schema)
            stats["calls"] += 1
            stats["tokens"] += r.total_tokens
            stats["seconds"] += time.monotonic() - t0
            return {"data": r.data, "provider": args.provider, "model": model, "total_tokens": r.total_tokens}

        job = dict(asset_id=f"ast_bench_{name}"[:24], name=name, version=1, job_id=f"bench_{name}", job_type="agent.building", quality_profile="stylized_detailed",
                   formats=["glb"], thumbnail_size=256, thumbnail_samples=8,
                   params={"reference_ids": ["ref_000000000000"], "category": "house", "max_iterations": args.iterations, "target_score": args.target,
                           "texture_resolution": 1024})
        row: dict = {"case": name, "image": str(img), "provider": args.provider, "model": model}
        cloud_img = None
        try:
            run_agent_job(job, d / "agent_run", lambda e: print(e.get("message", ""), flush=True) if e.get("type") == "log" else None, ai,
                          blender_bin=blender)
            hist = json.loads((d / "agent_run" / "out" / "agent" / "history.json").read_text(encoding="utf-8"))
            best = max(hist["rounds"], key=lambda r: r["score"])
            cloud_img = d / "agent_run" / best["renders"][1]  # front_right
            row.update(cloud_best_score=hist["best_score"], cloud_rounds=[{"score": r["score"], "issues": r["issues"][:5]} for r in hist["rounds"]], **stats)
        except Exception as exc:  # noqa: BLE001 - a failed case is reported, not hidden
            row.update(cloud_error=f"{type(exc).__name__}: {exc}"[:500], **stats)

        def judge(gen, label: str) -> tuple[Path, float | None]:
            renders = _render(gen, d / label, blender)
            score = None
            if args.judge:
                import base64

                spec_json = {"note": f"{label} spec (not produced by you)", "summary": gen.summary.get("spec", {})}
                crit = ai({"task": "critique", "renders_b64": [base64.b64encode(p.read_bytes()).decode() for p in renders], "spec": spec_json, "iteration": 0})
                score = float(crit["data"].get("score", 0))
            return renders[1], score

        kit_img = qwen_img = None
        if arch:
            kit_img, row["kit_score"] = judge(generate_house(ARCHETYPES[arch](1), 6), "kit")
        if name in qwen:
            from assetforge_vision.mapper import description_to_spec
            from assetforge_vision.schema import parse_description

            qwen_img, row["qwen_score"] = judge(generate_house(description_to_spec(parse_description(qwen[name]["parsed"])), 6), "qwen")
        report.append(row)
        tiles.append([("Referência", img, ""), ("Kit (Claude)", kit_img, f"{row.get('kit_score', '')}"), ("Qwen 7B", qwen_img, f"{row.get('qwen_score', '')}"),
                      (f"{args.provider} agente", cloud_img, f"{row.get('cloud_best_score', row.get('cloud_error', ''))}")])
        print(json.dumps({k: v for k, v in row.items() if k != "cloud_rounds"}, ensure_ascii=False), flush=True)

    tw, th = 420, 420
    sheet = Image.new("RGB", (tw * 4, (th + 28) * len(tiles)), (32, 34, 38))
    draw = ImageDraw.Draw(sheet)
    for r, row_t in enumerate(tiles):
        for c, (label, path, score) in enumerate(row_t):
            x, y = c * tw, r * (th + 28)
            if path and Path(path).is_file():
                im = Image.open(path).convert("RGB")
                im.thumbnail((tw, th))
                sheet.paste(im, (x + (tw - im.width) // 2, y + 28 + (th - im.height) // 2))
            draw.text((x + 8, y + 6), f"{label}  {('nota ' + str(score)) if score not in ('', None) else ''}"[:60], fill=(235, 235, 235))
    sheet.save(out / "sheet.jpg", quality=90)
    (out / "results.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"sheet: {out / 'sheet.jpg'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
