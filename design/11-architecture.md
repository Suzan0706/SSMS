# 11. Architecture and Deployment

## 11.1 Logical architecture

```mermaid
flowchart LR
    classDef client fill:#e8f0fe,stroke:#1a73e8,color:#0b3d91
    classDef app fill:#e6f4ea,stroke:#188038,color:#0d652d
    classDef data fill:#fef7e0,stroke:#b06000,color:#5c3900
    classDef ext fill:#f3e8fd,stroke:#8430ce,color:#4a148c

    subgraph C["Client (offline-first PWA)"]
        UI["React 18 + TypeScript<br/>Vite · Tailwind · TanStack Query<br/>React Hook Form + Zod · i18next sw/en"]:::client
        SW["Workbox service worker<br/>app shell cache"]:::client
        DX[("Dexie / IndexedDB<br/>outbox: marks, attendance<br/>reference data")]:::client
    end
    subgraph E["Edge"]
        NG["Nginx<br/>TLS · HSTS · CSP · gzip/brotli<br/>rate limits · webhook IP allow-lists"]:::app
    end
    subgraph A["Application (stateless)"]
        API["FastAPI (async)<br/>routers → services → repositories<br/>tenant dependency · require_permission"]:::app
        WK["Celery workers<br/>queues: payments, sms, pdf, imports, reports"]:::app
        BT["Celery beat<br/>absence fan-out · reminders · reconciliation"]:::app
    end
    subgraph D["Data"]
        PG[("PostgreSQL 16<br/>RLS FORCED · composite FKs<br/>triggers · PgBouncer")]:::data
        RD[("Redis 7<br/>broker · rate limits · cache")]:::data
        S3[("S3-compatible storage<br/>documents · PDFs · imports")]:::data
    end
    subgraph X["External"]
        GE["GePG"]:::ext
        MM["Mobile money / aggregators"]:::ext
        SMS["Beem Africa / NextSMS"]:::ext
        BK["Bank interface"]:::ext
    end

    UI <--> SW
    UI <--> DX
    UI -- "HTTPS JSON · JWT · ETag" --> NG --> API
    API --> PG
    API --> RD
    API --> S3
    API -. "enqueue" .-> RD
    RD -.-> WK
    BT -.-> RD
    WK --> PG
    WK --> S3
    WK -- "bill requests" --> GE
    WK -- "push requests" --> MM
    WK -- "send" --> SMS
    GE -- "callbacks" --> NG
    MM -- "callbacks" --> NG
    SMS -- "delivery reports" --> NG
    BK -- "deposit confirmations (bank portal)" --> NG
```

| Layer | Rule |
|---|---|
| Router | Parses and validates input (Pydantic v2), declares `require_permission("module.action")`, calls exactly one service method, maps errors to the single error format. No SQL. |
| Service | Business rules, transactions, idempotency, enqueuing Celery tasks **after commit**. |
| Repository | SQLAlchemy 2 async queries with explicit column lists (no `SELECT *`), cursor pagination, always tenant-scoped. |
| Database | Last line of defence: RLS, composite FKs, CHECK/EXCLUDE, triggers ([06-data-model.md](06-data-model.md)). |

## 11.2 Request lifecycle and tenant context

```mermaid
sequenceDiagram
    participant C as Client
    participant MW as Middleware
    participant DEP as Dependencies
    participant R as Router
    participant S as Service
    participant DB as PostgreSQL (ssms_app)
    C->>MW: request + Bearer JWT (+ Idempotency-Key)
    MW->>MW: request_id, gzip, CORS allow-list, rate limit (Redis)
    MW->>DEP: current_user: verify JWT (exp, sig, aud, typ)
    DEP->>DB: BEGIN · SET LOCAL app.school_id = jwt.sch, app.user_id, app.request_id, app.client_ip
    DEP->>DB: user status + school status + permissions (one query, RLS)
    DEP->>DEP: require_permission("results.publish")
    DEP->>R: inject session, user, school
    R->>S: call
    S->>DB: queries (RLS + composite FKs apply)
    S->>DB: COMMIT (deferred checks: journals balanced)
    S-)S: enqueue Celery tasks after commit
    R-->>C: 2xx/4xx in {error_code, message, details} format
```

