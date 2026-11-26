#!/usr/bin/env bash
# Backup do AssetForge de um nó: banco (local OU externo), assets, estado dos workers e cópia do .env.
#   ./scripts/backup.sh [--with-models]        saída: backups/<data-hora>/
# Modelos de IA NÃO entram por padrão (dezenas de GB, baixáveis de novo com SHA-256); --with-models inclui.
# Só LÊ do banco/volumes; não para nenhum serviço. O .env copiado contém segredos: o diretório fica com permissão 700.
set -euo pipefail
cd "$(dirname "$0")/.."
with_models=0; [[ "${1:-}" == "--with-models" ]] && with_models=1
set -a; . ./.env; set +a
C=(docker compose --env-file .env -f deployment/docker-compose.yml)
stamp="$(date +%Y%m%d-%H%M%S)"; dest="backups/${stamp}"; mkdir -p "$dest"; chmod 700 backups "$dest"

if [[ ",${COMPOSE_PROFILES:-}," == *",standalone,"* ]]; then
  "${C[@]}" exec -T postgres pg_dump -U assetforge -d assetforge --format=custom > "${dest}/assetforge.dump"
else
  export AF_DB_URL="${ASSETFORGE_DATABASE_URL:?ASSETFORGE_DATABASE_URL não definido}"   # herdado do ambiente: não aparece na linha de comando
  docker run --rm -e AF_DB_URL postgres:16-alpine sh -c 'pg_dump --format=custom "$AF_DB_URL"' > "${dest}/assetforge.dump"
fi
for v in assets worker-cpu-state worker-gpu-state; do
  docker volume inspect "assetforge_${v}" >/dev/null 2>&1 || continue
  docker run --rm -v "assetforge_${v}:/data:ro" -v "$PWD/${dest}:/backup" alpine:3.20 tar -C /data -czf "/backup/${v}.tar.gz" .
done
(( with_models )) && docker run --rm -v assetforge_ai-models:/data:ro -v "$PWD/${dest}:/backup" alpine:3.20 tar -C /data -czf /backup/ai-models.tar.gz .
cp .env "${dest}/env.copy"; chmod 600 "${dest}/env.copy"
( cd "$dest" && sha256sum * > SHA256SUMS )
echo "backup em ${dest}"
ls -1dt backups/*/ 2>/dev/null | tail -n +15 | xargs -r rm -rf   # mantém os 14 mais recentes
