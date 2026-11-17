-- Phase 5 (Facilities and student life). Runs as the migration role; objects stay owned by ssms_owner.
SET ROLE ssms_owner;

-- Who allocated a bed or a seat, booked a venue, lent a book or changed a membership is audited
-- (discipline_records and health_records are audited since Phase 0).
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['hostels','hostel_rooms','accommodation_requests','hostel_allocations','buses','routes',
        'route_stops','transport_assignments','venues','venue_events','extracurricular_activities',
        'student_activities','library_books','library_loans']
    LOOP
        EXECUTE format('CREATE TRIGGER trg_%s_audit AFTER INSERT OR UPDATE OR DELETE ON %I '
                       'FOR EACH ROW EXECUTE FUNCTION fn_audit_row()', t, t);
    END LOOP;
END $$;

-- Overdue reminders look up open loans by due date.
CREATE INDEX ix_library_loans_due ON library_loans (school_id, due_date) WHERE returned_at IS NULL;

RESET ROLE;
