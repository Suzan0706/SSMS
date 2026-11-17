-- =====================================================================
--  SMART SCHOOL MANAGEMENT SYSTEM (SSMS) — multi-tenant PostgreSQL 16 schema
--  File: design/sql/schema.sql            Phase 0 design baseline
--
--  Conventions (see design/06-data-model.md for the reasoning)
--    * id UUID PK on every table; the API generates time-ordered UUIDv7,
--      the DB default gen_random_uuid() is the fallback.
--    * Every tenant table has school_id UUID NOT NULL, UNIQUE (school_id, id),
--      and references other tenant tables with COMPOSITE foreign keys
--      (school_id, x_id) -> x (school_id, id): a row can never point at
--      another school's row.
--    * Row-Level Security is ENABLED and FORCED on every tenant table
--      (section 13). The API sets SET LOCAL app.school_id per transaction.
--    * created_at / updated_at / created_by everywhere; deleted_at (soft delete)
--      everywhere except ledgers, logs and frozen results.
--    * Enumerations are VARCHAR + CHECK. Money is NUMERIC(14,2) TZS.
--    * Personal identifiers (phone, NIDA, birth certificate no., health notes)
--      are encrypted by the application (AES-256-GCM, *_enc BYTEA) with a
--      keyed blind index (*_hash = HMAC-SHA256) for exact-match lookups.
--  Only global (non-tenant) tables: platform_admins, roles, permissions,
--  role_permissions — platform reference data, not school business data.
-- =====================================================================

-- =====================================================================
-- 0. ROLES (this block runs as a superuser, once per cluster)
--    ssms_owner      owns every object, runs migrations and seeds. Never used at runtime.
--    ssms_app        runtime login for the API and Celery workers. NOSUPERUSER NOBYPASSRLS.
--    ssms_resolver   NOLOGIN BYPASSRLS. Owns only the SECURITY DEFINER resolver functions
--                    (section 17) that map an external identifier to a school before the
--                    tenant is known. Returns ids, never data.
--    ssms_platform   NOLOGIN BYPASSRLS. Super-admin console (create schools, cross-tenant
--                    support). Granted to a separate login used only by that console.
--    ssms_reporting  read-only analytics. NOBYPASSRLS (sees one school at a time).
--    Passwords are set by operations (ALTER ROLE ... PASSWORD), never in this file.
-- =====================================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ssms_owner') THEN
        CREATE ROLE ssms_owner NOLOGIN NOSUPERUSER NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ssms_app') THEN
        CREATE ROLE ssms_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ssms_resolver') THEN
        CREATE ROLE ssms_resolver NOLOGIN NOSUPERUSER BYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ssms_platform') THEN
        CREATE ROLE ssms_platform NOLOGIN NOSUPERUSER BYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ssms_reporting') THEN
        CREATE ROLE ssms_reporting NOLOGIN NOSUPERUSER NOBYPASSRLS;
    END IF;
END $$;

CREATE EXTENSION IF NOT EXISTS btree_gist;          -- EXCLUDE with = and && together

GRANT USAGE, CREATE ON SCHEMA public TO ssms_owner;
SET ROLE ssms_owner;                                -- everything below is owned by ssms_owner

CREATE TYPE timerange AS RANGE (subtype = time);

-- Request context set by the API with SET LOCAL (NULL = no access: fail closed)
CREATE FUNCTION app_school_id() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.school_id', true), '')::uuid $$;
CREATE FUNCTION app_user_id() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$;

CREATE FUNCTION fn_touch_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at := now(); RETURN NEW; END $$;

CREATE FUNCTION fn_block_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only/frozen: % not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'P0001';
END $$;

-- =====================================================================
-- 1. PLATFORM (global)
-- =====================================================================
CREATE TABLE platform_admins (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name      VARCHAR(100) NOT NULL,
    email          VARCHAR(254) NOT NULL,
    password_hash  VARCHAR(255) NOT NULL,
    mfa_secret_enc BYTEA,
    is_active      BOOLEAN      NOT NULL DEFAULT TRUE,
    last_login_at  TIMESTAMPTZ,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_platform_admins_email ON platform_admins (lower(email));

CREATE TABLE roles (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code        VARCHAR(30)  NOT NULL UNIQUE,
    name_en     VARCHAR(60)  NOT NULL,
    name_sw     VARCHAR(60)  NOT NULL,
    is_system   BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_roles_code CHECK (code ~ '^[a-z_]+$')
);

CREATE TABLE permissions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code            VARCHAR(60)  NOT NULL UNIQUE,          -- module.action, e.g. results.publish
    module          VARCHAR(30)  NOT NULL,
    description_en  VARCHAR(200) NOT NULL,
    description_sw  VARCHAR(200) NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_permissions_code CHECK (code ~ '^[a-z_]+\.[a-z_]+$')
);

CREATE TABLE role_permissions (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role_id        UUID NOT NULL REFERENCES roles (id),
    permission_id  UUID NOT NULL REFERENCES permissions (id),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_role_permissions UNIQUE (role_id, permission_id)
);

-- =====================================================================
-- 2. TENANTS
-- =====================================================================
CREATE TABLE schools (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code             VARCHAR(20)  NOT NULL UNIQUE,             -- URL slug, e.g. mfano-sec
    name             VARCHAR(150) NOT NULL,
    registration_no  VARCHAR(30)  UNIQUE,                      -- e.g. S.4521 / EM.11873
    ownership        VARCHAR(12)  NOT NULL,
    region           VARCHAR(40)  NOT NULL,
    district         VARCHAR(40)  NOT NULL,
    status           VARCHAR(12)  NOT NULL DEFAULT 'ONBOARDING',
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by       UUID REFERENCES platform_admins (id),
    deleted_at       TIMESTAMPTZ,
    CONSTRAINT ck_schools_code      CHECK (code ~ '^[a-z0-9-]{3,20}$'),
    CONSTRAINT ck_schools_ownership CHECK (ownership IN ('GOVERNMENT','PRIVATE','FAITH_BASED','COMMUNITY')),
    CONSTRAINT ck_schools_status    CHECK (status IN ('ONBOARDING','ACTIVE','SUSPENDED','CLOSED'))
);

CREATE TABLE school_settings (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id              UUID NOT NULL UNIQUE REFERENCES schools (id),
    motto                  VARCHAR(150),
    logo_file_key          VARCHAR(255),
    postal_address         VARCHAR(150),
    physical_address       VARCHAR(200),
    phone                  VARCHAR(12),                         -- school office line (not personal data)
    email                  VARCHAR(254),
    medium_of_instruction  VARCHAR(10)  NOT NULL DEFAULT 'KISWAHILI',
    default_language       CHAR(2)      NOT NULL DEFAULT 'sw',
    sms_sender_id          VARCHAR(11),
    gepg_sp_code           VARCHAR(10),
    gepg_sub_sp_code       VARCHAR(10),
    absence_sms_cutoff     TIME         NOT NULL DEFAULT '08:30',
    is_open_for_enrolment  BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by             UUID,
    deleted_at             TIMESTAMPTZ,
    CONSTRAINT uq_school_settings_tenant UNIQUE (school_id, id),
    CONSTRAINT ck_settings_medium CHECK (medium_of_instruction IN ('KISWAHILI','ENGLISH')),
    CONSTRAINT ck_settings_lang   CHECK (default_language IN ('sw','en')),
    CONSTRAINT ck_settings_phone  CHECK (phone ~ '^255[0-9]{9}$'),
    CONSTRAINT ck_settings_sender CHECK (sms_sender_id ~ '^[A-Za-z0-9 -]{3,11}$')
);

-- Gapless per-school document numbers (admission, invoice, receipt, application)
CREATE TABLE document_sequences (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id   UUID        NOT NULL REFERENCES schools (id),
    doc_type    VARCHAR(20) NOT NULL,
    year        SMALLINT    NOT NULL,
    last_value  INTEGER     NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_document_sequences UNIQUE (school_id, doc_type, year),
    CONSTRAINT ck_document_sequences_type CHECK (doc_type IN ('ADMISSION','APPLICATION','INVOICE','RECEIPT','JOURNAL')),
    CONSTRAINT ck_document_sequences_value CHECK (last_value >= 0)
);

-- =====================================================================
-- 3. PEOPLE AND ACCESS
-- =====================================================================
CREATE TABLE users (                                  -- abstract person + login
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id             UUID NOT NULL REFERENCES schools (id),
    first_name            VARCHAR(50)  NOT NULL,
    middle_name           VARCHAR(50),
    last_name             VARCHAR(50)  NOT NULL,
    gender                CHAR(1)      NOT NULL,
    date_of_birth         DATE,
    phone_enc             BYTEA,
    phone_hash            BYTEA,
    phone_last4           CHAR(4),
    email                 VARCHAR(254),
    username              VARCHAR(50),
    password_hash         VARCHAR(255),                 -- NULL: OTP-only parent or pupil without login
    preferred_language    CHAR(2)      NOT NULL DEFAULT 'sw',
    status                VARCHAR(10)  NOT NULL DEFAULT 'ACTIVE',
    failed_login_count    SMALLINT     NOT NULL DEFAULT 0,
    locked_until          TIMESTAMPTZ,
    last_login_at         TIMESTAMPTZ,
    must_change_password  BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by            UUID,
    deleted_at            TIMESTAMPTZ,
    CONSTRAINT uq_users_tenant UNIQUE (school_id, id),
    CONSTRAINT ck_users_gender CHECK (gender IN ('M','F')),
    CONSTRAINT ck_users_dob    CHECK (date_of_birth >= DATE '1920-01-01'),
    CONSTRAINT ck_users_phone  CHECK ((phone_enc IS NULL) = (phone_hash IS NULL) AND (phone_hash IS NULL) = (phone_last4 IS NULL)),
    CONSTRAINT ck_users_last4  CHECK (phone_last4 ~ '^[0-9]{4}$'),
    CONSTRAINT ck_users_email  CHECK (email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
    CONSTRAINT ck_users_lang   CHECK (preferred_language IN ('sw','en')),
    CONSTRAINT ck_users_status CHECK (status IN ('ACTIVE','DISABLED','LOCKED','NO_LOGIN')),
    CONSTRAINT ck_users_login  CHECK (status <> 'NO_LOGIN' OR password_hash IS NULL)
);
CREATE UNIQUE INDEX uq_users_username ON users (school_id, lower(username)) WHERE username IS NOT NULL AND deleted_at IS NULL;
CREATE UNIQUE INDEX uq_users_phone    ON users (school_id, phone_hash)      WHERE phone_hash IS NOT NULL AND deleted_at IS NULL;
CREATE UNIQUE INDEX uq_users_email    ON users (school_id, lower(email))    WHERE email IS NOT NULL AND deleted_at IS NULL;
CREATE INDEX ix_users_phone_lookup ON users (phone_hash) WHERE deleted_at IS NULL;   -- OTP login across schools
CREATE INDEX ix_users_name ON users (school_id, lower(last_name), lower(first_name));

CREATE TABLE user_roles (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id   UUID        NOT NULL REFERENCES schools (id),
    user_id     UUID        NOT NULL,
    role_id     UUID        NOT NULL REFERENCES roles (id),
    granted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by  UUID,
    CONSTRAINT uq_user_roles_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_user_roles_user FOREIGN KEY (school_id, user_id) REFERENCES users (school_id, id),
    CONSTRAINT ck_user_roles_dates CHECK (revoked_at IS NULL OR revoked_at >= granted_at)
);
CREATE UNIQUE INDEX uq_user_roles_active ON user_roles (school_id, user_id, role_id) WHERE revoked_at IS NULL;

CREATE TABLE refresh_tokens (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id   UUID        NOT NULL REFERENCES schools (id),
    user_id     UUID        NOT NULL,
    token_hash  CHAR(64)    NOT NULL UNIQUE,                -- SHA-256 of the opaque cookie value
    family_id   UUID        NOT NULL,
    issued_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ,
    user_agent  VARCHAR(255),
    ip_address  INET,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_refresh_tokens_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_refresh_tokens_user FOREIGN KEY (school_id, user_id) REFERENCES users (school_id, id),
    CONSTRAINT ck_refresh_tokens_expiry CHECK (expires_at > issued_at)
);
CREATE INDEX ix_refresh_tokens_family ON refresh_tokens (family_id);

CREATE TABLE otp_codes (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id    UUID        NOT NULL REFERENCES schools (id),
    user_id      UUID        NOT NULL,
    code_hash    CHAR(64)    NOT NULL,                     -- SHA-256(code || user_id), never the code
    purpose      VARCHAR(10) NOT NULL,
    expires_at   TIMESTAMPTZ NOT NULL,
    attempts     SMALLINT    NOT NULL DEFAULT 0,
    consumed_at  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_otp_codes_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_otp_codes_user FOREIGN KEY (school_id, user_id) REFERENCES users (school_id, id),
    CONSTRAINT ck_otp_purpose  CHECK (purpose IN ('LOGIN','RESET')),
    CONSTRAINT ck_otp_attempts CHECK (attempts BETWEEN 0 AND 5)
);
CREATE INDEX ix_otp_codes_user ON otp_codes (school_id, user_id, created_at DESC);

CREATE TABLE guardians (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id   UUID         NOT NULL REFERENCES schools (id),
    user_id     UUID         NOT NULL,
    nida_enc    BYTEA,
    nida_hash   BYTEA,
    occupation  VARCHAR(80),
    address     VARCHAR(200),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by  UUID,
    deleted_at  TIMESTAMPTZ,
    CONSTRAINT uq_guardians_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_guardians_user UNIQUE (school_id, user_id),
    CONSTRAINT fk_guardians_user FOREIGN KEY (school_id, user_id) REFERENCES users (school_id, id),
    CONSTRAINT ck_guardians_nida CHECK ((nida_enc IS NULL) = (nida_hash IS NULL))
);

CREATE TABLE students (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id            UUID        NOT NULL REFERENCES schools (id),
    user_id              UUID        NOT NULL,
    admission_no         VARCHAR(20) NOT NULL,             -- TZ-2026-0001
    birth_cert_no_enc    BYTEA,                            -- RITA birth certificate
    birth_cert_no_hash   BYTEA,
    nida_enc             BYTEA,                            -- optional for minors
    nida_hash            BYTEA,
    prem_number          VARCHAR(20),
    photo_file_key       VARCHAR(255),
    status               VARCHAR(12) NOT NULL DEFAULT 'APPLICANT',
    admission_date       DATE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by           UUID,
    deleted_at           TIMESTAMPTZ,
    CONSTRAINT uq_students_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_students_user UNIQUE (school_id, user_id),
    CONSTRAINT fk_students_user FOREIGN KEY (school_id, user_id) REFERENCES users (school_id, id),
    CONSTRAINT ck_students_status CHECK (status IN ('APPLICANT','ACTIVE','SUSPENDED','TRANSFERRED','GRADUATED','DROPPED_OUT')),
    CONSTRAINT ck_students_admission_no CHECK (admission_no ~ '^[A-Z]{2,4}-[0-9]{4}-[0-9]{4,6}$'),
    CONSTRAINT ck_students_bc   CHECK ((birth_cert_no_enc IS NULL) = (birth_cert_no_hash IS NULL)),
    CONSTRAINT ck_students_nida CHECK ((nida_enc IS NULL) = (nida_hash IS NULL))
);
CREATE UNIQUE INDEX uq_students_admission_no ON students (school_id, admission_no);
CREATE UNIQUE INDEX uq_students_birth_cert ON students (school_id, birth_cert_no_hash) WHERE birth_cert_no_hash IS NOT NULL AND deleted_at IS NULL;
CREATE INDEX ix_students_status ON students (school_id, status) WHERE deleted_at IS NULL;

CREATE TABLE student_status_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id       UUID         NOT NULL REFERENCES schools (id),
    student_id      UUID         NOT NULL,
    old_status      VARCHAR(12),
    new_status      VARCHAR(12)  NOT NULL,
    reason          VARCHAR(300) NOT NULL,
    effective_date  DATE         NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by      UUID,
    CONSTRAINT uq_student_status_history_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_status_history_student FOREIGN KEY (school_id, student_id) REFERENCES students (school_id, id),
    CONSTRAINT ck_status_history_change CHECK (old_status IS DISTINCT FROM new_status)
);

CREATE TABLE student_guardians (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id     UUID        NOT NULL REFERENCES schools (id),
    student_id    UUID        NOT NULL,
    guardian_id   UUID        NOT NULL,
    relationship  VARCHAR(10) NOT NULL,
    is_primary    BOOLEAN     NOT NULL DEFAULT FALSE,
    receives_sms  BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by    UUID,
    deleted_at    TIMESTAMPTZ,
    CONSTRAINT uq_student_guardians_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_sg_student  FOREIGN KEY (school_id, student_id)  REFERENCES students (school_id, id),
    CONSTRAINT fk_sg_guardian FOREIGN KEY (school_id, guardian_id) REFERENCES guardians (school_id, id),
    CONSTRAINT ck_sg_relationship CHECK (relationship IN ('FATHER','MOTHER','GUARDIAN','SPONSOR','SIBLING','OTHER'))
);
CREATE UNIQUE INDEX uq_student_guardians ON student_guardians (school_id, student_id, guardian_id) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_student_primary_guardian ON student_guardians (school_id, student_id) WHERE is_primary AND deleted_at IS NULL;
CREATE INDEX ix_student_guardians_guardian ON student_guardians (school_id, guardian_id);

CREATE TABLE consent_records (                        -- PDPA 2022: consent given by the guardian
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id     UUID        NOT NULL REFERENCES schools (id),
    guardian_id   UUID        NOT NULL,
    student_id    UUID,
    purpose       VARCHAR(20) NOT NULL,
    granted       BOOLEAN     NOT NULL,
    channel       VARCHAR(10) NOT NULL,
    recorded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    withdrawn_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by    UUID,
    CONSTRAINT uq_consent_records_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_consent_guardian FOREIGN KEY (school_id, guardian_id) REFERENCES guardians (school_id, id),
    CONSTRAINT fk_consent_student  FOREIGN KEY (school_id, student_id)  REFERENCES students (school_id, id),
    CONSTRAINT ck_consent_purpose CHECK (purpose IN ('SMS','DATA_PROCESSING','PHOTO_PUBLICATION','HEALTH_DATA')),
    CONSTRAINT ck_consent_channel CHECK (channel IN ('PAPER','PORTAL','SMS','IN_PERSON'))
);
CREATE INDEX ix_consent_guardian ON consent_records (school_id, guardian_id, purpose, recorded_at DESC);

CREATE TABLE data_subject_requests (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id        UUID         NOT NULL REFERENCES schools (id),
    subject_user_id  UUID         NOT NULL,
    request_type     VARCHAR(10)  NOT NULL,
    status           VARCHAR(12)  NOT NULL DEFAULT 'RECEIVED',
    details          VARCHAR(500),
    requested_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    due_at           TIMESTAMPTZ  NOT NULL,
    completed_at     TIMESTAMPTZ,
    handled_by       UUID,
    result_file_key  VARCHAR(255),
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by       UUID,
    CONSTRAINT uq_dsr_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_dsr_subject FOREIGN KEY (school_id, subject_user_id) REFERENCES users (school_id, id),
    CONSTRAINT fk_dsr_handler FOREIGN KEY (school_id, handled_by) REFERENCES users (school_id, id),
    CONSTRAINT ck_dsr_type   CHECK (request_type IN ('EXPORT','CORRECT','DELETE')),
    CONSTRAINT ck_dsr_status CHECK (status IN ('RECEIVED','IN_PROGRESS','COMPLETED','REJECTED'))
);

