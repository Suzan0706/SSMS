-- Phase 5 of the extension (design/20 §20.7): tables taken unchanged from design/sql/extension.sql §2 and §3.
SET ROLE ssms_owner;

CREATE TABLE admission_inquiries (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id        UUID         NOT NULL REFERENCES schools (id),
    full_name        VARCHAR(120) NOT NULL,
    phone            VARCHAR(15),
    email            VARCHAR(254),
    class_id         UUID,                                -- class wanted
    source           VARCHAR(12)  NOT NULL DEFAULT 'WALK_IN',
    message          VARCHAR(500),
    follow_up_on     DATE,
    notes            VARCHAR(1000),
    status           VARCHAR(10)  NOT NULL DEFAULT 'OPEN',
    application_id   UUID,                                -- set when converted
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by       UUID,
    deleted_at       TIMESTAMPTZ,
    CONSTRAINT uq_admission_inquiries_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_ai_class FOREIGN KEY (school_id, class_id) REFERENCES classes (school_id, id),
    CONSTRAINT fk_ai_application FOREIGN KEY (school_id, application_id) REFERENCES enrolment_applications (school_id, id),
    CONSTRAINT fk_ai_created_by FOREIGN KEY (school_id, created_by) REFERENCES users (school_id, id),
    CONSTRAINT ck_ai_contact CHECK (phone IS NOT NULL OR email IS NOT NULL),
    CONSTRAINT ck_ai_phone CHECK (phone IS NULL OR phone ~ '^255[67][0-9]{8}$'),
    CONSTRAINT ck_ai_source CHECK (source IN ('WALK_IN','PHONE','WEBSITE','REFERRAL','OTHER')),
    CONSTRAINT ck_ai_status CHECK (status IN ('OPEN','CONVERTED','CLOSED')),
    CONSTRAINT ck_ai_converted CHECK ((status = 'CONVERTED') = (application_id IS NOT NULL))
);
CREATE INDEX ix_admission_inquiries_follow_up ON admission_inquiries (school_id, follow_up_on) WHERE status = 'OPEN' AND deleted_at IS NULL;

CREATE TABLE school_events (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id    UUID         NOT NULL REFERENCES schools (id),
    title_en     VARCHAR(120) NOT NULL,
    title_sw     VARCHAR(120) NOT NULL,
    starts_on    DATE         NOT NULL,
    ends_on      DATE         NOT NULL,
    audience     VARCHAR(10)  NOT NULL DEFAULT 'ALL',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by   UUID,
    deleted_at   TIMESTAMPTZ,
    CONSTRAINT uq_school_events_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_se_created_by FOREIGN KEY (school_id, created_by) REFERENCES users (school_id, id),
    CONSTRAINT ck_se_dates CHECK (ends_on >= starts_on),
    CONSTRAINT ck_se_audience CHECK (audience IN ('ALL','STAFF','PARENTS','STUDENTS'))
);
CREATE INDEX ix_school_events_dates ON school_events (school_id, starts_on) WHERE deleted_at IS NULL;

-- ---------------------------------------------------------------------
-- 3. Staff attendance (FR-80), leave (FR-81), period attendance (FR-82)
-- ---------------------------------------------------------------------
CREATE TABLE staff_attendance (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id   UUID        NOT NULL REFERENCES schools (id),
    staff_id    UUID        NOT NULL,
    on_date     DATE        NOT NULL,
    status      VARCHAR(8)  NOT NULL,
    source      VARCHAR(6)  NOT NULL DEFAULT 'MANUAL',
    time_in     TIME,
    time_out    TIME,
    note        VARCHAR(200),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by  UUID,
    CONSTRAINT uq_staff_attendance_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_staff_attendance_day UNIQUE (school_id, staff_id, on_date),
    CONSTRAINT fk_sa_staff FOREIGN KEY (school_id, staff_id) REFERENCES staff (school_id, id),
    CONSTRAINT fk_sa_created_by FOREIGN KEY (school_id, created_by) REFERENCES users (school_id, id),
    CONSTRAINT ck_sa_status CHECK (status IN ('PRESENT','ABSENT','LATE','ON_LEAVE')),
    CONSTRAINT ck_sa_source CHECK (source IN ('MANUAL','DEVICE')),
    CONSTRAINT ck_sa_times CHECK (time_out IS NULL OR time_in IS NULL OR time_out >= time_in)
);

