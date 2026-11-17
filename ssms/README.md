# SSMS — multi-school management system (Phases 1–6, extension phases 1–13)

Multi-tenant Smart School Management System for Tanzania: FastAPI + async SQLAlchemy 2 + PostgreSQL 16 (Row-Level
Security), Redis/Celery, and a React PWA in Kiswahili and English. The design, schema and decisions are in
[`../design`](../design/README.md) (ADRs: [`../design/adr`](../design/adr/README.md)).

Phase 1 delivers: configuration, the single error format, authentication (staff password, parent SMS code,
rotating refresh cookie), RBAC, tenant isolation, audit trail, the super-admin console with school onboarding,
school settings, users and roles, staff, departments, students, guardians, consent, bulk import, background jobs,
and the web app for these screens.

Phase 2 (Academics) adds: academic configuration (years, terms, holidays, classes, streams, subjects,
combinations, rooms, versioned grading schemes, assessment components with weight check), the enrolment workflow
(public offerings, applications, documents, validation, approval, promotions), teaching assignments, timetable
(live clash check, generator), exams, offline marks entry with versioned sync and Excel upload, the validation
firewall, publication, frozen results with maker-checker amendments, report-card PDFs (ReportLab), results SMS,
analytics, and the web screens for all of it. API changes against the design are listed in
[`design/12-api-design.md` §12.3](../design/12-api-design.md#123-phase-2-implementation-notes).

Phase 3 (Finance) adds: fee items and structures with approval, discounts, invoice generation with installments,
GePG control numbers (signed XML; simulator in development), mobile-money callbacks and push prompts, cash and
bank-slip entry, bank-deposit confirmation, automatic allocation, a double-entry ledger, gapless receipts with the
amount in words, maker-checker reversals, daily reconciliation, aging/defaulters/collections reports (Excel),
overdue reminders, the parent statement and pay prompt, and the web screens (Fees, Bank, parent home). API
changes: [§12.4](../design/12-api-design.md#124-phase-3-implementation-notes); channels:
[ADR 0016](../design/adr/0016-payment-channels.md).

Phase 4 (Attendance and communication) adds: morning registers taken offline with conflict-safe sync, RFID/QR
gate devices and cards, attendance reports (Excel) and the chronic-absence list, absence SMS on recorded evidence
only, SMS credit (debit, skip, refund, low-credit notice, console top-up), delivery reports, announcements with
optional SMS, the in-app inbox, editable templates, the SMS log, and the parent and student homes. API changes:
[§12.5](../design/12-api-design.md#125-phase-4-implementation-notes); decisions:
[ADR 0017](../design/adr/0017-absence-evidence.md), [ADR 0018](../design/adr/0018-sms-credit-ledger.md).

Phase 5 (Facilities and student life) adds: hostels, rooms, accommodation requests and allocations, buses, routes
and stops with transport assignments (boarding and transport fees on the term invoice), venue bookings, discipline
records with parent SMS, clubs and memberships, the library with loans and overdue reminders, consented and
encrypted health records, and their screens. API changes:
[§12.6](../design/12-api-design.md#126-phase-5-implementation-notes); decision:
[ADR 0019](../design/adr/0019-facility-fees-on-the-term-invoice.md).

Phase 6 (Analytics and operations) adds: role dashboards, seven reports with preview and Excel/CSV/PDF export,
end-of-year compliance workbooks, data-subject requests (export, correction, anonymisation), the audit-log screen,
Prometheus metrics, JSON logs and optional Sentry, a synthetic multi-school data set with query-plan checks, k6
load scripts, and the production stack (beat, backups, alert rules). API changes:
[§12.7](../design/12-api-design.md#127-phase-6-implementation-notes); operations:
[design/18-operations.md](../design/18-operations.md); decisions: [ADR 0020](../design/adr/0020-observability.md),
[ADR 0021](../design/adr/0021-anonymise-not-delete.md).

## Layout

```text
ssms/
├── api/                     FastAPI service
│   ├── app/
│   │   ├── api/             routes: auth, platform, school, users, staff, students, imports, audit
│   │   ├── core/            config, errors, i18n, crypto, security, pagination, rate limits, storage, middleware
│   │   ├── db/              engines, sessions, per-transaction tenant context (SET LOCAL)
│   │   ├── models/          SQLAlchemy models mapped to design/sql/schema.sql
│   │   ├── schemas/         request / response models
│   │   ├── services/        business logic (auth, platform, onboarding, people, staff, students, imports, sms…)
│   │   ├── tasks/           Celery worker, task handlers, dispatcher (after-commit)
│   │   └── cli.py           operator commands (db-logins, create-platform-admin)
│   ├── migrations/          Alembic: 0001 baseline (design/sql/schema.sql), 0002 Phase 1, 0003 reference data
│   └── tests/               pytest on real PostgreSQL 16 (runtime role ssms_app)
├── web/                     React 18 + Vite + Tailwind PWA, Playwright E2E in web/e2e
├── docker-compose.yml       db, redis, migrate, api, worker, web (+ demo seed profile)
└── .env.example             every setting the stack needs
```

## Run with Docker

```bash
sh ssms/ops/gen-secrets.sh              # writes ssms/.env with new random secrets; then set the domain and providers
C="docker compose -f ssms/docker-compose.yml --env-file ssms/.env"
$C --profile edge --profile antivirus up -d --build     # HTTPS (Caddy) and virus scanning (ClamAV)
$C run --rm api python -m app.cli deploy-check          # storage round trip + scanner catches EICAR
$C run --rm api python -m app.cli create-platform-admin --email ops@example.co.tz --name "Operations"
$C --profile demo run --rm seed                         # demo data only — never on a real installation
```

Profiles: `edge` (HTTPS on 80/443 with automatic certificates), `antivirus` (ClamAV, about 1.5 GB of memory),
`objects` (SeaweedFS, an S3-compatible file store; or point `SSMS_S3_*` at a cloud store), `offsite` (encrypted
daily copies of the backups and uploaded files to another S3 store). Go-live checklist: design/18 §18.11. The full first
installation, upgrades, backups and the install and restore drills are in
[design/18-operations.md](../design/18-operations.md).

Open <http://localhost:8080>. With the demo seed, every role card on the front page has an account (school code
`mfano-sec`, password `Mfano@2026`): `admin` (school admin), `tch.laizer` (teacher), `bursar`, `reception`
(receptionist), `librarian`, `mf-2025-0014` (student), `mzazi` (parent: on the parent tab choose "sign in with a
username"; real parents use phone and SMS code). Platform console: `ops@ssms.co.tz` at `/console`.
The `migrate` service runs `alembic upgrade head` as the PostgreSQL superuser, then `python -m app.cli db-logins`
gives `ssms_app` its password and creates the console login `ssms_console`. The API and workers connect only as
`ssms_app` (NOSUPERUSER, NOBYPASSRLS); the console connects as `ssms_console` and switches to `ssms_platform`.

## Develop without Docker

Requirements: Python 3.12+, Node 20+, PostgreSQL 16 or newer.

**Windows with pgAdmin, existing database (e.g. `smart_school_db`):** run `windows\setup.bat`, then
`windows\start.bat` — see [CONNECT-DATABASE.md](CONNECT-DATABASE.md). The manual steps are below.

```bash
cd ssms/api
python -m venv .venv && . .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
createdb ssms
SSMS_MIGRATION_DATABASE_URL=postgresql+psycopg://postgres@localhost:5432/ssms alembic upgrade head
psql -d ssms -f ../../design/sql/seed.sql            # optional demo data (as a superuser; it switches roles)

export SSMS_ENVIRONMENT=development SSMS_TASKS_INLINE=true SSMS_COOKIE_SECURE=false \
       SSMS_DATABASE_URL=postgresql+psycopg://ssms_app@localhost:5432/ssms \
       SSMS_ENC_KEYS="1:$(openssl rand -base64 32)" SSMS_BLIND_INDEX_KEY="$(openssl rand -base64 32)"
uvicorn app.main:app --reload                        # API docs: http://127.0.0.1:8000/docs

cd ../web && npm install && npm run dev               # http://127.0.0.1:5173 (proxies /api to :8000)
```

`SSMS_TASKS_INLINE=true` runs background jobs inside the API process so Redis is not needed while developing;
production refuses it and uses `celery -A app.tasks.worker worker`. With the `console` SMS provider, messages
(including login codes) are written to the API log.

**Windows:** async psycopg cannot use the Proactor event loop. Start the API on a selector loop:

```python
import asyncio, uvicorn
server = uvicorn.Server(uvicorn.Config("app.main:app", port=8000, loop="none"))
asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
```

`python scripts/run_api.py` does exactly this on any system.

## Tests

```bash
cd ssms/api
SSMS_TEST_ADMIN_URL=postgresql://postgres@localhost:5432/postgres pytest --cov=app
```

The superuser URL is used only to create `ssms_test`, run the migrations and load the seed. The tests then log in
as `ssms_tester` (no privileges of its own) and every session runs `SET LOCAL ROLE ssms_app`, so all tests run
under RLS exactly as production; console tests use `SET LOCAL ROLE ssms_platform`. Each test runs in one
transaction that is rolled back. `tests/test_schema.py` also runs `design/sql/tests/*.sql` (43 database tests)
and checks that the models match the database.

Last run (2026-11-02, PostgreSQL 16.9): **289 passed, coverage 94 %** (floor 80 %); `ruff check` and
`ruff format --check` clean (also in CI).

### End-to-end tests

```bash
# API on a seeded database, SMS to the console log, tasks inline
# start the API with SSMS_LOGIN_ATTEMPTS_PER_MINUTE=60: the suite signs in more than 30 times a minute from one IP
(cd ssms/api && PORT=8000 python scripts/e2e_api.py > /path/to/api.log 2>&1 &)   # fixes the date to a school day
SSMS_API_URL=http://127.0.0.1:8000 E2E_API_LOG=/path/to/api.log npm --prefix ssms/web run e2e
```

Playwright starts `vite preview` (which proxies `/api`) and uses the installed Chrome (`E2E_BROWSER_CHANNEL`,
default `chrome`; CI uses `chromium`). The parent-login test reads the SMS code from `E2E_API_LOG`.
Last run (2026-11-02): **45 passed** on a freshly seeded database. The API and browser run on a fixed school day, so the result does
not depend on the real date. Web
build: **≈ 196 KB gzipped** in total, Phase 2–6 screens load as separate chunks (`npm run size`, budget 200 KB).

### Performance and load

```bash
# synthetic schools in a throwaway database (superuser, triggers off), then query plans as ssms_app under RLS
psql -d ssms_perf -v schools=20 -v students=1500 -v days=20 -v first=1 -f ssms/api/scripts/synthetic.sql
python ssms/api/scripts/explain.py postgresql://ssms_tester@localhost:5432/ssms_perf synth-1
# local load runner, or k6 against staging (ssms/loadtest/*.js, thresholds = NFR-03/04)
python ssms/api/scripts/loadtest.py reads --base http://127.0.0.1:8000 --users mfano-sec:<user>:<password>
python ssms/api/scripts/loadtest.py results-day --base http://localhost:8080 --term <term id> --users ...  # design/21 §21.3
k6 run -e BASE=https://staging.example -e USERS=users.csv -e TERM=<term id> ssms/loadtest/results_day.js
```

## Environment variables

All settings use the prefix `SSMS_`. Production refuses to start when a secret is missing or a development-only
option is set.

| Variable | Default | Meaning |
|---|---|---|
| `SSMS_ENVIRONMENT` | `development` | `development`, `test` or `production` (strict checks) |
| `SSMS_DATABASE_URL` | `postgresql+psycopg://ssms_app@localhost:5432/ssms` | Runtime login (must be `ssms_app` or a login that SETs ROLE to it) |
| `SSMS_DATABASE_SET_ROLE` | — | Role to switch to after connecting (local setups) |
| `SSMS_DB_POOL_SIZE` | `10` | Connections per API process |
| `SSMS_PLATFORM_DATABASE_URL` | `postgresql+psycopg://ssms_console@localhost:5432/ssms` | Console login |
| `SSMS_PLATFORM_DATABASE_SET_ROLE` | `ssms_platform` | Role the console switches to |
| `SSMS_MIGRATION_DATABASE_URL` | `postgresql+psycopg://postgres@localhost:5432/ssms` | Alembic only (creates roles and extensions) |
| `SSMS_REDIS_URL` | — | Rate limits (required in production) |
| `SSMS_CELERY_BROKER_URL` | `redis://localhost:6379/0` | Celery broker |
| `SSMS_TASKS_INLINE` | `false` | Run tasks in the API process (development/E2E only) |
| `SSMS_JWT_SECRET` | development value | ≥ 32 random characters in production |
| `SSMS_ACCESS_TOKEN_MINUTES` | `15` | Access token lifetime |
| `SSMS_REFRESH_TOKEN_DAYS` / `SSMS_PARENT_REFRESH_TOKEN_DAYS` | `7` / `30` | Refresh cookie lifetime (parents: VERIFY with schools) |
| `SSMS_SELECTION_TOKEN_MINUTES` | `5` | Parent school-choice token |
| `SSMS_COOKIE_SECURE` | `true` | `false` only for plain-http development |
| `SSMS_REFRESH_COOKIE_NAME` | `ssms_rt` | Cookie name (path `/api/v1/auth`, HttpOnly, SameSite=Strict) |
| `SSMS_ENC_KEYS` | — | Field-encryption keys `id:base64(32 bytes)`, comma-separated; keep old ids after rotation |
| `SSMS_ENC_ACTIVE_KEY_ID` | `1` | Key id used for new encryptions |
| `SSMS_BLIND_INDEX_KEY` | — | base64 ≥ 32 bytes; HMAC key for phone/NIDA/birth-certificate lookups (never rotate without re-indexing) |
| `SSMS_MAX_FAILED_LOGINS` / `SSMS_LOCKOUT_MINUTES` | `5` / `15` | Account lockout |
| `SSMS_LOGIN_ATTEMPTS_PER_MINUTE` | `10` | Per username (×3 per IP) |
| `SSMS_WEBHOOK_REQUESTS_PER_MINUTE` | `6000` | Provider callbacks per source IP |
| `SSMS_LOG_FORMAT` | `json` in production, else `text` | Log line format |
| `SSMS_SENTRY_DSN` / `SSMS_SENTRY_TRACES_SAMPLE_RATE` | — / `0` | Optional error reporting (personal data scrubbed) |
| `SSMS_METRICS_TOKEN` | — | When set, `/metrics` needs `Authorization: Bearer <token>` |
| `WEB_CONCURRENCY` / `PROMETHEUS_MULTIPROC_DIR` | `2` / — | Uvicorn workers; shared metrics directory when > 1 worker |
| `SSMS_OTP_TTL_SECONDS` / `SSMS_OTP_MAX_ATTEMPTS` | `300` / `5` | Parent SMS code |
| `SSMS_OTP_REQUESTS_PER_WINDOW` / `SSMS_OTP_WINDOW_SECONDS` | `3` / `900` | SMS code requests per phone |
| `SSMS_CORS_ORIGINS` | `["http://localhost:5173"]` | JSON list of allowed web origins |
| `SSMS_STORAGE_DIR` | `./storage` | Uploaded files and reports (local storage adapter) |
| `SSMS_STORAGE_BACKEND` | `local` | `local` or `s3` |
| `SSMS_S3_ENDPOINT_URL`, `SSMS_S3_BUCKET`, `SSMS_S3_REGION`, `SSMS_S3_ACCESS_KEY`, `SSMS_S3_SECRET_KEY` | —, —, `us-east-1`, —, — | S3-compatible store (empty endpoint = AWS); bucket and keys required in production with `s3` |
| `SSMS_CLAMAV_ADDRESS` | — | `host:port` of clamd (e.g. `clamav:3310`); uploads are scanned before they are stored |
| `SSMS_ALLOW_UNSCANNED_UPLOADS` | `false` | Production refuses to start without a scanner unless this is `true` |
| `SSMS_EMAIL_PROVIDER`, `SSMS_EMAIL_FROM`, `SSMS_SMTP_HOST`, `SSMS_SMTP_PORT`, `SSMS_SMTP_USER`, `SSMS_SMTP_PASSWORD` | `console`, …, `587` | Email; in production it is off unless `smtp` with a host |
| `SSMS_SMTP_STARTTLS` / `SSMS_SMTP_IMPLICIT_TLS` / `SSMS_SMTP_CA_FILE` | `true` / `false` / — | TLS with a verified certificate is required; implicit TLS is automatic on port 465; CA file only for a private CA |
| `SSMS_OFFSITE_S3_ENDPOINT_URL`, `_REGION`, `_BUCKET`, `_ACCESS_KEY`, `_SECRET_KEY` | — | Off-site profile: the bucket at another provider or region |
| `SSMS_OFFSITE_PASSPHRASE` / `SSMS_OFFSITE_SALT` | — | Encrypt the off-site copies; keep them outside the server |
| `SSMS_TRUSTED_PROXY` / `SSMS_EDGE_SUBNET` | `172.31.250.10` / `172.31.250.0/24` | The only proxy whose `X-Forwarded-For` nginx accepts, and its network |
| `SSMS_DOMAIN`, `SSMS_ACME_EMAIL`, `SSMS_TLS` | — | Edge profile: public name, certificate contact, or `internal` for a test certificate |
| `SSMS_WEB_BIND` / `SSMS_WEB_PORT` | `0.0.0.0` / `8080` | Plain web port; bind to `127.0.0.1` behind the edge |
| `CELERY_CONCURRENCY` | `4` | Worker processes |
| `SSMS_MAX_IMPORT_BYTES` | `10485760` | Upload limit for imports |
| `SSMS_SMS_PROVIDER` | `console` | `console` (development only), `beem`, `nextsms` |
| `SSMS_BEEM_API_KEY`, `SSMS_BEEM_SECRET_KEY` | — | Beem Africa credentials |
| `SSMS_NEXTSMS_USERNAME`, `SSMS_NEXTSMS_PASSWORD` | — | NextSMS credentials |
| `SSMS_SMS_DEFAULT_SENDER` | `SSMS` | Sender id when a school has none |
| `SSMS_SMS_WEBHOOK_SECRET` | — | Token in the delivery-report URL `/webhooks/sms/{provider}?token=…` (≥ 32 characters in production) |
| `SSMS_APP_DB_PASSWORD`, `SSMS_CONSOLE_DB_PASSWORD` | — | Used once by `python -m app.cli db-logins` |
| `SSMS_NEW_ADMIN_PASSWORD` | — | Optional, for `create-platform-admin` without a prompt |
| `SSMS_GEPG_MODE` | `simulator` | `simulator` (development: control numbers at once) or `live`; production requires `live` |
| `SSMS_GEPG_URL` | — | GePG bill submission endpoint (**VERIFY**) |
| `SSMS_GEPG_PRIVATE_KEY` / `SSMS_GEPG_PUBLIC_KEY` | — | PEM: our SP signing key / GePG verification key |
| `SSMS_GEPG_BILL_DAYS` | `30` | Control-number validity |
| `SSMS_MOBILE_WEBHOOK_SECRET` | — | HMAC-SHA256 key shared with the mobile-money aggregator (≥ 32 characters in production) |
| `SSMS_PUSH_PROVIDER` | `console` | Mobile-money push prompt: `console` (development) or `aggregator` |
| `SSMS_TEST_ADMIN_URL` | `postgresql://postgres@localhost:55433/postgres` | Tests: superuser for setup only |

## Example requests

```http
POST /api/v1/auth/login
Content-Type: application/json

{"school_code": "mfano-sec", "username": "admin", "password": "Mfano@2026"}
```

```json
200 OK   Set-Cookie: ssms_rt=…; HttpOnly; Path=/api/v1/auth; SameSite=strict
{"access_token": "eyJ…", "token_type": "bearer", "expires_in": 900,
 "user": {"id": "00000002-0000-4000-8000-000000000001", "full_name": "Halima Juma Mrisho", "username": "admin",
          "language": "sw", "must_change_password": false},
 "school": {"id": "00000001-0000-4000-8000-000000000001", "code": "mfano-sec",
            "name": "Shule ya Sekondari Mfano", "status": "ACTIVE"},
 "roles": ["school_admin"], "permissions": ["academics.configure", "audit.read", "…"]}
```

```http
POST /api/v1/students
Authorization: Bearer eyJ…

{"first_name": "Imani", "last_name": "Mollel", "gender": "F", "date_of_birth": "2013-05-20",
 "birth_cert_no": "BC-1100-2213", "stream_id": "00000013-0000-4000-8000-000000000001",
 "consent_data_processing": true,
 "guardians": [{"first_name": "Rehema", "last_name": "Mollel", "gender": "F", "phone": "0767111222",
                "relationship": "MOTHER", "is_primary": true, "sms_consent": true}]}
```

```json
201 Created
{"id": "01a1…", "admission_no": "TZ-2026-0001", "status": "ACTIVE", "has_birth_cert_no": true,
 "enrolment": {"class_code": "F1", "stream_name": "A", "academic_year": "2026", "…": "…"},
 "guardians": [{"full_name": "Rehema Mollel", "phone": "255767111222", "is_primary": true, "receives_sms": true}]}
```

Every error has one shape, in the caller's language (`Accept-Language`, default Kiswahili):

```json
422 Unprocessable Entity
{"error_code": "VALIDATION_ERROR", "message": "Taarifa ulizoweka si sahihi.",
 "details": [{"field": "guardians.0.phone", "code": "invalid_phone",
              "message": "Namba ya simu si sahihi. Mfano: 0754 123 456."}]}
```

Morning register from a phone (send again safely; a later mark from another phone wins):

```http
POST /api/v1/attendance/sync

{"items": [{"client_record_id": "8f0c…", "session_date": "2026-10-21", "stream_id": "…", "student_id": "…",
            "status": "ABSENT", "captured_at": "2026-10-21T07:45:00+03:00"}]}
```

`200 {"results": [{"client_record_id": "8f0c…", "result": "synced"}]}`; a gate reader posts
`POST /api/v1/devices/taps` with `X-Device-Key` and gets `present`, `late`, `duplicate` or `unknown_card` per tap.

Record cash (receipt at once; a repeat with the same key returns the same payment):

```http
POST /api/v1/payments
Idempotency-Key: 6f1c0e9a-2b7d-4c55-9d0e-1b8a3f2c7e41

{"student_id": "…", "channel": "CASH", "external_ref": "RB-0042", "amount_tzs": "150000.00",
 "payer_name": "Joseph Lyimo", "received_at": "2026-05-04T09:30:00+03:00"}
```

```json
201 Created
{"id": "…", "channel": "CASH", "amount_tzs": "150000.00", "allocated_tzs": "150000.00",
 "status": "CONFIRMED", "receipt": {"receipt_no": "RCT-2026-000007", "issued_at": "…"}, …}
```

Mobile money (aggregator → `POST /api/v1/webhooks/mpesa`, header `X-SSMS-Signature: sha256=<hex>`):
`{"transaction_id": "QK7…", "reference": "mfano-sec.MF-2025-0031", "amount": "50000", "msisdn": "255765000023",
"payer_name": "JOSEPH LYIMO", "timestamp": "2026-05-04T10:02:11+03:00"}` → `{"status": "ACCEPTED"}`.

Bulk import: `POST /api/v1/imports/students` (multipart `file`, header `Idempotency-Key`) → `202` job; poll
`GET /api/v1/jobs/{id}`; download `/jobs/{id}/files/errors` or `/files/result`.

## Security notes

- The school always comes from the verified token (`sch`), never from the URL or body; RLS enforces it again.
- Permissions are loaded on every request (ADR 0011): revoking a role, disabling a user or suspending a school
  takes effect immediately.
- Phones, NIDA and birth-certificate numbers are encrypted per field (AES-256-GCM) with keyed blind indexes;
  they are masked in responses unless the caller's role needs them; clear identifiers are read only through an
  audited endpoint.
- Passwords: Argon2id. Refresh tokens: random, stored as SHA-256, rotated on every use; reuse revokes the family.
  Parent codes: 6 digits, keyed hash, 5 attempts, 5 minutes, rate limited, same answer for unknown phones.
- Logs never contain secrets; the development console SMS provider logs message text and is refused in production.