CREATE TABLE departments (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id      UUID        NOT NULL REFERENCES schools (id),
    code           VARCHAR(10) NOT NULL,
    name_en        VARCHAR(80) NOT NULL,
    name_sw        VARCHAR(80) NOT NULL,
    head_staff_id  UUID,                                    -- FK added after staff
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by     UUID,
    deleted_at     TIMESTAMPTZ,
    CONSTRAINT uq_departments_tenant UNIQUE (school_id, id)
);
CREATE UNIQUE INDEX uq_departments_code ON departments (school_id, code) WHERE deleted_at IS NULL;

CREATE TABLE designations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id   UUID        NOT NULL REFERENCES schools (id),
    code        VARCHAR(20) NOT NULL,
    name_en     VARCHAR(60) NOT NULL,
    name_sw     VARCHAR(60) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by  UUID,
    deleted_at  TIMESTAMPTZ,
    CONSTRAINT uq_designations_tenant UNIQUE (school_id, id)
);
CREATE UNIQUE INDEX uq_designations_code ON designations (school_id, code) WHERE deleted_at IS NULL;

CREATE TABLE staff (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id             UUID          NOT NULL REFERENCES schools (id),
    user_id               UUID          NOT NULL,
    staff_no              VARCHAR(20)   NOT NULL,
    check_no              VARCHAR(20),                       -- government payroll check number
    department_id         UUID,
    designation_id        UUID,
    employment_type       VARCHAR(10)   NOT NULL DEFAULT 'PERMANENT',
    employment_date       DATE,
    salary_tzs            NUMERIC(14,2),                     -- restricted: payroll.read permission
    max_periods_per_week  SMALLINT      NOT NULL DEFAULT 30,
    status                VARCHAR(12)   NOT NULL DEFAULT 'ACTIVE',
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
    created_by            UUID,
    deleted_at            TIMESTAMPTZ,
    CONSTRAINT uq_staff_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_staff_user UNIQUE (school_id, user_id),
    CONSTRAINT fk_staff_user        FOREIGN KEY (school_id, user_id)        REFERENCES users (school_id, id),
    CONSTRAINT fk_staff_department  FOREIGN KEY (school_id, department_id)  REFERENCES departments (school_id, id),
    CONSTRAINT fk_staff_designation FOREIGN KEY (school_id, designation_id) REFERENCES designations (school_id, id),
    CONSTRAINT ck_staff_type   CHECK (employment_type IN ('PERMANENT','CONTRACT','VOLUNTEER','INTERN')),
    CONSTRAINT ck_staff_salary CHECK (salary_tzs >= 0),
    CONSTRAINT ck_staff_load   CHECK (max_periods_per_week BETWEEN 1 AND 50),
    CONSTRAINT ck_staff_status CHECK (status IN ('ACTIVE','ON_LEAVE','TRANSFERRED','RETIRED','TERMINATED'))
);
CREATE UNIQUE INDEX uq_staff_no ON staff (school_id, staff_no) WHERE deleted_at IS NULL;
ALTER TABLE departments ADD CONSTRAINT fk_departments_head
    FOREIGN KEY (school_id, head_staff_id) REFERENCES staff (school_id, id);

CREATE TABLE staff_qualifications (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id     UUID         NOT NULL REFERENCES schools (id),
    staff_id      UUID         NOT NULL,
    level         VARCHAR(12)  NOT NULL,
    title         VARCHAR(120) NOT NULL,
    institution   VARCHAR(120) NOT NULL,
    year_awarded  SMALLINT     NOT NULL,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by    UUID,
    deleted_at    TIMESTAMPTZ,
    CONSTRAINT uq_staff_qualifications_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_qualifications_staff FOREIGN KEY (school_id, staff_id) REFERENCES staff (school_id, id),
    CONSTRAINT ck_qualifications_level CHECK (level IN ('CERTIFICATE','DIPLOMA','DEGREE','POSTGRAD_DIP','MASTERS','PHD')),
    CONSTRAINT ck_qualifications_year  CHECK (year_awarded BETWEEN 1950 AND 2100)
);

-- =====================================================================
-- 4. ACADEMIC CONFIGURATION (data-driven)
-- =====================================================================
CREATE TABLE education_levels (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id   UUID        NOT NULL REFERENCES schools (id),
    code        VARCHAR(12) NOT NULL,
    name_en     VARCHAR(40) NOT NULL,
    name_sw     VARCHAR(40) NOT NULL,
    sort_order  SMALLINT    NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by  UUID,
    deleted_at  TIMESTAMPTZ,
    CONSTRAINT uq_education_levels_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_education_levels_code UNIQUE (school_id, code),
    CONSTRAINT ck_education_levels_code CHECK (code IN ('PRE_PRIMARY','PRIMARY','O_LEVEL','A_LEVEL'))
);

CREATE TABLE academic_years (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id   UUID        NOT NULL REFERENCES schools (id),
    name        VARCHAR(9)  NOT NULL,
    start_date  DATE        NOT NULL,
    end_date    DATE        NOT NULL,
    is_current  BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by  UUID,
    deleted_at  TIMESTAMPTZ,
    CONSTRAINT uq_academic_years_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_academic_years_name UNIQUE (school_id, name),
    CONSTRAINT ck_academic_years_dates CHECK (end_date > start_date)
);
CREATE UNIQUE INDEX uq_academic_years_current ON academic_years (school_id) WHERE is_current;

CREATE TABLE terms (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id         UUID        NOT NULL REFERENCES schools (id),
    academic_year_id  UUID        NOT NULL,
    term_no           SMALLINT    NOT NULL,
    name_en           VARCHAR(30) NOT NULL,
    name_sw           VARCHAR(30) NOT NULL,
    start_date        DATE        NOT NULL,
    end_date          DATE        NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by        UUID,
    deleted_at        TIMESTAMPTZ,
    CONSTRAINT uq_terms_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_terms_no UNIQUE (school_id, academic_year_id, term_no),
    CONSTRAINT fk_terms_year FOREIGN KEY (school_id, academic_year_id) REFERENCES academic_years (school_id, id),
    CONSTRAINT ck_terms_no CHECK (term_no BETWEEN 1 AND 4),
    CONSTRAINT ck_terms_dates CHECK (end_date > start_date),
    CONSTRAINT ex_terms_overlap EXCLUDE USING gist
        (school_id WITH =, academic_year_id WITH =, daterange(start_date, end_date, '[]') WITH &&)
        WHERE (deleted_at IS NULL)
);

CREATE TABLE public_holidays (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id     UUID        NOT NULL REFERENCES schools (id),
    holiday_date  DATE        NOT NULL,
    name_en       VARCHAR(80) NOT NULL,
    name_sw       VARCHAR(80) NOT NULL,
    kind          VARCHAR(15) NOT NULL DEFAULT 'NATIONAL',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by    UUID,
    deleted_at    TIMESTAMPTZ,
    CONSTRAINT uq_public_holidays_tenant UNIQUE (school_id, id),
    CONSTRAINT ck_public_holidays_kind CHECK (kind IN ('NATIONAL','SCHOOL_CLOSURE'))
);
CREATE UNIQUE INDEX uq_public_holidays_date ON public_holidays (school_id, holiday_date) WHERE deleted_at IS NULL;

CREATE TABLE grading_schemes (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id           UUID        NOT NULL REFERENCES schools (id),
    education_level_id  UUID        NOT NULL,
    academic_year_id    UUID        NOT NULL,
    name                VARCHAR(60) NOT NULL,
    version             SMALLINT    NOT NULL DEFAULT 1,
    best_n_subjects     SMALLINT,                          -- subjects counted for the division (O-Level 7)
    is_active           BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by          UUID,
    deleted_at          TIMESTAMPTZ,
    CONSTRAINT uq_grading_schemes_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_grading_schemes_version UNIQUE (school_id, education_level_id, academic_year_id, version),
    CONSTRAINT fk_grading_level FOREIGN KEY (school_id, education_level_id) REFERENCES education_levels (school_id, id),
    CONSTRAINT fk_grading_year  FOREIGN KEY (school_id, academic_year_id)   REFERENCES academic_years (school_id, id),
    CONSTRAINT ck_grading_best_n CHECK (best_n_subjects BETWEEN 1 AND 12)
);
CREATE UNIQUE INDEX uq_grading_schemes_active ON grading_schemes (school_id, education_level_id, academic_year_id) WHERE is_active AND deleted_at IS NULL;

CREATE TABLE grade_bands (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id          UUID         NOT NULL REFERENCES schools (id),
    grading_scheme_id  UUID         NOT NULL,
    letter             VARCHAR(2)   NOT NULL,
    min_score          SMALLINT     NOT NULL,
    max_score          SMALLINT     NOT NULL,
    points             SMALLINT     NOT NULL,
    remark_en          VARCHAR(20)  NOT NULL,
    remark_sw          VARCHAR(20)  NOT NULL,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by         UUID,
    CONSTRAINT uq_grade_bands_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_grade_bands_letter UNIQUE (school_id, grading_scheme_id, letter),
    CONSTRAINT fk_grade_bands_scheme FOREIGN KEY (school_id, grading_scheme_id) REFERENCES grading_schemes (school_id, id),
    CONSTRAINT ck_grade_bands_range CHECK (min_score BETWEEN 0 AND 100 AND max_score BETWEEN min_score AND 100),
    CONSTRAINT ck_grade_bands_points CHECK (points BETWEEN 0 AND 9),
    CONSTRAINT ex_grade_bands_overlap EXCLUDE USING gist
        (grading_scheme_id WITH =, int4range(min_score, max_score, '[]') WITH &&)
);

CREATE TABLE division_rules (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id          UUID        NOT NULL REFERENCES schools (id),
    grading_scheme_id  UUID        NOT NULL,
    division           VARCHAR(3)  NOT NULL,                -- I, II, III, IV, 0
    min_points         SMALLINT    NOT NULL,
    max_points         SMALLINT    NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by         UUID,
    CONSTRAINT uq_division_rules_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_division_rules UNIQUE (school_id, grading_scheme_id, division),
    CONSTRAINT fk_division_scheme FOREIGN KEY (school_id, grading_scheme_id) REFERENCES grading_schemes (school_id, id),
    CONSTRAINT ck_division_range CHECK (max_points >= min_points AND min_points >= 0),
    CONSTRAINT ex_division_overlap EXCLUDE USING gist
        (grading_scheme_id WITH =, int4range(min_points, max_points, '[]') WITH &&)
);

CREATE TABLE subjects (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id      UUID        NOT NULL REFERENCES schools (id),
    code           VARCHAR(10) NOT NULL,
    necta_code     VARCHAR(5),
    name_en        VARCHAR(80) NOT NULL,
    name_sw        VARCHAR(80) NOT NULL,
    department_id  UUID,
    room_type      VARCHAR(12) NOT NULL DEFAULT 'CLASSROOM',  -- room the timetable must use
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by     UUID,
    deleted_at     TIMESTAMPTZ,
    CONSTRAINT uq_subjects_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_subjects_department FOREIGN KEY (school_id, department_id) REFERENCES departments (school_id, id),
    CONSTRAINT ck_subjects_room_type CHECK (room_type IN ('CLASSROOM','LABORATORY','ICT_LAB','WORKSHOP','HALL'))
);
CREATE UNIQUE INDEX uq_subjects_code ON subjects (school_id, code) WHERE deleted_at IS NULL;

CREATE TABLE classes (                                 -- Standard I..VII, Form I..VI
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id           UUID        NOT NULL REFERENCES schools (id),
    education_level_id  UUID        NOT NULL,
    code                VARCHAR(6)  NOT NULL,              -- F2, STD7
    name_en             VARCHAR(30) NOT NULL,
    name_sw             VARCHAR(30) NOT NULL,
    sort_order          SMALLINT    NOT NULL,
    next_class_id       UUID,                              -- promotion path (NULL = final class)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by          UUID,
    deleted_at          TIMESTAMPTZ,
    CONSTRAINT uq_classes_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_classes_level FOREIGN KEY (school_id, education_level_id) REFERENCES education_levels (school_id, id),
    CONSTRAINT fk_classes_next  FOREIGN KEY (school_id, next_class_id) REFERENCES classes (school_id, id)
);
CREATE UNIQUE INDEX uq_classes_code ON classes (school_id, code) WHERE deleted_at IS NULL;

CREATE TABLE combinations (                            -- A-Level PCM, HGL, ...
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id           UUID         NOT NULL REFERENCES schools (id),
    education_level_id  UUID         NOT NULL,
    code                VARCHAR(6)   NOT NULL,
    name_en             VARCHAR(100) NOT NULL,
    name_sw             VARCHAR(100) NOT NULL,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by          UUID,
    deleted_at          TIMESTAMPTZ,
    CONSTRAINT uq_combinations_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_combinations_level FOREIGN KEY (school_id, education_level_id) REFERENCES education_levels (school_id, id)
);
CREATE UNIQUE INDEX uq_combinations_code ON combinations (school_id, code) WHERE deleted_at IS NULL;

CREATE TABLE combination_subjects (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id       UUID        NOT NULL REFERENCES schools (id),
    combination_id  UUID        NOT NULL,
    subject_id      UUID        NOT NULL,
    is_principal    BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by      UUID,
    CONSTRAINT uq_combination_subjects_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_combination_subjects UNIQUE (school_id, combination_id, subject_id),
    CONSTRAINT fk_cs_combination FOREIGN KEY (school_id, combination_id) REFERENCES combinations (school_id, id),
    CONSTRAINT fk_cs_subject     FOREIGN KEY (school_id, subject_id)     REFERENCES subjects (school_id, id)
);

CREATE TABLE class_subjects (                          -- curriculum of a class
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id         UUID        NOT NULL REFERENCES schools (id),
    class_id          UUID        NOT NULL,
    subject_id        UUID        NOT NULL,
    is_compulsory     BOOLEAN     NOT NULL DEFAULT TRUE,
    periods_per_week  SMALLINT    NOT NULL DEFAULT 4,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by        UUID,
    deleted_at        TIMESTAMPTZ,
    CONSTRAINT uq_class_subjects_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_class_subjects_class   FOREIGN KEY (school_id, class_id)   REFERENCES classes (school_id, id),
    CONSTRAINT fk_class_subjects_subject FOREIGN KEY (school_id, subject_id) REFERENCES subjects (school_id, id),
    CONSTRAINT ck_class_subjects_periods CHECK (periods_per_week BETWEEN 1 AND 12)
);
CREATE UNIQUE INDEX uq_class_subjects ON class_subjects (school_id, class_id, subject_id) WHERE deleted_at IS NULL;

CREATE TABLE rooms (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id   UUID         NOT NULL REFERENCES schools (id),
    code        VARCHAR(12)  NOT NULL,
    name        VARCHAR(60)  NOT NULL,
    room_type   VARCHAR(12)  NOT NULL DEFAULT 'CLASSROOM',
    capacity    SMALLINT     NOT NULL,
    equipment   VARCHAR(300),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by  UUID,
    deleted_at  TIMESTAMPTZ,
    CONSTRAINT uq_rooms_tenant UNIQUE (school_id, id),
    CONSTRAINT ck_rooms_type CHECK (room_type IN ('CLASSROOM','LABORATORY','ICT_LAB','WORKSHOP','HALL')),
    CONSTRAINT ck_rooms_capacity CHECK (capacity > 0)
);
CREATE UNIQUE INDEX uq_rooms_code ON rooms (school_id, code) WHERE deleted_at IS NULL;

CREATE TABLE streams (                                 -- Form II B (permanent; teacher per year below)
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id     UUID        NOT NULL REFERENCES schools (id),
    class_id      UUID        NOT NULL,
    name          VARCHAR(10) NOT NULL,                 -- A, B, PCM
    capacity      SMALLINT    NOT NULL,
    home_room_id  UUID,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by    UUID,
    deleted_at    TIMESTAMPTZ,
    CONSTRAINT uq_streams_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_streams_class FOREIGN KEY (school_id, class_id)     REFERENCES classes (school_id, id),
    CONSTRAINT fk_streams_room  FOREIGN KEY (school_id, home_room_id) REFERENCES rooms (school_id, id),
    CONSTRAINT ck_streams_capacity CHECK (capacity BETWEEN 1 AND 200)
);
CREATE UNIQUE INDEX uq_streams_name ON streams (school_id, class_id, name) WHERE deleted_at IS NULL;

CREATE TABLE stream_class_teachers (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id         UUID        NOT NULL REFERENCES schools (id),
    stream_id         UUID        NOT NULL,
    academic_year_id  UUID        NOT NULL,
    staff_id          UUID        NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by        UUID,
    CONSTRAINT uq_stream_class_teachers_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_stream_class_teachers UNIQUE (school_id, stream_id, academic_year_id),
    CONSTRAINT fk_sct_stream FOREIGN KEY (school_id, stream_id)        REFERENCES streams (school_id, id),
    CONSTRAINT fk_sct_year   FOREIGN KEY (school_id, academic_year_id) REFERENCES academic_years (school_id, id),
    CONSTRAINT fk_sct_staff  FOREIGN KEY (school_id, staff_id)         REFERENCES staff (school_id, id)
);

CREATE TABLE teaching_assignments (                    -- teacher-subject-class for a year
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id         UUID        NOT NULL REFERENCES schools (id),
    academic_year_id  UUID        NOT NULL,
    stream_id         UUID        NOT NULL,
    subject_id        UUID        NOT NULL,
    staff_id          UUID        NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by        UUID,
    deleted_at        TIMESTAMPTZ,
    CONSTRAINT uq_teaching_assignments_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_ta_year    FOREIGN KEY (school_id, academic_year_id) REFERENCES academic_years (school_id, id),
    CONSTRAINT fk_ta_stream  FOREIGN KEY (school_id, stream_id)        REFERENCES streams (school_id, id),
    CONSTRAINT fk_ta_subject FOREIGN KEY (school_id, subject_id)       REFERENCES subjects (school_id, id),
    CONSTRAINT fk_ta_staff   FOREIGN KEY (school_id, staff_id)         REFERENCES staff (school_id, id)
);
CREATE UNIQUE INDEX uq_teaching_assignments ON teaching_assignments (school_id, academic_year_id, stream_id, subject_id) WHERE deleted_at IS NULL;
CREATE INDEX ix_teaching_assignments_staff ON teaching_assignments (school_id, staff_id, academic_year_id);

CREATE TABLE assessment_components (                   -- CA, tests, mid-term, terminal ... with weights
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id           UUID         NOT NULL REFERENCES schools (id),
    term_id             UUID         NOT NULL,
    education_level_id  UUID         NOT NULL,
    subject_id          UUID,                            -- NULL = every subject of the level
    code                VARCHAR(12)  NOT NULL,
    name_en             VARCHAR(40)  NOT NULL,
    name_sw             VARCHAR(40)  NOT NULL,
    max_score           NUMERIC(6,2) NOT NULL,
    weight              NUMERIC(5,2) NOT NULL,           -- % of the final score (weights total 100)
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by          UUID,
    deleted_at          TIMESTAMPTZ,
    CONSTRAINT uq_assessment_components_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_assessment_components UNIQUE NULLS NOT DISTINCT (school_id, term_id, education_level_id, subject_id, code),
    CONSTRAINT fk_ac_term    FOREIGN KEY (school_id, term_id)            REFERENCES terms (school_id, id),
    CONSTRAINT fk_ac_level   FOREIGN KEY (school_id, education_level_id) REFERENCES education_levels (school_id, id),
    CONSTRAINT fk_ac_subject FOREIGN KEY (school_id, subject_id)         REFERENCES subjects (school_id, id),
    CONSTRAINT ck_ac_code   CHECK (code IN ('CA','TEST','MIDTERM','TERMINAL','ANNUAL','PROJECT','PRACTICAL')),
    CONSTRAINT ck_ac_max    CHECK (max_score > 0 AND max_score <= 1000),
    CONSTRAINT ck_ac_weight CHECK (weight > 0 AND weight <= 100)
);

