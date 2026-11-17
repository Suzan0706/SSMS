# 9. Sequence Diagrams

All endpoints are under `/api/v1`. Every API transaction starts with `SET LOCAL app.school_id, app.user_id, app.client_ip, app.request_id` (the tenant dependency) as the role `ssms_app`, so RLS and the audit trigger apply. `-)` is an asynchronous Celery message; `-->>` is a reply. Tables touched are named on the database arrows.

## 9.1 Enrolment (corrected from the baseline)

```mermaid
sequenceDiagram
    autonumber
    actor A as Parent / Student
    participant UI as React PWA
    participant API as FastAPI
    participant DB as PostgreSQL
    participant S3 as Object storage
    participant Q as Celery
    actor T as Teacher
    actor H as School Admin

    A->>UI: Inquire (school code from the URL)
    UI->>API: GET /enrolment/offerings?year=2027
    API->>DB: resolve_school_by_code() → SET LOCAL app.school_id
    API->>DB: SELECT classes, streams, v_stream_occupancy, enrolment_requirements
    API-->>UI: 200 classes with places left
    loop until a class is accepted
        A->>UI: Choose class → "Endelea na darasa hili? / Pursue?"
        alt No
            UI-->>A: "Jaribu madarasa mengine / Try other classes"
        end
    end
    UI->>API: POST /enrolment/applications {class_id, applicant, guardians, consent}
    API->>DB: INSERT users, students (APPLICANT), guardians, student_guardians, consent_records,<br/>enrolment_applications (REQUIREMENTS_PENDING, APP-no via next_document_no)
    API-->>UI: 201 + requirements list
    loop each requirement
        UI->>API: POST /enrolment/applications/{id}/documents (multipart)
        API->>API: magic bytes, ≤ 5 MB, SHA-256
        API->>S3: PUT <school>/enrolment/<app>/<uuid>
        API->>DB: INSERT enrolment_documents (PENDING)
    end
    UI->>API: POST /enrolment/applications/{id}/submit
    API->>DB: UPDATE enrolment_applications → UNDER_REVIEW
    API-)Q: notify validators
    T->>API: PATCH /enrolment/documents/{id} {VALID | INVALID + comment}
    API->>DB: UPDATE enrolment_documents · derive application status
    alt any INVALID
        API->>DB: application → REQUIREMENTS_PENDING
        API-)Q: SMS "Baadhi ya mahitaji si sahihi / Some requirements are invalid"
        Note over A,UI: re-upload only the invalid documents
    else all required VALID
        API-)Q: SMS "Mahitaji yamekamilika / Requirements completed"
    end
    H->>API: POST /enrolment/applications/{id}/approve {stream_id} ("Thibitisha usajili?")
    alt Yes
        API->>DB: BEGIN · admission no. (next_document_no) · students ACTIVE + status history ·<br/>INSERT enrolments (capacity trigger) · user login · invoice (fee structure) · COMMIT
        API-)Q: SMS "Usajili umekamilika — MF-2027-0012" · GePG bill request
        API-->>H: 200 APPROVED
    else No
        H->>API: POST .../reject {reason}  or  .../cancel {reason}
        API->>DB: application REJECTED / CANCELLED (reason required)
        API-)Q: SMS "Usajili umesitishwa / Enrolment cancelled"
    end
```

Corrections against the baseline:

- The baseline used lifelines for data ("Student Information", "Successfully Enrolled"); here the lifelines are real components.
- A "no" answer loops back to the class list.
- Faculty validation is per document.
- Approval is one transaction with capacity, admission number and invoice.
- Long-lived lifelines are not destroyed.

## 9.2 Mark entry → validation firewall → publish → report cards → SMS

