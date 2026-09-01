#!/usr/bin/env bash
# Backup manual do PostgreSQL self-hosted via `docker compose exec`. PGPASSWORD
# é repassado pela API do Docker (nunca em argv), então não aparece em `ps aux`.
set -euo pipefail

DIRETORIO_RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIRETORIO_RAIZ"

if [ ! -f .env ]; then
  echo "Erro: .env não encontrado em $DIRETORIO_RAIZ. Backup requer POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

: "${POSTGRES_USER:?POSTGRES_USER não definido no .env}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD não definido no .env}"
: "${POSTGRES_DB:?POSTGRES_DB não definido no .env}"

mkdir -p backups
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARQUIVO="backups/${POSTGRES_DB}_${TIMESTAMP}.dump"

export PGPASSWORD="$POSTGRES_PASSWORD"

echo "Gerando backup de '${POSTGRES_DB}' em ${ARQUIVO}..."
# -Fc: formato custom, comprimido e restaurável seletivamente com pg_restore.
docker compose exec -T -e PGPASSWORD postgres \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc >"$ARQUIVO"

echo "Backup concluído: ${ARQUIVO} ($(du -h "$ARQUIVO" | cut -f1))"
