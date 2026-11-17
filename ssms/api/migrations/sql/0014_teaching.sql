-- Phase 6 of the extension (design/20 §20.7): tables taken unchanged from design/sql/extension.sql §6.
-- Lesson (period) attendance needs no table: attendance_sessions of kind LESSON already exist (design/20 §20.2).
SET ROLE ssms_owner;

CREATE TABLE study_materials (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id         UUID         NOT NULL REFERENCES schools (id),
    academic_year_id  UUID         NOT NULL,
    subject_id        UUID         NOT NULL,
    title             VARCHAR(150) NOT NULL,
    description       VARCHAR(1000),
    file_id           UUID,
    link_url          VARCHAR(500),
    published_by      UUID         NOT NULL,              -- staff member
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by        UUID,
    deleted_at        TIMESTAMPTZ,
    CONSTRAINT uq_study_materials_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_sm_year FOREIGN KEY (school_id, academic_year_id) REFERENCES academic_years (school_id, id),
    CONSTRAINT fk_sm_subject FOREIGN KEY (school_id, subject_id) REFERENCES subjects (school_id, id),
    CONSTRAINT fk_sm_file FOREIGN KEY (school_id, file_id) REFERENCES stored_files (school_id, id),
    CONSTRAINT fk_sm_staff FOREIGN KEY (school_id, published_by) REFERENCES staff (school_id, id),
    CONSTRAINT fk_sm_created_by FOREIGN KEY (school_id, created_by) REFERENCES users (school_id, id),
    CONSTRAINT ck_sm_content CHECK (num_nonnulls(file_id, link_url) = 1),
    CONSTRAINT ck_sm_link CHECK (link_url IS NULL OR link_url ~ '^https://')
);

CREATE TABLE study_material_streams (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id    UUID        NOT NULL REFERENCES schools (id),
    material_id  UUID        NOT NULL,
    stream_id    UUID        NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by   UUID,
    CONSTRAINT uq_study_material_streams_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_study_material_streams UNIQUE (school_id, material_id, stream_id),
    CONSTRAINT fk_sms_material FOREIGN KEY (school_id, material_id) REFERENCES study_materials (school_id, id),
    CONSTRAINT fk_sms_stream FOREIGN KEY (school_id, stream_id) REFERENCES streams (school_id, id),
    CONSTRAINT fk_sms_created_by FOREIGN KEY (school_id, created_by) REFERENCES users (school_id, id)
);
CREATE INDEX ix_study_material_streams_stream ON study_material_streams (school_id, stream_id);

CREATE TABLE homework (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id         UUID          NOT NULL REFERENCES schools (id),
    academic_year_id  UUID          NOT NULL,
    subject_id        UUID          NOT NULL,
    title             VARCHAR(150)  NOT NULL,
    instructions      VARCHAR(4000) NOT NULL,
    file_id           UUID,
    max_score         NUMERIC(5,1),                       -- NULL = feedback only
    due_at            TIMESTAMPTZ   NOT NULL,
    notify_parents    BOOLEAN       NOT NULL DEFAULT FALSE,
    set_by            UUID          NOT NULL,              -- staff member
    created_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
    created_by        UUID,
    deleted_at        TIMESTAMPTZ,
    CONSTRAINT uq_homework_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_hw_year FOREIGN KEY (school_id, academic_year_id) REFERENCES academic_years (school_id, id),
    CONSTRAINT fk_hw_subject FOREIGN KEY (school_id, subject_id) REFERENCES subjects (school_id, id),
    CONSTRAINT fk_hw_file FOREIGN KEY (school_id, file_id) REFERENCES stored_files (school_id, id),
    CONSTRAINT fk_hw_staff FOREIGN KEY (school_id, set_by) REFERENCES staff (school_id, id),
    CONSTRAINT fk_hw_created_by FOREIGN KEY (school_id, created_by) REFERENCES users (school_id, id),
    CONSTRAINT ck_hw_score CHECK (max_score IS NULL OR max_score > 0)
);
CREATE INDEX ix_homework_due ON homework (school_id, due_at) WHERE deleted_at IS NULL;

CREATE TABLE homework_streams (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id    UUID        NOT NULL REFERENCES schools (id),
    homework_id  UUID        NOT NULL,
    stream_id    UUID        NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by   UUID,
    CONSTRAINT uq_homework_streams_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_homework_streams UNIQUE (school_id, homework_id, stream_id),
    CONSTRAINT fk_hs_homework FOREIGN KEY (school_id, homework_id) REFERENCES homework (school_id, id),
    CONSTRAINT fk_hs_stream FOREIGN KEY (school_id, stream_id) REFERENCES streams (school_id, id),
    CONSTRAINT fk_hs_created_by FOREIGN KEY (school_id, created_by) REFERENCES users (school_id, id)
);
CREATE INDEX ix_homework_streams_stream ON homework_streams (school_id, stream_id);

CREATE TABLE homework_submissions (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id      UUID          NOT NULL REFERENCES schools (id),
    homework_id    UUID          NOT NULL,
    enrolment_id   UUID          NOT NULL,
    body           VARCHAR(8000),
    file_id        UUID,
    submitted_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    is_late        BOOLEAN       NOT NULL DEFAULT FALSE,  -- set by the service from homework.due_at
    score          NUMERIC(5,1),
    feedback       VARCHAR(2000),
    marked_by      UUID,
    marked_at      TIMESTAMPTZ,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    created_by     UUID,
    CONSTRAINT uq_homework_submissions_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_homework_submissions UNIQUE (school_id, homework_id, enrolment_id),
    CONSTRAINT fk_hsub_homework FOREIGN KEY (school_id, homework_id) REFERENCES homework (school_id, id),
    CONSTRAINT fk_hsub_enrolment FOREIGN KEY (school_id, enrolment_id) REFERENCES enrolments (school_id, id),
    CONSTRAINT fk_hsub_file FOREIGN KEY (school_id, file_id) REFERENCES stored_files (school_id, id),
    CONSTRAINT fk_hsub_marked_by FOREIGN KEY (school_id, marked_by) REFERENCES staff (school_id, id),
    CONSTRAINT fk_hsub_created_by FOREIGN KEY (school_id, created_by) REFERENCES users (school_id, id),
    CONSTRAINT ck_hsub_content CHECK (num_nonnulls(body, file_id) >= 1),
    CONSTRAINT ck_hsub_marked CHECK ((marked_by IS NULL) = (marked_at IS NULL)),
    CONSTRAINT ck_hsub_score CHECK (score IS NULL OR score >= 0)
);


DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['study_materials','study_material_streams','homework','homework_streams','homework_submissions'] LOOP
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
