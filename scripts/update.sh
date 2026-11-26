#!/usr/bin/env bash
# Update AssetForge to the checked-out version. Takes a backup first (central only), then rebuilds ONLY this project.
#   ./scripts/update.sh central|worker-cpu|worker-intel
set -euo pipefail
cd "$(dirname "$0")/.."
role="${1:?usage: update.sh central|worker-cpu|worker-intel}"
if [[ "$role" == "central" ]]; then
  ./scripts/backup.sh
  docker compose --env-file .env -f deployment/docker-compose.central.yml up -d --build
  docker compose --env-file .env -f deployment/docker-compose.central.yml ps
else
  files=(-f deployment/docker-compose.worker-cpu.yml)
  [[ "$role" == "worker-intel" ]] && files+=(-f deployment/docker-compose.worker-intel.yml)
  docker compose --env-file .env.worker "${files[@]}" up -d --build
fi
