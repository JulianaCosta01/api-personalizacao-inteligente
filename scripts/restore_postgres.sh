#!/usr/bin/env bash
# Restore do PostgreSQL self-hosted (Fase 11 — Documento 5 §185).
#
# Operação destrutiva: --clean --if-exists derruba e recria cada objeto do
# banco alvo antes de restaurar o dump — por isso exige confirmação explícita
# do nome do banco antes de prosseguir. --no-owner --no-privileges evitam
# falha por divergência de papéis entre o ambiente do dump e o atual.
#
# Mesma estratégia de autenticação seguida em backup_postgres.sh: pg_restore
# roda dentro do container via `docker compose exec`, com PGPASSWORD
# propagado pela API do Docker (nunca em argv, nunca em arquivo) — ver
# comentário completo lá.
set -euo pipefail

DIRETORIO_RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIRETORIO_RAIZ"

ARQUIVO_DUMP="${1:-}"
if [ -z "$ARQUIVO_DUMP" ] || [ ! -f "$ARQUIVO_DUMP" ]; then
  echo "Uso: $0 <caminho-do-dump>" >&2
  echo "Backups disponíveis:" >&2
  ls -1 backups/*.dump 2>/dev/null >&2 || echo "  (nenhum em backups/)" >&2
  exit 1
fi

if [ ! -f .env ]; then
  echo "Erro: .env não encontrado em $DIRETORIO_RAIZ." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

: "${POSTGRES_USER:?POSTGRES_USER não definido no .env}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD não definido no .env}"
: "${POSTGRES_DB:?POSTGRES_DB não definido no .env}"

echo "ATENÇÃO: isso vai APAGAR e recriar os objetos existentes no banco '${POSTGRES_DB}' antes de restaurar ${ARQUIVO_DUMP}."
read -r -p "Digite o nome do banco (${POSTGRES_DB}) para confirmar: " CONFIRMACAO
if [ "$CONFIRMACAO" != "$POSTGRES_DB" ]; then
  echo "Confirmação não confere. Abortando, nada foi alterado." >&2
  exit 1
fi

export PGPASSWORD="$POSTGRES_PASSWORD"

echo "Restaurando ${ARQUIVO_DUMP} em '${POSTGRES_DB}'..."
docker compose exec -T -e PGPASSWORD postgres \
  pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-privileges <"$ARQUIVO_DUMP"

echo "Restore concluído."
