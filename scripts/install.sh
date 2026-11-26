#!/usr/bin/env bash
# AssetForge manual installer. Run on the target server (no SSH from the developer is assumed).
#   ./scripts/install.sh central     # PostgreSQL + API + dashboard
#   ./scripts/install.sh worker-cpu  # CPU worker (Blender headless)
#   ./scripts/install.sh worker-intel# hybrid Intel GPU/CPU worker (adds /dev/dri passthrough)
# It only creates files inside this repository folder and starts/updates ITS OWN compose project; it does not
# touch other containers, drivers or services on the host.
set -euo pipefail
cd "$(dirname "$0")/.."
role="${1:-}"
[[ "$role" =~ ^(central|worker-cpu|worker-intel)$ ]] || { echo "usage: $0 central|worker-cpu|worker-intel"; exit 2; }
command -v docker >/dev/null || { echo "docker is required"; exit 1; }
docker compose version >/dev/null || { echo "docker compose v2 is required"; exit 1; }

gen() { openssl rand -base64 48 | tr -d '\n/+=' | cut -c1-48; }

if [[ "$role" == "central" ]]; then
  envfile=.env
  if [[ ! -f $envfile ]]; then
    cp .env.example "$envfile"; chmod 600 "$envfile"
    sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(gen)|; s|^ASSETFORGE_SECRET_KEY=.*|ASSETFORGE_SECRET_KEY=$(gen)|" "$envfile"
    admin_pw="$(gen)"; sed -i "s|^ASSETFORGE_ADMIN_PASSWORD=.*|ASSETFORGE_ADMIN_PASSWORD=${admin_pw}|" "$envfile"
    echo "Created $envfile with generated secrets. Initial admin password: ${admin_pw}  (change it after first login)"
  fi
  docker compose --env-file "$envfile" -f deployment/docker-compose.central.yml up -d --build
  echo "Dashboard/API on port $(grep ^ASSETFORGE_PORT= "$envfile" | cut -d= -f2). Health: /api/v1/health/ready"
else
  envfile=.env.worker
  if [[ ! -f $envfile ]]; then
    cp .env.example "$envfile"; chmod 600 "$envfile"
    echo "Created $envfile - edit ASSETFORGE_SERVER_URL, ASSETFORGE_WORKER_NAME, ASSETFORGE_ENROLLMENT_TOKEN and the limits, then re-run."
    exit 0
  fi
  files=(-f deployment/docker-compose.worker-cpu.yml)
  [[ "$role" == "worker-intel" ]] && files+=(-f deployment/docker-compose.worker-intel.yml)
  docker compose --env-file "$envfile" "${files[@]}" up -d --build
fi