-- =====================================================================
-- 5. ENROLMENT
-- =====================================================================
CREATE TABLE enrolment_requirements (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id           UUID         NOT NULL REFERENCES schools (id),
    education_level_id  UUID,                            -- NULL = all levels
    class_id            UUID,                            -- NULL = all classes of the level
    name_en             VARCHAR(100) NOT NULL,
    name_sw             VARCHAR(100) NOT NULL,
    description         VARCHAR(300),
    is_required         BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by          UUID,
    deleted_at          TIMESTAMPTZ,
    CONSTRAINT uq_enrolment_requirements_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_er_level FOREIGN KEY (school_id, education_level_id) REFERENCES education_levels (school_id, id),
    CONSTRAINT fk_er_class FOREIGN KEY (school_id, class_id)           REFERENCES classes (school_id, id)
);

CREATE TABLE enrolment_applications (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id         UUID         NOT NULL REFERENCES schools (id),
    application_no    VARCHAR(20)  NOT NULL,             -- APP-2026-0001
    student_id        UUID         NOT NULL,
    class_id          UUID         NOT NULL,
    combination_id    UUID,
    academic_year_id  UUID         NOT NULL,
    status            VARCHAR(20)  NOT NULL DEFAULT 'INQUIRED',
    submitted_at      TIMESTAMPTZ,
    decided_at        TIMESTAMPTZ,
    decided_by        UUID,
    decision_reason   VARCHAR(300),
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by        UUID,
    deleted_at        TIMESTAMPTZ,
    CONSTRAINT uq_enrolment_applications_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_enrolment_applications_no UNIQUE (school_id, application_no),
    CONSTRAINT fk_ea_student     FOREIGN KEY (school_id, student_id)       REFERENCES students (school_id, id),
    CONSTRAINT fk_ea_class       FOREIGN KEY (school_id, class_id)         REFERENCES classes (school_id, id),
    CONSTRAINT fk_ea_combination FOREIGN KEY (school_id, combination_id)   REFERENCES combinations (school_id, id),
    CONSTRAINT fk_ea_year        FOREIGN KEY (school_id, academic_year_id) REFERENCES academic_years (school_id, id),
    CONSTRAINT fk_ea_decided_by  FOREIGN KEY (school_id, decided_by)       REFERENCES users (school_id, id),
    CONSTRAINT ck_ea_status CHECK (status IN ('INQUIRED','REQUIREMENTS_PENDING','UNDER_REVIEW','APPROVED','REJECTED','CANCELLED')),
    CONSTRAINT ck_ea_decision CHECK (status NOT IN ('APPROVED','REJECTED','CANCELLED') OR (decided_at IS NOT NULL AND decision_reason IS NOT NULL))
);
CREATE UNIQUE INDEX uq_enrolment_applications_open ON enrolment_applications (school_id, student_id, academic_year_id)
    WHERE status NOT IN ('REJECTED','CANCELLED') AND deleted_at IS NULL;
CREATE INDEX ix_enrolment_applications_status ON enrolment_applications (school_id, status, created_at);

CREATE TABLE enrolment_documents (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id          UUID         NOT NULL REFERENCES schools (id),
    application_id     UUID         NOT NULL,
    requirement_id     UUID         NOT NULL,
    file_key           VARCHAR(255) NOT NULL,
    file_name          VARCHAR(255) NOT NULL,
    mime_type          VARCHAR(50)  NOT NULL,
    size_bytes         INTEGER      NOT NULL,
    sha256             CHAR(64)     NOT NULL,
    validation_status  VARCHAR(8)   NOT NULL DEFAULT 'PENDING',
    validated_by       UUID,
    validated_at       TIMESTAMPTZ,
    comment            VARCHAR(300),
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by         UUID,
    deleted_at         TIMESTAMPTZ,
    CONSTRAINT uq_enrolment_documents_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_ed_application FOREIGN KEY (school_id, application_id) REFERENCES enrolment_applications (school_id, id),
    CONSTRAINT fk_ed_requirement FOREIGN KEY (school_id, requirement_id) REFERENCES enrolment_requirements (school_id, id),
    CONSTRAINT fk_ed_validator   FOREIGN KEY (school_id, validated_by)   REFERENCES users (school_id, id),
    CONSTRAINT ck_ed_mime   CHECK (mime_type IN ('application/pdf','image/jpeg','image/png')),
    CONSTRAINT ck_ed_size   CHECK (size_bytes BETWEEN 1 AND 5242880),
    CONSTRAINT ck_ed_status CHECK (validation_status IN ('PENDING','VALID','INVALID')),
    CONSTRAINT ck_ed_validated CHECK (validation_status = 'PENDING' OR (validated_by IS NOT NULL AND validated_at IS NOT NULL)),
    CONSTRAINT ck_ed_comment CHECK (validation_status <> 'INVALID' OR comment IS NOT NULL)
);
CREATE UNIQUE INDEX uq_enrolment_documents ON enrolment_documents (school_id, application_id, requirement_id) WHERE deleted_at IS NULL;

CREATE TABLE enrolments (                              -- one per student per year; history kept on promotion
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id         UUID        NOT NULL REFERENCES schools (id),
    student_id        UUID        NOT NULL,
    stream_id         UUID        NOT NULL,
    academic_year_id  UUID        NOT NULL,
    combination_id    UUID,
    application_id    UUID,
    status            VARCHAR(15) NOT NULL DEFAULT 'ACTIVE',
    started_on        DATE        NOT NULL,
    ended_on          DATE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by        UUID,
    CONSTRAINT uq_enrolments_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_enrolments_student_year UNIQUE (school_id, student_id, academic_year_id),
    CONSTRAINT fk_enrolments_student     FOREIGN KEY (school_id, student_id)       REFERENCES students (school_id, id),
    CONSTRAINT fk_enrolments_stream      FOREIGN KEY (school_id, stream_id)        REFERENCES streams (school_id, id),
    CONSTRAINT fk_enrolments_year        FOREIGN KEY (school_id, academic_year_id) REFERENCES academic_years (school_id, id),
    CONSTRAINT fk_enrolments_combination FOREIGN KEY (school_id, combination_id)   REFERENCES combinations (school_id, id),
    CONSTRAINT fk_enrolments_application FOREIGN KEY (school_id, application_id)   REFERENCES enrolment_applications (school_id, id),
    CONSTRAINT ck_enrolments_status CHECK (status IN ('ACTIVE','PROMOTED','REPEATED','TRANSFERRED_OUT','GRADUATED','WITHDRAWN')),
    CONSTRAINT ck_enrolments_dates  CHECK (ended_on IS NULL OR ended_on >= started_on),
    CONSTRAINT ck_enrolments_end    CHECK ((status = 'ACTIVE') = (ended_on IS NULL))
);
CREATE INDEX ix_enrolments_stream ON enrolments (school_id, stream_id, academic_year_id) WHERE status = 'ACTIVE';

-- =====================================================================
-- 6. TIMETABLE AND EXAMS (no student column: students reach slots through enrolments)
-- =====================================================================
CREATE TABLE timetable_slots (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id    UUID        NOT NULL REFERENCES schools (id),
    term_id      UUID        NOT NULL,
    stream_id    UUID        NOT NULL,
    subject_id   UUID        NOT NULL,
    staff_id     UUID        NOT NULL,
    room_id      UUID        NOT NULL,
    day_of_week  SMALLINT    NOT NULL,                  -- 1 Monday .. 6 Saturday
    time_start   TIME        NOT NULL,
    time_end     TIME        NOT NULL,
    slot         timerange   GENERATED ALWAYS AS (timerange(time_start, time_end, '[)')) STORED,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by   UUID,
    deleted_at   TIMESTAMPTZ,
    CONSTRAINT uq_timetable_slots_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_tt_term    FOREIGN KEY (school_id, term_id)    REFERENCES terms (school_id, id),
    CONSTRAINT fk_tt_stream  FOREIGN KEY (school_id, stream_id)  REFERENCES streams (school_id, id),
    CONSTRAINT fk_tt_subject FOREIGN KEY (school_id, subject_id) REFERENCES subjects (school_id, id),
    CONSTRAINT fk_tt_staff   FOREIGN KEY (school_id, staff_id)   REFERENCES staff (school_id, id),
    CONSTRAINT fk_tt_room    FOREIGN KEY (school_id, room_id)    REFERENCES rooms (school_id, id),
    CONSTRAINT ck_tt_day  CHECK (day_of_week BETWEEN 1 AND 6),
    CONSTRAINT ck_tt_time CHECK (time_end > time_start),
    CONSTRAINT ex_tt_teacher EXCLUDE USING gist (staff_id WITH =, term_id WITH =, day_of_week WITH =, slot WITH &&) WHERE (deleted_at IS NULL),
    CONSTRAINT ex_tt_room    EXCLUDE USING gist (room_id WITH =, term_id WITH =, day_of_week WITH =, slot WITH &&) WHERE (deleted_at IS NULL),
    CONSTRAINT ex_tt_class   EXCLUDE USING gist (stream_id WITH =, term_id WITH =, day_of_week WITH =, slot WITH &&) WHERE (deleted_at IS NULL)
);

CREATE TABLE exam_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id   UUID        NOT NULL REFERENCES schools (id),
    term_id     UUID        NOT NULL,
    name_en     VARCHAR(60) NOT NULL,
    name_sw     VARCHAR(60) NOT NULL,
    kind        VARCHAR(10) NOT NULL,
    start_date  DATE        NOT NULL,
    end_date    DATE        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by  UUID,
    deleted_at  TIMESTAMPTZ,
    CONSTRAINT uq_exam_sessions_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_exam_sessions_term FOREIGN KEY (school_id, term_id) REFERENCES terms (school_id, id),
    CONSTRAINT ck_exam_sessions_kind  CHECK (kind IN ('MONTHLY','MIDTERM','TERMINAL','ANNUAL','MOCK')),
    CONSTRAINT ck_exam_sessions_dates CHECK (end_date >= start_date)
);

CREATE TABLE exams (                                   -- "Set Exams": one paper
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id        UUID        NOT NULL REFERENCES schools (id),
    exam_session_id  UUID        NOT NULL,
    class_id         UUID        NOT NULL,
    subject_id       UUID        NOT NULL,
    room_id          UUID,                             -- venue
    exam_date        DATE        NOT NULL,
    time_start       TIME        NOT NULL,
    time_end         TIME        NOT NULL,
    slot             timerange   GENERATED ALWAYS AS (timerange(time_start, time_end, '[)')) STORED,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by       UUID,
    deleted_at       TIMESTAMPTZ,
    CONSTRAINT uq_exams_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_exams_session FOREIGN KEY (school_id, exam_session_id) REFERENCES exam_sessions (school_id, id),
    CONSTRAINT fk_exams_class   FOREIGN KEY (school_id, class_id)        REFERENCES classes (school_id, id),
    CONSTRAINT fk_exams_subject FOREIGN KEY (school_id, subject_id)      REFERENCES subjects (school_id, id),
    CONSTRAINT fk_exams_room    FOREIGN KEY (school_id, room_id)         REFERENCES rooms (school_id, id),
    CONSTRAINT ck_exams_time CHECK (time_end > time_start),
    CONSTRAINT ex_exams_class EXCLUDE USING gist (class_id WITH =, exam_date WITH =, slot WITH &&) WHERE (deleted_at IS NULL),
    CONSTRAINT ex_exams_room  EXCLUDE USING gist (room_id WITH =, exam_date WITH =, slot WITH &&) WHERE (deleted_at IS NULL)
);
CREATE UNIQUE INDEX uq_exams_paper ON exams (school_id, exam_session_id, class_id, subject_id) WHERE deleted_at IS NULL;

-- =====================================================================
-- 7. MARKS AND RESULTS (draft -> validation firewall -> frozen publication)
-- =====================================================================
CREATE TABLE mark_entries (                            -- DRAFT, editable until locked
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id          UUID         NOT NULL REFERENCES schools (id),
    enrolment_id       UUID         NOT NULL,          -- student + stream + year
    subject_id         UUID         NOT NULL,
    component_id       UUID         NOT NULL,          -- implies the term
    score              NUMERIC(6,2),                   -- NULL = not yet entered / absent
    is_absent          BOOLEAN      NOT NULL DEFAULT FALSE,
    entered_by         UUID         NOT NULL,
    version            INTEGER      NOT NULL DEFAULT 1, -- optimistic concurrency for offline sync
    client_updated_at  TIMESTAMPTZ,
    locked_at          TIMESTAMPTZ,                    -- set at publication
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by         UUID,
    deleted_at         TIMESTAMPTZ,
    CONSTRAINT uq_mark_entries_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_me_enrolment FOREIGN KEY (school_id, enrolment_id) REFERENCES enrolments (school_id, id),
    CONSTRAINT fk_me_subject   FOREIGN KEY (school_id, subject_id)   REFERENCES subjects (school_id, id),
    CONSTRAINT fk_me_component FOREIGN KEY (school_id, component_id) REFERENCES assessment_components (school_id, id),
    CONSTRAINT fk_me_entered   FOREIGN KEY (school_id, entered_by)   REFERENCES users (school_id, id),
    CONSTRAINT ck_me_score CHECK (score >= 0),
    CONSTRAINT ck_me_absent CHECK (NOT is_absent OR score IS NULL),
    CONSTRAINT ck_me_version CHECK (version >= 1)
);
CREATE UNIQUE INDEX uq_mark_entries ON mark_entries (school_id, enrolment_id, subject_id, component_id) WHERE deleted_at IS NULL;
CREATE INDEX ix_mark_entries_component ON mark_entries (school_id, component_id, subject_id);

CREATE TABLE result_publications (                     -- one publication = one class, one term
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id          UUID        NOT NULL REFERENCES schools (id),
    term_id            UUID        NOT NULL,
    class_id           UUID        NOT NULL,
    grading_scheme_id  UUID        NOT NULL,
    scheme_version     SMALLINT    NOT NULL,
    published_by       UUID        NOT NULL,
    published_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by         UUID,
    CONSTRAINT uq_result_publications_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_result_publications UNIQUE (school_id, term_id, class_id),
    CONSTRAINT fk_rp_term   FOREIGN KEY (school_id, term_id)           REFERENCES terms (school_id, id),
    CONSTRAINT fk_rp_class  FOREIGN KEY (school_id, class_id)          REFERENCES classes (school_id, id),
    CONSTRAINT fk_rp_scheme FOREIGN KEY (school_id, grading_scheme_id) REFERENCES grading_schemes (school_id, id),
    CONSTRAINT fk_rp_user   FOREIGN KEY (school_id, published_by)      REFERENCES users (school_id, id)
);

CREATE TABLE result_amendments (                       -- the only way to change a frozen result
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id            UUID         NOT NULL REFERENCES schools (id),
    published_result_id  UUID         NOT NULL,         -- FK added after published_results
    new_score            NUMERIC(5,2) NOT NULL,
    reason               VARCHAR(300) NOT NULL,
    requested_by         UUID         NOT NULL,
    status               VARCHAR(10)  NOT NULL DEFAULT 'PENDING',
    decided_by           UUID,
    decided_at           TIMESTAMPTZ,
    decision_note        VARCHAR(300),
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by           UUID,
    CONSTRAINT uq_result_amendments_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_ra_requested FOREIGN KEY (school_id, requested_by) REFERENCES users (school_id, id),
    CONSTRAINT fk_ra_decided   FOREIGN KEY (school_id, decided_by)   REFERENCES users (school_id, id),
    CONSTRAINT ck_ra_score  CHECK (new_score BETWEEN 0 AND 100),
    CONSTRAINT ck_ra_status CHECK (status IN ('PENDING','APPROVED','REJECTED')),
    CONSTRAINT ck_ra_decision CHECK (status = 'PENDING' OR (decided_by IS NOT NULL AND decided_at IS NOT NULL)),
    CONSTRAINT ck_ra_maker_checker CHECK (decided_by IS NULL OR decided_by <> requested_by)
);

