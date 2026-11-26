"""Optional weight quantisation of the vision model on CPU. Measured on the 206 (Zen2, no bf16/AVX512): fp32 0.81 tok/s; bf16 unusable (stalls);
int8 on EVERYTHING 4.2 tok/s but the model stops following the prompt; int8 only on the language-model blocks 2.7 tok/s and half the RAM."""

from __future__ import annotations

from typing import Any

MODES = ("fp32", "int8lm")


def apply_quant(model: Any, mode: str) -> Any:
    if mode == "fp32":
        return model
    if mode != "int8lm":
        raise ValueError(f"unknown quantisation mode {mode!r}; use one of {MODES}")
    import torch

    layers = model.model.layers if hasattr(model.model, "layers") else model.model.language_model.layers
    for i, layer in enumerate(layers):  # vision tower, embeddings and lm_head stay fp32
        layers[i] = torch.ao.quantization.quantize_dynamic(layer, {torch.nn.Linear}, dtype=torch.qint8)
    return model
