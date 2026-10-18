#!/bin/sh
# Nightly pg_dump of the actron and temporal databases, keeping BACKUP_KEEP_DAYS days.
# Restore: see docs/runbook.md ("Backups and restore").
set -eu
KEEP="${BACKUP_KEEP_DAYS:-7}"
INTERVAL="${BACKUP_INTERVAL_SECONDS:-86400}"

run_backup() {
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  for db in actron temporal; do
    out="/backups/${db}-${stamp}.dump"
    if pg_dump --format=custom --file="${out}.tmp" "$db"; then
      mv "${out}.tmp" "$out"
      echo "{\"level\":\"info\",\"msg\":\"backup written\",\"db\":\"$db\",\"file\":\"$out\"}"
    else
      rm -f "${out}.tmp"
      echo "{\"level\":\"error\",\"msg\":\"backup failed\",\"db\":\"$db\"}"
    fi
  done
  find /backups -name '*.dump' -mtime +"$KEEP" -delete
}

if [ "${1:-}" = "--once" ]; then
  run_backup
  exit 0
fi

while true; do
  run_backup
  sleep "$INTERVAL"
done
