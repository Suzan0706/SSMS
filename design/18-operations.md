# 18. Deployment and operations

This chapter is the runbook for people who install and run SSMS: first installation, secrets, TLS, upgrades,
backups and the restore drill, key rotation, monitoring, and what to do when a provider is down. Commands assume
the single-server stack in [`ssms/docker-compose.yml`](../ssms/docker-compose.yml); a managed database or several
API hosts change the commands, not the steps.

## 18.1 What runs

| Service | Image | Purpose | Scale |
|---|---|---|---|
| `db` | postgres:16.9 | All school data, RLS per school | One primary; managed PostgreSQL 16 with PITR preferred |
| `redis` | redis:7.4 | Celery broker, rate limits | One; data is disposable |
| `migrate` | ssms-api | `alembic upgrade head`, then the runtime logins | One-shot on every release |
| `api` | ssms-api | FastAPI, `WEB_CONCURRENCY` workers | Add workers, then hosts behind the load balancer |
| `worker` | ssms-api | Celery tasks: SMS, payments, imports, exports, reports | Add replicas when the queue grows |
| `beat` | ssms-api | Schedules: absence alerts every 5 min (Mon–Fri 08:00–12:59), fee reminders 09:00, library 10:00 (EAT) | **Exactly one** |
| `backup` | postgres:16.9 | One `pg_dump` per calendar day (checked every 10 min, written atomically), 14 days kept | One |
| `web` | ssms-web (Nginx) | PWA and the same-origin `/api` proxy; trusts `X-Forwarded-For` only from `SSMS_TRUSTED_PROXY` | Behind TLS termination |
| `edge` (profile `edge`) | caddy:2.10 | HTTPS on 80/443, automatic certificates, `/metrics` closed | One per server; or a load balancer instead |
| `clamav` (profile `antivirus`) | clamav/clamav:1.4.3 | Scans every upload before it is stored; about 1.5 GB memory | One |
| `objects` (profile `objects`) | seaweedfs:4.48 | S3-compatible file store; or a cloud S3 store instead | One; required for several API hosts |

All long-running services restart on failure (`unless-stopped`) and keep at most 5 × 20 MB of logs each. `worker`
answers a Celery ping as its health check; `beat` has none (it is the container's only process, so the container
stops with it and restarts).

