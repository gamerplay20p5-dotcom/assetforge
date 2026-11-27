#!/usr/bin/env python3
"""Compare renders with the original reference using the central Gemini pool (inside the API container),
or with GEMINI_API_KEY from the environment.

    python gemini_compare.py --ref ref.png --label "LOD0 15k" --views front_left=a.png front_right=b.png back=c.png aerial=d.png --out result.json [--db]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

for d in ("apps/api", "generators/vision", "/app/apps/api", "/app/generators/vision"):
    sys.path.insert(0, d)

from assetforge_api.ai.providers import make_provider, pick_model  # noqa: E402
try:
    from assetforge_vision import compare  # noqa: E402
except ImportError:  # running from a bare folder next to compare.py (e.g. a throw-away container)
    import importlib.util

    _spec = importlib.util.spec_from_file_location("compare", Path(__file__).with_name("compare.py"))
    compare = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(compare)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", type=Path, required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--views", nargs="+", required=True, help="name=path ...")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--db", action="store_true", help="use the central AI pool inside the API container")
    ap.add_argument("--extra", default="")
    a = ap.parse_args()
    names, imgs = [], [(a.ref.read_bytes(), "image/png")]
    for v in a.views:
        n, p = v.split("=", 1)
        names.append(n)
        imgs.append((Path(p).read_bytes(), "image/png"))
    prompt = compare.compare_prompt(names, a.label, a.extra)
    started = time.monotonic()
    cached = False
    if a.db:
        from assetforge_api.ai.router import AiRejected, AiRouter, NoKeyAvailable
        from assetforge_api.config import get_settings
        from assetforge_api.db import Database

        settings = get_settings()
        with Database(settings.database_url).session() as db:
            try:
                answer = AiRouter(db, settings.resolved_secret()).generate_json(
                    "asset.visual_review", compare.SYSTEM, prompt, imgs, compare.COMPARE_SCHEMA,
                    compare.PROMPT_VERSION, provider="gemini",
                )
            except NoKeyAvailable as exc:
                print("Gemini pool unavailable; consult central AI usage.", file=sys.stderr)
                if exc.retry_at:
                    print(f"Retry after {exc.retry_at.isoformat()}", file=sys.stderr)
                return 75
            except AiRejected:
                print("Gemini rejected the evaluation; consult central AI usage.", file=sys.stderr)
                return 1
        model, tokens, data, cached = answer.model, answer.total_tokens, answer.data, answer.cached
    else:
        prov = make_provider("gemini", os.environ["GEMINI_API_KEY"])
        model = pick_model("gemini", [m["name"] for m in prov.list_models()])
        result = prov.generate_json(model, compare.SYSTEM, prompt, imgs, compare.COMPARE_SCHEMA)
        tokens, data = result.total_tokens, result.data
    out = {"label": a.label, "model": model, "tokens": tokens, "cached": cached,
           "seconds": round(time.monotonic() - started, 1), **compare.clean(data)}
    a.out.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("label", "overall", "verdict")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