CREATE TABLE published_results (                       -- FROZEN: no UPDATE / DELETE (trigger)
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id        UUID         NOT NULL REFERENCES schools (id),
    publication_id   UUID         NOT NULL,
    enrolment_id     UUID         NOT NULL,
    subject_id       UUID         NOT NULL,
    final_score      NUMERIC(5,2) NOT NULL,             -- weighted total out of 100
    letter_grade     VARCHAR(2)   NOT NULL,
    points           SMALLINT     NOT NULL,
    subject_position SMALLINT     NOT NULL,             -- ties share a position
    supersedes_id    UUID,                              -- previous version (amendment)
    amendment_id     UUID,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by       UUID,
    CONSTRAINT uq_published_results_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_published_results_supersedes UNIQUE (school_id, supersedes_id),
    CONSTRAINT fk_pr_publication FOREIGN KEY (school_id, publication_id) REFERENCES result_publications (school_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_pr_enrolment   FOREIGN KEY (school_id, enrolment_id)   REFERENCES enrolments (school_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_pr_subject     FOREIGN KEY (school_id, subject_id)     REFERENCES subjects (school_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_pr_supersedes  FOREIGN KEY (school_id, supersedes_id)  REFERENCES published_results (school_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_pr_amendment   FOREIGN KEY (school_id, amendment_id)   REFERENCES result_amendments (school_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_pr_score CHECK (final_score BETWEEN 0 AND 100),
    CONSTRAINT ck_pr_position CHECK (subject_position >= 1),
    CONSTRAINT ck_pr_amendment CHECK ((supersedes_id IS NULL) = (amendment_id IS NULL))
);
CREATE INDEX ix_published_results_enrolment ON published_results (school_id, enrolment_id, publication_id);
CREATE UNIQUE INDEX uq_published_results_original ON published_results (school_id, publication_id, enrolment_id, subject_id) WHERE supersedes_id IS NULL;
ALTER TABLE result_amendments ADD CONSTRAINT fk_ra_result
    FOREIGN KEY (school_id, published_result_id) REFERENCES published_results (school_id, id) ON DELETE RESTRICT;

CREATE TABLE student_term_summaries (                  -- FROZEN with the publication
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id       UUID         NOT NULL REFERENCES schools (id),
    publication_id  UUID         NOT NULL,
    enrolment_id    UUID         NOT NULL,
    total_score     NUMERIC(7,2) NOT NULL,
    average_score   NUMERIC(5,2) NOT NULL,
    subjects_sat    SMALLINT     NOT NULL,
    total_points    SMALLINT,                           -- best-n points; NULL when too few subjects
    division        VARCHAR(3),                         -- NULL = incomplete
    class_position  SMALLINT     NOT NULL,
    supersedes_id   UUID,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by      UUID,
    CONSTRAINT uq_student_term_summaries_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_sts_supersedes UNIQUE (school_id, supersedes_id),
    CONSTRAINT fk_sts_publication FOREIGN KEY (school_id, publication_id) REFERENCES result_publications (school_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_sts_enrolment   FOREIGN KEY (school_id, enrolment_id)   REFERENCES enrolments (school_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_sts_supersedes  FOREIGN KEY (school_id, supersedes_id)  REFERENCES student_term_summaries (school_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_sts_average CHECK (average_score BETWEEN 0 AND 100),
    CONSTRAINT ck_sts_position CHECK (class_position >= 1)
);
CREATE UNIQUE INDEX uq_sts_original ON student_term_summaries (school_id, publication_id, enrolment_id) WHERE supersedes_id IS NULL;

CREATE TABLE report_card_comments (                    -- editable until report cards are issued
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id              UUID         NOT NULL REFERENCES schools (id),
    publication_id         UUID         NOT NULL,
    enrolment_id           UUID         NOT NULL,
    class_teacher_comment  VARCHAR(400),
    head_teacher_comment   VARCHAR(400),
    created_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by             UUID,
    CONSTRAINT uq_report_card_comments_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_report_card_comments UNIQUE (school_id, publication_id, enrolment_id),
    CONSTRAINT fk_rcc_publication FOREIGN KEY (school_id, publication_id) REFERENCES result_publications (school_id, id),
    CONSTRAINT fk_rcc_enrolment   FOREIGN KEY (school_id, enrolment_id)   REFERENCES enrolments (school_id, id)
);

-- =====================================================================
-- 8. ATTENDANCE
-- =====================================================================
CREATE TABLE devices (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id     UUID         NOT NULL REFERENCES schools (id),
    name          VARCHAR(60)  NOT NULL,
    kind          VARCHAR(12)  NOT NULL,
    api_key_hash  CHAR(64)     NOT NULL UNIQUE,
    location      VARCHAR(100),
    status        VARCHAR(10)  NOT NULL DEFAULT 'ACTIVE',
    last_seen_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by    UUID,
    deleted_at    TIMESTAMPTZ,
    CONSTRAINT uq_devices_tenant UNIQUE (school_id, id),
    CONSTRAINT ck_devices_kind   CHECK (kind IN ('RFID_READER','QR_SCANNER','TABLET')),
    CONSTRAINT ck_devices_status CHECK (status IN ('ACTIVE','DISABLED'))
);

CREATE TABLE rfid_cards (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id   UUID        NOT NULL REFERENCES schools (id),
    student_id  UUID        NOT NULL,
    token_hash  CHAR(64)    NOT NULL,                   -- SHA-256 of card UID / QR payload (unique per school)
    kind        VARCHAR(4)  NOT NULL,
    status      VARCHAR(8)  NOT NULL DEFAULT 'ACTIVE',
    issued_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by  UUID,
    deleted_at  TIMESTAMPTZ,
    CONSTRAINT uq_rfid_cards_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_rfid_cards_token UNIQUE (school_id, token_hash),
    CONSTRAINT fk_rfid_student FOREIGN KEY (school_id, student_id) REFERENCES students (school_id, id),
    CONSTRAINT ck_rfid_kind   CHECK (kind IN ('RFID','QR')),
    CONSTRAINT ck_rfid_status CHECK (status IN ('ACTIVE','LOST','REVOKED'))
);
CREATE UNIQUE INDEX uq_rfid_active_card ON rfid_cards (school_id, student_id, kind) WHERE status = 'ACTIVE' AND deleted_at IS NULL;

CREATE TABLE attendance_sessions (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id          UUID        NOT NULL REFERENCES schools (id),
    session_date       DATE        NOT NULL,
    kind               VARCHAR(8)  NOT NULL,             -- REGISTER (class, morning), GATE (school), LESSON
    stream_id          UUID,
    timetable_slot_id  UUID,
    taken_by           UUID,
    opened_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at          TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by         UUID,
    CONSTRAINT uq_attendance_sessions_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_attendance_sessions UNIQUE NULLS NOT DISTINCT (school_id, session_date, kind, stream_id, timetable_slot_id),
    CONSTRAINT fk_as_stream FOREIGN KEY (school_id, stream_id)         REFERENCES streams (school_id, id),
    CONSTRAINT fk_as_slot   FOREIGN KEY (school_id, timetable_slot_id) REFERENCES timetable_slots (school_id, id),
    CONSTRAINT fk_as_taker  FOREIGN KEY (school_id, taken_by)          REFERENCES users (school_id, id),
    CONSTRAINT ck_as_kind CHECK (kind IN ('REGISTER','GATE','LESSON')),
    CONSTRAINT ck_as_scope CHECK (
        (kind = 'GATE' AND stream_id IS NULL AND timetable_slot_id IS NULL) OR
        (kind = 'REGISTER' AND stream_id IS NOT NULL AND timetable_slot_id IS NULL) OR
        (kind = 'LESSON' AND stream_id IS NOT NULL AND timetable_slot_id IS NOT NULL))
);

CREATE TABLE attendance_records (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id         UUID        NOT NULL REFERENCES schools (id),
    session_id        UUID        NOT NULL,
    student_id        UUID        NOT NULL,
    status            VARCHAR(8)  NOT NULL,
    source            VARCHAR(6)  NOT NULL DEFAULT 'MANUAL',
    device_id         UUID,
    captured_at       TIMESTAMPTZ NOT NULL,              -- when it happened (device / phone clock)
    synced_at         TIMESTAMPTZ NOT NULL DEFAULT now(), -- when the server received it
    client_record_id  UUID        NOT NULL,              -- idempotent offline sync
    recorded_by       UUID,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by        UUID,
    CONSTRAINT uq_attendance_records_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_attendance_records UNIQUE (school_id, session_id, student_id),
    CONSTRAINT uq_attendance_client UNIQUE (school_id, client_record_id),
    CONSTRAINT fk_ar_session  FOREIGN KEY (school_id, session_id)  REFERENCES attendance_sessions (school_id, id),
    CONSTRAINT fk_ar_student  FOREIGN KEY (school_id, student_id)  REFERENCES students (school_id, id),
    CONSTRAINT fk_ar_device   FOREIGN KEY (school_id, device_id)   REFERENCES devices (school_id, id),
    CONSTRAINT fk_ar_recorder FOREIGN KEY (school_id, recorded_by) REFERENCES users (school_id, id),
    CONSTRAINT ck_ar_status CHECK (status IN ('PRESENT','ABSENT','LATE','EXCUSED')),
    CONSTRAINT ck_ar_source CHECK (source IN ('MANUAL','RFID','QR')),
    CONSTRAINT ck_ar_device CHECK ((source = 'MANUAL') = (device_id IS NULL))
);
CREATE INDEX ix_attendance_records_student ON attendance_records (school_id, student_id, captured_at);

CREATE TABLE absence_alerts (                          -- one SMS per student per day, ever
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id        UUID        NOT NULL REFERENCES schools (id),
    student_id       UUID        NOT NULL,
    absence_date     DATE        NOT NULL,
    sms_message_id   UUID,                               -- FK added after sms_messages
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by       UUID,
    CONSTRAINT uq_absence_alerts_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_absence_alerts UNIQUE (school_id, student_id, absence_date),
    CONSTRAINT fk_aa_student FOREIGN KEY (school_id, student_id) REFERENCES students (school_id, id)
);

-- =====================================================================
-- 9. FINANCE (TZS, double-entry ledger)
-- =====================================================================
CREATE TABLE ledger_accounts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id   UUID        NOT NULL REFERENCES schools (id),
    code        VARCHAR(10) NOT NULL,
    name_en     VARCHAR(80) NOT NULL,
    name_sw     VARCHAR(80) NOT NULL,
    kind        VARCHAR(10) NOT NULL,
    is_system   BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by  UUID,
    CONSTRAINT uq_ledger_accounts_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_ledger_accounts_code UNIQUE (school_id, code),
    CONSTRAINT ck_ledger_accounts_kind CHECK (kind IN ('ASSET','LIABILITY','EQUITY','INCOME','EXPENSE'))
);

CREATE TABLE fee_items (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id          UUID        NOT NULL REFERENCES schools (id),
    code               VARCHAR(12) NOT NULL,
    name_en            VARCHAR(80) NOT NULL,
    name_sw            VARCHAR(80) NOT NULL,
    gfs_code           VARCHAR(20),                      -- GePG revenue (GFS) code
    income_account_id  UUID        NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by         UUID,
    deleted_at         TIMESTAMPTZ,
    CONSTRAINT uq_fee_items_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_fee_items_account FOREIGN KEY (school_id, income_account_id) REFERENCES ledger_accounts (school_id, id),
    CONSTRAINT ck_fee_items_code CHECK (code IN ('TUITION','BOARDING','TRANSPORT','MEALS','UNIFORM','EXAMINATION','DEVELOPMENT','OTHER'))
);
CREATE UNIQUE INDEX uq_fee_items_code ON fee_items (school_id, code) WHERE deleted_at IS NULL;

CREATE TABLE fee_structures (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id         UUID        NOT NULL REFERENCES schools (id),
    academic_year_id  UUID        NOT NULL,
    class_id          UUID        NOT NULL,
    name              VARCHAR(80) NOT NULL,
    status            VARCHAR(10) NOT NULL DEFAULT 'DRAFT',
    approved_by       UUID,
    approved_at       TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by        UUID,
    deleted_at        TIMESTAMPTZ,
    CONSTRAINT uq_fee_structures_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_fs_year     FOREIGN KEY (school_id, academic_year_id) REFERENCES academic_years (school_id, id),
    CONSTRAINT fk_fs_class    FOREIGN KEY (school_id, class_id)         REFERENCES classes (school_id, id),
    CONSTRAINT fk_fs_approver FOREIGN KEY (school_id, approved_by)      REFERENCES users (school_id, id),
    CONSTRAINT ck_fs_status CHECK (status IN ('DRAFT','APPROVED','ARCHIVED')),
    CONSTRAINT ck_fs_approval CHECK (status = 'DRAFT' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL))
);
CREATE UNIQUE INDEX uq_fee_structures_live ON fee_structures (school_id, academic_year_id, class_id) WHERE status <> 'ARCHIVED' AND deleted_at IS NULL;

CREATE TABLE fee_structure_lines (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id         UUID          NOT NULL REFERENCES schools (id),
    fee_structure_id  UUID          NOT NULL,
    fee_item_id       UUID          NOT NULL,
    term_id           UUID,                              -- NULL = billed once a year (first term)
    amount_tzs        NUMERIC(14,2) NOT NULL,
    is_optional       BOOLEAN       NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
    created_by        UUID,
    deleted_at        TIMESTAMPTZ,
    CONSTRAINT uq_fee_structure_lines_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_fsl_structure FOREIGN KEY (school_id, fee_structure_id) REFERENCES fee_structures (school_id, id),
    CONSTRAINT fk_fsl_item      FOREIGN KEY (school_id, fee_item_id)      REFERENCES fee_items (school_id, id),
    CONSTRAINT fk_fsl_term      FOREIGN KEY (school_id, term_id)          REFERENCES terms (school_id, id),
    CONSTRAINT ck_fsl_amount CHECK (amount_tzs >= 0)
);
CREATE UNIQUE INDEX uq_fee_structure_lines ON fee_structure_lines (school_id, fee_structure_id, fee_item_id, term_id) NULLS NOT DISTINCT WHERE deleted_at IS NULL;

CREATE TABLE discount_rules (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id   UUID          NOT NULL REFERENCES schools (id),
    code        VARCHAR(20)   NOT NULL,
    name_en     VARCHAR(80)   NOT NULL,
    name_sw     VARCHAR(80)   NOT NULL,
    kind        VARCHAR(12)   NOT NULL,
    percent     NUMERIC(5,2),
    amount_tzs  NUMERIC(14,2),
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    created_by  UUID,
    deleted_at  TIMESTAMPTZ,
    CONSTRAINT uq_discount_rules_tenant UNIQUE (school_id, id),
    CONSTRAINT ck_dr_kind CHECK (kind IN ('SCHOLARSHIP','SIBLING','STAFF_CHILD','BURSARY','OTHER')),
    CONSTRAINT ck_dr_value CHECK ((percent IS NULL) <> (amount_tzs IS NULL)),
    CONSTRAINT ck_dr_percent CHECK (percent > 0 AND percent <= 100),
    CONSTRAINT ck_dr_amount CHECK (amount_tzs > 0)
);
CREATE UNIQUE INDEX uq_discount_rules_code ON discount_rules (school_id, code) WHERE deleted_at IS NULL;

CREATE TABLE student_discounts (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id         UUID         NOT NULL REFERENCES schools (id),
    student_id        UUID         NOT NULL,
    discount_rule_id  UUID         NOT NULL,
    academic_year_id  UUID         NOT NULL,
    reason            VARCHAR(200) NOT NULL,
    approved_by       UUID         NOT NULL,
    approved_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by        UUID,
    deleted_at        TIMESTAMPTZ,
    CONSTRAINT uq_student_discounts_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_sd_student  FOREIGN KEY (school_id, student_id)       REFERENCES students (school_id, id),
    CONSTRAINT fk_sd_rule     FOREIGN KEY (school_id, discount_rule_id) REFERENCES discount_rules (school_id, id),
    CONSTRAINT fk_sd_year     FOREIGN KEY (school_id, academic_year_id) REFERENCES academic_years (school_id, id),
    CONSTRAINT fk_sd_approver FOREIGN KEY (school_id, approved_by)      REFERENCES users (school_id, id)
);
CREATE UNIQUE INDEX uq_student_discounts ON student_discounts (school_id, student_id, discount_rule_id, academic_year_id) WHERE deleted_at IS NULL;

CREATE TABLE invoices (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id     UUID          NOT NULL REFERENCES schools (id),
    invoice_no    VARCHAR(20)   NOT NULL,                -- INV-2026-000001
    student_id    UUID          NOT NULL,
    term_id       UUID          NOT NULL,
    issued_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    due_date      DATE          NOT NULL,
    -- Derived, maintained ONLY by trg_invoices_derive from lines and allocations:
    total_tzs     NUMERIC(14,2) NOT NULL DEFAULT 0,
    paid_tzs      NUMERIC(14,2) NOT NULL DEFAULT 0,
    balance_tzs   NUMERIC(14,2) GENERATED ALWAYS AS (total_tzs - paid_tzs) STORED,
    status        VARCHAR(15)   NOT NULL DEFAULT 'UNPAID',
    cancelled_at  TIMESTAMPTZ,
    cancel_reason VARCHAR(300),
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    created_by    UUID,
    CONSTRAINT uq_invoices_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_invoices_no UNIQUE (school_id, invoice_no),
    CONSTRAINT fk_invoices_student FOREIGN KEY (school_id, student_id) REFERENCES students (school_id, id),
    CONSTRAINT fk_invoices_term    FOREIGN KEY (school_id, term_id)    REFERENCES terms (school_id, id),
    CONSTRAINT ck_invoices_amounts CHECK (total_tzs >= 0 AND paid_tzs >= 0),
    CONSTRAINT ck_invoices_status CHECK (status IN ('UNPAID','PARTIALLY_PAID','FULLY_PAID','OVERPAID','CANCELLED')),
    CONSTRAINT ck_invoices_cancel CHECK ((cancelled_at IS NULL) = (cancel_reason IS NULL))
);
CREATE UNIQUE INDEX uq_invoices_student_term ON invoices (school_id, student_id, term_id) WHERE cancelled_at IS NULL;
CREATE INDEX ix_invoices_status_due ON invoices (school_id, status, due_date);

CREATE TABLE invoice_lines (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id         UUID          NOT NULL REFERENCES schools (id),
    invoice_id        UUID          NOT NULL,
    fee_item_id       UUID          NOT NULL,
    kind              VARCHAR(8)    NOT NULL DEFAULT 'CHARGE',
    description       VARCHAR(120)  NOT NULL,            -- snapshot at billing time
    amount_tzs        NUMERIC(14,2) NOT NULL,            -- snapshot at billing time, always > 0
    discount_rule_id  UUID,
    created_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
    created_by        UUID,
    deleted_at        TIMESTAMPTZ,
    CONSTRAINT uq_invoice_lines_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_il_invoice  FOREIGN KEY (school_id, invoice_id)       REFERENCES invoices (school_id, id),
    CONSTRAINT fk_il_item     FOREIGN KEY (school_id, fee_item_id)      REFERENCES fee_items (school_id, id),
    CONSTRAINT fk_il_discount FOREIGN KEY (school_id, discount_rule_id) REFERENCES discount_rules (school_id, id),
    CONSTRAINT ck_il_kind   CHECK (kind IN ('CHARGE','DISCOUNT')),
    CONSTRAINT ck_il_amount CHECK (amount_tzs > 0),
    CONSTRAINT ck_il_discount CHECK ((kind = 'DISCOUNT') = (discount_rule_id IS NOT NULL))
);
CREATE INDEX ix_invoice_lines_invoice ON invoice_lines (school_id, invoice_id);

CREATE TABLE invoice_installments (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id   UUID          NOT NULL REFERENCES schools (id),
    invoice_id  UUID          NOT NULL,
    seq         SMALLINT      NOT NULL,
    due_date    DATE          NOT NULL,
    amount_tzs  NUMERIC(14,2) NOT NULL,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    created_by  UUID,
    CONSTRAINT uq_invoice_installments_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_invoice_installments UNIQUE (school_id, invoice_id, seq),
    CONSTRAINT fk_ii_invoice FOREIGN KEY (school_id, invoice_id) REFERENCES invoices (school_id, id),
    CONSTRAINT ck_ii_seq CHECK (seq BETWEEN 1 AND 12),
    CONSTRAINT ck_ii_amount CHECK (amount_tzs > 0)
);

CREATE TABLE gepg_bills (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id           UUID          NOT NULL REFERENCES schools (id),
    invoice_id          UUID          NOT NULL,
    -- Both stay globally unique on purpose: GePG callbacks arrive before the school is
    -- known and are routed by resolve_gepg_bill(). bill_ref embeds the school code
    -- (<code>-<year>-<seq>) and control numbers are issued unique by GePG.
    bill_ref            VARCHAR(40)   NOT NULL UNIQUE,   -- our BillId sent to GePG
    control_number      VARCHAR(12)   UNIQUE,
    amount_tzs          NUMERIC(14,2) NOT NULL,
    status              VARCHAR(10)   NOT NULL DEFAULT 'REQUESTED',
    expires_at          TIMESTAMPTZ   NOT NULL,
    request_payload     JSONB         NOT NULL,
    response_payload    JSONB,
    signature_verified  BOOLEAN       NOT NULL DEFAULT FALSE,
    requested_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
    issued_at           TIMESTAMPTZ,
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    created_by          UUID,
    CONSTRAINT uq_gepg_bills_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_gepg_invoice FOREIGN KEY (school_id, invoice_id) REFERENCES invoices (school_id, id),
    CONSTRAINT ck_gepg_control CHECK (control_number ~ '^[0-9]{12}$'),
    CONSTRAINT ck_gepg_amount  CHECK (amount_tzs > 0),
    CONSTRAINT ck_gepg_status  CHECK (status IN ('REQUESTED','ISSUED','FAILED','EXPIRED','CANCELLED','PAID')),
    CONSTRAINT ck_gepg_issued  CHECK (status NOT IN ('ISSUED','PAID') OR (control_number IS NOT NULL AND signature_verified))
);
CREATE UNIQUE INDEX uq_gepg_bills_open ON gepg_bills (school_id, invoice_id) WHERE status IN ('REQUESTED','ISSUED');

CREATE TABLE payments (                                -- money received; never edited after confirmation
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id          UUID          NOT NULL REFERENCES schools (id),
    student_id         UUID          NOT NULL,
    channel            VARCHAR(10)   NOT NULL,
    external_ref       VARCHAR(60)   NOT NULL,            -- provider receipt / bank ref / cash receipt book no.
    amount_tzs         NUMERIC(14,2) NOT NULL,
    payer_name         VARCHAR(100),
    payer_phone_hash   BYTEA,
    payer_phone_last4  CHAR(4),
    gepg_bill_id       UUID,
    status             VARCHAR(10)   NOT NULL DEFAULT 'PENDING',
    received_at        TIMESTAMPTZ   NOT NULL,
    confirmed_at       TIMESTAMPTZ,
    recorded_by        UUID,                              -- NULL = gateway callback
    raw_payload        JSONB,                             -- redacted copy of the provider message
    created_at         TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ   NOT NULL DEFAULT now(),
    created_by         UUID,
    CONSTRAINT uq_payments_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_payments_external_ref UNIQUE (school_id, channel, external_ref),   -- idempotency per school
    CONSTRAINT fk_payments_student  FOREIGN KEY (school_id, student_id)   REFERENCES students (school_id, id),
    CONSTRAINT fk_payments_bill     FOREIGN KEY (school_id, gepg_bill_id) REFERENCES gepg_bills (school_id, id),
    CONSTRAINT fk_payments_recorder FOREIGN KEY (school_id, recorded_by)  REFERENCES users (school_id, id),
    CONSTRAINT ck_payments_channel CHECK (channel IN ('GEPG','MPESA','TIGOPESA','AIRTEL','HALOPESA','BANK','CASH')),
    CONSTRAINT ck_payments_amount  CHECK (amount_tzs > 0),
    CONSTRAINT ck_payments_status  CHECK (status IN ('PENDING','CONFIRMED','FAILED','REVERSED')),
    CONSTRAINT ck_payments_confirmed CHECK (status NOT IN ('CONFIRMED','REVERSED') OR confirmed_at IS NOT NULL),
    CONSTRAINT ck_payments_manual CHECK (channel NOT IN ('CASH','BANK') OR recorded_by IS NOT NULL),
    CONSTRAINT ck_payments_last4 CHECK (payer_phone_last4 ~ '^[0-9]{4}$')
);
CREATE INDEX ix_payments_student ON payments (school_id, student_id, received_at DESC);
CREATE INDEX ix_payments_received ON payments (school_id, received_at);

CREATE TABLE payment_allocations (                     -- oldest due first; append-only
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id   UUID          NOT NULL REFERENCES schools (id),
    payment_id  UUID          NOT NULL,
    invoice_id  UUID          NOT NULL,
    amount_tzs  NUMERIC(14,2) NOT NULL,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    created_by  UUID,
    CONSTRAINT uq_payment_allocations_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_payment_allocations UNIQUE (school_id, payment_id, invoice_id),
    CONSTRAINT fk_pa_payment FOREIGN KEY (school_id, payment_id) REFERENCES payments (school_id, id),
    CONSTRAINT fk_pa_invoice FOREIGN KEY (school_id, invoice_id) REFERENCES invoices (school_id, id),
    CONSTRAINT ck_pa_amount CHECK (amount_tzs > 0)
);
CREATE INDEX ix_payment_allocations_invoice ON payment_allocations (school_id, invoice_id);

CREATE TABLE payment_reversals (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id    UUID         NOT NULL REFERENCES schools (id),
    payment_id   UUID         NOT NULL,
    reason       VARCHAR(300) NOT NULL,
    reversed_by  UUID         NOT NULL,
    approved_by  UUID         NOT NULL,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by   UUID,
    CONSTRAINT uq_payment_reversals_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_payment_reversals_payment UNIQUE (school_id, payment_id),
    CONSTRAINT fk_prv_payment  FOREIGN KEY (school_id, payment_id)  REFERENCES payments (school_id, id),
    CONSTRAINT fk_prv_reverser FOREIGN KEY (school_id, reversed_by) REFERENCES users (school_id, id),
    CONSTRAINT fk_prv_approver FOREIGN KEY (school_id, approved_by) REFERENCES users (school_id, id),
    CONSTRAINT ck_prv_maker_checker CHECK (reversed_by <> approved_by)
);

CREATE TABLE receipts (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id     UUID         NOT NULL REFERENCES schools (id),
    receipt_no    VARCHAR(20)  NOT NULL,                 -- RCT-2026-000001, gapless per school
    payment_id    UUID         NOT NULL,
    issued_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    pdf_file_key  VARCHAR(255),
    sms_sent_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by    UUID,
    CONSTRAINT uq_receipts_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_receipts_no UNIQUE (school_id, receipt_no),
    CONSTRAINT uq_receipts_payment UNIQUE (school_id, payment_id),
    CONSTRAINT fk_receipts_payment FOREIGN KEY (school_id, payment_id) REFERENCES payments (school_id, id)
);

CREATE TABLE journals (                                -- double-entry header; append-only
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id    UUID         NOT NULL REFERENCES schools (id),
    journal_no   VARCHAR(20)  NOT NULL,
    posted_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    source_type  VARCHAR(12)  NOT NULL,
    source_id    UUID         NOT NULL,
    memo         VARCHAR(200) NOT NULL,
    posted_by    UUID,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by   UUID,
    CONSTRAINT uq_journals_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_journals_no UNIQUE (school_id, journal_no),
    CONSTRAINT fk_journals_user FOREIGN KEY (school_id, posted_by) REFERENCES users (school_id, id),
    CONSTRAINT ck_journals_source CHECK (source_type IN ('INVOICE','INVOICE_CANCEL','PAYMENT','REVERSAL','DISCOUNT','ADJUSTMENT'))
);
CREATE INDEX ix_journals_source ON journals (school_id, source_type, source_id);

CREATE TABLE ledger_entries (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id    UUID          NOT NULL REFERENCES schools (id),
    journal_id   UUID          NOT NULL,
    account_id   UUID          NOT NULL,
    student_id   UUID,                                    -- receivable / credit sub-ledger
    debit_tzs    NUMERIC(14,2) NOT NULL DEFAULT 0,
    credit_tzs   NUMERIC(14,2) NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    created_by   UUID,
    CONSTRAINT uq_ledger_entries_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_le_journal FOREIGN KEY (school_id, journal_id) REFERENCES journals (school_id, id),
    CONSTRAINT fk_le_account FOREIGN KEY (school_id, account_id) REFERENCES ledger_accounts (school_id, id),
    CONSTRAINT fk_le_student FOREIGN KEY (school_id, student_id) REFERENCES students (school_id, id),
    CONSTRAINT ck_le_one_side CHECK ((debit_tzs > 0 AND credit_tzs = 0) OR (credit_tzs > 0 AND debit_tzs = 0))
);
CREATE INDEX ix_ledger_entries_account ON ledger_entries (school_id, account_id, student_id);

CREATE TABLE bank_deposit_confirmations (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id         UUID          NOT NULL REFERENCES schools (id),
    bank_reference    VARCHAR(60)   NOT NULL,
    deposit_date      DATE          NOT NULL,
    amount_tzs        NUMERIC(14,2) NOT NULL,
    student_id        UUID,
    depositor_name    VARCHAR(100),
    status            VARCHAR(10)   NOT NULL DEFAULT 'SUBMITTED',
    submitted_by      UUID          NOT NULL,            -- bursar or parent upload
    confirmed_by      UUID,                              -- bank_officer
    confirmed_at      TIMESTAMPTZ,
    payment_id        UUID,
    note              VARCHAR(300),
    created_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
    created_by        UUID,
    CONSTRAINT uq_bank_deposits_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_bank_deposits_ref UNIQUE (school_id, bank_reference),
    CONSTRAINT fk_bd_student   FOREIGN KEY (school_id, student_id)   REFERENCES students (school_id, id),
    CONSTRAINT fk_bd_submitter FOREIGN KEY (school_id, submitted_by) REFERENCES users (school_id, id),
    CONSTRAINT fk_bd_confirmer FOREIGN KEY (school_id, confirmed_by) REFERENCES users (school_id, id),
    CONSTRAINT fk_bd_payment   FOREIGN KEY (school_id, payment_id)   REFERENCES payments (school_id, id),
    CONSTRAINT ck_bd_amount CHECK (amount_tzs > 0),
    CONSTRAINT ck_bd_status CHECK (status IN ('SUBMITTED','CONFIRMED','REJECTED','MATCHED')),
    CONSTRAINT ck_bd_confirm CHECK (status = 'SUBMITTED' OR (confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)),
    CONSTRAINT ck_bd_matched CHECK ((status = 'MATCHED') = (payment_id IS NOT NULL))
);

CREATE TABLE reconciliation_runs (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id             UUID          NOT NULL REFERENCES schools (id),
    run_date              DATE          NOT NULL,
    channel               VARCHAR(10)   NOT NULL,
    statement_file_key    VARCHAR(255),
    statement_total_tzs   NUMERIC(14,2) NOT NULL DEFAULT 0,
    system_total_tzs      NUMERIC(14,2) NOT NULL DEFAULT 0,
    matched_count         INTEGER       NOT NULL DEFAULT 0,
    exception_count       INTEGER       NOT NULL DEFAULT 0,
    status                VARCHAR(10)   NOT NULL DEFAULT 'RUNNING',
    completed_at          TIMESTAMPTZ,
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
    created_by            UUID,
    CONSTRAINT uq_reconciliation_runs_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_reconciliation_runs UNIQUE (school_id, run_date, channel),
    CONSTRAINT ck_rr_channel CHECK (channel IN ('GEPG','MPESA','TIGOPESA','AIRTEL','HALOPESA','BANK','CASH')),
    CONSTRAINT ck_rr_status  CHECK (status IN ('RUNNING','BALANCED','EXCEPTIONS','FAILED'))
);

CREATE TABLE reconciliation_items (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id             UUID          NOT NULL REFERENCES schools (id),
    run_id                UUID          NOT NULL,
    external_ref          VARCHAR(60)   NOT NULL,
    statement_amount_tzs  NUMERIC(14,2),
    payment_id            UUID,
    status                VARCHAR(22)   NOT NULL,
    resolved_by           UUID,
    resolved_at           TIMESTAMPTZ,
    note                  VARCHAR(300),
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
    created_by            UUID,
    CONSTRAINT uq_reconciliation_items_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_ri_run      FOREIGN KEY (school_id, run_id)      REFERENCES reconciliation_runs (school_id, id),
    CONSTRAINT fk_ri_payment  FOREIGN KEY (school_id, payment_id)  REFERENCES payments (school_id, id),
    CONSTRAINT fk_ri_resolver FOREIGN KEY (school_id, resolved_by) REFERENCES users (school_id, id),
    CONSTRAINT ck_ri_status CHECK (status IN ('MATCHED','MISSING_IN_SYSTEM','MISSING_IN_STATEMENT','AMOUNT_MISMATCH'))
);

-- =====================================================================
-- 10. FACILITIES
-- =====================================================================
CREATE TABLE hostels (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id        UUID        NOT NULL REFERENCES schools (id),
    name             VARCHAR(60) NOT NULL,
    gender           VARCHAR(5)  NOT NULL,
    warden_staff_id  UUID,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by       UUID,
    deleted_at       TIMESTAMPTZ,
    CONSTRAINT uq_hostels_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_hostels_warden FOREIGN KEY (school_id, warden_staff_id) REFERENCES staff (school_id, id),
    CONSTRAINT ck_hostels_gender CHECK (gender IN ('M','F','MIXED'))
);

CREATE TABLE hostel_rooms (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id   UUID        NOT NULL REFERENCES schools (id),
    hostel_id   UUID        NOT NULL,
    name        VARCHAR(20) NOT NULL,
    capacity    SMALLINT    NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by  UUID,
    deleted_at  TIMESTAMPTZ,
    CONSTRAINT uq_hostel_rooms_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_hostel_rooms_hostel FOREIGN KEY (school_id, hostel_id) REFERENCES hostels (school_id, id),
    CONSTRAINT ck_hostel_rooms_capacity CHECK (capacity BETWEEN 1 AND 100)
);
CREATE UNIQUE INDEX uq_hostel_rooms_name ON hostel_rooms (school_id, hostel_id, name) WHERE deleted_at IS NULL;

CREATE TABLE accommodation_requests (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id            UUID         NOT NULL REFERENCES schools (id),
    student_id           UUID         NOT NULL,
    term_id              UUID         NOT NULL,
    preferred_hostel_id  UUID,
    status               VARCHAR(10)  NOT NULL DEFAULT 'PENDING',
    decided_by           UUID,
    decided_at           TIMESTAMPTZ,
    note                 VARCHAR(300),
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by           UUID,
    deleted_at           TIMESTAMPTZ,
    CONSTRAINT uq_accommodation_requests_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_acr_student FOREIGN KEY (school_id, student_id)          REFERENCES students (school_id, id),
    CONSTRAINT fk_acr_term    FOREIGN KEY (school_id, term_id)             REFERENCES terms (school_id, id),
    CONSTRAINT fk_acr_hostel  FOREIGN KEY (school_id, preferred_hostel_id) REFERENCES hostels (school_id, id),
    CONSTRAINT fk_acr_decider FOREIGN KEY (school_id, decided_by)          REFERENCES users (school_id, id),
    CONSTRAINT ck_acr_status CHECK (status IN ('PENDING','APPROVED','REJECTED','CANCELLED'))
);
CREATE UNIQUE INDEX uq_accommodation_open ON accommodation_requests (school_id, student_id, term_id) WHERE status IN ('PENDING','APPROVED') AND deleted_at IS NULL;

CREATE TABLE hostel_allocations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id       UUID        NOT NULL REFERENCES schools (id),
    student_id      UUID        NOT NULL,
    hostel_room_id  UUID        NOT NULL,
    term_id         UUID        NOT NULL,
    request_id      UUID,
    allocated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    vacated_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by      UUID,
    CONSTRAINT uq_hostel_allocations_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_ha_student FOREIGN KEY (school_id, student_id)     REFERENCES students (school_id, id),
    CONSTRAINT fk_ha_room    FOREIGN KEY (school_id, hostel_room_id) REFERENCES hostel_rooms (school_id, id),
    CONSTRAINT fk_ha_term    FOREIGN KEY (school_id, term_id)        REFERENCES terms (school_id, id),
    CONSTRAINT fk_ha_request FOREIGN KEY (school_id, request_id)     REFERENCES accommodation_requests (school_id, id),
    CONSTRAINT ck_ha_dates CHECK (vacated_at IS NULL OR vacated_at >= allocated_at)
);
CREATE UNIQUE INDEX uq_hostel_allocations_active ON hostel_allocations (school_id, student_id, term_id) WHERE vacated_at IS NULL;

CREATE TABLE buses (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id        UUID        NOT NULL REFERENCES schools (id),
    bus_no           VARCHAR(12) NOT NULL,                 -- registration plate, e.g. T 123 DEF
    capacity         SMALLINT    NOT NULL,
    driver_staff_id  UUID,
    status           VARCHAR(10) NOT NULL DEFAULT 'ACTIVE',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by       UUID,
    deleted_at       TIMESTAMPTZ,
    CONSTRAINT uq_buses_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_buses_driver FOREIGN KEY (school_id, driver_staff_id) REFERENCES staff (school_id, id),
    CONSTRAINT ck_buses_plate    CHECK (bus_no ~ '^T ?[0-9]{3} ?[A-Z]{3}$'),
    CONSTRAINT ck_buses_capacity CHECK (capacity BETWEEN 1 AND 100),
    CONSTRAINT ck_buses_status   CHECK (status IN ('ACTIVE','REPAIR','RETIRED'))
);
CREATE UNIQUE INDEX uq_buses_no ON buses (school_id, bus_no) WHERE deleted_at IS NULL;

CREATE TABLE routes (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id      UUID          NOT NULL REFERENCES schools (id),
    name           VARCHAR(60)   NOT NULL,
    description    VARCHAR(300),
    term_fee_tzs   NUMERIC(14,2) NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    created_by     UUID,
    deleted_at     TIMESTAMPTZ,
    CONSTRAINT uq_routes_tenant UNIQUE (school_id, id),
    CONSTRAINT ck_routes_fee CHECK (term_fee_tzs >= 0)
);

CREATE TABLE route_stops (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id    UUID        NOT NULL REFERENCES schools (id),
    route_id     UUID        NOT NULL,
    seq          SMALLINT    NOT NULL,
    name         VARCHAR(60) NOT NULL,
    pickup_time  TIME        NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by   UUID,
    deleted_at   TIMESTAMPTZ,
    CONSTRAINT uq_route_stops_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_route_stops_route FOREIGN KEY (school_id, route_id) REFERENCES routes (school_id, id),
    CONSTRAINT ck_route_stops_seq CHECK (seq >= 1)
);
CREATE UNIQUE INDEX uq_route_stops_seq ON route_stops (school_id, route_id, seq) WHERE deleted_at IS NULL;

CREATE TABLE transport_assignments (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id   UUID        NOT NULL REFERENCES schools (id),
    student_id  UUID        NOT NULL,
    route_id    UUID        NOT NULL,
    bus_id      UUID        NOT NULL,
    stop_id     UUID        NOT NULL,
    term_id     UUID        NOT NULL,
    ended_at    TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by  UUID,
    CONSTRAINT uq_transport_assignments_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_tra_student FOREIGN KEY (school_id, student_id) REFERENCES students (school_id, id),
    CONSTRAINT fk_tra_route   FOREIGN KEY (school_id, route_id)   REFERENCES routes (school_id, id),
    CONSTRAINT fk_tra_bus     FOREIGN KEY (school_id, bus_id)     REFERENCES buses (school_id, id),
    CONSTRAINT fk_tra_stop    FOREIGN KEY (school_id, stop_id)    REFERENCES route_stops (school_id, id),
    CONSTRAINT fk_tra_term    FOREIGN KEY (school_id, term_id)    REFERENCES terms (school_id, id)
);
CREATE UNIQUE INDEX uq_transport_active ON transport_assignments (school_id, student_id, term_id) WHERE ended_at IS NULL;

CREATE TABLE venues (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id    UUID        NOT NULL REFERENCES schools (id),
    name         VARCHAR(60) NOT NULL,
    total_seats  SMALLINT    NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by   UUID,
    deleted_at   TIMESTAMPTZ,
    CONSTRAINT uq_venues_tenant UNIQUE (school_id, id),
    CONSTRAINT ck_venues_seats CHECK (total_seats > 0)
);

CREATE TABLE venue_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id       UUID         NOT NULL REFERENCES schools (id),
    venue_id        UUID         NOT NULL,
    name            VARCHAR(100) NOT NULL,
    event_date      DATE         NOT NULL,
    time_start      TIME         NOT NULL,
    time_end        TIME         NOT NULL,
    slot            timerange    GENERATED ALWAYS AS (timerange(time_start, time_end, '[)')) STORED,
    seats_occupied  SMALLINT     NOT NULL DEFAULT 0,
    organiser_id    UUID,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by      UUID,
    deleted_at      TIMESTAMPTZ,
    CONSTRAINT uq_venue_events_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_ve_venue     FOREIGN KEY (school_id, venue_id)     REFERENCES venues (school_id, id),
    CONSTRAINT fk_ve_organiser FOREIGN KEY (school_id, organiser_id) REFERENCES users (school_id, id),
    CONSTRAINT ck_ve_time  CHECK (time_end > time_start),
    CONSTRAINT ck_ve_seats CHECK (seats_occupied >= 0),
    CONSTRAINT ex_ve_overlap EXCLUDE USING gist (venue_id WITH =, event_date WITH =, slot WITH &&) WHERE (deleted_at IS NULL)
);

-- =====================================================================
-- 11. STUDENT LIFE
-- =====================================================================
CREATE TABLE discipline_records (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id           UUID         NOT NULL REFERENCES schools (id),
    student_id          UUID         NOT NULL,
    incident_date       DATE         NOT NULL,
    category            VARCHAR(15)  NOT NULL,
    description         VARCHAR(1000) NOT NULL,
    action_taken        VARCHAR(500),
    resolution          VARCHAR(500),
    status              VARCHAR(8)   NOT NULL DEFAULT 'OPEN',
    parent_notified_at  TIMESTAMPTZ,
    recorded_by         UUID         NOT NULL,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by          UUID,
    deleted_at          TIMESTAMPTZ,
    CONSTRAINT uq_discipline_records_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_dr_student  FOREIGN KEY (school_id, student_id)  REFERENCES students (school_id, id),
    CONSTRAINT fk_dr_recorder FOREIGN KEY (school_id, recorded_by) REFERENCES users (school_id, id),
    CONSTRAINT ck_dr_category CHECK (category IN ('LATENESS','TRUANCY','FIGHTING','BULLYING','THEFT','CHEATING','PROPERTY_DAMAGE','OTHER')),
    CONSTRAINT ck_dr_status CHECK (status IN ('OPEN','RESOLVED')),
    CONSTRAINT ck_dr_resolved CHECK (status = 'OPEN' OR resolution IS NOT NULL)
);

CREATE TABLE extracurricular_activities (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id        UUID        NOT NULL REFERENCES schools (id),
    name             VARCHAR(80) NOT NULL,
    kind             VARCHAR(10) NOT NULL,
    patron_staff_id  UUID,
    meeting_day      SMALLINT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by       UUID,
    deleted_at       TIMESTAMPTZ,
    CONSTRAINT uq_activities_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_activities_patron FOREIGN KEY (school_id, patron_staff_id) REFERENCES staff (school_id, id),
    CONSTRAINT ck_activities_kind CHECK (kind IN ('CLUB','SPORT','SOCIETY','ARTS')),
    CONSTRAINT ck_activities_day  CHECK (meeting_day BETWEEN 1 AND 7)
);

CREATE TABLE student_activities (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id         UUID        NOT NULL REFERENCES schools (id),
    student_id        UUID        NOT NULL,
    activity_id       UUID        NOT NULL,
    academic_year_id  UUID        NOT NULL,
    role              VARCHAR(10) NOT NULL DEFAULT 'MEMBER',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by        UUID,
    deleted_at        TIMESTAMPTZ,
    CONSTRAINT uq_student_activities_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_sa_student  FOREIGN KEY (school_id, student_id)       REFERENCES students (school_id, id),
    CONSTRAINT fk_sa_activity FOREIGN KEY (school_id, activity_id)      REFERENCES extracurricular_activities (school_id, id),
    CONSTRAINT fk_sa_year     FOREIGN KEY (school_id, academic_year_id) REFERENCES academic_years (school_id, id),
    CONSTRAINT ck_sa_role CHECK (role IN ('MEMBER','LEADER','CAPTAIN','SECRETARY'))
);
CREATE UNIQUE INDEX uq_student_activities ON student_activities (school_id, student_id, activity_id, academic_year_id) WHERE deleted_at IS NULL;

CREATE TABLE library_books (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id   UUID         NOT NULL REFERENCES schools (id),
    isbn        VARCHAR(17),
    title       VARCHAR(200) NOT NULL,
    author      VARCHAR(150),
    subject_id  UUID,
    copies      SMALLINT     NOT NULL DEFAULT 1,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by  UUID,
    deleted_at  TIMESTAMPTZ,
    CONSTRAINT uq_library_books_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_lb_subject FOREIGN KEY (school_id, subject_id) REFERENCES subjects (school_id, id),
    CONSTRAINT ck_lb_copies CHECK (copies >= 0),
    CONSTRAINT ck_lb_isbn CHECK (isbn ~ '^[0-9X-]{10,17}$')
);

CREATE TABLE library_loans (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id         UUID        NOT NULL REFERENCES schools (id),
    book_id           UUID        NOT NULL,
    borrower_user_id  UUID        NOT NULL,
    loaned_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    due_date          DATE        NOT NULL,
    returned_at       TIMESTAMPTZ,
    issued_by         UUID        NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by        UUID,
    CONSTRAINT uq_library_loans_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_ll_book     FOREIGN KEY (school_id, book_id)          REFERENCES library_books (school_id, id),
    CONSTRAINT fk_ll_borrower FOREIGN KEY (school_id, borrower_user_id) REFERENCES users (school_id, id),
    CONSTRAINT fk_ll_issuer   FOREIGN KEY (school_id, issued_by)        REFERENCES users (school_id, id)
);
CREATE INDEX ix_library_loans_open ON library_loans (school_id, book_id) WHERE returned_at IS NULL;

CREATE TABLE health_records (                          -- restricted: health.read permission + consent
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id    UUID        NOT NULL REFERENCES schools (id),
    student_id   UUID        NOT NULL,
    record_date  DATE        NOT NULL,
    kind         VARCHAR(12) NOT NULL,
    notes_enc    BYTEA       NOT NULL,                  -- encrypted free text
    recorded_by  UUID        NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by   UUID,
    deleted_at   TIMESTAMPTZ,
    CONSTRAINT uq_health_records_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_hr_student  FOREIGN KEY (school_id, student_id)  REFERENCES students (school_id, id),
    CONSTRAINT fk_hr_recorder FOREIGN KEY (school_id, recorded_by) REFERENCES users (school_id, id),
    CONSTRAINT ck_hr_kind CHECK (kind IN ('ALLERGY','CONDITION','CLINIC_VISIT','VACCINATION'))
);

-- =====================================================================
-- 12. COMMUNICATION AND SYSTEM
-- =====================================================================
CREATE TABLE announcements (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id       UUID          NOT NULL REFERENCES schools (id),
    title           VARCHAR(120)  NOT NULL,
    body            VARCHAR(2000) NOT NULL,
    language        CHAR(2)       NOT NULL DEFAULT 'sw',
    audience        VARCHAR(12)   NOT NULL,
    class_id        UUID,
    stream_id       UUID,
    target_user_id  UUID,
    send_sms        BOOLEAN       NOT NULL DEFAULT FALSE,
    publish_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    created_by      UUID,
    deleted_at      TIMESTAMPTZ,
    CONSTRAINT uq_announcements_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_ann_class  FOREIGN KEY (school_id, class_id)       REFERENCES classes (school_id, id),
    CONSTRAINT fk_ann_stream FOREIGN KEY (school_id, stream_id)      REFERENCES streams (school_id, id),
    CONSTRAINT fk_ann_user   FOREIGN KEY (school_id, target_user_id) REFERENCES users (school_id, id),
    CONSTRAINT ck_ann_lang CHECK (language IN ('sw','en')),
    CONSTRAINT ck_ann_audience CHECK (
        (audience IN ('SCHOOL','STAFF','PARENTS') AND class_id IS NULL AND stream_id IS NULL AND target_user_id IS NULL) OR
        (audience = 'CLASS'      AND class_id IS NOT NULL AND stream_id IS NULL AND target_user_id IS NULL) OR
        (audience = 'STREAM'     AND stream_id IS NOT NULL AND class_id IS NULL AND target_user_id IS NULL) OR
        (audience = 'INDIVIDUAL' AND target_user_id IS NOT NULL AND class_id IS NULL AND stream_id IS NULL))
);

CREATE TABLE notifications (                           -- in-app inbox
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id   UUID         NOT NULL REFERENCES schools (id),
    user_id     UUID         NOT NULL,
    kind        VARCHAR(30)  NOT NULL,
    title       VARCHAR(120) NOT NULL,
    body        VARCHAR(500) NOT NULL,
    link        VARCHAR(200),
    read_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by  UUID,
    CONSTRAINT uq_notifications_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_notifications_user FOREIGN KEY (school_id, user_id) REFERENCES users (school_id, id)
);
CREATE INDEX ix_notifications_unread ON notifications (school_id, user_id, created_at DESC) WHERE read_at IS NULL;

CREATE TABLE message_templates (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id   UUID         NOT NULL REFERENCES schools (id),
    key         VARCHAR(40)  NOT NULL,
    language    CHAR(2)      NOT NULL,
    body        VARCHAR(480) NOT NULL,                  -- {placeholders}; <= 3 SMS segments
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by  UUID,
    deleted_at  TIMESTAMPTZ,
    CONSTRAINT uq_message_templates_tenant UNIQUE (school_id, id),
    CONSTRAINT ck_mt_lang CHECK (language IN ('sw','en')),
    CONSTRAINT ck_mt_key  CHECK (key ~ '^[a-z_]+$')
);
CREATE UNIQUE INDEX uq_message_templates ON message_templates (school_id, key, language) WHERE deleted_at IS NULL;

CREATE TABLE sms_messages (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id            UUID         NOT NULL REFERENCES schools (id),
    to_user_id           UUID,
    to_phone_enc         BYTEA        NOT NULL,
    to_phone_last4       CHAR(4)      NOT NULL,
    template_key         VARCHAR(40),
    language             CHAR(2)      NOT NULL,
    body                 VARCHAR(480) NOT NULL,
    segments             SMALLINT     NOT NULL,
    provider             VARCHAR(12)  NOT NULL,
    provider_message_id  VARCHAR(80),
    status               VARCHAR(10)  NOT NULL DEFAULT 'QUEUED',
    cost_credits         SMALLINT     NOT NULL DEFAULT 0,
    error                VARCHAR(300),
    idempotency_key      VARCHAR(80)  NOT NULL,          -- e.g. absence:<student>:<date>
    related_entity       VARCHAR(40),
    related_id           UUID,
    queued_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    sent_at              TIMESTAMPTZ,
    delivered_at         TIMESTAMPTZ,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by           UUID,
    CONSTRAINT uq_sms_messages_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_sms_messages_idem UNIQUE (school_id, idempotency_key),
    CONSTRAINT fk_sms_user FOREIGN KEY (school_id, to_user_id) REFERENCES users (school_id, id),
    CONSTRAINT ck_sms_lang CHECK (language IN ('sw','en')),
    CONSTRAINT ck_sms_segments CHECK (segments BETWEEN 1 AND 3),
    CONSTRAINT ck_sms_provider CHECK (provider IN ('BEEM','NEXTSMS','CONSOLE')),
    CONSTRAINT ck_sms_status CHECK (status IN ('QUEUED','SENT','DELIVERED','FAILED','SKIPPED'))
);
CREATE INDEX ix_sms_messages_status ON sms_messages (school_id, status, queued_at);
ALTER TABLE absence_alerts ADD CONSTRAINT fk_aa_sms
    FOREIGN KEY (school_id, sms_message_id) REFERENCES sms_messages (school_id, id);

CREATE TABLE sms_credit_transactions (                 -- balance = view v_sms_credit_balance
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id       UUID         NOT NULL REFERENCES schools (id),
    kind            VARCHAR(8)   NOT NULL,
    credits         INTEGER      NOT NULL,              -- always positive; kind gives the sign
    sms_message_id  UUID,
    note            VARCHAR(200),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by      UUID,
    CONSTRAINT uq_sms_credit_transactions_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_sct_sms FOREIGN KEY (school_id, sms_message_id) REFERENCES sms_messages (school_id, id),
    CONSTRAINT ck_sct_kind CHECK (kind IN ('TOPUP','DEBIT','REFUND')),
    CONSTRAINT ck_sct_credits CHECK (credits > 0),
    CONSTRAINT ck_sct_debit CHECK ((kind = 'DEBIT') = (sms_message_id IS NOT NULL))
);

CREATE TABLE audit_logs (                              -- append-only
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id          UUID        NOT NULL REFERENCES schools (id),
    occurred_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_user_id      UUID,
    actor_platform_id  UUID REFERENCES platform_admins (id),
    action             VARCHAR(20) NOT NULL,
    entity_type        VARCHAR(40) NOT NULL,
    entity_id          UUID,
    before_data        JSONB,
    after_data         JSONB,
    ip_address         INET,
    user_agent         VARCHAR(255),
    request_id         UUID,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_audit_logs_tenant UNIQUE (school_id, id),
    CONSTRAINT ck_audit_action CHECK (action IN ('INSERT','UPDATE','DELETE','LOGIN','LOGIN_FAILED','LOGOUT',
        'OTP_SENT','OTP_FAILED','TOKEN_REUSE','PASSWORD_CHANGE','ROLE_GRANT','ROLE_REVOKE','EXPORT','VIEW_SENSITIVE','PUBLISH'))
);
CREATE INDEX ix_audit_entity ON audit_logs (school_id, entity_type, entity_id, occurred_at DESC);
CREATE INDEX ix_audit_actor  ON audit_logs (school_id, actor_user_id, occurred_at DESC);
CREATE INDEX brin_audit_time ON audit_logs USING brin (occurred_at);

CREATE TABLE background_jobs (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id              UUID         NOT NULL REFERENCES schools (id),
    kind                   VARCHAR(25)  NOT NULL,
    status                 VARCHAR(10)  NOT NULL DEFAULT 'QUEUED',
    progress_pct           SMALLINT     NOT NULL DEFAULT 0,
    total_items            INTEGER,
    processed_items        INTEGER      NOT NULL DEFAULT 0,
    error_count            INTEGER      NOT NULL DEFAULT 0,
    input_file_key         VARCHAR(255),
    result_file_key        VARCHAR(255),
    error_report_file_key  VARCHAR(255),
    idempotency_key        VARCHAR(80),
    celery_task_id         VARCHAR(64),
    requested_by           UUID         NOT NULL,
    started_at             TIMESTAMPTZ,
    finished_at            TIMESTAMPTZ,
    created_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by             UUID,
    CONSTRAINT uq_background_jobs_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_bj_requester FOREIGN KEY (school_id, requested_by) REFERENCES users (school_id, id),
    CONSTRAINT ck_bj_kind CHECK (kind IN ('IMPORT_STUDENTS','IMPORT_GUARDIANS','IMPORT_STAFF','IMPORT_MARKS',
        'REPORT_CARDS','RECEIPT_PDF','EXPORT','COMPLIANCE_EXPORT','SMS_BATCH','RECONCILIATION','INVOICE_RUN','PROMOTION')),
    CONSTRAINT ck_bj_status CHECK (status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
    CONSTRAINT ck_bj_progress CHECK (progress_pct BETWEEN 0 AND 100)
);
CREATE UNIQUE INDEX uq_background_jobs_idem ON background_jobs (school_id, kind, idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE TABLE idempotency_keys (                        -- Idempotency-Key header store (24 h)
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id        UUID         NOT NULL REFERENCES schools (id),
    scope            VARCHAR(60)  NOT NULL,             -- METHOD + route template
    key              VARCHAR(80)  NOT NULL,
    request_hash     CHAR(64)     NOT NULL,
    response_status  SMALLINT,
    response_body    JSONB,
    expires_at       TIMESTAMPTZ  NOT NULL,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by       UUID,
    CONSTRAINT uq_idempotency_keys_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_idempotency_keys UNIQUE (school_id, scope, key)
);

-- =====================================================================
-- 13. TENANT ISOLATION, created_by FKs, updated_at — applied to every table
-- =====================================================================
DO $$
DECLARE t record;
BEGIN
    FOR t IN
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'school_id' AND NOT a.attisdropped
        WHERE c.relkind = 'r'
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t.relname);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t.relname);
        EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (school_id = app_school_id()) '
                       'WITH CHECK (school_id = app_school_id())', t.relname);
    END LOOP;

    FOR t IN
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
        JOIN pg_attribute a  ON a.attrelid = c.oid AND a.attname = 'created_by' AND NOT a.attisdropped
        JOIN pg_attribute a2 ON a2.attrelid = c.oid AND a2.attname = 'school_id' AND NOT a2.attisdropped
        WHERE c.relkind = 'r'
    LOOP
        EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (school_id, created_by) '
                       'REFERENCES users (school_id, id)', t.relname, 'fk_' || t.relname || '_created_by');
    END LOOP;

    FOR t IN
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'updated_at' AND NOT a.attisdropped
        WHERE c.relkind = 'r'
    LOOP
        EXECUTE format('CREATE TRIGGER trg_%s_updated BEFORE UPDATE ON %I '
                       'FOR EACH ROW EXECUTE FUNCTION fn_touch_updated_at()', t.relname, t.relname);
    END LOOP;
END $$;

-- The tenant registry itself: a school sees only its own row.
ALTER TABLE schools ENABLE ROW LEVEL SECURITY;
ALTER TABLE schools FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON schools USING (id = app_school_id()) WITH CHECK (id = app_school_id());

-- =====================================================================
-- 14. AUDIT TRAIL (rule 4)
-- =====================================================================
CREATE FUNCTION fn_redact(j JSONB) RETURNS JSONB LANGUAGE sql IMMUTABLE AS $$
    SELECT COALESCE(jsonb_object_agg(key, value), '{}'::jsonb)
    FROM jsonb_each(j)
    WHERE key NOT LIKE '%\_enc' AND key NOT LIKE '%\_hash' AND key <> 'password_hash'
$$;

CREATE FUNCTION fn_audit_row() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_old JSONB;
    v_new JSONB;
    v_row JSONB;
BEGIN
    IF TG_OP IN ('UPDATE','DELETE') THEN v_old := fn_redact(to_jsonb(OLD)); END IF;
    IF TG_OP IN ('INSERT','UPDATE') THEN v_new := fn_redact(to_jsonb(NEW)); END IF;
    IF TG_OP = 'UPDATE' AND (v_old - 'updated_at') = (v_new - 'updated_at') THEN
        RETURN NULL;                                       -- nothing visible changed
    END IF;
    v_row := COALESCE(v_new, v_old);
    INSERT INTO audit_logs (school_id, actor_user_id, actor_platform_id, action, entity_type, entity_id,
                            before_data, after_data, ip_address, request_id)
    VALUES ((v_row ->> 'school_id')::uuid,
            app_user_id(),
            NULLIF(current_setting('app.platform_admin_id', true), '')::uuid,
            TG_OP, TG_TABLE_NAME, (v_row ->> 'id')::uuid, v_old, v_new,
            NULLIF(current_setting('app.client_ip', true), '')::inet,
            NULLIF(current_setting('app.request_id', true), '')::uuid);
    RETURN NULL;
END $$;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'users','user_roles','students','student_guardians','guardians','staff','consent_records',
        'enrolment_applications','enrolment_documents','enrolments','mark_entries','result_publications',
        'published_results','result_amendments','student_term_summaries','attendance_records',
        'fee_structures','fee_structure_lines','student_discounts','invoices','invoice_lines',
        'gepg_bills','payments','payment_allocations','payment_reversals','bank_deposit_confirmations',
        'discipline_records','health_records','grading_schemes','grade_bands','assessment_components']
    LOOP
        EXECUTE format('CREATE TRIGGER trg_%s_audit AFTER INSERT OR UPDATE OR DELETE ON %I '
                       'FOR EACH ROW EXECUTE FUNCTION fn_audit_row()', t, t);
    END LOOP;
END $$;

-- =====================================================================
-- 15. INTEGRITY TRIGGERS
-- =====================================================================

-- 15.1 Gapless per-school document numbers (row lock held until commit)
CREATE FUNCTION next_document_no(p_school UUID, p_type VARCHAR, p_year SMALLINT) RETURNS INTEGER
LANGUAGE sql AS $$
    INSERT INTO document_sequences AS d (school_id, doc_type, year, last_value)
    VALUES (p_school, p_type, p_year, 1)
    ON CONFLICT (school_id, doc_type, year) DO UPDATE SET last_value = d.last_value + 1
    RETURNING last_value
$$;

-- 15.2 Frozen and append-only tables (rules 4 and 5)
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['result_publications','published_results','student_term_summaries',
                             'journals','ledger_entries','payment_allocations','payment_reversals']
    LOOP
        EXECUTE format('CREATE TRIGGER trg_%s_frozen BEFORE UPDATE OR DELETE ON %I '
                       'FOR EACH ROW EXECUTE FUNCTION fn_block_change()', t, t);
    END LOOP;
END $$;
CREATE TRIGGER trg_audit_logs_frozen BEFORE UPDATE OR DELETE OR TRUNCATE ON audit_logs
    FOR EACH STATEMENT EXECUTE FUNCTION fn_block_change();

-- 15.3 A new version of a published result needs an APPROVED amendment for that result
CREATE FUNCTION fn_published_result_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.supersedes_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM result_amendments a
        WHERE a.school_id = NEW.school_id AND a.id = NEW.amendment_id
          AND a.published_result_id = NEW.supersedes_id AND a.status = 'APPROVED') THEN
        RAISE EXCEPTION 'published result % can only be superseded through an approved amendment', NEW.supersedes_id
            USING ERRCODE = 'P0001';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_published_results_guard BEFORE INSERT ON published_results
    FOR EACH ROW EXECUTE FUNCTION fn_published_result_guard();