```mermaid
sequenceDiagram
    autonumber
    actor T as Teacher
    participant UI as PWA + Dexie
    participant API as FastAPI
    participant DB as PostgreSQL
    participant Q as Celery
    participant PDF as WeasyPrint
    actor H as School Admin

    T->>UI: Type scores (offline OK)
    UI->>UI: Dexie outbox {mark key, score, version, client_updated_at} — "Saved offline"
    UI->>API: PUT /marks/batch (when online, backoff retry)
    loop each mark
        API->>DB: UPDATE mark_entries SET score WHERE id AND version = :v<br/>(trigger: ≤ max, not locked, version + 1)
        alt version mismatch
            API-->>UI: 409 per cell {server_score, server_version} → "Conflict"
        else score > max
            API-->>UI: 422 per cell
        end
    end
    API-->>UI: 200 synced
    H->>API: POST /results/publish {term_id, class_id}
    API->>DB: SELECT results_firewall(term, class)
    alt problems found
        API-->>H: 422 INCOMPLETE_GRADES_BLOCK [admission no., name, subject, component, teacher, message sw/en]
    else clean
        API->>DB: SELECT publish_results(term, class) — one transaction:<br/>weighted totals · grade_bands · points · RANK positions · best-n division ·<br/>INSERT result_publications, published_results, student_term_summaries ·<br/>UPDATE mark_entries.locked_at · audit PUBLISH
        API->>DB: INSERT background_jobs (REPORT_CARDS)
        API-->>H: 201 {publication_id, job_id}
        API-)Q: render report cards
        Q->>DB: SELECT v_current_term_summaries, v_current_results, report_card_comments
        Q->>PDF: HTML → PDF per student
        Q->>DB: UPDATE background_jobs (progress %)
        Q-)Q: SMS "Matokeo yametoka / Results ready" (one idempotency key per student and publication)
    end
```

## 9.3 Payment callback (GePG / mobile money) — respond in < 2 s

```mermaid
sequenceDiagram
    autonumber
    participant GW as GePG / M-Pesa / Airtel
    participant NG as Nginx
    participant API as FastAPI
    participant DB as PostgreSQL
    participant Q as Celery
    actor P as Parent

    GW->>NG: POST /webhooks/gepg/payment (signed XML)
    NG->>NG: IP allow-list, body ≤ 64 KB, rate limit
    NG->>API: forward
    API->>API: verify signature (provider certificate / HMAC)
    alt bad signature
        API-->>GW: 401 + alert
    else valid
        API->>DB: resolve_gepg_bill(control_number) → (school_id, bill_id)
        API->>DB: SET LOCAL app.school_id
        API->>DB: INSERT payments (CONFIRMED, raw_payload redacted)<br/>ON CONFLICT (school_id, channel, external_ref) DO NOTHING
        alt duplicate (already recorded)
            API-->>GW: ACK (idempotent)
        else new
            API-)Q: allocate(payment_id)
            API-->>GW: ACK (TrxStsCode 7101 — VERIFY)
            Q->>DB: BEGIN · SET LOCAL app.school_id
            Q->>DB: SELECT invoices WHERE student, balance > 0 ORDER BY due_date FOR UPDATE
            Q->>DB: INSERT payment_allocations (oldest due first, trigger re-derives invoices)
            Q->>DB: INSERT journals + ledger_entries (Dr clearing / Cr 1300, Cr 2100 for credit)
            Q->>DB: INSERT receipts (next_document_no) · COMMIT (deferred balance check)
            Q-)Q: render receipt PDF
            Q->>DB: INSERT sms_messages (key receipt:<payment>)
            Q-)P: SMS "Tumepokea TZS 400,000 … Risiti RCT-2026-000001. Salio TZS 280,000"
        end
    end
```

The heavy work (allocation, ledger, PDF, SMS) is queued, so the gateway always gets its acknowledgement in under 2 s. Retries with the same `external_ref` are absorbed by the unique constraint.

## 9.4 Daily absence alert job

```mermaid
sequenceDiagram
    autonumber
    participant B as Celery beat
    participant W as Celery worker
    participant DB as PostgreSQL
    participant SMS as SMS adapter (Beem / NextSMS)
    actor G as Guardian

    B-)W: every 5 min on weekdays: absence_fanout()
    W->>DB: list_active_school_ids()
    loop each school whose absence_sms_cutoff has just passed (EAT)
        W-)W: absence_alerts(school_id, today)
        W->>DB: SET LOCAL app.school_id
        W->>DB: skip if public_holidays has today or the term is closed
        W->>DB: students with ACTIVE enrolment, no GATE/REGISTER PRESENT or LATE today,<br/>no absence_alerts row today
        loop each absent student
            W->>DB: guardians with receives_sms and SMS consent (consent_records)
            W->>DB: INSERT sms_messages (idempotency_key absence:<student>:<date>) ON CONFLICT DO NOTHING
            W->>DB: INSERT absence_alerts (UNIQUE student + date)
            W->>DB: INSERT sms_credit_transactions (DEBIT)
            W->>SMS: send(phone, body sw/en)
            SMS-->>W: provider message id
            SMS-)G: SMS "… hakufika shuleni leo …"
            W->>DB: UPDATE sms_messages SENT
        end
    end
    SMS->>W: delivery report webhook → UPDATE sms_messages DELIVERED / FAILED
```

