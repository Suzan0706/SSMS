# SSMS — Smart School Management System (design)

Multi-tenant, offline-first school management for Tanzania, built with FastAPI, PostgreSQL 16 and a React PWA. It works in Kiswahili and English and supports NECTA grading, TZS, GePG and mobile money.

This folder is the **Phase 0 deliverable**: the design documents plus an executable schema, seed and database tests. **Phases 1–6 (Foundation, Academics, Finance, Attendance and communication, Facilities and student life, Analytics and operations)** code lives in [`../ssms`](../ssms/README.md); its decisions are in [adr/](adr/README.md). Version 1 (the single-school design) lives in `../docs`, `../db` and `../backend` and is kept unchanged for reference.

| § | Document | Content |
|---|---|---|
| 1 | [01-introduction.md](01-introduction.md) | Problem, scope by phase, actors, multi-tenancy model, assumptions, VERIFY list |
| 2 | [02-requirements.md](02-requirements.md) | 71 functional requirements, 15 non-functional, MoSCoW, acceptance criteria |
| 3 | [03-context-dfd.md](03-context-dfd.md) | Context diagram, DFD Level 1 (balanced) and Level 2 for 2.0, 4.0, 5.0 |
| 4 | [04-use-cases.md](04-use-cases.md) | Use case diagrams with «include»/«extend», detailed descriptions |
| 5 | [05-erd.md](05-erd.md) | Crow's Foot ERDs by area |
| 6 | [06-data-model.md](06-data-model.md) | DDL rules: tenancy, encryption, 3NF, triggers, views, indexes |
| 7 | [07-data-dictionary.md](07-data-dictionary.md) | Every column of all 99 tables (generated from the live schema) |
| 8 | [08-class-diagram.md](08-class-diagram.md) | Domain class diagrams |
| 9 | [09-sequence-diagrams.md](09-sequence-diagrams.md) | Enrolment, results, payment callback, absence job, scheduling, login + OTP |
| 10 | [10-activity-diagrams.md](10-activity-diagrams.md) | Swimlanes: enrolment, fee payment, scheduling, publishing results |
| 11 | [11-architecture.md](11-architecture.md) | Architecture, request lifecycle, offline sync, results-day scale, deployment, ADRs |
| 12 | [12-api-design.md](12-api-design.md) | Conventions and every endpoint |
| 13 | [13-io-specifications.md](13-io-specifications.md) | Every form with validation and sw/en errors; every output |
| 14 | [14-wireframes.md](14-wireframes.md) | Every portal screen, mobile-first |
| 15 | [15-security.md](15-security.md) | RBAC matrix, RLS + resolvers, JWT/OTP, payments, audit, PDPA 2022 |
| 16 | [16-test-plan.md](16-test-plan.md) | Database test results, test cases per use case, E2E, load, UAT |
| 17 | [17-corrections.md](17-corrections.md) | Corrections against the baseline, version 1 and Phase 0 defects |
| 18 | [18-operations.md](18-operations.md) | Deployment, backups and restore drill, key rotation, monitoring, incidents |
| 19 | [19-reference-analysis.md](19-reference-analysis.md) | Weblizar reference analysis, gap analysis against the brief, decisions, FR-72 to FR-99 |
| 20 | [20-extension-architecture.md](20-extension-architecture.md) | Extension architecture: 23 new tables (`sql/extension.sql`), permissions, API, web, build plan |
| — | [adr/](adr/README.md) | 21 architecture decision records |
| — | [PROGRESS.md](PROGRESS.md) | Build log; read this first after an interruption |

## Executable design

| File | What |
|---|---|
| [sql/schema.sql](sql/schema.sql) | 99 tables, RLS on 95, 10 views, triggers, `publish_results()`, resolvers, roles and grants |
| [sql/seed.sql](sql/seed.sql) | Two schools (Mfano secondary, Upendo primary); every demo password is `Mfano@2026` |
| [sql/tests/01_isolation.sql](sql/tests/01_isolation.sql) | 16 tenant-isolation and resolver tests (as `ssms_app`) |
| [sql/tests/02_integrity.sql](sql/tests/02_integrity.sql) | 27 integrity tests (clashes, marks, ledger, invoices, frozen results, audit) |

```bash
createdb ssms_test
psql -d ssms_test -f design/sql/schema.sql                       # as a superuser (creates roles)
psql -d ssms_test -f design/sql/seed.sql                         # switches to ssms_owner itself
psql -v ON_ERROR_STOP=1 -d ssms_test -f design/sql/tests/01_isolation.sql
psql -v ON_ERROR_STOP=1 -d ssms_test -f design/sql/tests/02_integrity.sql
```

Phase 0 verification ran on PGlite (a PostgreSQL 18 build): 43 of 43 tests passed. Phase 1 re-ran them on **real PostgreSQL 16.9**: 43/43 PASS (after fixing D10); CI runs them on every push. Diagrams are Mermaid; in VS Code, install "Markdown Preview Mermaid Support".
