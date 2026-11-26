#!/usr/bin/env bash
# Backup of the central server: PostgreSQL dump + asset storage volume. Output: ./backups/<timestamp>/
# Restore procedure: docs/DEPLOYMENT.md ("Backup e recuperação").
set -euo pipefail
cd "$(dirname "$0")/.."
stamp="$(date +%Y%m%d-%H%M%S)"
dest="backups/${stamp}"
mkdir -p "$dest"
compose=(docker compose --env-file .env -f deployment/docker-compose.central.yml)
"${compose[@]}" exec -T postgres pg_dump -U assetforge -d assetforge --format=custom > "${dest}/assetforge.dump"
# assets volume -> tar (read-only mount, throwaway alpine container; does not touch running services)
vol="$(docker volume ls --format '{{.Name}}' | grep -E '(^|_)assets$' | grep assetforge | head -n1)"
docker run --rm -v "${vol}:/data:ro" -v "$PWD/${dest}:/backup" alpine:3.20 tar -C /data -czf /backup/assets.tar.gz .
( cd "$dest" && sha256sum assetforge.dump assets.tar.gz > SHA256SUMS )
echo "backup written to ${dest}"
# keep the last 14 backups
ls -1dt backups/*/ 2>/dev/null | tail -n +15 | xargs -r rm -rf
