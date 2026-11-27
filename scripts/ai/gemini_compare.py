#!/usr/bin/env python3
"""Compare renders with the original reference using the Gemini key stored in the AssetForge API (run INSIDE the api container, so the key never leaves
the server), or with GEMINI_API_KEY from the environment.

    python gemini_compare.py --ref ref.png --label "LOD0 15k" --views front_left=a.png front_right=b.png back=c.png aerial=d.png --out result.json [--db]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
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
    ap.add_argument("--db", action="store_true", help="use the key stored in the AssetForge database (inside the api container)")
    ap.add_argument("--extra", default="")
    a = ap.parse_args()
    if a.db:
        from assetforge_api.ai.crypto import decrypt
        from assetforge_api.config import get_settings
        from assetforge_api.db import Database
        from assetforge_api.models import AiKey

        s = get_settings()
        k = Database(s.database_url).session().query(AiKey).filter(AiKey.provider == "gemini", AiKey.enabled.is_(True)).order_by(AiKey.priority).first()
        prov, model = make_provider("gemini", decrypt(s.resolved_secret(), k.key_enc), k.base_url), k.model
    else:
        prov = make_provider("gemini", os.environ["GEMINI_API_KEY"])
        model = pick_model("gemini", [m["name"] for m in prov.list_models()])
    names, imgs = [], [(a.ref.read_bytes(), "image/png")]
    for v in a.views:
        n, p = v.split("=", 1)
        names.append(n)
        imgs.append((Path(p).read_bytes(), "image/png"))
    r = prov.generate_json(model, compare.SYSTEM, compare.compare_prompt(names, a.label, a.extra), imgs, compare.COMPARE_SCHEMA)
    out = {"label": a.label, "model": model, "tokens": r.total_tokens, "seconds": round(r.latency_ms / 1000, 1), **compare.clean(r.data)}
    a.out.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("label", "overall", "verdict")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
