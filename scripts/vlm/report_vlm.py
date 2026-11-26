#!/usr/bin/env python3
"""Turn the benchmark JSON files into a Markdown report (time, RAM, CPU, per-field accuracy, house by house).

    python scripts/vlm/report_vlm.py --in reports_out/vlm --out reports_out/vlm/results.md
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def fmt(v) -> str:
    return json.dumps(v, ensure_ascii=False) if isinstance(v, list) else str(v)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    md: list[str] = []
    for f in sorted(args.src.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        rows = d["rows"]
        md += [f"## {d['model']}", "", f"torch {d['torch']} · {d['threads']} threads · imagem até {d['max_side']}² px · carga {d['load_seconds']} s · RAM na carga {d['load_peak_rss_gb']} GB", "",
               "| casa | tempo | tokens gerados | RAM pico | CPU média / pico | JSON válido | acertos |", "|---|---|---|---|---|---|---|"]
        per_field: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        hit_total = tot_total = 0
        for r in rows:
            md.append(f"| {r['house']} | {r['seconds']} s | {r['new_tokens']} | {r['peak_rss_gb']} GB | {r['cpu_mean_percent']}% / {r['cpu_peak_percent']}% | "
                      f"{'sim' if r['valid'] else 'NÃO'} | {r['hits']}/{r['total']} |")
            hit_total += r["hits"]
            tot_total += r["total"]
            for k, v in (r.get("fields") or {}).items():
                per_field[k][1] += 1
                per_field[k][0] += int(v["ok"])
        secs = [r["seconds"] for r in rows]
        md += ["", f"**Total:** {hit_total}/{tot_total} campos corretos ({100 * hit_total / max(1, tot_total):.0f}%) · tempo médio {sum(secs) / max(1, len(secs)):.0f} s por imagem", "",
               "Acerto por campo:", "", "| campo | acertos |", "|---|---|"]
        for k, (h, t) in sorted(per_field.items(), key=lambda kv: kv[1][0] / max(1, kv[1][1])):
            md.append(f"| {k} | {h}/{t} |")
        md += ["", "Erros, casa por casa (previsto → esperado):", ""]
        for r in rows:
            if not r["valid"]:
                md.append(f"- **{r['house']}**: resposta inválida ({r.get('error')})")
                continue
            bad = [f"{k}: {fmt(v['pred'])} → {fmt(v['truth'])}{' (ausente)' if v.get('missing') else ''}" for k, v in r["fields"].items() if not v["ok"]]
            md.append(f"- **{r['house']}**: " + ("; ".join(bad) if bad else "tudo certo"))
        md.append("")
    args.out.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
