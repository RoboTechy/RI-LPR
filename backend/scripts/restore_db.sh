#!/usr/bin/env bash
# Restores a backup created by backup_db.sh into the running "db"
# container. DESTRUCTIVE - overwrites every row currently in the
# database with whatever the backup file contains. See backend/README.md's
# "Backups" section for when/why you'd need this.
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: $0 <path-to-backup.sql.gz>" >&2
  echo "  e.g. $0 backups/ri_lpr_2026-11-14_020000.sql.gz" >&2
  exit 1
fi

BACKUP_FILE="$1"
cd "$(dirname "$0")/.."  # backend/

if [ ! -f "$BACKUP_FILE" ]; then
  echo "No such file: $BACKUP_FILE" >&2
  exit 1
fi

echo "This will REPLACE every row currently in the ri_lpr database with the"
echo "contents of:"
echo "  $BACKUP_FILE"
echo "This cannot be undone unless you have ANOTHER backup of the current data."
read -r -p "Type 'yes' to continue: " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
  echo "Aborted - nothing was changed."
  exit 1
fi

echo "[$(date -Iseconds)] restoring $BACKUP_FILE ..."
gunzip -c "$BACKUP_FILE" | docker compose exec -T db psql -U ri_lpr -d ri_lpr
echo "[$(date -Iseconds)] restore complete."
echo "Restart the api and worker containers now: docker compose restart api worker"
