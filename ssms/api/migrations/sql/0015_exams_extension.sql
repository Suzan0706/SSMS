-- Phase 7 of the extension (design/20 §20.7): exam_candidates, taken unchanged from design/sql/extension.sql §4.
SET ROLE ssms_owner;

CREATE TABLE exam_candidates (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id        UUID        NOT NULL REFERENCES schools (id),
    exam_session_id  UUID        NOT NULL,
    enrolment_id     UUID        NOT NULL,
    candidate_no     VARCHAR(20) NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by       UUID,
    CONSTRAINT uq_exam_candidates_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_exam_candidates_student UNIQUE (school_id, exam_session_id, enrolment_id),
    CONSTRAINT uq_exam_candidates_no UNIQUE (school_id, exam_session_id, candidate_no),
    CONSTRAINT fk_ec_session FOREIGN KEY (school_id, exam_session_id) REFERENCES exam_sessions (school_id, id),
    CONSTRAINT fk_ec_enrolment FOREIGN KEY (school_id, enrolment_id) REFERENCES enrolments (school_id, id),
    CONSTRAINT fk_ec_created_by FOREIGN KEY (school_id, created_by) REFERENCES users (school_id, id)
);

ALTER TABLE exam_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE exam_candidates FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON exam_candidates USING (school_id = app_school_id()) WITH CHECK (school_id = app_school_id());
CREATE TRIGGER trg_exam_candidates_updated BEFORE UPDATE ON exam_candidates FOR EACH ROW EXECUTE FUNCTION fn_touch_updated_at();
CREATE TRIGGER trg_exam_candidates_audit AFTER INSERT OR UPDATE OR DELETE ON exam_candidates FOR EACH ROW EXECUTE FUNCTION fn_audit_row();

RESET ROLE;
GRANT SELECT, INSERT, UPDATE ON exam_candidates TO ssms_app;
GRANT SELECT ON exam_candidates TO ssms_platform, ssms_reporting;
