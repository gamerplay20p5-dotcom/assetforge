#!/usr/bin/env bash
# Instalação do AssetForge em UMA máquina (ex.: a 206), tudo em Docker. Execução MANUAL, na própria máquina.
#
#   ./scripts/install_single_node.sh standalone              # PostgreSQL local em Docker
#   ./scripts/install_single_node.sh external-db             # PostgreSQL externo (edite ASSETFORGE_DATABASE_URL no .env)
#   opções:  --no-ai   (só CPU: sem ComfyUI/worker Intel)    --no-start (só prepara .env e valida a configuração)
#
# Cria/usa apenas arquivos desta pasta e o projeto Compose "assetforge". NÃO altera drivers, NÃO usa sudo, NÃO toca em
# outros containers/serviços da máquina (AI Stream Clipper etc.). Escrito e revisado, mas NÃO executado pelo autor.
set -euo pipefail
cd "$(dirname "$0")/.."
profile="${1:-}"; shift || true
[[ "$profile" =~ ^(standalone|external-db)$ ]] || { echo "uso: $0 standalone|external-db [--no-ai] [--no-start]"; exit 2; }
ai=1; start=1
for a in "$@"; do case "$a" in --no-ai) ai=0;; --no-start) start=0;; *) echo "opção desconhecida: $a"; exit 2;; esac; done

command -v docker >/dev/null || { echo "docker não encontrado"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "docker compose v2 é necessário"; exit 1; }
gen() { openssl rand -base64 60 | tr -d '\n/+=' | cut -c1-"${1:-40}"; }
setvar() { # setvar CHAVE VALOR  (substitui a linha CHAVE= no .env)
  local k="$1" v="$2"; v="${v//\\/\\\\}"; v="${v//|/\\|}"
  if grep -q "^${k}=" .env; then sed -i "s|^${k}=.*|${k}=${v}|" .env; else echo "${k}=${v}" >> .env; fi
}

if [[ ! -f .env ]]; then
  cp "deployment/${profile}.env.example" .env; chmod 600 .env
  [[ "$profile" == standalone ]] && setvar POSTGRES_PASSWORD "$(gen 32)"
  setvar ASSETFORGE_SECRET_KEY "$(gen 48)"
  admin_pw="$(gen 20)"; setvar ASSETFORGE_ADMIN_PASSWORD "$admin_pw"
  t_cpu="enr_$(gen 40)"; t_gpu="enr_$(gen 40)"
  setvar ASSETFORGE_ENROLLMENT_TOKEN_CPU "$t_cpu"; setvar ASSETFORGE_ENROLLMENT_TOKEN_GPU "$t_gpu"
  setvar ASSETFORGE_BOOTSTRAP_ENROLLMENT_TOKENS "${t_cpu},${t_gpu}"
  setvar HOSTNAME_TAG "$(hostname -s | tr -cd 'A-Za-z0-9_.-')"
  echo "Criado .env (permissão 600) com segredos gerados. Senha inicial do admin: ${admin_pw}   (troque depois)"
fi

# GPU Intel: o container acessa /dev/dri com os gids dos grupos do HOST (sem privileged)
if (( ai )); then
  if ls /dev/dri/renderD* >/dev/null 2>&1; then
    rg="$(getent group render | cut -d: -f3 || true)"; vg="$(getent group video | cut -d: -f3 || true)"
    [[ -n "$rg" ]] && setvar RENDER_GID "$rg"; [[ -n "$vg" ]] && setvar VIDEO_GID "$vg"
    echo "GPU: $(ls /dev/dri/renderD* | tr '\n' ' ') | render gid=${rg:-?} video gid=${vg:-?}"
  else
    echo "AVISO: nenhum /dev/dri/renderD* — sem GPU Intel utilizável. Use --no-ai ou carregue o driver (ação do administrador)."; exit 3
  fi
  setvar COMPOSE_PROFILES "${profile},ai"
else
  setvar COMPOSE_PROFILES "${profile}"; setvar RENDER_GID "0"
fi

if [[ "$profile" == external-db ]] && grep -q "HOST_DO_BANCO\|SENHA@" .env; then
  echo "Edite .env: ASSETFORGE_DATABASE_URL (banco/usuário exclusivos; veja scripts/db/create_assetforge_db.sql) e rode de novo."; exit 4
fi

C=(docker compose --env-file .env -f deployment/docker-compose.yml)
"${C[@]}" config >/dev/null && echo "Configuração do Compose válida."
(( start )) || { echo "--no-start: nada foi iniciado."; exit 0; }
"${C[@]}" up -d --build
"${C[@]}" ps
port="$(grep ^ASSETFORGE_PORT= .env | cut -d= -f2)"
cat <<EOF

Pronto. Painel/API: http://$(hostname -I 2>/dev/null | awk '{print $1}'):${port:-8000}   Saúde: /api/v1/health/ready
Próximos passos (IA, nesta ordem — nada de IA fica disponível antes de validar):
  ./scripts/intel_ai/docker_tasks.sh models-list
  ./scripts/intel_ai/docker_tasks.sh models-download      # baixa pesos (lê as licenças antes)
  ./scripts/intel_ai/docker_tasks.sh validate             # roda texto→imagem→3D DE VERDADE e mede VRAM/RAM/temperatura
Backup: ./scripts/backup.sh   |   Restauração: ./scripts/restore.sh backups/<data>
EOF
