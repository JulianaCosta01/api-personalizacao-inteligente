#!/usr/bin/env bash
# Backup do PostgreSQL self-hosted (Fase 11 — Documento 5 §185: "backup do
# banco confirmado"). Documento 4 §19 presumia backup automático via Supabase
# gerenciado; o banco oficial é self-hosted em Docker, por isso este script
# cobre o critério de forma manual e testada (agendamento automático fica
# fora deste escopo).
#
# pg_dump roda DENTRO do container postgres via `docker compose exec`, sem
# exigir cliente Postgres instalado no host. Autenticação explícita com a
# senha real do .env — nunca presume "trust" na conexão local do Postgres.
# A senha é repassada ao processo do container via `docker compose exec -e
# PGPASSWORD` SEM valor anexado: nesse formato o Docker propaga o valor já
# exportado no ambiente deste script pela API do daemon, não pela linha de
# comando — por isso PGPASSWORD nunca aparece em `ps aux` do host, nunca é
# impresso e nunca é gravado em arquivo.
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
# -Fc: formato custom (comprimido, restaurável seletivamente com pg_restore)
# — padrão recomendado pela documentação do Postgres para este porte de banco.
docker compose exec -T -e PGPASSWORD postgres \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc >"$ARQUIVO"

echo "Backup concluído: ${ARQUIVO} ($(du -h "$ARQUIVO" | cut -f1))"
