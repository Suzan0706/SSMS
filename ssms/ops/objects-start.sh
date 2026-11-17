#!/bin/sh
# Starts SeaweedFS as the S3-compatible file store (docker compose --profile objects).
# Access requires the key pair from .env; the identity file is written inside the container, never to the disk.
set -eu
umask 077
cat > /tmp/s3.json <<JSON
{"identities": [{"name": "ssms", "credentials": [{"accessKey": "${SSMS_S3_ACCESS_KEY}", "secretKey": "${SSMS_S3_SECRET_KEY}"}],
  "actions": ["Read", "Write", "List", "Tagging", "Admin"]}]}
JSON
exec weed server -dir=/data -s3 -s3.port=8333 -s3.config=/tmp/s3.json -master.volumeSizeLimitMB=1024