## 9.5 Class scheduling with clash detection

```mermaid
sequenceDiagram
    autonumber
    actor H as School Admin
    participant UI as PWA
    participant API as FastAPI
    participant SV as SchedulingService
    participant DB as PostgreSQL

    H->>UI: Stream, subject, teacher, room, day, start, end
    UI->>API: POST /timetable/check (live while typing)
    API->>SV: find_conflicts()
    SV->>DB: SELECT timetable_slots overlapping (teacher | room | stream) same term & day
    SV->>DB: teaching_assignments (teacher assigned?) · rooms (type, capacity) ·<br/>SUM periods for teacher (load ≤ max_periods_per_week)
    API-->>UI: {ok, conflicts[], problems[], free_slots[]}
    H->>UI: Save
    UI->>API: POST /timetable/slots
    API->>SV: create()
    SV->>DB: INSERT timetable_slots (3 EXCLUDE constraints re-check under concurrency)
    alt concurrent clash
        DB-->>SV: 23P01 exclusion_violation
        API-->>UI: 409 TIMETABLE_CLASH {conflicting slot}
    else inserted
        API-->>UI: 201 slot
    end
    opt Auto-generate
        H->>API: POST /timetable/generate {term_id, stream_ids, persist:false}
        API->>SV: generate() — most-constrained-first greedy + one-step repair
        API-->>H: draft {placed[], unplaced[]}
        H->>API: POST /timetable/generate {persist:true}
        API->>DB: INSERT all slots in one transaction (constraints verify)
    end
```

## 9.6 Login with role check, OTP for parents, audit

```mermaid
sequenceDiagram
    autonumber
    actor U as Staff / Student
    actor P as Parent
    participant API as FastAPI
    participant DB as PostgreSQL
    participant Q as Celery / SMS

    U->>API: POST /auth/login {school_code, username, password}
    API->>DB: resolve_school_by_code() → SET LOCAL app.school_id
    API->>DB: SELECT users WHERE lower(username) (RLS: this school only)
    alt locked
        API-->>U: 423 {locked_until}
    else bad password / unknown
        API->>DB: UPDATE users failed_login_count (+ lock at 5) · INSERT audit_logs LOGIN_FAILED
        API-->>U: 401 "Jina au nenosiri si sahihi"
    else ok
        API->>DB: SELECT user_roles → role_permissions → permissions
        API->>DB: INSERT refresh_tokens (sha256, family) · audit LOGIN
        API-->>U: 200 access JWT {sub, sch, roles, exp 15m} + Set-Cookie refresh (HttpOnly, Secure, SameSite=Strict)
    end

    P->>API: POST /auth/otp/request {phone}
    API->>API: normalise 255XXXXXXXXX, HMAC blind index, rate limit 3 / 15 min
    API->>DB: resolve_users_by_phone(hash) → [(school, user)]
    loop each match
        API->>DB: SET LOCAL app.school_id · INSERT otp_codes (sha256(code‖user), 5 min)
    end
    API-)Q: one SMS "Namba yako ya kuingia ni 482913"
    API-->>P: 200 "Code sent" (same reply for unknown phones)
    P->>API: POST /auth/otp/verify {phone, code}
    API->>DB: verify per school (attempts ≤ 5), consume
    alt more than one school
        API-->>P: 200 {choose: [{school, name}]} + short-lived selection token
        P->>API: POST /auth/select-school {selection_token, school_id}
    end
    API->>DB: INSERT refresh_tokens · audit LOGIN
    API-->>P: 200 tokens (role parent → portal.parent)
    Note over API,DB: Every later request: JWT verified → SET LOCAL app.school_id = sch →<br/>require_permission('x.y') → RLS + composite FKs keep the request inside the school
```
