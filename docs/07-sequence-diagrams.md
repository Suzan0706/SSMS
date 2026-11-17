# 7. Sequence Diagrams

All endpoints are under `/api/v1`. Writes run inside one database transaction that begins with `SET LOCAL app.user_id / app.user_role / app.client_ip / app.request_id`, so the audit trigger records who did what. In the diagrams, `-)` is an asynchronous Celery message and `-->>` is a reply.

## 7.1 Baseline — Student Enrolment (reproduced)

```mermaid
sequenceDiagram
    actor Student
    participant SMS as School Management System
    participant Server as School Server
    participant Info as Student Information
    participant Done as Successfully Enrolled

    Student->>SMS: Inquires for enrolment
    SMS->>Server: Processing
    Server-->>SMS: List of courses offered
    SMS-->>Student: List of courses offered
    Student->>SMS: Choose a course
    SMS->>Server: Processing
    Server-->>SMS: Course information
    SMS-->>Student: Pursue the course?
    alt yes
        Student->>SMS: Yes
        SMS->>Server: Processing
        Server-->>Student: List of requirements
    else no
        Student->>SMS: No
        SMS->>Server: Processing
        Server-->>Student: Try other courses
    end
    Student->>SMS: Complies with requirements
    SMS->>Info: Saving information
    SMS-->>Student: Confirm enrolment?
    alt yes
        SMS->>Done: Confirmation
        Done-->>Student: Enrolment complete
    else no
        SMS->>Done: Cancelling transaction
        Done-->>Student: Enrolment cancelled
    end
```

**What is wrong.**

1. "Student Information" and "Successfully Enrolled" are data and a state, not objects that can receive messages.
2. Requirements are "saved" but nobody validates them, although the activity diagram says the faculty checks validity.
3. The "no" branch does not loop back to choosing a course.
4. Nothing checks capacity or an existing enrolment.
5. Confirmation creates no class links, no invoice and no status change.
6. **All lifelines are destroyed at the end**, including the server and the database. These live on after one enrolment; only the user's session ends.
7. Typos: "Inqure", "Succesfully".

## 7.2 Corrected — Student Enrolment