-- 15.4 Draft marks: range check, optimistic version, lock after publication
CREATE FUNCTION fn_mark_entries_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_max NUMERIC;
BEGIN
    IF TG_OP IN ('UPDATE','DELETE') AND OLD.locked_at IS NOT NULL THEN
        RAISE EXCEPTION 'marks are locked after publication; request a result amendment'
            USING ERRCODE = 'P0001';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    IF NEW.score IS NOT NULL THEN
        SELECT max_score INTO v_max FROM assessment_components
        WHERE school_id = NEW.school_id AND id = NEW.component_id;
        IF NEW.score > v_max THEN
            RAISE EXCEPTION 'score % exceeds the component maximum %', NEW.score, v_max
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        NEW.version := OLD.version + 1;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_mark_entries_guard BEFORE INSERT OR UPDATE OR DELETE ON mark_entries
    FOR EACH ROW EXECUTE FUNCTION fn_mark_entries_guard();

-- 15.5 Invoice totals, paid amount and status are derived from lines and allocations
--      every time the invoice row is written, so they cannot drift.
CREATE FUNCTION fn_invoices_derive() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    SELECT COALESCE(SUM(CASE l.kind WHEN 'CHARGE' THEN l.amount_tzs ELSE -l.amount_tzs END), 0)
      INTO NEW.total_tzs
      FROM invoice_lines l
     WHERE l.school_id = NEW.school_id AND l.invoice_id = NEW.id AND l.deleted_at IS NULL;
    IF NEW.total_tzs < 0 THEN
        RAISE EXCEPTION 'discounts exceed charges on invoice %', NEW.invoice_no USING ERRCODE = 'check_violation';
    END IF;
    SELECT COALESCE(SUM(pa.amount_tzs), 0)
      INTO NEW.paid_tzs
      FROM payment_allocations pa
      JOIN payments p ON p.school_id = pa.school_id AND p.id = pa.payment_id
     WHERE pa.school_id = NEW.school_id AND pa.invoice_id = NEW.id AND p.status = 'CONFIRMED';
    IF NEW.cancelled_at IS NOT NULL AND NEW.paid_tzs > 0 THEN
        RAISE EXCEPTION 'invoice % has payments of %; reverse them or issue a discount line instead of cancelling',
            NEW.invoice_no, NEW.paid_tzs USING ERRCODE = 'P0001';
    END IF;
    NEW.status := CASE
        WHEN NEW.cancelled_at IS NOT NULL      THEN 'CANCELLED'
        WHEN NEW.paid_tzs > NEW.total_tzs      THEN 'OVERPAID'
        WHEN NEW.paid_tzs = NEW.total_tzs      THEN 'FULLY_PAID'
        WHEN NEW.paid_tzs = 0                  THEN 'UNPAID'
        ELSE 'PARTIALLY_PAID'
    END;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_invoices_derive BEFORE INSERT OR UPDATE ON invoices
    FOR EACH ROW EXECUTE FUNCTION fn_invoices_derive();

