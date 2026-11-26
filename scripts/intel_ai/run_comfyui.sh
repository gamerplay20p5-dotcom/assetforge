#!/usr/bin/env bash
# Sobe o ComfyUI headless (sem interface desktop do AI Playground), SOMENTE em loopback.
#   COMFY_HOME=~/assetforge-ai/ComfyUI ./scripts/intel_ai/run_comfyui.sh
# Parâmetros: os mesmos do AI Playground (--lowvram, --use-quad-cross-attention exigido pelo preset Pixel3D-Trellis).
# O --reserve-vram padrão do AI Playground é 6.0; numa Arc A750 de 8 GB isso deixaria ~2 GB úteis, então aqui o padrão
# é 1.0 e DEVE ser calibrado na validação (COMFY_RESERVE_VRAM). Esse valor é uma escolha NÃO validada.
set -euo pipefail
COMFY_HOME="${COMFY_HOME:-$HOME/assetforge-ai/ComfyUI}"
PORT="${COMFY_PORT:-8188}"
RESERVE="${COMFY_RESERVE_VRAM:-1.0}"
cd "$COMFY_HOME"
# Mesmas bibliotecas oneAPI que o AI Playground prepende (compiler/latest/lib fica de fora de propósito: quebra o ze_loader).
for d in /opt/intel/oneapi/mkl/latest/lib /opt/intel/oneapi/mkl/latest/lib/intel64 /opt/intel/oneapi/tbb/latest/lib \
         /opt/intel/oneapi/tbb/latest/lib/intel64/gcc4.8 /usr/lib/x86_64-linux-gnu; do
  [[ -d "$d" ]] && export LD_LIBRARY_PATH="$d:${LD_LIBRARY_PATH:-}"
done
# shellcheck disable=SC2086
exec .venv/bin/python main.py --listen 127.0.0.1 --port "$PORT" --disable-auto-launch \
  --lowvram --reserve-vram "$RESERVE" --use-quad-cross-attention ${COMFY_EXTRA_ARGS:-}