**Background jobs.** Each Celery task receives `school_id` and opens its own transaction with the same `SET LOCAL`. Cross-school schedules (absence alerts, reminders, reconciliation) fan out per school through `list_active_school_ids()`. Every task is idempotent: it uses natural keys or `idempotency_key` with `ON CONFLICT DO NOTHING`, and retries with exponential backoff and jitter (max 5).

## 11.3 Offline-first client

```mermaid
flowchart LR
    classDef c fill:#e8f0fe,stroke:#1a73e8,color:#0b3d91
    classDef s fill:#e6f4ea,stroke:#188038,color:#0d652d
    T["Teacher edits a mark / register"]:::c --> O[("Dexie outbox<br/>{entity, key, payload, version,<br/>client_updated_at, client_record_id}")]:::c
    O --> B["Badge: Imehifadhiwa nje ya mtandao<br/>Saved offline"]:::c
    O -->|online event / timer, backoff 2^n s + jitter| Q["Sync worker (in page / SW)"]:::c
    Q -->|PUT /marks/batch · POST /attendance/sync| API["API"]:::s
    API -->|200 per item| D["Remove from outbox → badge Synced"]:::c
    API -->|409 version conflict + server value| X["Badge Conflict → user picks value"]:::c
```

- **App shell.** Workbox precaches it and keeps the initial JS under 200 KB gzipped; each role's module is lazy-loaded.
- **Reference data** (class lists, components, timetable) is cached in IndexedDB with an `ETag`, and refreshed on `If-None-Match`.
- **Marks** use optimistic concurrency (`version`). **Attendance** uses an idempotent `client_record_id`, and the last `captured_at` wins.
- **No data is lost on refresh or app close**, because the outbox persists in IndexedDB. A Playwright test covers offline → reload → sync.

## 11.4 Results day and scale

Target: **5,000 concurrent parent logins, ~500 requests/s**, pages under 3 s on 3G.

| Technique | Detail |
|---|---|
| Pre-computed results | `publish_results()` freezes everything; reads are index lookups on `(school_id, enrolment_id)` |
| Pre-rendered PDFs | Report cards rendered by Celery into object storage at publication; download via short-lived signed URL (no API CPU) |
| Lightweight endpoints | `GET /parent/children/{id}/results` returns < 5 KB JSON with `ETag`; repeat visits get 304 |
| OTP throttling | 3 OTPs per phone per 15 min, 20 per IP per hour (Redis), SMS queue with a priority lane |
| Connection pooling | PgBouncer (transaction mode) in front of PostgreSQL. `SET LOCAL` is transaction-scoped, so it is safe with transaction pooling. |
| Horizontal scale | API and worker containers scale out (stateless JWT); Nginx least-connections |
| Read replica | Reporting and analytics read from a streaming replica as `ssms_reporting` |
| Staggered SMS | "Results ready" SMS sent in batches of 200/min per school, so not everyone logs in at the same second |
| Load test | k6 spike 0 → 5,000 virtual users in 2 min; pass = p95 < 1 s, errors < 0.5 % |

## 11.5 Deployment

