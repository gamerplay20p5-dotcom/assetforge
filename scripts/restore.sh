#!/usr/bin/env bash
# Restore a backup made by scripts/backup.sh into the CENTRAL stack. DESTRUCTIVE: replaces database and assets.
#   ./scripts/restore.sh backups/20260101-030000
set -euo pipefail
cd "$(dirname "$0")/.."
src="${1:?usage: restore.sh <backup-dir>}"
( cd "$src" && sha256sum -c SHA256SUMS )
read -r -p "This REPLACES the current database and assets with ${src}. Type 'restore' to continue: " ans
[[ "$ans" == "restore" ]] || { echo aborted; exit 1; }
compose=(docker compose --env-file .env -f deployment/docker-compose.central.yml)
"${compose[@]}" stop api
"${compose[@]}" exec -T postgres dropdb -U assetforge --if-exists assetforge
"${compose[@]}" exec -T postgres createdb -U assetforge assetforge
"${compose[@]}" exec -T postgres pg_restore -U assetforge -d assetforge --no-owner < "${src}/assetforge.dump"
vol="$(docker volume ls --format '{{.Name}}' | grep -E '(^|_)assets$' | grep assetforge | head -n1)"
docker run --rm -v "${vol}:/data" -v "$PWD/${src}:/backup:ro" alpine:3.20 sh -c 'rm -rf /data/* && tar -C /data -xzf /backup/assets.tar.gz'
"${compose[@]}" start api
echo restored