The student applies and submits documents, faculty validates them, and the **Registrar** confirms admission (the school's decision). The student or the registrar can cancel at any point before confirmation.

```mermaid
sequenceDiagram
    autonumber
    actor S as Student
    participant UI as React PWA
    participant API as FastAPI
    participant ES as EnrolmentService
    participant DB as PostgreSQL
    participant OS as Object Storage
    participant Q as Celery worker
    actor F as Instructor (Faculty)
    actor R as Registrar

    S->>UI: Inquire for enrolment
    UI->>API: GET /course-offerings?year=2026&is_open=true
    API->>DB: SELECT course_offerings ⋈ courses, class_levels,<br/>COUNT(enrolments CONFIRMED)
    DB-->>API: offerings + places left
    API-->>UI: 200 [offerings]
    UI-->>S: List of courses offered

    loop until the student accepts a course
        S->>UI: Choose a course
        UI->>API: GET /course-offerings/{id}
        API->>DB: SELECT course_subjects ⋈ subjects,<br/>enrolment_requirements
        API-->>UI: 200 course information
        UI-->>S: Pursue the course? / Endelea na kozi hii?
        alt No
            S->>UI: No
            UI-->>S: Try other courses / Jaribu kozi nyingine
        else Yes
            S->>UI: Yes
        end
    end

    UI->>API: POST /enrolments {offering_id}
    API->>ES: apply(student_id, offering_id)
    ES->>DB: INSERT enrolments (status PENDING)<br/>trigger fn_enrolments_one_per_year · audit_logs
    alt already enrolled this year or offering full
        DB-->>ES: 23505 / capacity check fails
        ES-->>API: ConflictError
        API-->>UI: 409 Already enrolled / No places left
    else created
        ES->>DB: SELECT enrolment_requirements (level, mandatory)
        API-->>UI: 201 {enrolment_id, requirements[]}
        UI-->>S: List of requirements / Orodha ya mahitaji
    end

    loop each requirement
        S->>UI: Upload file
        UI->>API: POST /enrolments/{id}/documents (multipart)
        API->>API: check magic bytes, size ≤ 5 MB, SHA-256
        API->>OS: PUT enrolments/{id}/{code}/{uuid}
        API->>DB: INSERT … ON CONFLICT (enrolment_id, requirement_id)<br/>DO UPDATE enrolment_documents (PENDING)
        API-->>UI: 201 document
    end

    S->>UI: Submit (complies with requirements)
    UI->>API: POST /enrolments/{id}/submit
    API->>DB: verify every mandatory requirement uploaded<br/>UPDATE enrolments SET status = SUBMITTED
    API-)Q: notify_validators(enrolment_id)
    Q-)F: Documents to validate (SMS / in-app)
    Note over F,DB: Faculty validates each document (UC-07, activity 8.1):<br/>PATCH /enrolment-documents/{id} → status VALIDATED or INVALID
    Q-)S: Requirements completed / some invalid

    R->>UI: Open VALIDATED enrolment — Confirm enrolment?
    alt Confirm
        UI->>API: POST /enrolments/{id}/confirm {stream: "A"}
        API->>ES: confirm(enrolment_id, stream)
        ES->>DB: SELECT course_offerings FOR UPDATE (capacity)
        ES->>DB: UPDATE enrolments SET status CONFIRMED, confirmed_at, confirmed_by
        ES->>DB: INSERT enrolment_schedules (all sessions of stream + term)<br/>trigger fn_enrolment_schedules_no_clash
        ES->>DB: UPDATE students SET current_status = ACTIVE<br/>INSERT student_status_history
        ES->>DB: INSERT invoices, invoice_items FROM fee_structures
        ES->>DB: COMMIT (audit_logs written by triggers)
        API-)Q: request_control_number(invoice_id), send_sms(enrolment complete)
        API-->>UI: 200 CONFIRMED
        UI-->>S: Enrolment complete / Usajili umekamilika
    else Cancel (registrar or student)
        UI->>API: POST /enrolments/{id}/cancel {reason}
        API->>DB: UPDATE enrolments SET status CANCELLED,<br/>cancelled_at, cancel_reason
        API-)Q: send_sms(enrolment cancelled)
        API-->>UI: 200 CANCELLED
        UI-->>S: Enrolment cancelled / Usajili umesitishwa
    end
```

No lifeline is destroyed. The API, the services and the database are long-lived, and the client simply leaves the screen.

## 7.3 Login

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant UI as React PWA
    participant API as FastAPI
    participant AS as AuthService
    participant DB as PostgreSQL

    U->>UI: Username, password, language
    UI->>API: POST /auth/login (form: username, password)
    API->>AS: authenticate(username, password, ip, user_agent)
    AS->>DB: SELECT users WHERE lower(username) = lower(:u)
    alt user not found or is_active = false
        AS->>AS: verify against a dummy hash (constant time)
        AS->>DB: INSERT audit_logs (LOGIN_FAILED)
        API-->>UI: 401 Invalid username or password
    else locked_until > now()
        AS->>DB: INSERT audit_logs (LOGIN_FAILED)
        API-->>UI: 423 Account locked until 10:15
    else wrong password
        AS->>DB: UPDATE users SET failed_login_count + 1<br/>(locked_until = now() + 15 min on the 5th)
        AS->>DB: INSERT audit_logs (LOGIN_FAILED)
        API-->>UI: 401 Invalid username or password
    else password correct
        AS->>AS: Argon2id verify (re-hash if parameters changed)
        AS->>DB: UPDATE users SET failed_login_count = 0, last_login_at = now()
        AS->>DB: INSERT refresh_tokens (sha256(token), family_id, expires_at = +7 d)
        AS->>DB: INSERT audit_logs (LOGIN)
        API-->>UI: 200 {access_token (JWT, 15 min), refresh_token, token_type}
        UI->>API: GET /auth/me (Authorization: Bearer …)
        API->>DB: SELECT users (+ students / instructors / guardians)
        API-->>UI: 200 profile, role, preferred_language
        UI-->>U: Role dashboard
    end
```

## 7.4 Schedule a Class

```mermaid
sequenceDiagram
    autonumber
    actor A as Admin (Academic Master)
    participant UI as React PWA
    participant API as FastAPI
    participant SS as SchedulingService
    participant DB as PostgreSQL
    participant Q as Celery worker

    A->>UI: Offering, stream, term, subject, instructor, room, day, times
    UI->>API: POST /schedules
    API->>API: require_role(ADMIN) · Pydantic: end > start, day 1–6
    API->>SS: create(payload)
    SS->>DB: SELECT course_offerings, terms (term in offering's year)
    SS->>DB: SELECT course_subjects (subject in course at level)
    SS->>DB: SELECT instructor_subjects (instructor qualified)
    SS->>DB: SELECT rooms (type, capacity) · COUNT confirmed enrolments in stream
    SS->>DB: SELECT schedules WHERE term, day AND slot && new slot<br/>AND (instructor = :i OR room = :r OR (offering, stream) = :c)
    SS->>DB: SELECT schedules ⋈ enrolment_schedules for the stream's students<br/>WHERE term, day AND slot && new slot
    SS->>DB: SELECT SUM(periods) for instructor in term
    alt any clash
        SS-->>API: ClashError [conflicting sessions]
        API-->>UI: 409 {conflicts: [{type: INSTRUCTOR, schedule_id: 6, ...}]}
    else wrong room type, room too small or load exceeded
        API-->>UI: 422 {reason}
    else valid
        SS->>DB: INSERT schedules (EXCLUDE constraints re-check)
        alt a concurrent request took the slot first
            DB-->>SS: 23P01 exclusion_violation
            API-->>UI: 409 Slot just taken, refresh
        else inserted
            SS->>DB: INSERT enrolment_schedules for CONFIRMED students of the stream
            SS->>DB: COMMIT (audit_logs via trigger)
            API-)Q: notify_instructor(schedule_id)
            API-->>UI: 201 schedule
            UI-->>A: Session added to timetable grid
        end
    end
```

## 7.5 Record a Payment (manual and GePG)

```mermaid
sequenceDiagram
    autonumber
    actor B as Bursar
    actor P as Parent
    participant UI as React PWA
    participant API as FastAPI
    participant PS as PaymentService
    participant DB as PostgreSQL
    participant Q as Celery worker
    participant G as GePG
    participant M as Mobile money / Bank

    rect rgb(235, 245, 255)
    Note over B,DB: A. Manual payment at the school (cash, bank slip, M-Pesa SMS)
    B->>UI: Student, invoice, amount TZS, method, reference, payer
    UI->>API: POST /transactions
    API->>API: require_role(BURSAR, ADMIN) · amount > 0 · reference unless CASH
    API->>PS: record_manual(...)
    PS->>DB: SELECT v_invoice_balances WHERE invoice_id (same student, not cancelled)
    PS->>DB: INSERT transactions (PAYMENT, COMPLETED, MANUAL, recorded_by)
    alt duplicate method + reference
        DB-->>PS: 23505 uq_trans_reference
        API-->>UI: 409 Payment already recorded
    else saved
        PS->>DB: SELECT v_invoice_balances (new balance)
        API-)Q: send_receipt_sms(trans_id)
        API-->>UI: 201 {trans_no, balance_tzs}
        UI-->>B: Print receipt
    end
    end

    rect rgb(240, 250, 240)
    Note over API,M: B. GePG control number and payment notification
    Q->>G: Bill request (signed XML: invoice_no, items, amount, payer phone)
    G-->>Q: Control number 9941xxxxxxxx
    Q->>DB: UPDATE invoices SET gepg_control_no
    Q-)P: SMS "Namba ya malipo 994120000001, TZS 680,000"
    P->>M: Pay with control number (M-Pesa / Tigo Pesa / Airtel Money / bank)
    M->>G: Payment
    G->>API: POST /payments/gepg/callback (signed XML)
    API->>API: Verify GePG signature (public certificate)
    alt bad signature
        API-->>G: 401
    else valid
        API->>DB: SELECT invoices WHERE gepg_control_no = :cn
        API->>DB: INSERT transactions (PAYMENT, GEPG, COMPLETED, reference = receipt)<br/>ON CONFLICT (payment_method, reference_no) DO NOTHING
        API-->>G: ACK (also for duplicates: idempotent)
        API-)Q: send_receipt_sms(trans_id)
        Q-)P: SMS receipt + balance
    end
    end
