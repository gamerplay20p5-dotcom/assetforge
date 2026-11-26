#!/usr/bin/env bash
# Restaura um backup feito por scripts/backup.sh. DESTRUTIVO para o banco do AssetForge e para os assets.
#   ./scripts/restore.sh backups/20260101-030000
# Standalone: recria o banco local. Banco externo: restaura SOMENTE no banco dedicado indicado em ASSETFORGE_DATABASE_URL
# (pg_restore --clean --if-exists), nunca em outros bancos do servidor.
set -euo pipefail
cd "$(dirname "$0")/.."
src="${1:?uso: restore.sh <diretorio-do-backup>}"
( cd "$src" && sha256sum -c SHA256SUMS )
set -a; . ./.env; set +a
C=(docker compose --env-file .env -f deployment/docker-compose.yml)
read -r -p "Isto SUBSTITUI o banco e os assets do AssetForge por ${src}. Digite 'restaurar': " ans
[[ "$ans" == "restaurar" ]] || { echo cancelado; exit 1; }
"${C[@]}" stop api worker-cpu worker-gpu 2>/dev/null || "${C[@]}" stop api worker-cpu
if [[ ",${COMPOSE_PROFILES:-}," == *",standalone,"* ]]; then
  "${C[@]}" up -d postgres
  "${C[@]}" exec -T postgres dropdb -U assetforge --if-exists assetforge
  "${C[@]}" exec -T postgres createdb -U assetforge assetforge
  "${C[@]}" exec -T postgres pg_restore -U assetforge -d assetforge --no-owner < "${src}/assetforge.dump"
else
  export AF_DB_URL="${ASSETFORGE_DATABASE_URL:?}"
  docker run --rm -i -e AF_DB_URL postgres:16-alpine sh -c 'pg_restore --clean --if-exists --no-owner -d "$AF_DB_URL"' < "${src}/assetforge.dump"
fi
for v in assets worker-cpu-state worker-gpu-state ai-models; do
  [[ -f "${src}/${v}.tar.gz" ]] || continue
  docker volume create "assetforge_${v}" >/dev/null
  docker run --rm -v "assetforge_${v}:/data" -v "$PWD/${src}:/backup:ro" alpine:3.20 sh -c "rm -rf /data/* /data/.[!.]* 2>/dev/null; tar -C /data -xzf /backup/${v}.tar.gz"
done
"${C[@]}" up -d
echo restaurado
