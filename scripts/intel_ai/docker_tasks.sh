#!/usr/bin/env bash
# Tarefas de IA no stack Docker de um único nó (use depois de scripts/install_single_node.sh).
#   ./scripts/intel_ai/docker_tasks.sh models-list
#   ./scripts/intel_ai/docker_tasks.sh models-download        # baixa os pesos (mostra licenças; exige confirmação)
#   ./scripts/intel_ai/docker_tasks.sh models-verify
#   ./scripts/intel_ai/docker_tasks.sh comfy-check            # ComfyUI enxerga a GPU XPU? (torch.xpu) — não gera nada
#   ./scripts/intel_ai/docker_tasks.sh validate [--repeat 3]  # execução REAL; só ela libera ai.* no worker
#   ./scripts/intel_ai/docker_tasks.sh benchmark [pasta_de_imagens] [perfil ...]
#   ./scripts/intel_ai/docker_tasks.sh export-reports         # copia relatórios/benchmarks para ./reports_out
#   ./scripts/intel_ai/docker_tasks.sh logs
# Providers CPU (método principal): ver também ./scripts/cpu3d/tasks.sh
# Não suspende nem altera outros serviços. Se precisar liberar VRAM suspendendo workers do AI Stream Clipper, faça-o
# conscientemente pelo asc-ctl (preservando dados) antes do 'validate'; este script não faz isso.
set -euo pipefail
cd "$(dirname "$0")/../.."
C=(docker compose --env-file .env -f deployment/docker-compose.yml)
cmd="${1:-}"; shift || true
tools() { "${C[@]}" --profile tools run --rm "$@"; }
case "$cmd" in
  models-list)     tools ai-tools scripts/intel_ai/download_models.py --models-dir /models --list ;;
  models-download) tools ai-tools scripts/intel_ai/download_models.py --models-dir /models --list
                   read -r -p "Li as licenças acima e aceito (digite 'aceito'): " a; [[ "$a" == aceito ]] || { echo cancelado; exit 1; }
                   tools ai-tools scripts/intel_ai/download_models.py --models-dir /models --accept-licenses ;;
  models-verify)   tools ai-tools scripts/intel_ai/download_models.py --models-dir /models --verify ;;
  comfy-check)     "${C[@]}" exec comfyui python -c "import torch;print('torch',torch.__version__,'| xpu:',torch.xpu.is_available(),'| dispositivos:',torch.xpu.device_count());[print(' -',torch.xpu.get_device_name(i)) for i in range(torch.xpu.device_count())]"
                   "${C[@]}" exec comfyui python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8188/system_stats').read().decode()[:600])" ;;
  validate)        tools ai-tools scripts/intel_ai/validate_node.py --state-dir /state --comfy-url http://comfyui:8188 --models-dir /models "$@"
                   echo "Se VALIDADO: reinicie o worker para anunciar ai.*  ->  docker compose --env-file .env -f deployment/docker-compose.yml restart worker-gpu" ;;
  benchmark)       imgs="${1:-}"; shift || true
                   if [[ -n "$imgs" && -d "$imgs" ]]; then
                     tools -v "$(cd "$imgs" && pwd):/refs:ro" ai-tools scripts/intel_ai/benchmark_ai.py --out /bench --comfy-url http://comfyui:8188 --models-dir /models --images /refs --profiles "${@:-stylized_standard}"
                   else
                     tools ai-tools scripts/intel_ai/benchmark_ai.py --out /bench --comfy-url http://comfyui:8188 --models-dir /models --from-procedural 4 --profiles "${@:-stylized_standard}"
                   fi ;;
  export-reports)  mkdir -p reports_out
                   for v in validation-reports bench-out; do
                     docker run --rm -v "assetforge_${v}:/src:ro" -v "$PWD/reports_out:/dst" alpine:3.20 sh -c "mkdir -p /dst/${v} && cp -r /src/. /dst/${v}/"
                   done; echo "copiado para ./reports_out" ;;
  logs)            "${C[@]}" logs --tail 200 comfyui worker-gpu ;;
  *) sed -n '2,14p' "$0"; exit 2 ;;
esac