Sizing for the first 50–100 schools (**VERIFY with the k6 staging run**, [16-test-plan.md](16-test-plan.md#164-automated-suites-phase-1)):
API host 4 vCPU / 8 GB (`WEB_CONCURRENCY=4`), worker 2 vCPU / 4 GB, PostgreSQL 4 vCPU / 16 GB with SSD. The local
measurements (one Windows process) are in [17-corrections.md §17.9](17-corrections.md#179-defects-and-decisions-in-phase-6).

## 18.2 First installation

1. `sh ssms/ops/gen-secrets.sh` writes `ssms/.env` from `.env.example` with new random secrets (never printed;
   database passwords are hex, because `/` or `+` from base64 would break the connection URLs). Then edit the
   non-secret values: `SSMS_DOMAIN`, `SSMS_ACME_EMAIL`, `SSMS_CORS_ORIGINS=["https://<domain>"]`, the SMS, email
   and payment providers. Keep the file readable by root only and store a copy in the organisation's secret
   manager — **losing `SSMS_ENC_KEYS` makes phones, NIDA numbers and health notes unreadable**.
2. Put the GePG SP certificate (PEM) in `SSMS_GEPG_PRIVATE_KEY` and GePG's public key in `SSMS_GEPG_PUBLIC_KEY`
   (VERIFY the format with GePG). The API refuses to start in production without them, with the simulator, with a
   console SMS provider or with a short webhook secret.
3. `docker compose -f ssms/docker-compose.yml --env-file ssms/.env --profile edge --profile antivirus up -d --build`
   (add `--profile objects` with `SSMS_STORAGE_BACKEND=s3` for the local object store). `migrate` creates the schema
   and the runtime logins; `api` waits for it. The first ClamAV start downloads its signatures (a few minutes).
   Production refuses to start without a scanner unless `SSMS_ALLOW_UNSCANNED_UPLOADS=true` is set on purpose.
4. `docker compose ... run --rm api python -m app.cli deploy-check`: file storage round trip (creates the S3 bucket)
   and the scanner catching the EICAR test string. It must print `deploy-check passed`.
5. Create the first console administrator: `docker compose run --rm api python -m app.cli create-platform-admin --email <ops email> --name "<name>"`
   (prints the TOTP provisioning URI once), sign in to the console and register the first school.
6. Give the providers their callback URLs: GePG `https://<host>/api/v1/webhooks/gepg/bill|payment`; the
   mobile-money aggregator `https://<host>/api/v1/webhooks/{mpesa|tigopesa|airtel|halopesa}` with the HMAC secret;
   the SMS provider `https://<host>/api/v1/webhooks/sms/{beem|nextsms}?token=<SSMS_SMS_WEBHOOK_SECRET>`. Restrict
   `/api/v1/webhooks/` to the providers' IP ranges at the load balancer.
7. Top up each school's SMS credit from the console (`POST /platform/schools/{id}/sms-credit`) after payment.

Never run the `seed` profile on a real installation (fake ciphertexts, demo passwords).

## 18.3 TLS and the edge

**Single server:** the `edge` profile runs Caddy on ports 80 and 443. It obtains and renews the certificate for
`SSMS_DOMAIN` itself (`SSMS_TLS=internal` uses its own CA for test installs), sends HSTS, closes `/metrics` and
forwards to `web`. Set `SSMS_WEB_BIND=127.0.0.1` so the plain port 8080 is not reachable from the network.

**Load balancer instead:** terminate TLS 1.2+ there, forward to port 8080, and set `SSMS_TRUSTED_PROXY` to the
balancer's address as `web` sees it (one address or a CIDR).

**Client addresses.** `web` takes the client address from `X-Forwarded-For` only when the request comes from
`SSMS_TRUSTED_PROXY`, and passes exactly one address to the API. Anyone else's header is ignored, so nobody can
choose their own address to escape the per-address sign-in limits or to write a false address into the audit log
(design/21, finding F7). The edge proxy has a fixed address on its own network (`SSMS_EDGE_SUBNET`, default
172.31.250.0/24); change both settings together if that subnet is already used on the host.

Set `SSMS_CORS_ORIGINS` to the public origin. The API port is reachable only on the private network. Request
bodies are limited to 21 MB at Nginx; the API applies each upload type's own limit (photos 300 KB, documents
10–20 MB, imports 10 MB).

## 18.4 Releases and upgrades

Migrations are forward-only (each Alembic revision runs one SQL file under `SET ROLE ssms_owner`).

1. Read the release notes and `design/17-corrections.md` for the new phase; check new settings in the README.
2. Take a fresh backup (`docker compose exec backup sh -c 'pg_dump -h db -U postgres -d ssms -Fc -f /backups/pre-release.dump'`).
3. `docker compose pull && docker compose up -d migrate` — wait for it to finish successfully.
4. `docker compose up -d api worker beat web`. Workers finish their current task before stopping (SIGTERM).
5. Run `python -m app.cli deploy-check` (as in 18.2), then check `/health/ready`, the error rate on the dashboard and one
   sign-in per role.

Rollback = deploy the previous images **and** restore the pre-release backup if the migration changed data; there
are no down-migrations.

## 18.5 Backups and the restore drill (NFR-06)

* **Daily logical backup** by the `backup` service (`/backups/ssms-YYYYMMDD-HHMM.dump`, 14 days). It checks the
  clock every 10 minutes and makes the day's dump if it is missing, so restarts and a paused host never skip a day
  (the earlier "dump, then sleep 24 hours" loop slipped by days on a machine that sleeps); a dump appears under its
  final name only when complete. A backup on the same disk is not a backup: see the off-site copies below.
* **RPO 15 minutes** needs continuous WAL archiving: use a managed PostgreSQL with point-in-time recovery, or
  pgBackRest with `archive_mode=on` to object storage. The nightly dump alone gives RPO 24 h.
* **Uploaded files** (`files` volume, or the S3 bucket: documents, photos, report cards, exports) are not in the
  dump; the off-site copies below include them.
* **Off-site copies** (profile `offsite`, `ssms/ops/offsite.sh` in the rclone image): once a day, after that day's
  dump exists, the dumps and every uploaded file are copied to an S3 bucket at another provider or in another region
  (`SSMS_OFFSITE_S3_*`). Contents and file names are encrypted on this server before they leave it (rclone `crypt`,
  keys `SSMS_OFFSITE_PASSPHRASE` and `SSMS_OFFSITE_SALT`), so the store only ever holds ciphertext. Each copy is
  verified against the source (`cryptcheck`) before it counts; files are copied, never synced, so a file discarded
  on the server keeps its off-site copy; dumps off-site are kept 90 days. The service is healthy only after a
  verified copy in the last 26 hours. **Keep the passphrase and salt outside this server** (secret manager): with
  the server lost, they and `SSMS_ENC_KEYS` are what make the copies usable.

  Restore from off-site onto a new server: `docker compose ... --profile offsite run --rm -v /srv/restore:/restore
  offsite restore` puts the newest dump in `/srv/restore/db` and all files in `/srv/restore/files`; then
  `pg_restore` the dump into the new database and copy the files into the `files` volume (or the S3 bucket).
  Tested 2026-11-02 with a throwaway S3 store: the restored dump was byte-identical and `pg_restore` read all 128
  tables; a photo restored byte-identical from the files volume and two files from an S3 file store; the store
  showed only encrypted names; a wrong passphrase showed nothing.

Quarterly restore drill (RTO 4 h), recorded in the operations log:

```bash
sh ssms/ops/restore-drill.sh ssms ssms/.env
```

It restores the newest dump into a scratch database next to the live one, warns if that dump is more than 26
hours old, checks that every journal balances, compares row counts of the main tables with the live database,
checks that row-level security came back, prints the time taken and drops the scratch copy. The live database
is only read. First run on the local stack (2026-11-02): 10 s, all checks passed. For a full drill also start a
throwaway API on the restored copy (same `SSMS_ENC_KEYS`) and check a sign-in, a student's phone number and a
receipt PDF.

## 18.6 Key and secret rotation

| Secret | How to rotate | Effect |
|---|---|---|
| `SSMS_ENC_KEYS` | Add `2:<new key>` next to `1:…`, set `SSMS_ENC_ACTIVE_KEY_ID=2`, restart. New writes use key 2; old values stay readable with key 1. **Never remove an old key** while data encrypted with it exists (no bulk re-encryption tool yet). | None for users |
| `SSMS_BLIND_INDEX_KEY` | Not rotatable without re-indexing every phone/NIDA/birth-certificate hash | Lookups break |
| `SSMS_JWT_SECRET` | Replace and restart | Access tokens stop working; browsers get new ones with the refresh cookie (stored hashed in the database), so users stay signed in. To sign everybody out, also revoke the refresh tokens |
| Webhook secrets, metrics token | Agree a switch time with the provider, update, restart | Callbacks fail in between (providers retry) |
| Database passwords | `python -m app.cli db-logins` with the new values, update `.env`, restart | Short restart |

## 18.7 Monitoring and alerts (NFR-13)

* **Metrics**: `GET /metrics` on every API container (Prometheus format; `PROMETHEUS_MULTIPROC_DIR` adds up the
  workers). Series: `ssms_http_requests_total{method,route,status}`, `ssms_http_request_seconds_bucket{method,route}`
  (route = template, e.g. `/students/{student_id}`). Sample scrape configuration and alert rules:
  [`ssms/ops/prometheus.yml`](../ssms/ops/prometheus.yml), [`ssms/ops/alerts.yml`](../ssms/ops/alerts.yml)
  (5xx > 1 %, GET p95 > 300 ms, callbacks p95 > 2 s, Celery backlog > 1,000, API down, disk < 15 %).
* **Logs**: one JSON object per line on stdout (`SSMS_LOG_FORMAT=json`), each request with its `rid` (also returned
  as `X-Request-ID`), method, path, status and duration. Ship them to the log store; keep 90 days.
* **Errors**: set `SSMS_SENTRY_DSN` to report exceptions; request bodies, cookies, query strings, authorization and
  signature headers are removed before sending.
* **Business checks** on the school dashboards: SMS credit below 100 (in-app notice to `sms.manage`), open
  data-subject requests and their due dates, reconciliation exceptions.

## 18.8 Incidents

| Situation | What happens | What to do |
|---|---|---|
| GePG unreachable | `gepg.submit` retries with backoff; control numbers wait | Tell bursars to accept cash/bank; check `GatewayUnavailable` in logs |
| SMS provider down | Messages stay QUEUED and retry; credit is debited once | Switch `SSMS_SMS_PROVIDER` to the other provider if the outage lasts |
| Celery backlog | Alerts, receipts and exports are late | Add `worker` replicas; check Redis memory |
| Database full / slow | API errors 5xx | Check disk alert, long queries (`pg_stat_activity`), vacuum |
| Suspected data leak | — | Revoke sessions (`SSMS_JWT_SECRET` rotation), keep the audit log, follow the PDPA breach-notification duty (**VERIFY** time limit) |
| Wrong publication of results | Results are frozen | Use amendments (maker-checker); never edit the database |

## 18.9 Data retention and privacy

Data-subject requests are answered from the Privacy screen within 30 days (**VERIFY** the PDPA regulations):
EXPORT produces one JSON file; DELETE anonymises the person while ledgers, receipts and published results stay, as
the law requires. Audit logs are append-only, kept for at least 7 years and never purged earlier; the system has no purge job, so today they stay for the life of the school record (**VERIFY** the legal period with the ministry). Exports and compliance files are audited (`EXPORT`).

## 18.10 Install drill (before go-live and after changing the stack)

Proves the steps in 18.2 on an empty stack, in production mode, next to any running one (own project name, own ports
and edge subnet), then removes it:

```bash
sh ssms/ops/gen-secrets.sh .env.drill        # then in it: SSMS_DOMAIN=localhost, SSMS_TLS=internal,
                                             # SSMS_WEB_PORT=8081, SSMS_EDGE_SUBNET=172.31.251.0/24,
                                             # SSMS_TRUSTED_PROXY=172.31.251.10, SSMS_STORAGE_BACKEND=s3
C="docker compose -p ssms-drill -f ssms/docker-compose.yml --env-file ssms/.env.drill --profile edge --profile antivirus --profile objects"
$C up -d                                     # wait until clamav is healthy (signatures)
$C run --rm --no-deps api python -m app.cli deploy-check
$C run --rm --no-deps -T api python - < ssms/ops/install-drill.py
sh ssms/ops/restore-drill.sh ssms-drill ssms/.env.drill
$C down -v && rm ssms/.env.drill             # only the drill's own volumes
```

`install-drill.py` creates a console administrator, signs in with the authenticator code (and checks a sign-in
without it is refused), registers a school, signs in as its administrator and changes the temporary password,
uploads a clean photo (scanned, stored in the object store, read back) and a Word document carrying the EICAR test
file (refused by ClamAV), and finds the school on the console dashboard. Secrets stay in memory; only results are
printed. Also check by hand: `http://` redirects to `https://`, `/metrics` answers 404 at the edge, a forged
`X-Forwarded-For` does not appear in the API's access log, and the object store refuses a wrong key.

First run, 2026-11-02 (one laptop, Docker Desktop): all checks passed after five fixes the drill found — the client
address could be forged (F7), pages lacked CSP and framing headers (F8), the console lost its database role after a
failed request (F9), the first backup of a new install was empty and nightly backups slipped (F10), nginx kept the
API's old address after a redeploy (F11); see design/21. ClamAV used about 920 MB after loading 3.6 million
signatures; the restore drill took 54 s.

## 18.11 Go-live checklist

Done and tested on this project: everything in 18.2–18.10. What only the operator can do, in this order:

| # | Step | How to check it |
|---|---|---|
| 1 | A server (4 vCPU / 8 GB to start, 18.1) with a public name pointing at it; ports 80 and 443 open | `dig <domain>` shows the server |
| 2 | `gen-secrets.sh`, then the domain, `SSMS_ACME_EMAIL`, `SSMS_CORS_ORIGINS`, `SSMS_WEB_BIND=127.0.0.1`; secrets copied to the secret manager | 18.2 |
| 3 | Start with `--profile edge --profile antivirus --profile offsite` | Caddy's log shows the certificate obtained; `https://<domain>` has a valid certificate (the drill used Caddy's internal CA, so this is the first real one) |
| 4 | Off-site bucket at another provider or region; `SSMS_OFFSITE_*` | `offsite` turns healthy within a day; `offsite.sh list` shows the dump |
| 5 | SMTP account (`SSMS_EMAIL_PROVIDER=smtp`, host, port 587 or 465, user, password) | Announcements page → "send me a test email" arrives; history shows SENT. Tested against a real SMTP server with STARTTLS and with implicit TLS; a certificate that does not verify is refused |
| 6 | SMS account (Beem or NextSMS) | Endpoints and payloads are **VERIFY** items in `app/services/sms.py`: confirm them with the provider's documentation and send one SMS to a staff phone |
| 7 | GePG registration and keys; mobile-money aggregator contract | **VERIFY** items (design/12, ADR 0016): run one control number and one payment end to end in the provider's test environment |
| 8 | `deploy-check`, `create-platform-admin`, first school from the console | 18.2 steps 4–5 |
| 9 | k6 results-day run against a staging copy (raise `SSMS_LOGIN_ATTEMPTS_PER_MINUTE` there or use several load generators: all k6 users sign in from one address) | design/21 §21.3 targets |
| 10 | UAT with school staff, one role at a time | design/16 §16.5, signed by the head teacher |
| 11 | First restore drill on the server, then quarterly | 18.5 |
