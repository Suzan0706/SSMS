-- Phase 2 (Academics). Runs as the migration role; objects stay owned by ssms_owner.
SET ROLE ssms_owner;

-- A subject can leave a combination (the runtime role has no DELETE): soft delete, like every other link table.
ALTER TABLE combination_subjects ADD COLUMN deleted_at TIMESTAMPTZ;

-- results_scope ignores subjects removed from a combination.
CREATE OR REPLACE FUNCTION results_scope(p_term_id UUID, p_class_id UUID)
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
        FROM enr JOIN combination_subjects cb ON cb.combination_id = enr.combination_id AND cb.deleted_at IS NULL
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

RESET ROLE;