```

## 7.6 Update Student Status

```mermaid
sequenceDiagram
    autonumber
    actor R as Registrar
    participant UI as React PWA
    participant API as FastAPI
    participant SV as StudentService
    participant DB as PostgreSQL
    participant Q as Celery worker
    actor G as Guardian

    R->>UI: New status, reason, effective date
    UI->>API: PATCH /students/{id}/status
    API->>API: require_role(REGISTRAR, ADMIN) · reason required
    API->>SV: change_status(student_id, new_status, reason, effective_date)
    SV->>DB: SELECT students WHERE student_id FOR UPDATE
    SV->>SV: check ALLOWED_TRANSITIONS[current][new]
    alt transition not allowed (e.g. GRADUATED → ACTIVE)
        API-->>UI: 422 Status change not allowed
    else allowed
        SV->>DB: UPDATE students SET current_status = :new
        SV->>DB: INSERT student_status_history (old, new, reason, changed_by)
        opt new status is TRANSFERRED or DROPPED_OUT
            SV->>DB: UPDATE users SET is_active = false
            SV->>DB: UPDATE refresh_tokens SET revoked_at = now()
        end
        SV->>DB: COMMIT (audit_logs row: students UPDATE, old/new values)
        API-)Q: notify_guardians(student_id, new_status)
        Q->>DB: SELECT student_guardians ⋈ users (phone, language)
        Q-)G: SMS "Hali ya mwanafunzi imebadilika: SUSPENDED …"
        API-->>UI: 200 {student, history_id}
    end
```
