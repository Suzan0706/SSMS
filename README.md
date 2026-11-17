
# SSMS

# School Management System (SMS) — System Design

Design and reference implementation of a School Management System for a Tanzanian school. It uses FastAPI and PostgreSQL 16, with Kiswahili/English, NECTA grading, TZS, GePG and mobile money.

## Contents

| § | Deliverable | File |
|---|---|---|
| 1 | Introduction: purpose, scope, actors, assumptions | [docs/01-introduction.md](docs/01-introduction.md) |
| 2 | Functional and non-functional requirements | [docs/02-requirements.md](docs/02-requirements.md) |
| 3 | Corrected ERD, PostgreSQL DDL (3NF), sample data | [docs/03-erd-and-ddl.md](docs/03-erd-and-ddl.md) |
| 4 | Data dictionary (35 tables, 287 columns) | [docs/04-data-dictionary.md](docs/04-data-dictionary.md) |
| 5 | Use case diagram and detailed use cases | [docs/05-use-cases.md](docs/05-use-cases.md) |
| 6 | DFD Level 0, 1, 2 (balanced) | [docs/06-dfd.md](docs/06-dfd.md) |
| 7 | Sequence diagrams (enrolment, login, scheduling, payment, status) | [docs/07-sequence-diagrams.md](docs/07-sequence-diagrams.md) |
| 8 | Activity diagrams with swimlanes | [docs/08-activity-diagrams.md](docs/08-activity-diagrams.md) |
| 9 | Class diagram and scheduling algorithm | [docs/09-class-diagram.md](docs/09-class-diagram.md) |
| 10 | Architecture and deployment | [docs/10-architecture.md](docs/10-architecture.md) |
| 11 | API design (+ code by module) | [docs/11-api-design.md](docs/11-api-design.md), [docs/11a-fastapi-code.md](docs/11a-fastapi-code.md) |
| 12 | Security design | [docs/12-security.md](docs/12-security.md) |
| 13 | Report designs | [docs/13-reports.md](docs/13-reports.md) |
| 14 | UI wireframes | [docs/14-wireframes.md](docs/14-wireframes.md) |
| 15 | Test plan | [docs/15-test-plan.md](docs/15-test-plan.md) |
| 16 | Summary of corrections | [docs/16-corrections-summary.md](docs/16-corrections-summary.md) |

## Repository layout

```text
db/schema.sql                 PostgreSQL 16 DDL: tables, constraints, triggers, views
db/seed.sql                   sample school (all demo passwords: Mfano@2026)
db/tests/test_constraints.sql 16 database integrity tests
backend/                      FastAPI reference implementation, Alembic, pytest suite
docs/                         the design document, sections 1–16
```

## Quick start

```bash
createdb sms && psql -d sms -f db/schema.sql && psql -d sms -f db/seed.sql
cd backend && pip install -e ".[dev]" && cp .env.example .env    # set SMS_DATABASE_URL, SMS_JWT_SECRET
uvicorn app.main:app --reload                                    # http://localhost:8000/docs
```

The diagrams are Mermaid. They render on GitHub and GitLab; in VS Code, install the "Markdown Preview Mermaid Support" extension.

