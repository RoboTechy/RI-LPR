#!/usr/bin/env bash
# Nightly database backup (see ADD-2 in the system review) - dumps the
# Postgres DB to a timestamped, gzip-compressed .sql.gz file and prunes
# anything older than BACKUP_RETENTION_DAYS.
#
# Run from cron (see backend/README.md's "Backups" section for the exact
# crontab line) or by hand: ./scripts/backup_db.sh
#
# Deliberately uses `docker compose exec db pg_dump` rather than a
# separately-installed pg_dump on the host - this always matches the
# exact Postgres server version running in the "db" container, so there's
# no client/server version-mismatch risk to worry about.
#
# Backups are written OUTSIDE any Docker-managed volume (a plain
# directory on the host, not db_data/media_data) on purpose: a
# `docker compose down -v`, or any failure that takes out those volumes,
# must not take the backups down with it.
set -euo pipefail

cd "$(dirname "$0")/.."  # backend/ - where docker-compose.yml lives

BACKUP_DIR="${RI_LPR_BACKUP_DIR:-$(pwd)/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
TIMESTAMP="$(date +%Y-%m-%d_%H%M%S)"
OUT_FILE="$BACKUP_DIR/ri_lpr_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "[$(date -Iseconds)] backing up database to $OUT_FILE"
# -T: no pseudo-TTY - required for piping exec's output cleanly,
# especially when this runs from cron with no TTY at all.
# Written to a .part file first and renamed only on success, so a
# killed/failed run never leaves a half-written file that LOOKS like a
# valid backup.
docker compose exec -T db pg_dump -U ri_lpr ri_lpr | gzip > "${OUT_FILE}.part"
mv "${OUT_FILE}.part" "$OUT_FILE"
echo "[$(date -Iseconds)] backup complete: $(du -h "$OUT_FILE" | cut -f1)"

echo "[$(date -Iseconds)] pruning backups older than ${RETENTION_DAYS} days"
find "$BACKUP_DIR" -maxdepth 1 -name 'ri_lpr_*.sql.gz' -mtime "+${RETENTION_DAYS}" -print -delete

echo "[$(date -Iseconds)] current backups in $BACKUP_DIR:"
ls -lh "$BACKUP_DIR"
