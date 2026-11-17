#!/bin/sh
# Encrypted off-server copies of the database dumps and the uploaded files (design/18.5). Runs in the rclone image.
#   offsite.sh run       every 10 minutes: make the day's copy if it is missing (the `offsite` service)
#   offsite.sh once      one copy now, then exit
#   offsite.sh list      what the off-site store holds (decrypted names)
#   offsite.sh restore   newest dump and all files into /restore (see design/18.5)
# Contents and names are encrypted here, before they leave the server: the store only ever sees ciphertext.
# Without SSMS_OFFSITE_PASSPHRASE and SSMS_OFFSITE_SALT the copies cannot be read: keep them outside this server.
set -eu

need() { eval "v=\${$1:-}"; if [ -z "$v" ]; then echo "$1 is not set" >&2; exit 2; fi; }
for name in SSMS_OFFSITE_S3_BUCKET SSMS_OFFSITE_S3_ACCESS_KEY SSMS_OFFSITE_S3_SECRET_KEY SSMS_OFFSITE_PASSPHRASE SSMS_OFFSITE_SALT; do
  need "$name"
done

export RCLONE_CONFIG_TARGET_TYPE=s3 RCLONE_CONFIG_TARGET_PROVIDER=Other
export RCLONE_CONFIG_TARGET_ACCESS_KEY_ID="$SSMS_OFFSITE_S3_ACCESS_KEY"
export RCLONE_CONFIG_TARGET_SECRET_ACCESS_KEY="$SSMS_OFFSITE_S3_SECRET_KEY"
export RCLONE_CONFIG_TARGET_ENDPOINT="${SSMS_OFFSITE_S3_ENDPOINT_URL:-}"
export RCLONE_CONFIG_TARGET_REGION="${SSMS_OFFSITE_S3_REGION:-us-east-1}"
export RCLONE_CONFIG_SECRET_TYPE=crypt
export RCLONE_CONFIG_SECRET_REMOTE="target:$SSMS_OFFSITE_S3_BUCKET/ssms"
RCLONE_CONFIG_SECRET_PASSWORD="$(rclone obscure "$SSMS_OFFSITE_PASSPHRASE")"
RCLONE_CONFIG_SECRET_PASSWORD2="$(rclone obscure "$SSMS_OFFSITE_SALT")"
export RCLONE_CONFIG_SECRET_PASSWORD RCLONE_CONFIG_SECRET_PASSWORD2

# Uploaded files live on the files volume, or in the S3 store when SSMS_STORAGE_BACKEND=s3.
if [ "${SSMS_STORAGE_BACKEND:-local}" = s3 ]; then
  export RCLONE_CONFIG_FILESTORE_TYPE=s3 RCLONE_CONFIG_FILESTORE_PROVIDER=Other
  export RCLONE_CONFIG_FILESTORE_ACCESS_KEY_ID="${SSMS_S3_ACCESS_KEY:-}"
  export RCLONE_CONFIG_FILESTORE_SECRET_ACCESS_KEY="${SSMS_S3_SECRET_KEY:-}"
  export RCLONE_CONFIG_FILESTORE_ENDPOINT="${SSMS_S3_ENDPOINT_URL:-}"
  export RCLONE_CONFIG_FILESTORE_REGION="${SSMS_S3_REGION:-us-east-1}"
  files="filestore:${SSMS_S3_BUCKET:-}"
else
  files=/data
fi

copy_once() {
  # Only complete dumps: a dump being written is still named *.dump.part.
  rclone copy /backups secret:db --include 'ssms-*.dump' || return 1
  rclone cryptcheck /backups secret:db --include 'ssms-*.dump' --one-way || return 1
  # Files are copied, never synced: discarding a file on the server does not remove its off-site copy.
  rclone copy "$files" secret:files || return 1
  rclone cryptcheck "$files" secret:files --one-way || return 1
  rclone delete secret:db --min-age 90d --include 'ssms-*.dump' || return 1
}

case "${1:-run}" in
  once)
    copy_once
    echo "offsite copy complete and verified"
    ;;
  list)
    rclone lsl secret:
    ;;
  restore)
    newest=$(rclone lsf secret:db --include 'ssms-*.dump' | sort | tail -1)
    [ -n "$newest" ] || { echo "no dump off-site" >&2; exit 1; }
    rclone copy "secret:db/$newest" /restore/db
    rclone copy secret:files /restore/files
    echo "restored $newest and the files into /restore"
    ;;
  run)
    while true; do
      day=$(date +%Y%m%d)
      if [ "$(cat /state/last-ok 2>/dev/null || true)" != "$day" ] && ls /backups/ssms-"$day"-*.dump >/dev/null 2>&1; then
        if copy_once; then
          echo "$day" > /state/last-ok
          echo "offsite copy $day complete and verified"
        else
          echo "offsite copy FAILED: will retry" >&2
        fi
      fi
      sleep 600
    done
    ;;
  *)
    echo "usage: offsite.sh run|once|list|restore" >&2
    exit 2
    ;;
esac