CREATE FUNCTION fn_touch_invoice() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE invoices SET updated_at = now()
     WHERE school_id = COALESCE(NEW.school_id, OLD.school_id)
       AND id = COALESCE(NEW.invoice_id, OLD.invoice_id);
    RETURN NULL;
END $$;
CREATE TRIGGER trg_invoice_lines_touch AFTER INSERT OR UPDATE OR DELETE ON invoice_lines
    FOR EACH ROW EXECUTE FUNCTION fn_touch_invoice();
CREATE TRIGGER trg_payment_allocations_touch AFTER INSERT ON payment_allocations
    FOR EACH ROW EXECUTE FUNCTION fn_touch_invoice();

-- 15.6 Allocation rules: confirmed payment, same student, open invoice, no over-allocation
CREATE FUNCTION fn_allocation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_pay   payments%ROWTYPE;
    v_inv   invoices%ROWTYPE;
    v_used  NUMERIC;
BEGIN
    SELECT * INTO v_pay FROM payments WHERE school_id = NEW.school_id AND id = NEW.payment_id FOR UPDATE;
    SELECT * INTO v_inv FROM invoices WHERE school_id = NEW.school_id AND id = NEW.invoice_id FOR UPDATE;
    IF v_pay.status <> 'CONFIRMED' THEN
        RAISE EXCEPTION 'only CONFIRMED payments can be allocated (payment is %)', v_pay.status USING ERRCODE = 'P0001';
    END IF;
    IF v_inv.student_id <> v_pay.student_id THEN
        RAISE EXCEPTION 'invoice % belongs to another student', v_inv.invoice_no USING ERRCODE = 'P0001';
    END IF;
    IF v_inv.cancelled_at IS NOT NULL THEN
        RAISE EXCEPTION 'invoice % is cancelled', v_inv.invoice_no USING ERRCODE = 'P0001';
    END IF;
    IF NEW.amount_tzs > v_inv.balance_tzs THEN
        RAISE EXCEPTION 'allocation % exceeds the balance % of invoice %', NEW.amount_tzs, v_inv.balance_tzs, v_inv.invoice_no
            USING ERRCODE = 'P0001';
    END IF;
    SELECT COALESCE(SUM(amount_tzs), 0) INTO v_used
      FROM payment_allocations WHERE school_id = NEW.school_id AND payment_id = NEW.payment_id;
    IF v_used + NEW.amount_tzs > v_pay.amount_tzs THEN
        RAISE EXCEPTION 'allocations would exceed the payment amount %', v_pay.amount_tzs USING ERRCODE = 'P0001';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_payment_allocations_guard BEFORE INSERT ON payment_allocations
    FOR EACH ROW EXECUTE FUNCTION fn_allocation_guard();