CREATE TABLE leave_types (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id       UUID        NOT NULL REFERENCES schools (id),
    name_en         VARCHAR(60) NOT NULL,
    name_sw         VARCHAR(60) NOT NULL,
    applies_to      VARCHAR(7)  NOT NULL,
    days_per_year   SMALLINT,                             -- NULL = no yearly limit
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by      UUID,
    deleted_at      TIMESTAMPTZ,
    CONSTRAINT uq_leave_types_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_lt_created_by FOREIGN KEY (school_id, created_by) REFERENCES users (school_id, id),
    CONSTRAINT ck_lt_applies CHECK (applies_to IN ('STAFF','STUDENT')),
    CONSTRAINT ck_lt_days CHECK (days_per_year IS NULL OR days_per_year > 0)
);
CREATE UNIQUE INDEX uq_leave_types_name ON leave_types (school_id, applies_to, lower(name_en)) WHERE deleted_at IS NULL;

CREATE TABLE leave_requests (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id      UUID         NOT NULL REFERENCES schools (id),
    leave_type_id  UUID         NOT NULL,
    staff_id       UUID,
    student_id     UUID,
    start_date     DATE         NOT NULL,
    end_date       DATE         NOT NULL,
    period         daterange    GENERATED ALWAYS AS (daterange(start_date, end_date, '[]')) STORED,
    reason         VARCHAR(500) NOT NULL,
    status         VARCHAR(9)   NOT NULL DEFAULT 'PENDING',
    decided_by     UUID,
    decided_at     TIMESTAMPTZ,
    decision_note  VARCHAR(300),
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by     UUID,
    CONSTRAINT uq_leave_requests_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_lr_type FOREIGN KEY (school_id, leave_type_id) REFERENCES leave_types (school_id, id),
    CONSTRAINT fk_lr_staff FOREIGN KEY (school_id, staff_id) REFERENCES staff (school_id, id),
    CONSTRAINT fk_lr_student FOREIGN KEY (school_id, student_id) REFERENCES students (school_id, id),
    CONSTRAINT fk_lr_decided_by FOREIGN KEY (school_id, decided_by) REFERENCES users (school_id, id),
    CONSTRAINT fk_lr_created_by FOREIGN KEY (school_id, created_by) REFERENCES users (school_id, id),
    CONSTRAINT ck_lr_one_person CHECK (num_nonnulls(staff_id, student_id) = 1),
    CONSTRAINT ck_lr_dates CHECK (end_date >= start_date),
    CONSTRAINT ck_lr_status CHECK (status IN ('PENDING','APPROVED','REJECTED','CANCELLED')),
    CONSTRAINT ck_lr_decision CHECK ((status IN ('APPROVED','REJECTED')) = (decided_by IS NOT NULL AND decided_at IS NOT NULL)),
    CONSTRAINT ck_lr_not_self CHECK (decided_by IS NULL OR decided_by <> created_by),
    CONSTRAINT ex_lr_staff   EXCLUDE USING gist (school_id WITH =, staff_id WITH =, period WITH &&) WHERE (status = 'APPROVED' AND staff_id IS NOT NULL),
    CONSTRAINT ex_lr_student EXCLUDE USING gist (school_id WITH =, student_id WITH =, period WITH &&) WHERE (status = 'APPROVED' AND student_id IS NOT NULL)
);
CREATE INDEX ix_leave_requests_pending ON leave_requests (school_id, created_at) WHERE status = 'PENDING';

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['admission_inquiries','school_events','staff_attendance','leave_types','leave_requests'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (school_id = app_school_id()) '
                       'WITH CHECK (school_id = app_school_id())', t);
        EXECUTE format('CREATE TRIGGER trg_%s_updated BEFORE UPDATE ON %I '
                       'FOR EACH ROW EXECUTE FUNCTION fn_touch_updated_at()', t, t);
        EXECUTE format('CREATE TRIGGER trg_%s_audit AFTER INSERT OR UPDATE OR DELETE ON %I '
                       'FOR EACH ROW EXECUTE FUNCTION fn_audit_row()', t, t);
        EXECUTE format('GRANT SELECT, INSERT, UPDATE ON %I TO ssms_app', t);
        EXECUTE format('GRANT SELECT ON %I TO ssms_platform, ssms_reporting', t);
    END LOOP;
END $$;

RESET ROLE;
