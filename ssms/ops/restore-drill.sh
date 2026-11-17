#!/bin/sh
# Quarterly restore drill (design/18.5, NFR-06): restores the newest nightly dump into a scratch database next to
# the live one, checks it, reports how long it took, and drops the scratch copy. The live database is only read.
#   sh ssms/ops/restore-drill.sh [compose project] [env file]       e.g. sh ssms/ops/restore-drill.sh ssms ssms/.env
set -eu
project=${1:-ssms}
envfile=${2:-ssms/.env}
compose="docker compose -p $project -f ssms/docker-compose.yml --env-file $envfile"
started=$(date +%s)

$compose exec -T backup sh -eu -c '
  dump=$(ls -t /backups/ssms-*.dump 2>/dev/null | head -1)
  [ -n "$dump" ] || { echo "no backup in /backups yet" >&2; exit 1; }
  age_h=$(( ($(date +%s) - $(stat -c %Y "$dump")) / 3600 ))
  echo "restoring $dump ($age_h h old)"
  [ "$age_h" -le 26 ] || echo "WARNING: the newest backup is older than a day: check the backup service" >&2
  dropdb -h db -U postgres --if-exists ssms_restore_drill
  createdb -h db -U postgres ssms_restore_drill
  pg_restore -h db -U postgres -d ssms_restore_drill --exit-on-error "$dump"
  if [ -z "$(psql -h db -U postgres -d ssms_restore_drill -Atc "\dt alembic_version" 2>/dev/null)" ]; then
    dropdb -h db -U postgres ssms_restore_drill
    echo "FAILED: $dump holds no SSMS schema (an empty database was backed up)" >&2; exit 1
  fi
  q() { psql -h db -U postgres -d "$1" -Atc "$2"; }
  unbalanced=$(q ssms_restore_drill "SELECT count(*) FROM (SELECT journal_id FROM ledger_entries GROUP BY journal_id HAVING sum(debit_tzs) <> sum(credit_tzs)) x")
  echo "unbalanced journals: $unbalanced"
  for t in schools users students invoices payments published_results stored_files audit_logs; do
    echo "$t: restored $(q ssms_restore_drill "SELECT count(*) FROM $t") / live now $(q ssms "SELECT count(*) FROM $t")"
  done
  rls=$(q ssms_restore_drill "SELECT count(*) FROM pg_class WHERE relrowsecurity AND relforcerowsecurity")
  echo "tables with forced row-level security: $rls"
  dropdb -h db -U postgres ssms_restore_drill
  [ "$unbalanced" = 0 ] && [ "$rls" -gt 0 ]
'
echo "restore drill passed in $(( $(date +%s) - started )) s (target RTO 4 h). Record it in the operations log."
echo "Uploaded files are not in the dump: check the files volume or the object store backup separately."
