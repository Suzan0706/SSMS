-- =====================================================================
--  School Management System (SMS) - PostgreSQL 16 schema
--  File: db/schema.sql
--
--  Normal form: 3NF. Derived values (invoice totals, balances, grades,
--  divisions, a student's current class) are computed in views, never
--  stored. The two deliberate exceptions are documented in
--  docs/03-erd-and-ddl.md section 3.4.
--
--  Conventions
--    * snake_case, plural table names, <entity>_id surrogate keys
--    * enumerations are VARCHAR + CHECK (easier to migrate than ENUM)
--    * money is NUMERIC(14,2) Tanzanian shillings (TZS), never FLOAT
--    * timestamps are TIMESTAMPTZ (stored UTC, shown in Africa/Dar_es_Salaam)
--    * phones are 255XXXXXXXXX (12 digits, no "+")
--    * every user-facing label has an _en and _sw column
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS btree_gist;   -- lets EXCLUDE mix "=" and "&&"

-- A range type over TIME so timetable clashes can be tested with "&&".
CREATE TYPE timerange AS RANGE (subtype = time);

CREATE FUNCTION fn_set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END $$;

-- =====================================================================
-- 1. NECTA grading reference data
-- =====================================================================
CREATE TABLE exam_scales (
    exam_scale       VARCHAR(5)   PRIMARY KEY,           -- PSLE / CSEE / ACSEE
    name_en          VARCHAR(80)  NOT NULL,
    name_sw          VARCHAR(80)  NOT NULL,
    best_n_subjects  SMALLINT,                           -- subjects counted for division
    CONSTRAINT ck_exam_scales_best_n CHECK (best_n_subjects BETWEEN 1 AND 10)
);

CREATE TABLE grading_scales (
    grading_scale_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    exam_scale       VARCHAR(5)   NOT NULL REFERENCES exam_scales (exam_scale),
    grade            VARCHAR(2)   NOT NULL,
    min_score        NUMERIC(5,2) NOT NULL,
    max_score        NUMERIC(5,2) NOT NULL,
    points           SMALLINT     NOT NULL,
    remark_en        VARCHAR(20)  NOT NULL,
    remark_sw        VARCHAR(20)  NOT NULL,
    CONSTRAINT uq_grading_scales_grade UNIQUE (exam_scale, grade),
    CONSTRAINT uq_grading_scales_min   UNIQUE (exam_scale, min_score),
    CONSTRAINT ck_grading_scales_range CHECK (min_score >= 0 AND max_score <= 100 AND max_score >= min_score),
    CONSTRAINT ck_grading_scales_points CHECK (points BETWEEN 1 AND 9)
);

CREATE TABLE division_scales (
    division_scale_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    exam_scale        VARCHAR(5) NOT NULL REFERENCES exam_scales (exam_scale),
    division          VARCHAR(3) NOT NULL,                -- I, II, III, IV, 0
    min_points        SMALLINT   NOT NULL,
    max_points        SMALLINT   NOT NULL,
    CONSTRAINT uq_division_scales UNIQUE (exam_scale, division),
    CONSTRAINT ck_division_scales_range CHECK (max_points >= min_points)
);

-- =====================================================================
-- 2. People and accounts (abstract Person/User -> role subtables)
-- =====================================================================
CREATE TABLE users (
    user_id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username            VARCHAR(50)  NOT NULL,
    password_hash       VARCHAR(255) NOT NULL,                 -- Argon2id PHC string
    role                VARCHAR(12)  NOT NULL,
    first_name          VARCHAR(50)  NOT NULL,
    middle_name         VARCHAR(50),
    last_name           VARCHAR(50)  NOT NULL,
    gender              CHAR(1)      NOT NULL,
    date_of_birth       DATE,                                  -- never store age
    phone               VARCHAR(12),
    email               VARCHAR(254),
    preferred_language  CHAR(2)      NOT NULL DEFAULT 'sw',
    is_active           BOOLEAN      NOT NULL DEFAULT TRUE,
    failed_login_count  SMALLINT     NOT NULL DEFAULT 0,
    locked_until        TIMESTAMPTZ,
    last_login_at       TIMESTAMPTZ,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_users_role   CHECK (role IN ('ADMIN','REGISTRAR','BURSAR','INSTRUCTOR','STUDENT','PARENT')),
    CONSTRAINT ck_users_gender CHECK (gender IN ('M','F')),
    CONSTRAINT ck_users_dob    CHECK (date_of_birth >= DATE '1920-01-01'),
    CONSTRAINT ck_users_phone  CHECK (phone ~ '^255[0-9]{9}$'),
    CONSTRAINT ck_users_email  CHECK (email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
    CONSTRAINT ck_users_lang   CHECK (preferred_language IN ('sw','en')),
    CONSTRAINT ck_users_failed CHECK (failed_login_count >= 0)
);
CREATE UNIQUE INDEX uq_users_username ON users (lower(username));
CREATE UNIQUE INDEX uq_users_email    ON users (lower(email)) WHERE email IS NOT NULL;
CREATE INDEX ix_users_role  ON users (role);
CREATE INDEX ix_users_phone ON users (phone);
CREATE INDEX ix_users_name  ON users (lower(last_name), lower(first_name));

-- Admin / Registrar / Bursar
CREATE TABLE staff (
    staff_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id      BIGINT      NOT NULL UNIQUE REFERENCES users (user_id),
    employee_no  VARCHAR(20) NOT NULL UNIQUE,
    job_title    VARCHAR(80) NOT NULL,
    hired_on     DATE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE departments (
    department_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code          VARCHAR(10) NOT NULL UNIQUE,
    name_en       VARCHAR(80) NOT NULL,
    name_sw       VARCHAR(80) NOT NULL
);

CREATE TABLE instructors (
    instructor_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id              BIGINT       NOT NULL UNIQUE REFERENCES users (user_id),
    employee_no          VARCHAR(20)  NOT NULL UNIQUE,         -- government check number
    department_id        INTEGER      NOT NULL REFERENCES departments (department_id),
    qualification        VARCHAR(100) NOT NULL,
    employment_date      DATE,
    employment_status    VARCHAR(12)  NOT NULL DEFAULT 'ACTIVE',
    max_periods_per_week SMALLINT     NOT NULL DEFAULT 30,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_instructors_status CHECK (employment_status IN ('ACTIVE','ON_LEAVE','TRANSFERRED','RETIRED')),
    CONSTRAINT ck_instructors_load   CHECK (max_periods_per_week BETWEEN 1 AND 50)
);
CREATE INDEX ix_instructors_department ON instructors (department_id);

CREATE TABLE guardians (
    guardian_id  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id      BIGINT       NOT NULL UNIQUE REFERENCES users (user_id),
    nida_no      CHAR(20)     UNIQUE,                          -- National ID, digits only
    occupation   VARCHAR(80),
    address      VARCHAR(200),
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_guardians_nida CHECK (nida_no ~ '^[0-9]{20}$')
);

CREATE TABLE students (
    student_id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         BIGINT       NOT NULL UNIQUE REFERENCES users (user_id),
    admission_no    VARCHAR(20)  NOT NULL UNIQUE,
    birth_cert_no   VARCHAR(30),
    necta_index_no  VARCHAR(20)  UNIQUE,                       -- e.g. S0334/0045/2025
    admission_date  DATE         NOT NULL DEFAULT CURRENT_DATE,
    current_status  VARCHAR(12)  NOT NULL DEFAULT 'APPLICANT',
    region          VARCHAR(40),
    district        VARCHAR(40),
    home_address    VARCHAR(200),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_students_status CHECK (current_status IN
        ('APPLICANT','ACTIVE','SUSPENDED','TRANSFERRED','DROPPED_OUT','GRADUATED'))
);
CREATE INDEX ix_students_status ON students (current_status);

CREATE TABLE student_guardians (
    student_id    BIGINT      NOT NULL REFERENCES students (student_id),
    guardian_id   BIGINT      NOT NULL REFERENCES guardians (guardian_id),
    relationship  VARCHAR(10) NOT NULL,
    is_primary    BOOLEAN     NOT NULL DEFAULT FALSE,
    PRIMARY KEY (student_id, guardian_id),
    CONSTRAINT ck_student_guardians_rel CHECK (relationship IN ('FATHER','MOTHER','GUARDIAN','SPONSOR','OTHER'))
);
CREATE UNIQUE INDEX uq_student_primary_guardian ON student_guardians (student_id) WHERE is_primary;
CREATE INDEX ix_student_guardians_guardian ON student_guardians (guardian_id);

CREATE TABLE student_status_history (
    history_id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    student_id      BIGINT       NOT NULL REFERENCES students (student_id),
    old_status      VARCHAR(12),
    new_status      VARCHAR(12)  NOT NULL,
    reason          VARCHAR(300) NOT NULL,
    effective_date  DATE         NOT NULL DEFAULT CURRENT_DATE,
    changed_by      BIGINT       REFERENCES users (user_id),
    changed_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_status_history_new CHECK (new_status IN
        ('APPLICANT','ACTIVE','SUSPENDED','TRANSFERRED','DROPPED_OUT','GRADUATED')),
    CONSTRAINT ck_status_history_changed CHECK (old_status IS DISTINCT FROM new_status)
);
CREATE INDEX ix_status_history_student ON student_status_history (student_id, changed_at DESC);

-- =====================================================================
-- 3. Academic calendar and class levels (Forms / Standards)
-- =====================================================================
CREATE TABLE academic_years (
    academic_year_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name             VARCHAR(9) NOT NULL UNIQUE,              -- '2026'
    start_date       DATE       NOT NULL,
    end_date         DATE       NOT NULL,
    is_current       BOOLEAN    NOT NULL DEFAULT FALSE,
    CONSTRAINT ck_academic_years_dates CHECK (end_date > start_date)
);
CREATE UNIQUE INDEX uq_academic_years_current ON academic_years (is_current) WHERE is_current;

CREATE TABLE terms (
    term_id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    academic_year_id INTEGER     NOT NULL REFERENCES academic_years (academic_year_id),
    term_no          SMALLINT    NOT NULL,
    name_en          VARCHAR(30) NOT NULL,
    name_sw          VARCHAR(30) NOT NULL,
    start_date       DATE        NOT NULL,
    end_date         DATE        NOT NULL,
    CONSTRAINT uq_terms_year_no UNIQUE (academic_year_id, term_no),
    CONSTRAINT ck_terms_no      CHECK (term_no BETWEEN 1 AND 4),
    CONSTRAINT ck_terms_dates   CHECK (end_date > start_date),
    CONSTRAINT ex_terms_overlap EXCLUDE USING gist
        (academic_year_id WITH =, daterange(start_date, end_date, '[]') WITH &&)
);

CREATE TABLE class_levels (
    level_id        INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code            VARCHAR(5)  NOT NULL UNIQUE,              -- F1..F6, STD1..STD7
    name_en         VARCHAR(30) NOT NULL,                     -- Form One
    name_sw         VARCHAR(30) NOT NULL,                     -- Kidato cha Kwanza
    education_level VARCHAR(12) NOT NULL,
    exam_scale      VARCHAR(5)  NOT NULL REFERENCES exam_scales (exam_scale),
    sort_order      SMALLINT    NOT NULL UNIQUE,
    CONSTRAINT ck_class_levels_edu CHECK (education_level IN ('PRE_PRIMARY','PRIMARY','O_LEVEL','A_LEVEL'))
);

-- =====================================================================
-- 4. Courses, subjects, offerings, rooms
-- =====================================================================
CREATE TABLE subjects (
    subject_id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    subject_code        VARCHAR(10) NOT NULL UNIQUE,
    necta_code          VARCHAR(5),
    name_en             VARCHAR(80) NOT NULL,
    name_sw             VARCHAR(80) NOT NULL,
    department_id       INTEGER     NOT NULL REFERENCES departments (department_id),
    room_type_required  VARCHAR(12) NOT NULL DEFAULT 'CLASSROOM',
    description         TEXT,
    is_active           BOOLEAN     NOT NULL DEFAULT TRUE,
    CONSTRAINT ck_subjects_room_type CHECK (room_type_required IN ('CLASSROOM','LABORATORY','ICT_LAB','LIBRARY','HALL'))
);
CREATE INDEX ix_subjects_department ON subjects (department_id);

CREATE TABLE instructor_subjects (                         -- who is qualified to teach what
    instructor_id BIGINT  NOT NULL REFERENCES instructors (instructor_id),
    subject_id    INTEGER NOT NULL REFERENCES subjects (subject_id),
    PRIMARY KEY (instructor_id, subject_id)
);
CREATE INDEX ix_instructor_subjects_subject ON instructor_subjects (subject_id);

CREATE TABLE designations (
    designation_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code           VARCHAR(20) NOT NULL UNIQUE,
    name_en        VARCHAR(60) NOT NULL,
    name_sw        VARCHAR(60) NOT NULL
);

CREATE TABLE instructor_designations (
    instructor_designation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    instructor_id    BIGINT     NOT NULL REFERENCES instructors (instructor_id),
    designation_id   INTEGER    NOT NULL REFERENCES designations (designation_id),
    academic_year_id INTEGER    NOT NULL REFERENCES academic_years (academic_year_id),
    department_id    INTEGER    REFERENCES departments (department_id),   -- for Head of Department
    level_id         INTEGER    REFERENCES class_levels (level_id),       -- for Class Teacher
    stream           VARCHAR(5),                                          -- for Class Teacher
    assigned_on      DATE       NOT NULL DEFAULT CURRENT_DATE,
    ended_on         DATE,
    assigned_by      BIGINT     REFERENCES users (user_id),
    CONSTRAINT ck_instr_desig_dates  CHECK (ended_on IS NULL OR ended_on >= assigned_on),
    CONSTRAINT ck_instr_desig_class  CHECK ((level_id IS NULL) = (stream IS NULL)),
    CONSTRAINT uq_instructor_designation UNIQUE NULLS NOT DISTINCT
        (instructor_id, designation_id, academic_year_id, department_id, level_id, stream)
);
CREATE INDEX ix_instr_desig_year ON instructor_designations (academic_year_id, designation_id);

CREATE TABLE courses (                                      -- programme / combination
    course_id       INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    course_code     VARCHAR(10)  NOT NULL UNIQUE,              -- OLG, PCM, HGL ...
    course_name     VARCHAR(100) NOT NULL,
    course_name_sw  VARCHAR(100) NOT NULL,
    course_desc     TEXT,
    education_level VARCHAR(12)  NOT NULL,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_courses_edu CHECK (education_level IN ('PRE_PRIMARY','PRIMARY','O_LEVEL','A_LEVEL'))
);

CREATE TABLE course_subjects (                              -- M:N course <-> subject, per level
    course_id        INTEGER  NOT NULL REFERENCES courses (course_id),
    level_id         INTEGER  NOT NULL REFERENCES class_levels (level_id),
    subject_id       INTEGER  NOT NULL REFERENCES subjects (subject_id),
    is_compulsory    BOOLEAN  NOT NULL DEFAULT TRUE,
    periods_per_week SMALLINT NOT NULL DEFAULT 4,
    PRIMARY KEY (course_id, level_id, subject_id),
    CONSTRAINT ck_course_subjects_periods CHECK (periods_per_week BETWEEN 1 AND 12)
);
CREATE INDEX ix_course_subjects_subject ON course_subjects (subject_id);

CREATE TABLE course_offerings (                             -- a course opened for a year + level
    offering_id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    course_id        INTEGER  NOT NULL REFERENCES courses (course_id),
    academic_year_id INTEGER  NOT NULL REFERENCES academic_years (academic_year_id),
    level_id         INTEGER  NOT NULL REFERENCES class_levels (level_id),
    capacity         SMALLINT NOT NULL,
    is_open          BOOLEAN  NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_course_offerings UNIQUE (course_id, academic_year_id, level_id),
    CONSTRAINT ck_course_offerings_capacity CHECK (capacity > 0)
);
CREATE INDEX ix_course_offerings_year ON course_offerings (academic_year_id, is_open);

CREATE TABLE rooms (
    room_id    INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_code  VARCHAR(10) NOT NULL UNIQUE,
    name       VARCHAR(60) NOT NULL,
    room_type  VARCHAR(12) NOT NULL DEFAULT 'CLASSROOM',
    capacity   SMALLINT    NOT NULL,
    is_active  BOOLEAN     NOT NULL DEFAULT TRUE,
    CONSTRAINT ck_rooms_type     CHECK (room_type IN ('CLASSROOM','LABORATORY','ICT_LAB','LIBRARY','HALL')),
    CONSTRAINT ck_rooms_capacity CHECK (capacity > 0)
);

-- =====================================================================
-- 5. Timetable. A schedule row is ONE weekly class session; it has no
--    student column. Students are linked through enrolment_schedules.
--    The three EXCLUDE constraints make instructor, room and class
--    clashes impossible even under concurrent writes.
-- =====================================================================
CREATE TABLE schedules (
    schedule_id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    offering_id   BIGINT     NOT NULL REFERENCES course_offerings (offering_id),
    stream        VARCHAR(5) NOT NULL DEFAULT 'A',
    term_id       INTEGER    NOT NULL REFERENCES terms (term_id),
    subject_id    INTEGER    NOT NULL REFERENCES subjects (subject_id),
    instructor_id BIGINT     NOT NULL REFERENCES instructors (instructor_id),
    room_id       INTEGER    NOT NULL REFERENCES rooms (room_id),
    day_of_week   SMALLINT   NOT NULL,                         -- 1 = Monday ... 6 = Saturday
    time_start    TIME       NOT NULL,
    time_end      TIME       NOT NULL,
    slot          timerange  GENERATED ALWAYS AS (timerange(time_start, time_end, '[)')) STORED,
    created_by    BIGINT     REFERENCES users (user_id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_schedules_stream CHECK (stream ~ '^[A-Z]{1,5}$'),
    CONSTRAINT ck_schedules_day    CHECK (day_of_week BETWEEN 1 AND 6),
    CONSTRAINT ck_schedules_time   CHECK (time_end > time_start),
    CONSTRAINT ex_schedules_instructor EXCLUDE USING gist
        (instructor_id WITH =, term_id WITH =, day_of_week WITH =, slot WITH &&),
    CONSTRAINT ex_schedules_room EXCLUDE USING gist
        (room_id WITH =, term_id WITH =, day_of_week WITH =, slot WITH &&),
    CONSTRAINT ex_schedules_class EXCLUDE USING gist
        (offering_id WITH =, stream WITH =, term_id WITH =, day_of_week WITH =, slot WITH &&)
);
CREATE INDEX ix_schedules_offering_term ON schedules (offering_id, stream, term_id);
CREATE INDEX ix_schedules_subject ON schedules (subject_id);

-- =====================================================================
-- 6. Enrolment, requirements and documents
-- =====================================================================
CREATE TABLE enrolment_requirements (
    requirement_id  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code            VARCHAR(20)  NOT NULL UNIQUE,
    name_en         VARCHAR(100) NOT NULL,
    name_sw         VARCHAR(100) NOT NULL,
    description     TEXT,
    education_level VARCHAR(12),                               -- NULL = every level
    is_mandatory    BOOLEAN      NOT NULL DEFAULT TRUE,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    CONSTRAINT ck_requirements_edu CHECK (education_level IN ('PRE_PRIMARY','PRIMARY','O_LEVEL','A_LEVEL'))
);

CREATE TABLE enrolments (
    enrolment_id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    enrolment_no   VARCHAR(20)  NOT NULL UNIQUE,               -- ENR-2026-000001
    student_id     BIGINT       NOT NULL REFERENCES students (student_id),
    offering_id    BIGINT       NOT NULL REFERENCES course_offerings (offering_id),
    stream         VARCHAR(5),
    status         VARCHAR(10)  NOT NULL DEFAULT 'PENDING',
    applied_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    submitted_at   TIMESTAMPTZ,
    confirmed_at   TIMESTAMPTZ,
    confirmed_by   BIGINT       REFERENCES users (user_id),
    cancelled_at   TIMESTAMPTZ,
    cancel_reason  VARCHAR(300),
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_enrolments_status CHECK (status IN
        ('PENDING','SUBMITTED','INVALID','VALIDATED','CONFIRMED','CANCELLED')),
    CONSTRAINT ck_enrolments_stream    CHECK (stream ~ '^[A-Z]{1,5}$'),
    CONSTRAINT ck_enrolments_confirmed CHECK (status <> 'CONFIRMED' OR (confirmed_at IS NOT NULL AND stream IS NOT NULL)),
    CONSTRAINT ck_enrolments_cancelled CHECK (status <> 'CANCELLED' OR (cancelled_at IS NOT NULL AND cancel_reason IS NOT NULL))
);
CREATE INDEX ix_enrolments_student  ON enrolments (student_id);
CREATE INDEX ix_enrolments_offering ON enrolments (offering_id, stream, status);

CREATE TABLE enrolment_documents (
    document_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    enrolment_id    BIGINT       NOT NULL REFERENCES enrolments (enrolment_id),
    requirement_id  INTEGER      NOT NULL REFERENCES enrolment_requirements (requirement_id),
    file_name       VARCHAR(255) NOT NULL,
    storage_key     VARCHAR(255) NOT NULL UNIQUE,              -- object-storage key, not a path
    mime_type       VARCHAR(50)  NOT NULL,
    file_size_bytes INTEGER      NOT NULL,
    sha256          CHAR(64)     NOT NULL,
    status          VARCHAR(8)   NOT NULL DEFAULT 'PENDING',
    remarks         VARCHAR(300),
    uploaded_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    validated_by    BIGINT       REFERENCES users (user_id),
    validated_at    TIMESTAMPTZ,
    CONSTRAINT uq_enrolment_documents UNIQUE (enrolment_id, requirement_id),
    CONSTRAINT ck_documents_mime   CHECK (mime_type IN ('application/pdf','image/jpeg','image/png')),
    CONSTRAINT ck_documents_size   CHECK (file_size_bytes BETWEEN 1 AND 5242880),   -- 5 MB
    CONSTRAINT ck_documents_status CHECK (status IN ('PENDING','VALID','INVALID')),
    CONSTRAINT ck_documents_validated CHECK (status = 'PENDING' OR (validated_by IS NOT NULL AND validated_at IS NOT NULL)),
    CONSTRAINT ck_documents_remarks   CHECK (status <> 'INVALID' OR remarks IS NOT NULL)
);

CREATE TABLE enrolment_schedules (                          -- M:N student enrolment <-> class session
    enrolment_id BIGINT      NOT NULL REFERENCES enrolments (enrolment_id),
    schedule_id  BIGINT      NOT NULL REFERENCES schedules (schedule_id),
    assigned_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (enrolment_id, schedule_id)
);
CREATE INDEX ix_enrolment_schedules_schedule ON enrolment_schedules (schedule_id);

-- =====================================================================
-- 7. Results and attendance
-- =====================================================================
CREATE TABLE results (
    result_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    enrolment_id    BIGINT       NOT NULL REFERENCES enrolments (enrolment_id),
    subject_id      INTEGER      NOT NULL REFERENCES subjects (subject_id),
    term_id         INTEGER      NOT NULL REFERENCES terms (term_id),
    assessment_type VARCHAR(10)  NOT NULL,
    score           NUMERIC(5,2) NOT NULL,                    -- grade/points derived in v_student_results
    is_published    BOOLEAN      NOT NULL DEFAULT FALSE,
    entered_by      BIGINT       NOT NULL REFERENCES users (user_id),
    entered_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_results UNIQUE (enrolment_id, subject_id, term_id, assessment_type),
    CONSTRAINT ck_results_type  CHECK (assessment_type IN ('MONTHLY','MIDTERM','TERMINAL','ANNUAL','MOCK')),
    CONSTRAINT ck_results_score CHECK (score BETWEEN 0 AND 100)
);
CREATE INDEX ix_results_term_subject ON results (term_id, subject_id);

CREATE TABLE attendance (
    attendance_id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    enrolment_id    BIGINT       NOT NULL,
    schedule_id     BIGINT       NOT NULL,
    attendance_date DATE         NOT NULL,
    status          VARCHAR(8)   NOT NULL,
    remarks         VARCHAR(200),
    recorded_by     BIGINT       NOT NULL REFERENCES users (user_id),
    recorded_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT fk_attendance_enrolment_schedule FOREIGN KEY (enrolment_id, schedule_id)
        REFERENCES enrolment_schedules (enrolment_id, schedule_id),   -- only students in that class
    CONSTRAINT uq_attendance UNIQUE (enrolment_id, schedule_id, attendance_date),
    CONSTRAINT ck_attendance_status CHECK (status IN ('PRESENT','ABSENT','LATE','EXCUSED'))
);
CREATE INDEX ix_attendance_schedule_date ON attendance (schedule_id, attendance_date);

-- =====================================================================
-- 8. Fees, invoices and transactions (TZS)
-- =====================================================================
CREATE TABLE fee_structures (
    fee_structure_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    term_id          INTEGER       NOT NULL REFERENCES terms (term_id),   -- annual fees are billed in term 1
    level_id         INTEGER       NOT NULL REFERENCES class_levels (level_id),
    course_id        INTEGER       REFERENCES courses (course_id),       -- NULL = every course at the level
    fee_item         VARCHAR(12)   NOT NULL,
    description      VARCHAR(120)  NOT NULL,
    amount_tzs       NUMERIC(14,2) NOT NULL,
    is_mandatory     BOOLEAN       NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_fee_structures UNIQUE NULLS NOT DISTINCT (term_id, level_id, course_id, fee_item),
    CONSTRAINT ck_fee_structures_item   CHECK (fee_item IN ('TUITION','BOARDING','MEALS','EXAMINATION','UNIFORM','DEVELOPMENT','OTHER')),
    CONSTRAINT ck_fee_structures_amount CHECK (amount_tzs >= 0)
);

CREATE TABLE invoices (
    invoice_id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    invoice_no      VARCHAR(20)  NOT NULL UNIQUE,              -- INV-2026-000001
    student_id      BIGINT       NOT NULL REFERENCES students (student_id),
    term_id         INTEGER      NOT NULL REFERENCES terms (term_id),
    gepg_control_no VARCHAR(12)  UNIQUE,                       -- issued by GePG
    issued_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    due_date        DATE         NOT NULL,
    issued_by       BIGINT       REFERENCES users (user_id),
    cancelled_at    TIMESTAMPTZ,
    cancel_reason   VARCHAR(300),
    CONSTRAINT uq_invoices_id_student UNIQUE (invoice_id, student_id),   -- target of composite FK
    CONSTRAINT ck_invoices_control_no CHECK (gepg_control_no ~ '^[0-9]{12}$'),
    CONSTRAINT ck_invoices_cancel     CHECK ((cancelled_at IS NULL) = (cancel_reason IS NULL))
);
CREATE INDEX ix_invoices_student_term ON invoices (student_id, term_id);

CREATE TABLE invoice_items (
    invoice_item_id  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    invoice_id       BIGINT        NOT NULL REFERENCES invoices (invoice_id),
    fee_structure_id BIGINT        REFERENCES fee_structures (fee_structure_id),
    description      VARCHAR(120)  NOT NULL,                   -- snapshot at billing time
    amount_tzs       NUMERIC(14,2) NOT NULL,                   -- snapshot at billing time
    CONSTRAINT ck_invoice_items_amount CHECK (amount_tzs >= 0)
);
CREATE INDEX ix_invoice_items_invoice ON invoice_items (invoice_id);

CREATE TABLE transactions (                                 -- append-only money ledger
    trans_id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trans_no          VARCHAR(20)   NOT NULL UNIQUE,           -- TXN-2026-000001
    trans_type        VARCHAR(10)   NOT NULL,
    trans_name        VARCHAR(120)  NOT NULL,                  -- human description (baseline field)
    student_id        BIGINT        NOT NULL REFERENCES students (student_id),
    invoice_id        BIGINT,
    amount_tzs        NUMERIC(14,2) NOT NULL,
    payment_method    VARCHAR(12),
    reference_no      VARCHAR(50),                             -- M-Pesa / bank / GePG receipt
    payer_name        VARCHAR(100),
    payer_phone       VARCHAR(12),
    status            VARCHAR(10)   NOT NULL DEFAULT 'PENDING',
    source            VARCHAR(10)   NOT NULL DEFAULT 'MANUAL',
    reverses_trans_id BIGINT        UNIQUE REFERENCES transactions (trans_id),
    trans_date        TIMESTAMPTZ   NOT NULL DEFAULT now(),
    recorded_by       BIGINT        REFERENCES users (user_id),
    created_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT fk_transactions_invoice FOREIGN KEY (invoice_id, student_id)
        REFERENCES invoices (invoice_id, student_id),
    CONSTRAINT ck_trans_type    CHECK (trans_type IN ('PAYMENT','REFUND','WAIVER','REVERSAL')),
    CONSTRAINT ck_trans_amount  CHECK (amount_tzs > 0),
    CONSTRAINT ck_trans_method  CHECK (payment_method IN ('CASH','BANK','MPESA','TIGO_PESA','AIRTEL_MONEY','GEPG')),
    CONSTRAINT ck_trans_status  CHECK (status IN ('PENDING','COMPLETED','FAILED')),
    CONSTRAINT ck_trans_source  CHECK (source IN ('MANUAL','GEPG','MOBILE_API')),
    CONSTRAINT ck_trans_method_required CHECK (trans_type IN ('WAIVER','REVERSAL') OR payment_method IS NOT NULL),
    CONSTRAINT ck_trans_reference CHECK (payment_method IS NULL OR payment_method = 'CASH' OR reference_no IS NOT NULL),
    CONSTRAINT ck_trans_reversal  CHECK ((trans_type = 'REVERSAL') = (reverses_trans_id IS NOT NULL)),
    CONSTRAINT ck_trans_recorder  CHECK (source <> 'MANUAL' OR recorded_by IS NOT NULL),
    CONSTRAINT ck_trans_phone     CHECK (payer_phone ~ '^255[0-9]{9}$'),
    CONSTRAINT uq_trans_reference UNIQUE (payment_method, reference_no)    -- no double posting
);
CREATE INDEX ix_transactions_student_date ON transactions (student_id, trans_date DESC);
CREATE INDEX ix_transactions_invoice ON transactions (invoice_id);
CREATE INDEX ix_transactions_date ON transactions (trans_date);

-- =====================================================================
-- 9. Security: refresh tokens and audit log
-- =====================================================================
CREATE TABLE refresh_tokens (
    token_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     BIGINT       NOT NULL REFERENCES users (user_id),
    token_hash  CHAR(64)     NOT NULL UNIQUE,                  -- SHA-256 of the opaque token
    family_id   UUID         NOT NULL,                         -- rotation chain (reuse detection)
    issued_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ  NOT NULL,
    revoked_at  TIMESTAMPTZ,
    user_agent  VARCHAR(255),
    ip_address  INET,
    CONSTRAINT ck_refresh_tokens_expiry CHECK (expires_at > issued_at)
);
CREATE INDEX ix_refresh_tokens_user   ON refresh_tokens (user_id) WHERE revoked_at IS NULL;
CREATE INDEX ix_refresh_tokens_family ON refresh_tokens (family_id);

CREATE TABLE audit_logs (
    audit_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    actor_user_id  BIGINT       REFERENCES users (user_id),    -- NULL = system / callback
    actor_role     VARCHAR(12),
    action         VARCHAR(20)  NOT NULL,
    entity_type    VARCHAR(40)  NOT NULL,
    entity_id      VARCHAR(40),
    old_values     JSONB,
    new_values     JSONB,
    ip_address     INET,
    user_agent     VARCHAR(255),
    request_id     UUID,
    CONSTRAINT ck_audit_action CHECK (action IN ('INSERT','UPDATE','DELETE','LOGIN','LOGIN_FAILED',
        'LOGOUT','TOKEN_REFRESH','TOKEN_REUSE','PASSWORD_CHANGE','EXPORT','VIEW_SENSITIVE'))
);
CREATE INDEX ix_audit_entity ON audit_logs (entity_type, entity_id, occurred_at DESC);
CREATE INDEX ix_audit_actor  ON audit_logs (actor_user_id, occurred_at DESC);
CREATE INDEX brin_audit_occurred ON audit_logs USING brin (occurred_at);

-- Document numbers (S2026-0001, ENR-2026-000001, INV-…, TXN-…) come from
-- sequences, so two clerks working at the same moment never get the same number.
CREATE SEQUENCE seq_admission_no;
CREATE SEQUENCE seq_enrolment_no;
CREATE SEQUENCE seq_invoice_no;
CREATE SEQUENCE seq_trans_no;

-- =====================================================================
-- 10. Integrity and audit triggers
-- =====================================================================

-- 10.1 Audit log is append-only (also REVOKE UPDATE/DELETE from the app role).
CREATE FUNCTION fn_audit_logs_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_logs is append-only (% blocked)', TG_OP;
END $$;
CREATE TRIGGER trg_audit_logs_append_only
    BEFORE UPDATE OR DELETE OR TRUNCATE ON audit_logs
    FOR EACH STATEMENT EXECUTE FUNCTION fn_audit_logs_append_only();

-- 10.2 Generic row audit. The API sets app.user_id / app.user_role /
--      app.client_ip / app.request_id with SET LOCAL in every transaction.
CREATE FUNCTION fn_audit_row() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_old JSONB;
    v_new JSONB;
BEGIN
    IF TG_OP IN ('UPDATE','DELETE') THEN v_old := to_jsonb(OLD) - 'password_hash'; END IF;
    IF TG_OP IN ('INSERT','UPDATE') THEN v_new := to_jsonb(NEW) - 'password_hash'; END IF;
    IF TG_OP = 'UPDATE' AND (v_old - 'updated_at') = (v_new - 'updated_at') THEN
        RETURN NULL;                                           -- nothing visible changed
    END IF;
    INSERT INTO audit_logs (actor_user_id, actor_role, action, entity_type, entity_id,
                            old_values, new_values, ip_address, request_id)
    VALUES (NULLIF(current_setting('app.user_id', true), '')::BIGINT,
            NULLIF(current_setting('app.user_role', true), ''),
            TG_OP, TG_TABLE_NAME,
            COALESCE(v_new, v_old) ->> TG_ARGV[0],
            v_old, v_new,
            NULLIF(current_setting('app.client_ip', true), '')::INET,
            NULLIF(current_setting('app.request_id', true), '')::UUID);
    RETURN NULL;
END $$;

CREATE TRIGGER trg_audit_users        AFTER INSERT OR UPDATE OR DELETE ON users        FOR EACH ROW EXECUTE FUNCTION fn_audit_row('user_id');
CREATE TRIGGER trg_audit_students     AFTER INSERT OR UPDATE OR DELETE ON students     FOR EACH ROW EXECUTE FUNCTION fn_audit_row('student_id');
CREATE TRIGGER trg_audit_instructors  AFTER INSERT OR UPDATE OR DELETE ON instructors  FOR EACH ROW EXECUTE FUNCTION fn_audit_row('instructor_id');
CREATE TRIGGER trg_audit_instr_desig  AFTER INSERT OR UPDATE OR DELETE ON instructor_designations FOR EACH ROW EXECUTE FUNCTION fn_audit_row('instructor_designation_id');
CREATE TRIGGER trg_audit_courses      AFTER INSERT OR UPDATE OR DELETE ON courses      FOR EACH ROW EXECUTE FUNCTION fn_audit_row('course_id');
CREATE TRIGGER trg_audit_subjects     AFTER INSERT OR UPDATE OR DELETE ON subjects     FOR EACH ROW EXECUTE FUNCTION fn_audit_row('subject_id');
CREATE TRIGGER trg_audit_offerings    AFTER INSERT OR UPDATE OR DELETE ON course_offerings FOR EACH ROW EXECUTE FUNCTION fn_audit_row('offering_id');
CREATE TRIGGER trg_audit_schedules    AFTER INSERT OR UPDATE OR DELETE ON schedules    FOR EACH ROW EXECUTE FUNCTION fn_audit_row('schedule_id');
CREATE TRIGGER trg_audit_enrolments   AFTER INSERT OR UPDATE OR DELETE ON enrolments   FOR EACH ROW EXECUTE FUNCTION fn_audit_row('enrolment_id');
CREATE TRIGGER trg_audit_documents    AFTER INSERT OR UPDATE OR DELETE ON enrolment_documents FOR EACH ROW EXECUTE FUNCTION fn_audit_row('document_id');
CREATE TRIGGER trg_audit_results      AFTER INSERT OR UPDATE OR DELETE ON results      FOR EACH ROW EXECUTE FUNCTION fn_audit_row('result_id');
CREATE TRIGGER trg_audit_fees         AFTER INSERT OR UPDATE OR DELETE ON fee_structures FOR EACH ROW EXECUTE FUNCTION fn_audit_row('fee_structure_id');
CREATE TRIGGER trg_audit_invoices     AFTER INSERT OR UPDATE OR DELETE ON invoices     FOR EACH ROW EXECUTE FUNCTION fn_audit_row('invoice_id');
CREATE TRIGGER trg_audit_transactions AFTER INSERT OR UPDATE OR DELETE ON transactions FOR EACH ROW EXECUTE FUNCTION fn_audit_row('trans_id');

-- 10.3 updated_at maintenance
CREATE TRIGGER trg_users_updated       BEFORE UPDATE ON users       FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
CREATE TRIGGER trg_students_updated    BEFORE UPDATE ON students    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
CREATE TRIGGER trg_instructors_updated BEFORE UPDATE ON instructors FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
CREATE TRIGGER trg_courses_updated     BEFORE UPDATE ON courses     FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
CREATE TRIGGER trg_schedules_updated   BEFORE UPDATE ON schedules   FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
CREATE TRIGGER trg_enrolments_updated  BEFORE UPDATE ON enrolments  FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
CREATE TRIGGER trg_results_updated     BEFORE UPDATE ON results     FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

-- 10.4 Transactions are append-only. Only a PENDING row may change, and
--      only its status / reference_no / trans_date (payment callback).
--      Mistakes are corrected by posting a REVERSAL row.
CREATE FUNCTION fn_transactions_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'transactions are append-only; post a REVERSAL instead';
    END IF;
    IF OLD.status <> 'PENDING'
       OR NEW.status NOT IN ('PENDING','COMPLETED','FAILED')
       OR (to_jsonb(NEW) - 'status' - 'reference_no' - 'trans_date')
          <> (to_jsonb(OLD) - 'status' - 'reference_no' - 'trans_date') THEN
        RAISE EXCEPTION 'transaction % is immutable once %', OLD.trans_no, OLD.status;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_transactions_guard
    BEFORE UPDATE OR DELETE ON transactions
    FOR EACH ROW EXECUTE FUNCTION fn_transactions_guard();

-- 10.5 One active (non-cancelled) enrolment per student per academic year.
--      Done in a trigger instead of copying academic_year_id into
--      enrolments, which would break 3NF. The student row lock
--      serialises concurrent enrolments of the same student.
CREATE FUNCTION fn_enrolments_one_per_year() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status = 'CANCELLED' THEN
        RETURN NEW;
    END IF;
    PERFORM 1 FROM students WHERE student_id = NEW.student_id FOR UPDATE;
    IF EXISTS (
        SELECT 1
        FROM enrolments e
        JOIN course_offerings o ON o.offering_id = e.offering_id
        JOIN course_offerings n ON n.offering_id = NEW.offering_id
        WHERE e.student_id = NEW.student_id
          AND e.enrolment_id <> NEW.enrolment_id
          AND e.status <> 'CANCELLED'
          AND o.academic_year_id = n.academic_year_id
    ) THEN
        RAISE EXCEPTION 'student % already has an active enrolment for this academic year', NEW.student_id
            USING ERRCODE = 'unique_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_enrolments_one_per_year
    BEFORE INSERT OR UPDATE OF student_id, offering_id, status ON enrolments
    FOR EACH ROW EXECUTE FUNCTION fn_enrolments_one_per_year();

-- 10.6 A student can never be placed in two overlapping class sessions.
CREATE FUNCTION fn_enrolment_schedules_no_clash() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_student BIGINT;
    v_term    INTEGER;
    v_day     SMALLINT;
    v_slot    timerange;
BEGIN
    SELECT student_id INTO v_student FROM enrolments WHERE enrolment_id = NEW.enrolment_id;
    SELECT term_id, day_of_week, slot INTO v_term, v_day, v_slot
      FROM schedules WHERE schedule_id = NEW.schedule_id;
    PERFORM 1 FROM students WHERE student_id = v_student FOR UPDATE;
    IF EXISTS (
        SELECT 1
        FROM enrolment_schedules es
        JOIN enrolments e ON e.enrolment_id = es.enrolment_id
        JOIN schedules  s ON s.schedule_id  = es.schedule_id
        WHERE e.student_id = v_student
          AND e.status <> 'CANCELLED'
          AND s.schedule_id <> NEW.schedule_id
          AND s.term_id = v_term
          AND s.day_of_week = v_day
          AND s.slot && v_slot
    ) THEN
        RAISE EXCEPTION 'student % already has a class that overlaps schedule %', v_student, NEW.schedule_id
            USING ERRCODE = 'exclusion_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_enrolment_schedules_no_clash
    BEFORE INSERT OR UPDATE ON enrolment_schedules
    FOR EACH ROW EXECUTE FUNCTION fn_enrolment_schedules_no_clash();

-- =====================================================================
-- 11. Views (derived data lives here, not in tables)
-- =====================================================================
CREATE VIEW v_invoice_balances AS
SELECT i.invoice_id,
       i.invoice_no,
       i.student_id,
       i.term_id,
       i.gepg_control_no,
       i.due_date,
       COALESCE(it.total_tzs, 0)                              AS total_tzs,
       COALESCE(tx.credited_tzs, 0)                           AS paid_tzs,
       COALESCE(it.total_tzs, 0) - COALESCE(tx.credited_tzs, 0) AS balance_tzs,
       CASE
           WHEN i.cancelled_at IS NOT NULL                            THEN 'CANCELLED'
           WHEN COALESCE(tx.credited_tzs, 0) >= COALESCE(it.total_tzs, 0) THEN 'PAID'
           WHEN COALESCE(tx.credited_tzs, 0) > 0                      THEN 'PARTIALLY_PAID'
           WHEN i.due_date < CURRENT_DATE                             THEN 'OVERDUE'
           ELSE 'UNPAID'
       END                                                    AS payment_status
FROM invoices i
LEFT JOIN (SELECT invoice_id, SUM(amount_tzs) AS total_tzs
           FROM invoice_items GROUP BY invoice_id) it ON it.invoice_id = i.invoice_id
LEFT JOIN (SELECT invoice_id,
                  SUM(CASE WHEN trans_type IN ('PAYMENT','WAIVER') THEN amount_tzs
                           ELSE -amount_tzs END) AS credited_tzs        -- REFUND, REVERSAL
           FROM transactions
           WHERE status = 'COMPLETED' AND invoice_id IS NOT NULL
           GROUP BY invoice_id) tx ON tx.invoice_id = i.invoice_id;

CREATE VIEW v_student_results AS
SELECT r.result_id,
       e.student_id,
       r.enrolment_id,
       r.term_id,
       r.subject_id,
       r.assessment_type,
       r.score,
       cl.exam_scale,
       g.grade,
       g.points,
       g.remark_en,
       g.remark_sw,
       r.is_published
FROM results r
JOIN enrolments       e  ON e.enrolment_id = r.enrolment_id
JOIN course_offerings o  ON o.offering_id  = e.offering_id
JOIN class_levels     cl ON cl.level_id    = o.level_id
LEFT JOIN LATERAL (
    SELECT gs.grade, gs.points, gs.remark_en, gs.remark_sw
    FROM grading_scales gs
    WHERE gs.exam_scale = cl.exam_scale AND r.score >= gs.min_score
    ORDER BY gs.min_score DESC
    LIMIT 1
) g ON TRUE;

CREATE VIEW v_class_lists AS                                 -- "List of Students" for instructors
SELECT s.schedule_id, s.term_id, s.subject_id, s.instructor_id,
       e.enrolment_id, e.stream, st.student_id, st.admission_no,
       u.first_name, u.middle_name, u.last_name, u.gender
FROM schedules s
JOIN enrolment_schedules es ON es.schedule_id = s.schedule_id
JOIN enrolments e  ON e.enrolment_id = es.enrolment_id AND e.status = 'CONFIRMED'
JOIN students   st ON st.student_id  = e.student_id
JOIN users      u  ON u.user_id      = st.user_id;

CREATE VIEW v_student_current_enrolment AS
SELECT e.student_id, e.enrolment_id, e.stream,
       o.offering_id, o.course_id, o.level_id, o.academic_year_id
FROM enrolments e
JOIN course_offerings o ON o.offering_id = e.offering_id
JOIN academic_years  ay ON ay.academic_year_id = o.academic_year_id AND ay.is_current
WHERE e.status = 'CONFIRMED';

-- =====================================================================
-- 12. Least-privilege roles (run as superuser; adjust passwords)
-- =====================================================================
-- CREATE ROLE sms_app LOGIN PASSWORD 'change-me';
-- GRANT USAGE ON SCHEMA public TO sms_app;
-- GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO sms_app;
-- GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO sms_app;
-- REVOKE UPDATE ON audit_logs FROM sms_app;            -- append-only
-- CREATE ROLE sms_reporting LOGIN PASSWORD 'change-me'; -- read-only for reports
-- GRANT SELECT ON ALL TABLES IN SCHEMA public TO sms_reporting;
-- REVOKE SELECT ON users, refresh_tokens FROM sms_reporting;
