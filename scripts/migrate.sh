#!/usr/bin/env bash
# scripts/migrate.sh — External Alembic migration runner (S3-4).
#
# DB schema is managed OUTSIDE the app. This script is the operator tool for
# zero-downtime, rollbackable production migrations: it takes a pg_dump backup
# BEFORE applying `alembic upgrade head`, and supports `rollback` (downgrade).
#
# Usage:
#   ./migrate.sh up                 # pg_dump backup (if pg client present) + alembic upgrade head
#   ./migrate.sh backup             # pg_dump current DB -> backups/pre_migrate_<ts>.sql
#   ./migrate.sh rollback [-1|<rev>] # alembic downgrade <target> (default -1); needs FORCE_ROLLBACK=1
#   ./migrate.sh status             # alembic current
#
# Env:
#   DATABASE_URL    required (postgresql://user:pass@host:port/db). Falls back to alembic.ini default.
#   BACKUP_DIR      backup dir (default: <project>/backups)
#   FORCE_ROLLBACK  set to 1 to permit a destructive rollback
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

NO_URL=0
if [[ -z "${DATABASE_URL:-}" ]]; then
  NO_URL=1
  echo "WARN: DATABASE_URL not set; alembic will use its alembic.ini default." >&2
fi

BACKUP_DIR="${BACKUP_DIR:-$PROJECT_ROOT/backups}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

# Derive pg client connection env vars from a postgresql:// URL so pg_dump works
# without a separate ~/.pgpass.
parse_pg_url() {
  local url="$1"
  local body="${url#postgresql://}"
  local user="${body%%:*}"
  local rest="${body#*:}"
  local pass="${rest%%@*}"
  local hostportdb="${rest#*@}"
  local host="${hostportdb%%:*}"
  local portdb="${hostportdb#*:}"
  local port="${portdb%%/*}"
  local db="${portdb#*/}"
  db="${db%%\?*}"
  PGUSER="$user"; PGPASSWORD="$pass"; PGHOST="$host"; PGPORT="$port"; PGDATABASE="$db"
  export PGUSER PGPASSWORD PGHOST PGPORT PGDATABASE
}

backup() {
  if [[ "$NO_URL" == "1" ]]; then
    echo "WARN: DATABASE_URL not set — skipping backup." >&2
    return 0
  fi
  if ! command -v pg_dump >/dev/null 2>&1; then
    echo "WARN: pg_dump not found on PATH — skipping backup (run on a host with the postgres client)." >&2
    return 0
  fi
  parse_pg_url "$DATABASE_URL"
  mkdir -p "$BACKUP_DIR"
  local out="$BACKUP_DIR/pre_migrate_${TIMESTAMP}.sql"
  echo ">> pg_dump -> $out"
  pg_dump --clean --if-exists --no-owner --no-privileges > "$out"
  echo ">> backup written: $out"
}

cmd="${1:-up}"
case "$cmd" in
  backup)
    backup
    ;;
  up)
    backup
    echo ">> alembic upgrade head"
    python -m alembic upgrade head
    echo ">> migration complete"
    ;;
  rollback)
    target="${2:--1}"
    if [[ "${FORCE_ROLLBACK:-0}" != "1" ]]; then
      echo "WARN: rollback will downgrade to '$target' and is destructive." >&2
      echo "      Set FORCE_ROLLBACK=1 to proceed, or restore the latest backup from $BACKUP_DIR." >&2
      exit 1
    fi
    echo ">> alembic downgrade $target"
    python -m alembic downgrade "$target"
    echo ">> rollback complete (to $target)"
    ;;
  status)
    python -m alembic current
    ;;
  *)
    echo "Unknown command: $cmd" >&2
    echo "Usage: $0 [up|backup|rollback [-1|<rev>]|status]" >&2
    exit 1
    ;;
esac
