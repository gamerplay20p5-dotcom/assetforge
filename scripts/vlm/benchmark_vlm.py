#!/usr/bin/env python3
"""Real benchmark of Qwen2.5-VL on CPU: read the finished image of each house -> JSON description -> compare with the ground truth.

    (inside the vlm container)
    python scripts/vlm/benchmark_vlm.py --model Qwen/Qwen2.5-VL-3B-Instruct --images /refs --out /out --threads 20 --max-side 640

Records, per image: wall time (load / prefill+generate), generated tokens, peak RSS of the process, mean/peak CPU of the process, the raw
answer, the parsed description and the per-field hits. Nothing is estimated.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "generators" / "vision"))

import psutil  # noqa: E402
from assetforge_vision import TRUTH  # noqa: E402
from assetforge_vision.evaluate import compare, score  # noqa: E402
from assetforge_vision.prompt import SYSTEM, USER, USER_ANALYSIS  # noqa: E402
from assetforge_vision.schema import DescriptionError, extract_json, parse_analysis, parse_description  # noqa: E402


class Sampler:
    def __init__(self) -> None:
        self.p = psutil.Process()
        self.peak_rss = 0
        self.cpu: list[float] = []
        self.stop = threading.Event()
        self.t = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        self.p.cpu_percent(None)
        while not self.stop.wait(1.0):
            self.peak_rss = max(self.peak_rss, self.p.memory_info().rss)
            self.cpu.append(self.p.cpu_percent(None))

    def __enter__(self):
        self.t.start()
        return self

    def __exit__(self, *a):
        self.stop.set()
        self.t.join(2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--images", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--threads", type=int, default=20)
    ap.add_argument("--max-side", type=int, default=640)
    ap.add_argument("--max-new-tokens", type=int, default=420)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--task", choices=["house", "analysis"], default="house")
    ap.add_argument("--extra", type=Path, default=None, help="folder of <category>__name.png images: only the category is checked")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    import torch
    from PIL import Image
    from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

    torch.set_num_threads(args.threads)
    t0 = time.monotonic()
    with Sampler() as load_s:
        processor = AutoProcessor.from_pretrained(args.model, min_pixels=128 * 28 * 28, max_pixels=args.max_side * args.max_side)
        model = Qwen2_5_VLForConditionalGeneration.from_pretrained(args.model, torch_dtype=torch.float32, low_cpu_mem_usage=True).eval()
    load_s_total = time.monotonic() - t0
    print(f"loaded {args.model} in {load_s_total:.0f}s, peak RSS {load_s.peak_rss / 2**30:.1f} GB", flush=True)

    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    jobs = [(key, args.images / key / "06_casa_finalizada.png", "house") for key in sorted(TRUTH) if not args.only or key in args.only]
    if args.extra:
        jobs += [(p.stem, p, p.stem.split("__")[0]) for p in sorted(args.extra.glob("*.png"))]
    for key, img_path, expect_cat in jobs:
        img = Image.open(img_path).convert("RGB")
        if key in TRUTH:  # the pack images have empty margins
            img = img.crop((int(img.width * 0.06), int(img.height * 0.09), int(img.width * 0.94), int(img.height * 0.88)))
        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": [{"type": "image", "image": img}, {"type": "text", "text": USER_ANALYSIS if args.task == "analysis" else USER}]}]
        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = processor(text=[text], images=[img], return_tensors="pt")
        n_in = int(inputs["input_ids"].shape[1])
        t1 = time.monotonic()
        with Sampler() as smp, torch.inference_mode():
            gen = model.generate(**inputs, max_new_tokens=args.max_new_tokens, do_sample=False)
        dt = time.monotonic() - t1
        new = gen[:, n_in:]
        answer = processor.batch_decode(new, skip_special_tokens=True)[0]
        row = dict(house=key, input_tokens=n_in, new_tokens=int(new.shape[1]), seconds=round(dt, 1), peak_rss_gb=round(smp.peak_rss / 2**30, 1),
                   cpu_mean_percent=round(sum(smp.cpu) / max(1, len(smp.cpu))), cpu_peak_percent=round(max(smp.cpu or [0])), answer=answer)
        try:
            raw = extract_json(answer)
            if args.task == "analysis":
                an = parse_analysis(raw)
                cat_ok = an.category == expect_cat
                row.update(category=an.category, subject=an.subject, isolated_object=an.isolated_object)
                if key in TRUTH and an.house is not None:
                    pred = an.house
                    res = compare(pred, TRUTH[key], present=set(raw.get("house") or {}))
                else:
                    pred, res = None, {}
                res = {"category": dict(ok=cat_ok, pred=an.category, truth=expect_cat), **res}
                hit, tot = score(res)
                row.update(valid=True, parsed=pred.to_dict() if pred else None, hits=hit, total=tot, fields=res)
            else:
                pred = parse_description(raw)
                res = compare(pred, TRUTH[key], present=set(raw))
                hit, tot = score(res)
                row.update(valid=True, parsed=pred.to_dict(), hits=hit, total=tot, fields=res)
        except DescriptionError as exc:
            row.update(valid=False, error=str(exc), hits=0, total=0)
        rows.append(row)
        print(f"{key}: {row['seconds']}s tokens={row['new_tokens']} valid={row['valid']} hits={row.get('hits')}/{row.get('total')}", flush=True)
        (args.out / f"{Path(args.model).name}{args.tag}.json").write_text(json.dumps(dict(model=args.model, host=platform.node(), threads=args.threads, max_side=args.max_side,
                                                                              load_seconds=round(load_s_total), load_peak_rss_gb=round(load_s.peak_rss / 2**30, 1),
                                                                              torch=torch.__version__, rows=rows), indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
