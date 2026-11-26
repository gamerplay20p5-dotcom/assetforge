#!/usr/bin/env bash
# Serviço de visão em GPU numa caixa SÓ-GPU (ex.: a 203, RTX 4090), sem docker compose (só docker). Rode na própria caixa, na pasta do projeto.
#   ./scripts/vlm/gpu_box.sh build        constrói a imagem
#   ./scripts/vlm/gpu_box.sh download     baixa os pesos do Qwen2.5-VL 7B para o volume (precisa de internet)
#   ./scripts/vlm/gpu_box.sh up           liga o serviço (porta ${VLM_PORT:-8081}, exige o token de .env.gpu)
#   ./scripts/vlm/gpu_box.sh benchmark <pasta>   mede velocidade/acerto na GPU (pasta/<casa>/06_casa_finalizada.png)
#   ./scripts/vlm/gpu_box.sh triposr-build | triposr-download | triposr-up    TripoSR (image-to-3D) em GPU, porta ${TRIPOSR_PORT:-8082}, mesmo token
#   ./scripts/vlm/gpu_box.sh down | logs
# A máquina só fornece GPU: o container usa poucos núcleos e pouca RAM (VLM_GPU_CPUS / VLM_GPU_MEM).
set -euo pipefail
cd "$(dirname "$0")/../.."
[ -f .env.gpu ] && set -a && . ./.env.gpu && set +a
IMG=assetforge-vlm-gpu:local
VOL=assetforge-gpu_vlm-models
MODEL="${VLM_MODEL:-Qwen/Qwen2.5-VL-7B-Instruct}"
OUTDIR="$PWD/vlm_results"; mkdir -p -m 777 "$OUTDIR"   # criada pelo usuário (o Docker a criaria como root)
HARDEN=(--cap-drop ALL --security-opt no-new-privileges --pids-limit 512)
case "${1:-}" in
  build) docker build -f deployment/Dockerfile.vlm-gpu -t "$IMG" . ;;
  download)
    docker run --rm "${HARDEN[@]}" --cpus 4 -v "$VOL":/models --entrypoint python "$IMG" -c "from huggingface_hub import snapshot_download as s; print(s('$MODEL'))" ;;
  up)
    : "${VLM_TOKEN:?defina VLM_TOKEN em .env.gpu}"
    docker rm -f vlm-gpu >/dev/null 2>&1 || true
    docker run -d --name vlm-gpu --restart unless-stopped --gpus all "${HARDEN[@]}" \
      --cpus "${VLM_GPU_CPUS:-4}" --memory "${VLM_GPU_MEM:-12g}" --tmpfs /tmp:size=1g \
      -e VLM_MODEL="$MODEL" -e VLM_TOKEN="$VLM_TOKEN" -e VLM_MAX_SIDE="${VLM_MAX_SIDE:-640}" -e VLM_IDLE_UNLOAD_SECONDS="${VLM_IDLE_UNLOAD_SECONDS:-1800}" -e HF_HUB_OFFLINE=1 \
      -v "$VOL":/models -p "${VLM_BIND:-0.0.0.0}:${VLM_PORT:-8081}:8080" "$IMG" ;;
  benchmark)
    docker run --rm --gpus all "${HARDEN[@]}" --cpus "${VLM_GPU_CPUS:-4}" --memory "${VLM_GPU_MEM:-12g}" -e HF_HUB_OFFLINE=1 \
      -v "$VOL":/models -v "$(readlink -f "${2:?pasta com as imagens}")":/refs:ro -v "$OUTDIR":/out --entrypoint python "$IMG" \
      /app/scripts/vlm/benchmark_vlm.py --model "$MODEL" --images /refs --out /out --device cuda --task analysis --tag _gpu --max-new-tokens 520 "${@:3}" ;;
  triposr-build) docker build -f deployment/Dockerfile.triposr-gpu -t assetforge-triposr-gpu:local . ;;
  triposr-download)  # baixa os pesos (MIT) e roda uma inferência real de aquecimento NA GPU
    docker run --rm --gpus all "${HARDEN[@]}" --cpus 4 --memory "${VLM_GPU_MEM:-12g}" -v assetforge-gpu_triposr-models:/models --tmpfs /work:size=4g,uid=10004       -e HOME=/tmp assetforge-triposr-gpu:local python -m assetforge_cpu3d.download ;;
  triposr-up)
    : "${VLM_TOKEN:?defina VLM_TOKEN em .env.gpu}"
    docker rm -f triposr-gpu >/dev/null 2>&1 || true
    docker run -d --name triposr-gpu --restart unless-stopped --gpus all "${HARDEN[@]}"       --cpus "${TRIPOSR_GPU_CPUS:-4}" --memory "${TRIPOSR_GPU_MEM:-12g}" --shm-size 2g --tmpfs /work:size=4g,uid=10004 --tmpfs /tmp:size=2g       -e PROVIDER_TOKEN="$VLM_TOKEN" -e PROVIDER_THREADS=4 -e PROVIDER_CONCURRENCY=1 -e HF_HUB_OFFLINE=1 -e HOME=/tmp       -v assetforge-gpu_triposr-models:/models -p "${VLM_BIND:-0.0.0.0}:${TRIPOSR_PORT:-8082}:8080" assetforge-triposr-gpu:local ;;
  down) docker rm -f vlm-gpu triposr-gpu 2>/dev/null || true ;;
  logs) docker logs --tail 50 vlm-gpu ;;
  *) sed -n 2,9p "$0"; exit 1 ;;
esac
