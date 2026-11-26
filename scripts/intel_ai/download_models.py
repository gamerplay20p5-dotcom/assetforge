#!/usr/bin/env python3
"""Baixa (ou apenas lista/verifica) os modelos dos workflows da Intel, com SHA-256 e licenças.

    python3 scripts/intel_ai/download_models.py --models-dir ~/assetforge-ai/ComfyUI/models --list
    python3 scripts/intel_ai/download_models.py --models-dir ... --accept-licenses
    python3 scripts/intel_ai/download_models.py --models-dir ... --verify

Baixar é uma ação explícita: sem --accept-licenses o script só mostra a tabela de licenças e sai. Depois de baixado,
tudo funciona offline. Respeite o espaço em disco (o Pixal3D int8 sozinho tem ~5,6 GB; veja --list).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # consoles Windows (cp1252)
ROOT = Path(__file__).resolve().parents[2]
for d in ("generators/intel_ai", "generators/procedural", "packages/asset-contract"):
    sys.path.insert(0, str(ROOT / d))

from assetforge_intel_ai import ModelStore, required_specs  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models-dir", required=True, type=Path)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--accept-licenses", action="store_true", help="confirmo que li e aceito as licenças listadas")
    ap.add_argument("--only", choices=["image_to_3d", "text_to_image"], action="append")
    args = ap.parse_args()
    caps = tuple(args.only) if args.only else ("image_to_3d", "text_to_image")
    specs = required_specs(caps)
    store = ModelStore(args.models_dir)
    print(f"{'modelo':92} {'presente':8} licença / uso comercial (Brasil)")
    for row in store.status(specs):
        flag = {"ok": "ok", "verify": "VERIFICAR"}.get(row["commercial_br"], row["commercial_br"])
        print(f"{row['key'][:92]:92} {'sim' if row['present'] else 'não':8} {row['license']} [{flag}]")
        if row["note"]:
            print(f"{'':101}↳ {row['note']}")
    if args.list or (not args.accept_licenses and not args.verify):
        print("\nNada foi baixado. Use --accept-licenses para baixar os modelos ausentes.")
        return 0
    if args.verify:
        bad = [s.key for s in specs if s.local_path(args.models_dir).is_file() and not store.verify(s)]
        print("verificação SHA-256:", "ok" if not bad else f"FALHOU em {bad}")
        return 1 if bad else 0
    for s in store.missing(specs):
        print(f"baixando {s.key} …")
        last = [0.0]

        def prog(done: int, total: int | None) -> None:
            if total and done / total - last[0] >= 0.05:
                last[0] = done / total
                print(f"  {done / total:5.0%}", flush=True)

        store.download(s, prog)
        print("  verificado.")
    print("pronto.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
