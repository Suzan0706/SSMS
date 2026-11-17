# 10. System Architecture

## 10.1 Three-tier architecture

```mermaid
flowchart LR
    classDef client fill:#e8f0fe,stroke:#1a73e8,color:#0b3d91
    classDef app fill:#e6f4ea,stroke:#188038,color:#0d652d
    classDef data fill:#fef7e0,stroke:#b06000,color:#5c3900
    classDef ext fill:#f3e8fd,stroke:#8430ce,color:#4a148c

    subgraph T1["Tier 1 — Presentation"]
        PWA["React + Tailwind PWA<br/>Kiswahili / English<br/>service worker cache"]:::client
    end
    subgraph T2["Tier 2 — Application"]
        NGINX["Nginx<br/>TLS · HSTS · rate limit · static files"]:::app
        API["FastAPI (Uvicorn workers)<br/>/api/v1 · OpenAPI /docs"]:::app
        WORKER["Celery workers<br/>SMS · GePG · reports"]:::app
        BEAT["Celery beat<br/>fee reminders 08:00 EAT"]:::app
    end
    subgraph T3["Tier 3 — Data"]
        PG[("PostgreSQL 16<br/>3NF schema · triggers · views")]:::data
        REDIS[("Redis<br/>Celery broker + results")]:::data
        OBJ[("Object storage (MinIO / S3)<br/>requirement documents, report files")]:::data
    end
    GEPG["GePG"]:::ext
    SMSGW["Bulk SMS gateway"]:::ext

    PWA -- "HTTPS JSON + JWT" --> NGINX --> API
    API --> PG
    API -- "enqueue" --> REDIS --> WORKER
    BEAT --> REDIS
    WORKER --> PG
    API --> OBJ
    WORKER --> OBJ
    WORKER -- "signed XML" --> GEPG
    GEPG -- "payment callback" --> NGINX
    WORKER --> SMSGW
```

| Tier | Responsibility | Technology |
|---|---|---|
| Presentation | Screens, input validation for usability, offline cache of read-only data (timetable, results, invoices), language switch | React 18, Tailwind CSS, React Query, i18next, Workbox PWA |
| Application | Authentication, role checks, business rules (services), REST API, background jobs | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Celery |
| Data | Integrity rules (constraints, triggers), audit, derived views, files | PostgreSQL 16, Redis 7, MinIO/S3 |

**Why this split.** Every hard rule is enforced twice: once by the service, for a friendly bilingual message, and once by PostgreSQL (EXCLUDE, CHECK, FK, triggers). Data therefore stays correct even with concurrent users or a future second client, such as a mobile app. Slow or unreliable work (SMS, GePG, PDF generation) runs in Celery, so API responses stay fast on school internet connections.

## 10.2 Backend layering

```mermaid
flowchart TB
    R["routers/ — HTTP: paths, status codes, role dependencies"]
    S["schemas/ — Pydantic v2: validation, phone normalisation, bilingual errors"]
    SV["services/ — business rules: enrolment, scheduling, payments, status"]
    M["models/ — SQLAlchemy 2 ORM mapping of db/schema.sql"]
    I["integrations/ — GePG adapter"]
    T["tasks/ — Celery: SMS, control numbers, reminders"]
    DB[("PostgreSQL")]
    R --> S
    R --> SV
    SV --> M --> DB
    SV --> I
    R -. "enqueue after commit" .-> T
    T --> SV
```

Routers stay thin: they check roles, call one service function, commit, then enqueue notifications. The commit comes first so an SMS is never sent for a change that was rolled back. Source: [backend/app/](../backend/app/).

## 10.3 Deployment diagram

