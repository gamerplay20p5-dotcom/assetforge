#!/usr/bin/env bash
# Atualiza o AssetForge de um nó para a versão em checkout: backup -> rebuild SOMENTE deste projeto Compose.
#   git pull && ./scripts/update.sh
# Atenção: o esquema do banco é criado por create_all (sem Alembic ainda): leia o changelog antes de atualizar.
set -euo pipefail
cd "$(dirname "$0")/.."
./scripts/backup.sh
docker compose --env-file .env -f deployment/docker-compose.yml up -d --build
docker compose --env-file .env -f deployment/docker-compose.yml ps
