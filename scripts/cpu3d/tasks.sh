#!/usr/bin/env bash
# Tarefas dos providers CPU de image-to-3D (Stable Fast 3D, TripoSR) no stack Docker de um nó (método principal de geração por IA).
#   ./scripts/cpu3d/tasks.sh build                       # constrói as imagens dos providers (demora; baixa torch CPU etc.)
#   ./scripts/cpu3d/tasks.sh setup triposr               # baixa pesos (MIT) e roda uma inferência REAL de aquecimento
#   HF_TOKEN=hf_xxx ./scripts/cpu3d/tasks.sh setup sf3d  # idem para o SF3D (pesos 'gated': aceite a licença no HF com a sua conta)
#   ./scripts/cpu3d/tasks.sh up                          # sobe providers + worker-ai (perfil cpu3d)
#   ./scripts/cpu3d/tasks.sh status                      # saúde/consumo dos providers
#   ./scripts/cpu3d/tasks.sh benchmark ./referencias [perfil ...]   # SUAS imagens -> tempo/RAM/CPU + comparação visual
#   ./scripts/cpu3d/tasks.sh export                      # copia o resultado do benchmark para ./reports_out/bench
#   ./scripts/cpu3d/tasks.sh offline                     # depois dos downloads: providers sem acesso à internet (CPU3D_OFFLINE=1)
# Só opera o projeto Compose "assetforge". Não toca em drivers, BIOS, kernel ou em outros serviços.
set -euo pipefail
cd "$(dirname "$0")/../.."
C=(docker compose --env-file .env -f deployment/docker-compose.yml)
cmd="${1:-}"; shift || true
case "$cmd" in
  build)  "${C[@]}" --profile cpu3d build triposr sf3d worker-ai ;;
  setup)  p="${1:?triposr|sf3d}"
          [[ "$p" == sf3d && -z "${HF_TOKEN:-}" && -z "$(grep '^HF_TOKEN=' .env | cut -d= -f2)" ]] && echo "Aviso: sf3d precisa de HF_TOKEN (pesos gated)."
          HF_TOKEN="${HF_TOKEN:-$(grep '^HF_TOKEN=' .env | cut -d= -f2)}" "${C[@]}" --profile tools run --rm -e HF_TOKEN "${p}-setup" ;;
  up)     COMPOSE_PROFILES="$(grep '^COMPOSE_PROFILES=' .env | cut -d= -f2),cpu3d" "${C[@]}" up -d triposr sf3d worker-ai ;;
  status) for p in triposr sf3d; do echo "== $p"; "${C[@]}" exec -T "$p" python -c "import json,urllib.request as u;print(json.dumps(json.loads(u.urlopen('http://127.0.0.1:8080/health').read()),indent=1)[:700]);print(u.urlopen('http://127.0.0.1:8080/stats').read().decode())" || true; done ;;
  benchmark) imgs="${1:?pasta com as imagens}"; shift || true
          "${C[@]}" --profile tools run --rm -v "$(cd "$imgs" && pwd):/refs:ro" cpu3d-tools scripts/cpu3d/benchmark_cpu3d.py --images /refs --out /bench --profiles "${@:-stylized_standard}" ;;
  export) mkdir -p reports_out/bench; docker run --rm -v assetforge_bench-out:/src:ro -v "$PWD/reports_out/bench:/dst" alpine:3.20 sh -c 'cp -r /src/. /dst/'; echo "copiado para ./reports_out/bench" ;;
  offline) sed -i 's/^CPU3D_OFFLINE=.*/CPU3D_OFFLINE=1/' .env; "${C[@]}" up -d --force-recreate triposr sf3d; echo "providers agora em modo offline" ;;
  *) sed -n '2,12p' "$0"; exit 2 ;;
esac