```mermaid
flowchart TB
    classDef node fill:#f1f3f4,stroke:#5f6368,color:#202124
    classDef art fill:#e6f4ea,stroke:#188038,color:#0d652d

    subgraph DEV["«device» Phones (Android 8+, Chrome), office PCs"]
        PWA["«artifact» SSMS PWA"]:::art
    end
    subgraph LB["«node» Edge VM — Nginx (2 vCPU)"]
        NGX["«container» nginx:1.27<br/>TLS, CSP, rate limits"]:::art
    end
    subgraph APP["«node» App VMs ×2 — Ubuntu 24.04, 4 vCPU, 8 GB (Docker)"]
        API1["«container» ssms-api (uvicorn, 4 workers)"]:::art
        WK1["«container» ssms-worker (queues: payments, sms)"]:::art
        WK2["«container» ssms-worker (queues: pdf, imports, reports)"]:::art
        BEAT["«container» ssms-beat (single instance)"]:::art
    end
    subgraph DATA["«node» Data VMs"]
        PGB["«container» pgbouncer"]:::art
        PGP["«artifact» PostgreSQL 16 primary (8 vCPU, 32 GB, SSD)"]:::art
        PGR["«artifact» PostgreSQL 16 replica (reporting, failover)"]:::art
        RED["«container» redis:7 (AOF)"]:::art
        MIN["«artifact» S3-compatible storage (MinIO or provider)"]:::art
    end
    subgraph OBS["«node» Observability"]
        PROM["Prometheus + Grafana"]:::art
        SEN["Sentry"]:::art
        LOG["JSON logs → Loki"]:::art
    end
    subgraph BK["«node» Off-site backup (second region)"]
        BAK["pgBackRest repo (encrypted), S3 replica"]:::art
    end

    PWA -- HTTPS 443 --> NGX --> API1
    API1 --> PGB --> PGP
    WK1 --> PGB
    WK2 --> PGB
    PGP -- streaming replication --> PGR
    API1 --> RED
    WK1 --> RED
    WK2 --> RED
    BEAT --> RED
    API1 --> MIN
    WK2 --> MIN
    PGP -- WAL + nightly full --> BAK
    MIN -- replication --> BAK
    API1 -.-> SEN
    API1 -.-> PROM
    WK1 -.-> LOG
```

- **Environments:** `dev` (docker-compose on a laptop), `staging` (one VM, anonymised data), `production` (above).
- **Hosting:** in a Tanzanian data centre where possible (PDPA cross-border rules — **VERIFY** contracts).
- **CI/CD (GitHub Actions):**
  - lint (ruff, eslint), type-check (mypy, tsc);
  - pytest with coverage ≥ 80 % on services;
  - the SQL tests in `design/sql/tests` against a PostgreSQL 16 service container, run as `ssms_app`;
  - `alembic check`, Playwright, bundle size < 200 KB;
  - ZAP baseline, `pip-audit` / `npm audit`;
  - build images → staging → manual approval → production.
- **Backups:** WAL archiving (RPO ≤ 15 min), nightly full, 35-day retention, quarterly restore drill (RTO ≤ 4 h).
- **Secrets:** environment variables injected from the host secret store. Never in images or git.

## 11.6 Architecture decisions

Full records (context, decision, consequences, evidence): [adr/](adr/README.md). Phase 1 added [0011](adr/0011-permissions-per-request.md) permissions per request, [0012](adr/0012-synchronous-onboarding.md) synchronous onboarding and [0013](adr/0013-all-or-nothing-imports.md) all-or-nothing imports.

| ADR | Decision | Main reason |
|---|---|---|
| 0001 | Shared schema + `school_id` + forced RLS + composite FKs (pool model) | Cheapest for many small schools; three independent isolation layers |
| 0002 | Resolver functions (SECURITY DEFINER, ids only) for pre-tenant lookups | Webhooks, devices, OTP and cookies arrive before the school is known |
| 0003 | UUIDv7 generated in the API | Ids known offline; time-ordered B-tree inserts |
| 0004 | Business rules duplicated in the DB (EXCLUDE, triggers) and the services | Correct under concurrency and against buggy clients; friendly errors from services |
| 0005 | Frozen results + amendments instead of updates | Legal record; audit; maker-checker |
| 0006 | Double-entry ledger with deferred balance check | Reconciliation and auditor trust |
| 0007 | Webhooks acknowledge fast; Celery does allocation/PDF/SMS | < 2 s callback SLA; retries are idempotent |
| 0008 | Optimistic concurrency (`version`) for marks, `client_record_id` for attendance | Offline-first on weak networks without lost updates |
| 0009 | Provider adapters (`PaymentGateway`, `SmsGateway`) | Swap Beem/NextSMS or aggregators by configuration |
| 0010 | Application-level encryption + HMAC blind index | PDPA; DB dumps do not reveal phones or NIDA |