```mermaid
flowchart TB
    classDef node fill:#f1f3f4,stroke:#5f6368,color:#202124
    classDef art fill:#e6f4ea,stroke:#188038,color:#0d652d

    subgraph Users["«device» Phones, laptops, school office PCs"]
        BROWSER["«artifact» PWA in Chrome / Edge / Firefox"]:::art
    end

    subgraph VPS["«node» App server — Ubuntu 24.04 LTS, 4 vCPU, 8 GB RAM (data centre in Tanzania or region)"]
        subgraph DOCKER["«execution environment» Docker Engine + Compose"]
            NG["«container» nginx:1.27<br/>:443 TLS (Let's Encrypt)"]:::art
            APIc["«container» sms-api<br/>uvicorn app.main:app --workers 4 --proxy-headers"]:::art
            WK["«container» sms-worker<br/>celery -A app.tasks.celery_app worker"]:::art
            BT["«container» sms-beat<br/>celery -A app.tasks.celery_app beat"]:::art
            RD["«container» redis:7"]:::art
            MN["«container» minio (documents)"]:::art
        end
    end

    subgraph DBN["«node» Database server — Ubuntu 24.04, 4 vCPU, 16 GB RAM, SSD"]
        PGP["«artifact» PostgreSQL 16 primary"]:::art
        BK["«artifact» pgBackRest<br/>WAL archive + nightly full backup (encrypted)"]:::art
    end
    subgraph DR["«node» Off-site backup (different region / provider)"]
        BKS["«artifact» Encrypted backup repository"]:::art
    end

    BROWSER -- "HTTPS 443" --> NG
    NG --> APIc
    APIc -- "TCP 5432, TLS" --> PGP
    WK -- "TCP 5432, TLS" --> PGP
    APIc --> RD
    WK --> RD
    BT --> RD
    APIc --> MN
    PGP --> BK -- "S3 / SSH" --> BKS
    WK -- "HTTPS" --> EXT1["«external» GePG"]
    WK -- "HTTPS" --> EXT2["«external» SMS gateway"]
    EXT1 -- "HTTPS callback" --> NG
```

A small school can run everything on one server: drop the separate database node and keep the off-site backup. A large school or a district can scale the API and worker containers horizontally behind Nginx, because the API is stateless (JWT) and all state lives in PostgreSQL, Redis and object storage.

## 10.4 Example `docker-compose.yml`

A starting point for staging. It has not been run as part of this design, so review the values before use.

```yaml
# File: deploy/docker-compose.yml
services:
  api:
    build: ../backend
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --proxy-headers --forwarded-allow-ips="*"
    env_file: ../backend/.env
    depends_on: [redis]
    restart: unless-stopped
  worker:
    build: ../backend
    command: celery -A app.tasks.celery_app worker --loglevel=INFO --concurrency=4
    env_file: ../backend/.env
    depends_on: [redis]
    restart: unless-stopped
  beat:
    build: ../backend
    command: celery -A app.tasks.celery_app beat --loglevel=INFO
    env_file: ../backend/.env
    depends_on: [redis]
    restart: unless-stopped
  redis:
    image: redis:7.4-alpine
    restart: unless-stopped
  minio:
    image: minio/minio:RELEASE.2024-12-18T13-15-44Z
    command: server /data
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
    volumes: [minio-data:/data]
    restart: unless-stopped
  nginx:
    image: nginx:1.27-alpine
    ports: ["80:80", "443:443"]
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ../frontend/dist:/usr/share/nginx/html:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro
    depends_on: [api]
    restart: unless-stopped
volumes:
  minio-data:
```

## 10.5 Operational concerns

| Concern | Decision |
|---|---|
| Configuration | Environment variables with the `SMS_` prefix ([backend/.env.example](../backend/.env.example)); the app refuses to start in production with the default JWT secret |
| Migrations | `alembic upgrade head` on deploy; the baseline runs `db/schema.sql`. `alembic check` in CI fails if ORM models drift from the database |
| Logs | JSON logs to stdout, collected by the host. Each log line and the `X-Request-ID` header carry the same id as `audit_logs.request_id` |
| Monitoring | `/health` uptime check every minute; PostgreSQL slow-query log (> 500 ms); Celery queue length alert (> 500) |
| Backups | pgBackRest: WAL archiving (RPO ≤ 15 min) and a nightly full backup, AES-256 encrypted, with an off-site copy; quarterly restore drill |
| Time | Servers in UTC; UI and SMS in EAT (UTC+3, no daylight saving) |
| Low bandwidth | Gzip/Brotli at Nginx, paged lists (25 rows), PWA caches timetable, results and invoices for offline reading |
