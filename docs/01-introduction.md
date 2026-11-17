# 1. Introduction

## 1.1 Purpose

This document specifies the design of the **School Management System (SMS)** for a Tanzanian school. It reproduces the baseline UML/DFD model, corrects its flaws (summarised in [section 16](16-corrections-summary.md)) and extends it into a design a development team can build and test from.

The SMS manages:

- student records and status (admission → active → suspended / transferred / dropped out / graduated);
- courses (programmes and combinations such as *O-Level General* or *PCM*), subjects and yearly course offerings;
- instructors, their departments and designations (Class Teacher, Head of Department, Academic Master …);
- class schedules (timetables) without instructor, room, class or student clashes;
- enrolment, including requirement documents validated by faculty;
- fees, GePG control numbers, mobile-money and cash payments in TZS;
- results (NECTA grading) and attendance;
- a tamper-evident **transaction history and audit trail** of every change to records, transactions and status.

## 1.2 Scope

| In scope | Out of scope (future phases) |
|---|---|
| Web/PWA client in Kiswahili and English | Native Android/iOS apps |
| Single school, multiple streams and levels (Standards I–VII, Forms I–VI) | Multi-school / district (multi-tenant) deployment |
| Admissions, enrolment, timetabling, results, attendance, fees | Payroll, library, hostel allocation, transport, inventory |
| GePG and mobile-money payment integration | Direct NECTA examination registration (export file only) |
| SMS notifications to parents and students | Learning management (assignments, e-learning content) |
| Reports: student list, timetable, enrolment, transactions, status, report card | Business-intelligence dashboards across schools |

## 1.3 Actors

| Actor | Kiswahili | Description | System role(s) |
|---|---|---|---|
| Admin / Registrar | Msimamizi / Msajili | Manages students, courses, subjects, instructors, schedules, enrolment. A **Bursar** (Mhasibu) is the finance specialisation of this actor and records payments. | `ADMIN`, `REGISTRAR`, `BURSAR` |
| Student | Mwanafunzi | Applies and enrols, uploads requirement documents, views courses, timetable, status, results and invoices. | `STUDENT` |
| Instructor (School Faculty) | Mwalimu | Receives class lists, enters subject results and attendance ("Subject Field" in the baseline), validates enrolment documents. | `INSTRUCTOR` |
| Parent / Guardian | Mzazi / Mlezi | Views their own children's records, results, attendance and payments; pays fees. | `PARENT` |
| Payment Gateway | Lango la Malipo | External system: GePG and mobile-money operators (M-Pesa, Tigo Pesa / Mixx by Yas, Airtel Money). Issues control numbers and posts payment confirmations. | system (signed callback) |
| SMS Gateway | Huduma ya SMS | External bulk-SMS provider used by background jobs. | system |

## 1.4 Assumptions

Each assumption is one line; changing one changes the design where noted.

1. One school per deployment; a `school_id` column would be added for multi-school use.
2. Academic year = calendar year (January–December), split into **two terms** (`terms` supports up to four).
3. Secondary levels are Forms I–VI; primary levels Standards I–VII are seeded but optional.
4. A "course" is a **programme/combination** (e.g. OLG, PCM, HGL), not a single subject; subjects are linked to courses many-to-many per level.
5. Each class stream follows one timetable; parallel electives inside a stream are timetabled as separate streams/groups.
6. The baseline "Subject Field" sent by instructors means subject-level data: marks and attendance.
7. Grade boundaries and divisions follow the published NECTA scales and are **stored as data**, so a regulation change needs no code change (seed values must be checked against current NECTA rules).
8. Tuition is fee-free in government schools; the fee module still runs for contributions and for private schools. Sample amounts are illustrative.
9. Government schools receive payments through **GePG** (control numbers); private schools may also accept direct mobile money, bank and cash.
10. Every student has a login account (the username is the admission number); a parent can be linked to several students.
11. Phone numbers are stored as `255XXXXXXXXX` (12 digits); emails are optional.
12. Documents are stored in S3-compatible object storage (MinIO on-premises or a cloud bucket), not in the database.
13. Server time is UTC; the UI shows `Africa/Dar_es_Salaam` (EAT, UTC+3).
14. Personal data processing must comply with Tanzania's **Personal Data Protection Act, 2022**.
15. Internet may be slow or intermittent, so the client is a PWA that caches read-only data offline.

## 1.5 Document map

| § | Deliverable | File |
|---|---|---|
| 1 | Introduction | this file |
| 2 | Functional and non-functional requirements | [02-requirements.md](02-requirements.md) |
| 3 | ERD + PostgreSQL DDL + sample data | [03-erd-and-ddl.md](03-erd-and-ddl.md), [../db/schema.sql](../db/schema.sql), [../db/seed.sql](../db/seed.sql) |
| 4 | Data dictionary | [04-data-dictionary.md](04-data-dictionary.md) |
| 5 | Use cases | [05-use-cases.md](05-use-cases.md) |
| 6 | Data flow diagrams | [06-dfd.md](06-dfd.md) |
| 7 | Sequence diagrams | [07-sequence-diagrams.md](07-sequence-diagrams.md) |
| 8 | Activity diagrams | [08-activity-diagrams.md](08-activity-diagrams.md) |
| 9 | Class diagram and scheduling algorithm | [09-class-diagram.md](09-class-diagram.md) |
| 10 | Architecture and deployment | [10-architecture.md](10-architecture.md) |
| 11 | API design and FastAPI code | [11-api-design.md](11-api-design.md), [../backend/](../backend/) |
| 12 | Security design | [12-security.md](12-security.md) |
| 13 | Report designs | [13-reports.md](13-reports.md) |
| 14 | UI wireframes | [14-wireframes.md](14-wireframes.md) |
| 15 | Test plan | [15-test-plan.md](15-test-plan.md) |
| 16 | Summary of corrections | [16-corrections-summary.md](16-corrections-summary.md) |

## 1.6 Notation

- ERD: Crow's Foot (Mermaid `erDiagram`).
- UML 2.x use case, sequence, activity and class diagrams (Mermaid). Mermaid has no native use-case or swimlane activity diagram, so these are drawn as flowcharts: actors as person nodes, swimlanes as subgraphs.
- DFD: Yourdon/DeMarco. External entities are rectangles, processes are rounded nodes numbered `n.0` (Level 1) and `n.m` (Level 2), and data stores are open-sided boxes labelled `Dn`.
