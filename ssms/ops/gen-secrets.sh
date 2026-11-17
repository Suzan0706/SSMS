#!/bin/sh
# Writes a new ssms/.env from .env.example with fresh random secrets (design/18.2). Never prints a secret and
# never overwrites an existing file. Then edit the non-secret values (domain, providers) in the new file.
#   sh ssms/ops/gen-secrets.sh            -> ssms/.env
#   sh ssms/ops/gen-secrets.sh other.env  -> ssms/other.env
set -eu
cd "$(dirname "$0")/.."
out=${1:-.env}
if [ -e "$out" ]; then echo "$out already exists: not overwritten" >&2; exit 1; fi
umask 077
hex() { openssl rand -hex "$1"; }            # hex: safe inside database URLs
b64() { openssl rand -base64 32; }           # 32 random bytes, as the encryption and blind-index keys need
sed -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(hex 24)|" \
    -e "s|^SSMS_APP_DB_PASSWORD=.*|SSMS_APP_DB_PASSWORD=$(hex 24)|" \
    -e "s|^SSMS_CONSOLE_DB_PASSWORD=.*|SSMS_CONSOLE_DB_PASSWORD=$(hex 24)|" \
    -e "s|^SSMS_JWT_SECRET=.*|SSMS_JWT_SECRET=$(hex 48)|" \
    -e "s|^SSMS_ENC_KEYS=.*|SSMS_ENC_KEYS=1:$(b64)|" \
    -e "s|^SSMS_BLIND_INDEX_KEY=.*|SSMS_BLIND_INDEX_KEY=$(b64)|" \
    -e "s|^SSMS_SMS_WEBHOOK_SECRET=.*|SSMS_SMS_WEBHOOK_SECRET=$(hex 32)|" \
    -e "s|^SSMS_MOBILE_WEBHOOK_SECRET=.*|SSMS_MOBILE_WEBHOOK_SECRET=$(hex 32)|" \
    -e "s|^SSMS_METRICS_TOKEN=.*|SSMS_METRICS_TOKEN=$(hex 32)|" \
    -e "s|^SSMS_S3_ACCESS_KEY=.*|SSMS_S3_ACCESS_KEY=ssms$(hex 8)|" \
    -e "s|^SSMS_S3_SECRET_KEY=.*|SSMS_S3_SECRET_KEY=$(hex 32)|" \
    -e "s|^SSMS_OFFSITE_PASSPHRASE=.*|SSMS_OFFSITE_PASSPHRASE=$(hex 32)|" \
    -e "s|^SSMS_OFFSITE_SALT=.*|SSMS_OFFSITE_SALT=$(hex 32)|" \
    .env.example > "$out"
if grep -qE "change-me|REPLACE_WITH" "$out"; then echo "a placeholder was left in $out" >&2; exit 1; fi
echo "Wrote ssms/$out with new secrets (not shown). Keep a copy of SSMS_ENC_KEYS and SSMS_BLIND_INDEX_KEY in"
echo "the organisation's secret manager: without them phone numbers, NIDA numbers and health notes cannot be read."
echo "Do the same with SSMS_OFFSITE_PASSPHRASE and SSMS_OFFSITE_SALT: without them off-site backups cannot be read."
