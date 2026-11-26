#!/usr/bin/env python3
"""Measure what really speeds up the CPU vision model: weight dtype (fp32 / bf16 / int8 dynamic quantisation), tokens per second.

    python scripts/vlm/speed_probe.py --model Qwen/Qwen2.5-VL-7B-Instruct --image /refs/<house>/06_casa_finalizada.png --mode fp32|bf16|int8 --tokens 40
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "generators" / "vision"))

import psutil  # noqa: E402
from assetforge_vision.prompt import SYSTEM, USER_ANALYSIS  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--image", type=Path, required=True)
    ap.add_argument("--mode", choices=["fp32", "bf16", "int8", "int8lm"], default="fp32")
    ap.add_argument("--tokens", type=int, default=40)
    ap.add_argument("--threads", type=int, default=20)
    a = ap.parse_args()
    import torch
    from PIL import Image
    from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

    torch.set_num_threads(a.threads)
    t0 = time.monotonic()
    proc = AutoProcessor.from_pretrained(a.model, min_pixels=128 * 28 * 28, max_pixels=640 * 640)
    dtype = torch.bfloat16 if a.mode == "bf16" else torch.float32
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(a.model, torch_dtype=dtype, low_cpu_mem_usage=True).eval()
    if a.mode == "int8":
        model = torch.ao.quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8)
    elif a.mode == "int8lm":  # only the decoder blocks of the language model; vision tower, embeddings and lm_head stay fp32
        lm = model.model.layers if hasattr(model.model, "layers") else model.model.language_model.layers
        for i, layer in enumerate(lm):
            lm[i] = torch.ao.quantization.quantize_dynamic(layer, {torch.nn.Linear}, dtype=torch.qint8)
    load = time.monotonic() - t0
    img = Image.open(a.image).convert("RGB")
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": [{"type": "image", "image": img}, {"type": "text", "text": USER_ANALYSIS}]}]
    text = proc.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    inp = proc(text=[text], images=[img], return_tensors="pt")
    n_in = int(inp["input_ids"].shape[1])
    with torch.inference_mode():
        t1 = time.monotonic()
        model.generate(**inp, max_new_tokens=1, do_sample=False)  # prefill (+1 token)
        pre = time.monotonic() - t1
        t2 = time.monotonic()
        out = model.generate(**inp, max_new_tokens=a.tokens, do_sample=False)
        total = time.monotonic() - t2
    n_new = int(out.shape[1] - n_in)
    decode = max(total - pre, 1e-6)
    print(f"RESULT mode={a.mode} load={load:.0f}s prompt_tokens={n_in} prefill={pre:.1f}s new_tokens={n_new} decode={decode:.1f}s "
          f"-> {max(n_new - 1, 1) / decode:.2f} tok/s  rss={psutil.Process().memory_info().rss / 2**30:.1f}GB")
    print("TEXT", proc.batch_decode(out[:, n_in:], skip_special_tokens=True)[0][:160].replace("\n", " "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