-- 15.7 Payments: never deleted; money fields immutable; legal status transitions only
CREATE FUNCTION fn_payments_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_mutable TEXT[] := ARRAY['status','confirmed_at','updated_at','gepg_bill_id','raw_payload'];
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'payments are never deleted; record a reversal' USING ERRCODE = 'P0001';
    END IF;
    IF (to_jsonb(NEW) - v_mutable) <> (to_jsonb(OLD) - v_mutable) THEN
        RAISE EXCEPTION 'payment % is immutable except for its status', OLD.external_ref USING ERRCODE = 'P0001';
    END IF;
    IF NEW.status <> OLD.status AND NOT (
           (OLD.status = 'PENDING'   AND NEW.status IN ('CONFIRMED','FAILED'))
        OR (OLD.status = 'CONFIRMED' AND NEW.status = 'REVERSED' AND EXISTS (
               SELECT 1 FROM payment_reversals r WHERE r.school_id = NEW.school_id AND r.payment_id = NEW.id))) THEN
        RAISE EXCEPTION 'illegal payment status change % -> %', OLD.status, NEW.status USING ERRCODE = 'P0001';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_payments_guard BEFORE UPDATE OR DELETE ON payments
    FOR EACH ROW EXECUTE FUNCTION fn_payments_guard();

CREATE FUNCTION fn_payment_status_touch() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE invoices i SET updated_at = now()
      FROM payment_allocations pa
     WHERE pa.school_id = NEW.school_id AND pa.payment_id = NEW.id
       AND i.school_id = pa.school_id AND i.id = pa.invoice_id;
    RETURN NULL;
END $$;
CREATE TRIGGER trg_payments_status_touch AFTER UPDATE OF status ON payments
    FOR EACH ROW EXECUTE FUNCTION fn_payment_status_touch();

CREATE FUNCTION fn_payment_reversal_apply() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE payments SET status = 'REVERSED' WHERE school_id = NEW.school_id AND id = NEW.payment_id;
    RETURN NULL;
END $$;
CREATE TRIGGER trg_payment_reversals_apply AFTER INSERT ON payment_reversals
    FOR EACH ROW EXECUTE FUNCTION fn_payment_reversal_apply();

-- 15.8 Receipts: only the PDF key and SMS timestamp may be filled in later
CREATE FUNCTION fn_receipts_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_mutable TEXT[] := ARRAY['pdf_file_key','sms_sent_at','updated_at'];
BEGIN
    IF TG_OP = 'DELETE' OR (to_jsonb(NEW) - v_mutable) <> (to_jsonb(OLD) - v_mutable) THEN
        RAISE EXCEPTION 'receipt % cannot be changed', OLD.receipt_no USING ERRCODE = 'P0001';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_receipts_guard BEFORE UPDATE OR DELETE ON receipts
    FOR EACH ROW EXECUTE FUNCTION fn_receipts_guard();

-- 15.9 Double entry: every journal balances, checked at COMMIT
CREATE FUNCTION fn_journal_balanced() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_journal UUID := CASE TG_TABLE_NAME WHEN 'journals' THEN NEW.id
                                         ELSE (to_jsonb(NEW) ->> 'journal_id')::uuid END;
    v_dr NUMERIC; v_cr NUMERIC; v_n INTEGER;
BEGIN
    SELECT COALESCE(SUM(debit_tzs), 0), COALESCE(SUM(credit_tzs), 0), COUNT(*)
      INTO v_dr, v_cr, v_n
      FROM ledger_entries WHERE school_id = NEW.school_id AND journal_id = v_journal;
    IF v_n < 2 OR v_dr <> v_cr THEN
        RAISE EXCEPTION 'journal % is unbalanced: debit %, credit %, % lines', v_journal, v_dr, v_cr, v_n
            USING ERRCODE = 'P0001';
    END IF;
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER trg_ledger_entries_balanced AFTER INSERT ON ledger_entries
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fn_journal_balanced();
CREATE CONSTRAINT TRIGGER trg_journals_balanced AFTER INSERT ON journals
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fn_journal_balanced();

-- 15.10 Capacity rules (stream, hostel room, bus, venue, library copies)
CREATE FUNCTION fn_capacity_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_capacity INTEGER; v_used INTEGER;
BEGIN
    IF TG_TABLE_NAME = 'enrolments' THEN
        IF NEW.status <> 'ACTIVE' THEN RETURN NEW; END IF;
        SELECT capacity INTO v_capacity FROM streams WHERE school_id = NEW.school_id AND id = NEW.stream_id FOR UPDATE;
        SELECT COUNT(*) INTO v_used FROM enrolments
         WHERE school_id = NEW.school_id AND stream_id = NEW.stream_id AND academic_year_id = NEW.academic_year_id
           AND status = 'ACTIVE' AND id <> NEW.id;
    ELSIF TG_TABLE_NAME = 'hostel_allocations' THEN
        IF NEW.vacated_at IS NOT NULL THEN RETURN NEW; END IF;
        SELECT capacity INTO v_capacity FROM hostel_rooms WHERE school_id = NEW.school_id AND id = NEW.hostel_room_id FOR UPDATE;
        SELECT COUNT(*) INTO v_used FROM hostel_allocations
         WHERE school_id = NEW.school_id AND hostel_room_id = NEW.hostel_room_id AND term_id = NEW.term_id
           AND vacated_at IS NULL AND id <> NEW.id;
    ELSIF TG_TABLE_NAME = 'transport_assignments' THEN
        IF NEW.ended_at IS NOT NULL THEN RETURN NEW; END IF;
        SELECT capacity INTO v_capacity FROM buses WHERE school_id = NEW.school_id AND id = NEW.bus_id FOR UPDATE;
        SELECT COUNT(*) INTO v_used FROM transport_assignments
         WHERE school_id = NEW.school_id AND bus_id = NEW.bus_id AND term_id = NEW.term_id
           AND ended_at IS NULL AND id <> NEW.id;
    ELSIF TG_TABLE_NAME = 'venue_events' THEN
        SELECT total_seats INTO v_capacity FROM venues WHERE school_id = NEW.school_id AND id = NEW.venue_id;
        v_used := NEW.seats_occupied - 1;                  -- compare seats, not rows
    ELSIF TG_TABLE_NAME = 'library_loans' THEN
        IF NEW.returned_at IS NOT NULL THEN RETURN NEW; END IF;
        SELECT copies INTO v_capacity FROM library_books WHERE school_id = NEW.school_id AND id = NEW.book_id FOR UPDATE;
        SELECT COUNT(*) INTO v_used FROM library_loans
         WHERE school_id = NEW.school_id AND book_id = NEW.book_id AND returned_at IS NULL AND id <> NEW.id;
    END IF;
    IF v_used + 1 > v_capacity THEN
        RAISE EXCEPTION '% is full (capacity %)', TG_TABLE_NAME, v_capacity USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['enrolments','hostel_allocations','transport_assignments','venue_events','library_loans']
    LOOP
        EXECUTE format('CREATE TRIGGER trg_%s_capacity BEFORE INSERT OR UPDATE ON %I '
                       'FOR EACH ROW EXECUTE FUNCTION fn_capacity_guard()', t, t);
    END LOOP;
END $$;

-- =====================================================================
-- 16. VIEWS (security_invoker: RLS of the caller applies)
-- =====================================================================
CREATE VIEW v_current_results WITH (security_invoker = true) AS
SELECT pr.*
FROM published_results pr
WHERE NOT EXISTS (SELECT 1 FROM published_results n
                  WHERE n.school_id = pr.school_id AND n.supersedes_id = pr.id);

CREATE VIEW v_current_term_summaries WITH (security_invoker = true) AS
SELECT s.*
FROM student_term_summaries s
WHERE NOT EXISTS (SELECT 1 FROM student_term_summaries n
                  WHERE n.school_id = s.school_id AND n.supersedes_id = s.id);

CREATE VIEW v_component_weight_totals WITH (security_invoker = true) AS
SELECT school_id, term_id, education_level_id, subject_id, SUM(weight) AS total_weight, COUNT(*) AS components
FROM assessment_components
WHERE deleted_at IS NULL
GROUP BY school_id, term_id, education_level_id, subject_id;

CREATE VIEW v_payment_unallocated WITH (security_invoker = true) AS
SELECT p.school_id, p.id AS payment_id, p.student_id, p.amount_tzs,
       p.amount_tzs - COALESCE(SUM(pa.amount_tzs), 0) AS unallocated_tzs
FROM payments p
LEFT JOIN payment_allocations pa ON pa.school_id = p.school_id AND pa.payment_id = p.id
WHERE p.status = 'CONFIRMED'
GROUP BY p.school_id, p.id, p.student_id, p.amount_tzs;

CREATE VIEW v_student_fee_position WITH (security_invoker = true) AS
SELECT s.school_id, s.id AS student_id,
       COALESCE((SELECT SUM(i.balance_tzs) FROM invoices i
                 WHERE i.school_id = s.school_id AND i.student_id = s.id AND i.cancelled_at IS NULL
                   AND i.balance_tzs > 0), 0) AS outstanding_tzs,
       COALESCE((SELECT SUM(u.unallocated_tzs) FROM v_payment_unallocated u
                 WHERE u.school_id = s.school_id AND u.student_id = s.id), 0) AS credit_tzs
FROM students s;

CREATE VIEW v_installment_status WITH (security_invoker = true) AS
SELECT ii.school_id, ii.invoice_id, ii.seq, ii.due_date, ii.amount_tzs,
       LEAST(ii.amount_tzs, GREATEST(0, i.paid_tzs - (SUM(ii.amount_tzs) OVER w - ii.amount_tzs))) AS covered_tzs,
       CASE
           WHEN i.paid_tzs >= SUM(ii.amount_tzs) OVER w THEN 'PAID'
           WHEN ii.due_date < CURRENT_DATE THEN 'OVERDUE'
           ELSE 'DUE'
       END AS status
FROM invoice_installments ii
JOIN invoices i ON i.school_id = ii.school_id AND i.id = ii.invoice_id
WINDOW w AS (PARTITION BY ii.school_id, ii.invoice_id ORDER BY ii.seq);

CREATE VIEW v_invoice_aging WITH (security_invoker = true) AS
SELECT i.school_id, i.id AS invoice_id, i.student_id, i.invoice_no, i.due_date, i.balance_tzs,
       CASE
           WHEN i.due_date >= CURRENT_DATE           THEN 'NOT_DUE'
           WHEN CURRENT_DATE - i.due_date <= 30      THEN '1-30'
           WHEN CURRENT_DATE - i.due_date <= 60      THEN '31-60'
           WHEN CURRENT_DATE - i.due_date <= 90      THEN '61-90'
           ELSE '90+'
       END AS aging_bucket
FROM invoices i
WHERE i.cancelled_at IS NULL AND i.balance_tzs > 0;

CREATE VIEW v_chronic_absence WITH (security_invoker = true) AS
SELECT ar.school_id, ar.student_id,
       date_trunc('week', s.session_date)::date AS week_start,
       COUNT(DISTINCT s.session_date) AS days_absent
FROM attendance_records ar
JOIN attendance_sessions s ON s.school_id = ar.school_id AND s.id = ar.session_id
WHERE ar.status = 'ABSENT' AND s.kind = 'REGISTER'
GROUP BY ar.school_id, ar.student_id, date_trunc('week', s.session_date)
HAVING COUNT(DISTINCT s.session_date) >= 3;

CREATE VIEW v_stream_occupancy WITH (security_invoker = true) AS
SELECT st.school_id, st.id AS stream_id, e.academic_year_id, st.capacity,
       COUNT(e.id) AS enrolled, st.capacity - COUNT(e.id) AS places_left
FROM streams st
JOIN enrolments e ON e.school_id = st.school_id AND e.stream_id = st.id AND e.status = 'ACTIVE'
GROUP BY st.school_id, st.id, e.academic_year_id, st.capacity;

CREATE VIEW v_sms_credit_balance WITH (security_invoker = true) AS
SELECT school_id,
       SUM(CASE kind WHEN 'DEBIT' THEN -credits ELSE credits END) AS credits_left
FROM sms_credit_transactions
GROUP BY school_id;

-- =====================================================================
-- 17. RESULTS: validation firewall, publication, amendment (SECURITY INVOKER: RLS applies)
-- =====================================================================

-- 17.1 What must be marked: every ACTIVE enrolment of the class x its subjects
--      (compulsory class subjects + combination subjects + optional subjects it has marks in)
--      x the components that apply (subject-specific components replace the level-wide ones).
--      component_id is NULL when a subject has no component at all.
CREATE FUNCTION results_scope(p_term_id UUID, p_class_id UUID)
RETURNS TABLE (enrolment_id UUID, stream_id UUID, subject_id UUID,
               component_id UUID, component_code VARCHAR, max_score NUMERIC, weight NUMERIC)
LANGUAGE sql STABLE AS $$
    WITH enr AS (
        SELECT e.id AS enrolment_id, e.stream_id, e.combination_id
        FROM enrolments e
        JOIN streams s ON s.school_id = e.school_id AND s.id = e.stream_id AND s.class_id = p_class_id
        JOIN terms   t ON t.school_id = e.school_id AND t.id = p_term_id AND t.academic_year_id = e.academic_year_id
        WHERE e.status = 'ACTIVE'
    ), subj AS (
        SELECT enr.enrolment_id, enr.stream_id, cs.subject_id
        FROM enr JOIN class_subjects cs ON cs.class_id = p_class_id AND cs.is_compulsory AND cs.deleted_at IS NULL
        UNION
        SELECT enr.enrolment_id, enr.stream_id, cb.subject_id
        FROM enr JOIN combination_subjects cb ON cb.combination_id = enr.combination_id
        UNION
        SELECT enr.enrolment_id, enr.stream_id, me.subject_id
        FROM enr
        JOIN mark_entries me ON me.enrolment_id = enr.enrolment_id AND me.deleted_at IS NULL
        JOIN assessment_components ac ON ac.id = me.component_id AND ac.term_id = p_term_id
    ), lvl AS (
        SELECT education_level_id FROM classes WHERE id = p_class_id
    )
    SELECT subj.enrolment_id, subj.stream_id, subj.subject_id, ac.id, ac.code, ac.max_score, ac.weight
    FROM subj
    LEFT JOIN assessment_components ac
           ON ac.term_id = p_term_id AND ac.deleted_at IS NULL
          AND ac.education_level_id = (SELECT education_level_id FROM lvl)
          AND (ac.subject_id = subj.subject_id
               OR (ac.subject_id IS NULL AND NOT EXISTS (
                     SELECT 1 FROM assessment_components x
                     WHERE x.term_id = p_term_id AND x.deleted_at IS NULL
                       AND x.education_level_id = ac.education_level_id
                       AND x.subject_id = subj.subject_id)))
