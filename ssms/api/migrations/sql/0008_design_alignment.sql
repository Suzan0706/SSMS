-- Design alignment: a Registrar role, and the subjects each teacher is qualified to teach.
SET ROLE ssms_owner;

INSERT INTO roles (id, code, name_en, name_sw) VALUES
 ('00000003-0000-4000-8000-00000000000c'::uuid, 'registrar', 'Registrar', 'Msajili')
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code IN (
    'students.read','students.create','students.update','students.status','students.import','guardians.manage',
    'enrolment.manage','enrolment.validate','enrolment.decide','staff.read','academics.configure',
    'timetable.read','timetable.manage','exams.read','attendance.read','reports.read')
WHERE r.code = 'registrar'
ON CONFLICT DO NOTHING;

CREATE TABLE staff_subjects (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id   UUID        NOT NULL REFERENCES schools (id),
    staff_id    UUID        NOT NULL,
    subject_id  UUID        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by  UUID,
    deleted_at  TIMESTAMPTZ,
    CONSTRAINT uq_staff_subjects_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_ss_staff   FOREIGN KEY (school_id, staff_id)   REFERENCES staff (school_id, id),
    CONSTRAINT fk_ss_subject FOREIGN KEY (school_id, subject_id) REFERENCES subjects (school_id, id),
    CONSTRAINT fk_ss_created_by FOREIGN KEY (school_id, created_by) REFERENCES users (school_id, id)
);
CREATE UNIQUE INDEX uq_staff_subjects ON staff_subjects (school_id, staff_id, subject_id) WHERE deleted_at IS NULL;

ALTER TABLE staff_subjects ENABLE ROW LEVEL SECURITY;
ALTER TABLE staff_subjects FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON staff_subjects
    USING (school_id = app_school_id()) WITH CHECK (school_id = app_school_id());
CREATE TRIGGER trg_staff_subjects_updated BEFORE UPDATE ON staff_subjects
    FOR EACH ROW EXECUTE FUNCTION fn_touch_updated_at();
CREATE TRIGGER trg_staff_subjects_audit AFTER INSERT OR UPDATE OR DELETE ON staff_subjects
    FOR EACH ROW EXECUTE FUNCTION fn_audit_row();

RESET ROLE;
GRANT SELECT, INSERT, UPDATE ON staff_subjects TO ssms_app, ssms_platform;
GRANT SELECT ON staff_subjects TO ssms_reporting;

-- Existing schools keep working: whoever already teaches a subject counts as qualified for it.
-- Runs as the migration login (a superuser): RLS would hide every row without a school context.
INSERT INTO staff_subjects (school_id, staff_id, subject_id)
SELECT school_id, staff_id, subject_id FROM teaching_assignments WHERE deleted_at IS NULL
UNION
SELECT school_id, staff_id, subject_id FROM timetable_slots WHERE deleted_at IS NULL;
