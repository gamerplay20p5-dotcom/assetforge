#!/usr/bin/env bash
# Tarefas do serviço de visão (Qwen2.5-VL, CPU). Rode na máquina, na pasta do projeto.
#   ./scripts/vlm/tasks.sh download [modelo]   baixa os pesos para o volume vlm-models (precisa de internet; 7B ~16 GB)
#   ./scripts/vlm/tasks.sh up                  liga o serviço (perfil vision) e aponta a API para ele
#   ./scripts/vlm/tasks.sh benchmark ./pasta   mede tempo/RAM/CPU e acerto contra a verdade (pasta/<casa>/06_casa_finalizada.png)
set -euo pipefail
cd "$(dirname "$0")/../.."
DC="docker compose --env-file .env -f deployment/docker-compose.yml"
case "${1:-}" in
  download)
    MODEL="${2:-Qwen/Qwen2.5-VL-7B-Instruct}"
    docker build -q -f deployment/Dockerfile.vlm -t assetforge-vlm:local . >/dev/null
    docker run --rm --cap-drop ALL --security-opt no-new-privileges --cpus 4 -v assetforge_vlm-models:/models --entrypoint python assetforge-vlm:local \
      -c "from huggingface_hub import snapshot_download as s; print(s('$MODEL'))" ;;
  up)
    grep -q '^ASSETFORGE_VLM_URL=' .env || echo 'ASSETFORGE_VLM_URL=http://vlm:8080' >> .env
    grep -q 'vision' <<<"$(grep '^COMPOSE_PROFILES=' .env)" || sed -i 's/^COMPOSE_PROFILES=\(.*\)$/COMPOSE_PROFILES=\1,vision/' .env
    $DC up -d --build vlm api ;;
  benchmark)
    docker run --rm --cap-drop ALL --security-opt no-new-privileges --cpus "${VLM_DOCKER_CPUS:-22}" --memory "${VLM_DOCKER_MEM:-64g}" -e HF_HUB_OFFLINE=1 \
      -v assetforge_vlm-models:/models -v "$(readlink -f "${2:?pasta com as imagens}")":/refs:ro -v "$PWD/vlm_out":/out assetforge-vlm:local \
      --model "${VLM_MODEL:-Qwen/Qwen2.5-VL-7B-Instruct}" --images /refs --out /out --threads "${VLM_THREADS:-20}" ;;
  *) sed -n 2,6p "$0"; exit 1 ;;
esac