$$;

-- 17.2 Validation firewall: one row per problem, empty = safe to publish.
--      Feeds 422 INCOMPLETE_GRADES_BLOCK (bilingual messages are built by the API from problem_code).
CREATE FUNCTION results_firewall(p_term_id UUID, p_class_id UUID)
RETURNS TABLE (problem_code TEXT, admission_no VARCHAR, student_name TEXT, subject_code VARCHAR,
               component_code VARCHAR, teacher_name TEXT, detail TEXT)
LANGUAGE sql STABLE AS $$
    WITH sc AS (SELECT * FROM results_scope(p_term_id, p_class_id)),
    who AS (
        SELECT e.id AS enrolment_id, st.admission_no, u.first_name || ' ' || u.last_name AS student_name,
               e.academic_year_id
        FROM enrolments e
        JOIN students st ON st.school_id = e.school_id AND st.id = e.student_id
        JOIN users u     ON u.school_id = st.school_id AND u.id = st.user_id
    ),
    teacher AS (
        SELECT ta.stream_id, ta.subject_id, ta.academic_year_id, tu.first_name || ' ' || tu.last_name AS teacher_name
        FROM teaching_assignments ta
        JOIN staff sf  ON sf.school_id = ta.school_id AND sf.id = ta.staff_id
        JOIN users tu  ON tu.school_id = sf.school_id AND tu.id = sf.user_id
        WHERE ta.deleted_at IS NULL
    )
    SELECT 'ALREADY_PUBLISHED'::text, NULL::varchar, NULL::text, NULL::varchar, NULL::varchar, NULL::text,
           'Results for this class and term are already published'::text
    WHERE EXISTS (SELECT 1 FROM result_publications WHERE term_id = p_term_id AND class_id = p_class_id)
    UNION ALL
    SELECT 'NO_GRADING_SCHEME', NULL, NULL, NULL, NULL, NULL, 'No active grading scheme for this level and year'
    WHERE NOT EXISTS (
        SELECT 1 FROM grading_schemes g
        JOIN classes c ON c.id = p_class_id AND g.education_level_id = c.education_level_id
        JOIN terms   t ON t.id = p_term_id AND g.academic_year_id = t.academic_year_id
        WHERE g.is_active AND g.deleted_at IS NULL)
    UNION ALL
    SELECT 'NO_STUDENTS', NULL, NULL, NULL, NULL, NULL, 'The class has no active enrolments for this term'
    WHERE NOT EXISTS (SELECT 1 FROM sc)
    UNION ALL
    SELECT 'WEIGHTS_NOT_100', NULL, NULL, s.code, NULL, NULL,
           'Component weights total ' || COALESCE(w.total, 0) || ', must be 100'
    FROM (SELECT DISTINCT subject_id FROM sc) d
    JOIN subjects s ON s.id = d.subject_id
    LEFT JOIN (SELECT x.subject_id, SUM(x.weight) AS total
               FROM (SELECT DISTINCT subject_id, component_id, weight FROM sc WHERE component_id IS NOT NULL) x
               GROUP BY x.subject_id) w ON w.subject_id = d.subject_id
    WHERE COALESCE(w.total, 0) <> 100
    UNION ALL
    SELECT CASE WHEN me.score IS NOT NULL AND me.score > sc.max_score THEN 'OUT_OF_RANGE' ELSE 'MISSING_MARK' END,
           who.admission_no, who.student_name, s.code, sc.component_code, t.teacher_name,
           CASE WHEN me.score IS NOT NULL THEN 'Score ' || me.score || ' > max ' || sc.max_score ELSE 'No mark entered' END
    FROM sc
    JOIN who      ON who.enrolment_id = sc.enrolment_id
    JOIN subjects s ON s.id = sc.subject_id
    LEFT JOIN teacher t ON t.stream_id = sc.stream_id AND t.subject_id = sc.subject_id AND t.academic_year_id = who.academic_year_id
    LEFT JOIN mark_entries me ON me.enrolment_id = sc.enrolment_id AND me.subject_id = sc.subject_id
                             AND me.component_id = sc.component_id AND me.deleted_at IS NULL
    WHERE sc.component_id IS NOT NULL
      AND (me.id IS NULL OR (me.score IS NULL AND NOT me.is_absent) OR me.score > sc.max_score)
$$;

-- 17.3 Summary row for one student from the CURRENT result versions of a publication
CREATE FUNCTION term_summary_values(p_publication_id UUID, p_enrolment_id UUID)
RETURNS TABLE (total_score NUMERIC, average_score NUMERIC, subjects_sat INTEGER, total_points INTEGER, division VARCHAR)
LANGUAGE sql STABLE AS $$
    WITH pub AS (
        SELECT p.grading_scheme_id, g.best_n_subjects
        FROM result_publications p JOIN grading_schemes g ON g.id = p.grading_scheme_id
        WHERE p.id = p_publication_id
    ), r AS (
        SELECT final_score, points,
               ROW_NUMBER() OVER (ORDER BY points, final_score DESC) AS rn
        FROM v_current_results
        WHERE publication_id = p_publication_id AND enrolment_id = p_enrolment_id
    ), agg AS (
        SELECT SUM(final_score) AS total, ROUND(AVG(final_score), 2) AS avg, COUNT(*)::int AS n,
               CASE WHEN (SELECT best_n_subjects FROM pub) IS NULL OR COUNT(*) < (SELECT best_n_subjects FROM pub)
                    THEN NULL
                    ELSE SUM(points) FILTER (WHERE rn <= (SELECT best_n_subjects FROM pub))::int END AS best
        FROM r
    )
    SELECT agg.total, agg.avg, agg.n, agg.best,
           (SELECT d.division FROM division_rules d
            WHERE d.grading_scheme_id = (SELECT grading_scheme_id FROM pub)
              AND agg.best BETWEEN d.min_points AND d.max_points)
    FROM agg
$$;

-- 17.4 Stage 2: publish one class for one term in ONE transaction.
--      Weighted final score = SUM(score / max_score * weight); absent = 0 (VERIFY with the school).
--      Grade band uses the score rounded to a whole number (NECTA bands are integers).
CREATE FUNCTION publish_results(p_term_id UUID, p_class_id UUID) RETURNS UUID
LANGUAGE plpgsql AS $$
DECLARE
    v_school   UUID := app_school_id();
    v_user     UUID := app_user_id();
    v_scheme   grading_schemes%ROWTYPE;
    v_pub      UUID;
    v_problems INTEGER;
BEGIN
    IF v_school IS NULL OR v_user IS NULL THEN
        RAISE EXCEPTION 'publish_results needs app.school_id and app.user_id' USING ERRCODE = 'P0001';
    END IF;
    PERFORM 1 FROM classes WHERE id = p_class_id FOR UPDATE;           -- one publisher at a time
    SELECT COUNT(*) INTO v_problems FROM results_firewall(p_term_id, p_class_id);
    IF v_problems > 0 THEN
        RAISE EXCEPTION 'INCOMPLETE_GRADES_BLOCK: % problem(s); call results_firewall() for the list', v_problems
            USING ERRCODE = 'SS422';
    END IF;
    SELECT g.* INTO v_scheme
    FROM grading_schemes g
    JOIN classes c ON c.id = p_class_id AND g.education_level_id = c.education_level_id
    JOIN terms   t ON t.id = p_term_id AND g.academic_year_id = t.academic_year_id
    WHERE g.is_active AND g.deleted_at IS NULL;

    INSERT INTO result_publications (school_id, term_id, class_id, grading_scheme_id, scheme_version, published_by, created_by)
    VALUES (v_school, p_term_id, p_class_id, v_scheme.id, v_scheme.version, v_user, v_user)
    RETURNING id INTO v_pub;

    INSERT INTO published_results (school_id, publication_id, enrolment_id, subject_id, final_score,
                                   letter_grade, points, subject_position, created_by)
    SELECT v_school, v_pub, f.enrolment_id, f.subject_id, f.final_score, gb.letter, gb.points,
           RANK() OVER (PARTITION BY f.subject_id ORDER BY f.final_score DESC), v_user
    FROM (
        SELECT sc.enrolment_id, sc.subject_id,
               ROUND(SUM(COALESCE(me.score, 0) / sc.max_score * sc.weight), 2) AS final_score
        FROM results_scope(p_term_id, p_class_id) sc
        JOIN mark_entries me ON me.enrolment_id = sc.enrolment_id AND me.subject_id = sc.subject_id
                            AND me.component_id = sc.component_id AND me.deleted_at IS NULL
        GROUP BY sc.enrolment_id, sc.subject_id
    ) f
    JOIN grade_bands gb ON gb.grading_scheme_id = v_scheme.id
                       AND ROUND(f.final_score) BETWEEN gb.min_score AND gb.max_score;

    INSERT INTO student_term_summaries (school_id, publication_id, enrolment_id, total_score, average_score,
                                        subjects_sat, total_points, division, class_position, created_by)
    SELECT v_school, v_pub, e.enrolment_id, t.total_score, t.average_score, t.subjects_sat, t.total_points,
           t.division, RANK() OVER (ORDER BY t.average_score DESC), v_user
    FROM (SELECT DISTINCT enrolment_id FROM published_results WHERE publication_id = v_pub) e
    CROSS JOIN LATERAL term_summary_values(v_pub, e.enrolment_id) t;

    UPDATE mark_entries me SET locked_at = now()
    FROM results_scope(p_term_id, p_class_id) sc
    WHERE me.enrolment_id = sc.enrolment_id AND me.subject_id = sc.subject_id
      AND me.component_id = sc.component_id AND me.deleted_at IS NULL;

    INSERT INTO audit_logs (school_id, actor_user_id, action, entity_type, entity_id, after_data, request_id)
    VALUES (v_school, v_user, 'PUBLISH', 'result_publications', v_pub,
            jsonb_build_object('term_id', p_term_id, 'class_id', p_class_id, 'scheme_version', v_scheme.version),
            NULLIF(current_setting('app.request_id', true), '')::uuid);
    RETURN v_pub;
END $$;

-- 17.5 Approve an amendment (maker-checker) and freeze a new version of the result and summary.
--      Positions are not re-ranked (the published order stands); this is shown on the report card.
CREATE FUNCTION amend_result(p_amendment_id UUID, p_note VARCHAR DEFAULT NULL) RETURNS UUID
LANGUAGE plpgsql AS $$
DECLARE
    v_user    UUID := app_user_id();
    v_a       result_amendments%ROWTYPE;
    v_old     published_results%ROWTYPE;
    v_scheme  UUID;
    v_band    grade_bands%ROWTYPE;
    v_new     UUID;
    v_sum     student_term_summaries%ROWTYPE;
BEGIN
    SELECT * INTO v_a FROM result_amendments WHERE id = p_amendment_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'amendment % not found', p_amendment_id USING ERRCODE = 'P0002';
    END IF;
    IF v_a.status <> 'PENDING' THEN
        RAISE EXCEPTION 'amendment is already %', v_a.status USING ERRCODE = 'P0001';
    END IF;
    IF v_user IS NULL OR v_user = v_a.requested_by THEN
        RAISE EXCEPTION 'maker-checker: the approver must be a different user from the requester'
            USING ERRCODE = 'P0001';
    END IF;
    SELECT * INTO v_old FROM published_results WHERE id = v_a.published_result_id;
    IF EXISTS (SELECT 1 FROM published_results WHERE supersedes_id = v_old.id) THEN
        RAISE EXCEPTION 'result % has already been superseded; amend the current version', v_old.id
            USING ERRCODE = 'P0001';
    END IF;

    UPDATE result_amendments
       SET status = 'APPROVED', decided_by = v_user, decided_at = now(), decision_note = p_note
     WHERE id = v_a.id;

    SELECT grading_scheme_id INTO v_scheme FROM result_publications WHERE id = v_old.publication_id;
    SELECT * INTO v_band FROM grade_bands
     WHERE grading_scheme_id = v_scheme AND ROUND(v_a.new_score) BETWEEN min_score AND max_score;

    INSERT INTO published_results (school_id, publication_id, enrolment_id, subject_id, final_score, letter_grade,
                                   points, subject_position, supersedes_id, amendment_id, created_by)
    VALUES (v_old.school_id, v_old.publication_id, v_old.enrolment_id, v_old.subject_id, v_a.new_score,
            v_band.letter, v_band.points, v_old.subject_position, v_old.id, v_a.id, v_user)
    RETURNING id INTO v_new;

    SELECT * INTO v_sum FROM v_current_term_summaries
     WHERE publication_id = v_old.publication_id AND enrolment_id = v_old.enrolment_id;
    INSERT INTO student_term_summaries (school_id, publication_id, enrolment_id, total_score, average_score,
                                        subjects_sat, total_points, division, class_position, supersedes_id, created_by)
    SELECT v_old.school_id, v_old.publication_id, v_old.enrolment_id, t.total_score, t.average_score,
           t.subjects_sat, t.total_points, t.division, v_sum.class_position, v_sum.id, v_user
    FROM term_summary_values(v_old.publication_id, v_old.enrolment_id) t;
    RETURN v_new;
END $$;

-- =====================================================================
-- 18. RESOLVERS: the only cross-tenant lookups (SECURITY DEFINER, owned by ssms_resolver).
--     Each maps an external identifier to ids; the caller then sets app.school_id and
--     reads everything else under RLS.
-- =====================================================================
CREATE FUNCTION resolve_school_by_code(p_code TEXT) RETURNS UUID
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT id FROM public.schools
    WHERE code = lower(p_code) AND status IN ('ONBOARDING','ACTIVE') AND deleted_at IS NULL
$$;

CREATE FUNCTION resolve_device(p_api_key_hash TEXT) RETURNS TABLE (school_id UUID, device_id UUID)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT d.school_id, d.id FROM public.devices d
    WHERE d.api_key_hash = p_api_key_hash AND d.status = 'ACTIVE' AND d.deleted_at IS NULL
$$;

CREATE FUNCTION resolve_gepg_bill(p_control_number TEXT DEFAULT NULL, p_bill_ref TEXT DEFAULT NULL)
RETURNS TABLE (school_id UUID, bill_id UUID)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT g.school_id, g.id FROM public.gepg_bills g
    WHERE (p_control_number IS NOT NULL AND g.control_number = p_control_number)
       OR (p_bill_ref IS NOT NULL AND g.bill_ref = p_bill_ref)
$$;

CREATE FUNCTION resolve_refresh_token(p_token_hash TEXT) RETURNS TABLE (school_id UUID, user_id UUID, family_id UUID)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    -- Returned even when revoked/expired, so the API can detect token reuse under RLS.
    SELECT r.school_id, r.user_id, r.family_id FROM public.refresh_tokens r WHERE r.token_hash = p_token_hash
$$;

CREATE FUNCTION resolve_users_by_phone(p_phone_hash BYTEA) RETURNS TABLE (school_id UUID, user_id UUID)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    -- Parent OTP login: guardians only, active accounts, active schools.
    SELECT u.school_id, u.id
    FROM public.users u
    JOIN public.guardians g ON g.school_id = u.school_id AND g.user_id = u.id AND g.deleted_at IS NULL
    JOIN public.schools s   ON s.id = u.school_id AND s.status = 'ACTIVE' AND s.deleted_at IS NULL
    WHERE u.phone_hash = p_phone_hash AND u.status = 'ACTIVE' AND u.deleted_at IS NULL
$$;

CREATE FUNCTION list_active_school_ids() RETURNS SETOF UUID
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    -- Celery beat fan-out (absence alerts, reminders): one job per school, each under its own context.
    SELECT id FROM public.schools WHERE status = 'ACTIVE' AND deleted_at IS NULL ORDER BY id
$$;

-- =====================================================================
-- 19. OWNERSHIP AND PRIVILEGES (as superuser again)
-- =====================================================================
RESET ROLE;

ALTER FUNCTION resolve_school_by_code(TEXT)       OWNER TO ssms_resolver;
ALTER FUNCTION resolve_device(TEXT)               OWNER TO ssms_resolver;
ALTER FUNCTION resolve_gepg_bill(TEXT, TEXT)      OWNER TO ssms_resolver;
ALTER FUNCTION resolve_refresh_token(TEXT)        OWNER TO ssms_resolver;
ALTER FUNCTION resolve_users_by_phone(BYTEA)      OWNER TO ssms_resolver;
ALTER FUNCTION list_active_school_ids()           OWNER TO ssms_resolver;

-- The resolver role reads only the columns the resolvers need.
GRANT USAGE ON SCHEMA public TO ssms_resolver;
GRANT SELECT (id, code, status, deleted_at)                          ON schools        TO ssms_resolver;
GRANT SELECT (school_id, id, api_key_hash, status, deleted_at)       ON devices        TO ssms_resolver;
GRANT SELECT (school_id, id, control_number, bill_ref)               ON gepg_bills     TO ssms_resolver;
GRANT SELECT (school_id, user_id, family_id, token_hash)             ON refresh_tokens TO ssms_resolver;
GRANT SELECT (school_id, id, phone_hash, status, deleted_at)         ON users          TO ssms_resolver;
GRANT SELECT (school_id, user_id, deleted_at)                        ON guardians      TO ssms_resolver;

REVOKE ALL ON FUNCTION resolve_school_by_code(TEXT), resolve_device(TEXT), resolve_gepg_bill(TEXT, TEXT),
    resolve_refresh_token(TEXT), resolve_users_by_phone(BYTEA), list_active_school_ids() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION resolve_school_by_code(TEXT), resolve_device(TEXT), resolve_gepg_bill(TEXT, TEXT),
    resolve_refresh_token(TEXT), resolve_users_by_phone(BYTEA), list_active_school_ids() TO ssms_app;

-- Runtime role: read/write business data, soft deletes only (DELETE just on housekeeping tables).
GRANT USAGE ON SCHEMA public TO ssms_app, ssms_platform, ssms_reporting;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO ssms_app;
GRANT DELETE ON otp_codes, refresh_tokens, idempotency_keys, notifications TO ssms_app;
REVOKE ALL ON platform_admins FROM ssms_app;
REVOKE INSERT, UPDATE ON roles, permissions, role_permissions, schools FROM ssms_app;
REVOKE UPDATE ON audit_logs, journals, ledger_entries, result_publications, published_results,
    student_term_summaries, payment_allocations, payment_reversals FROM ssms_app;

-- Super-admin console (BYPASSRLS): no DELETE either; schools are closed, not deleted.
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO ssms_platform;
REVOKE UPDATE ON audit_logs, journals, ledger_entries, result_publications, published_results,
    student_term_summaries, payment_allocations, payment_reversals FROM ssms_platform;

-- Reporting: read-only, one school at a time, no credentials or health data.
GRANT SELECT ON ALL TABLES IN SCHEMA public TO ssms_reporting;
REVOKE SELECT ON platform_admins, users, refresh_tokens, otp_codes, health_records, idempotency_keys FROM ssms_reporting;
