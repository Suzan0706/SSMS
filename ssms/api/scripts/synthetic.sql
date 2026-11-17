-- Synthetic multi-school data for performance work (NFR-05). NEVER on a real database: it runs as the superuser in
-- replica mode (no triggers, no foreign-key checks) to load fast, and fills fake people.
--   createdb ssms_perf && alembic upgrade head   (SSMS_MIGRATION_DATABASE_URL pointing at ssms_perf)
--   psql -d ssms_perf -v schools=20 -v students=1500 -v days=20 -v first=1 -f ssms/api/scripts/synthetic.sql
-- Run again with -v first=21 (and so on) to add more schools to the same database.
-- Per school: one current year with two terms, 4 classes x 4 streams, :students students each with a guardian,
-- active enrolments, :days school days of morning registers (about 9 in 10 present), a Term One invoice per student
-- and one mobile-money payment for most of them.

\set ON_ERROR_STOP 1
SELECT set_config('synth.schools', :'schools', false), set_config('synth.students', :'students', false),
       set_config('synth.days', :'days', false), set_config('synth.first', :'first', false);

SET session_replication_role = replica;

DO $$
DECLARE
    n_schools int := current_setting('synth.schools')::int;
    per int := current_setting('synth.students')::int;
    n_days int := current_setting('synth.days')::int;
    first int := current_setting('synth.first')::int;
    sch uuid; yr uuid; t1 uuid; lvl uuid; cls uuid; admin uuid;
    streams uuid[]; s int; c int; k int;
BEGIN
    FOR s IN first..first + n_schools - 1 LOOP
        sch := gen_random_uuid();
        INSERT INTO schools (id, code, name, ownership, region, district, status)
        VALUES (sch, 'synth-' || s, 'Synthetic School ' || s, 'GOVERNMENT', 'Dodoma', 'Dodoma City', 'ACTIVE');
        INSERT INTO school_settings (school_id) VALUES (sch);
        admin := gen_random_uuid();
        INSERT INTO users (id, school_id, first_name, last_name, gender, status)
        VALUES (admin, sch, 'Office', 'Admin', 'F', 'NO_LOGIN');
        yr := gen_random_uuid();
        INSERT INTO academic_years (id, school_id, name, start_date, end_date, is_current)
        VALUES (yr, sch, '2026', '2026-01-01', '2026-12-31', true);
        t1 := gen_random_uuid();
        INSERT INTO terms (id, school_id, academic_year_id, term_no, name_en, name_sw, start_date, end_date) VALUES
            (t1, sch, yr, 1, 'Term One', 'Muhula wa Kwanza', '2026-01-12', '2026-06-05'),
            (gen_random_uuid(), sch, yr, 2, 'Term Two', 'Muhula wa Pili', '2026-07-06', '2026-12-04');
        lvl := gen_random_uuid();
        INSERT INTO education_levels (id, school_id, code, name_en, name_sw, sort_order)
        VALUES (lvl, sch, 'O_LEVEL', 'Ordinary level', 'Sekondari ya kawaida', 3);
        streams := '{}';
        FOR c IN 1..4 LOOP
            cls := gen_random_uuid();
            INSERT INTO classes (id, school_id, education_level_id, code, name_en, name_sw, sort_order)
            VALUES (cls, sch, lvl, 'F' || c, 'Form ' || c, 'Kidato ' || c, c);
            FOR k IN 1..4 LOOP
                streams := streams || gen_random_uuid();
                INSERT INTO streams (id, school_id, class_id, name, capacity)
                VALUES (streams[array_length(streams, 1)], sch, cls, chr(64 + k), 200);
            END LOOP;
        END LOOP;

        CREATE TEMP TABLE kids ON COMMIT DROP AS
        SELECT g, gen_random_uuid() AS uid, gen_random_uuid() AS sid, gen_random_uuid() AS guid,
               gen_random_uuid() AS gid, streams[1 + (g % 16)] AS stream_id,
               CASE WHEN g % 2 = 0 THEN 'M' ELSE 'F' END AS gender
        FROM generate_series(1, per) g;

        INSERT INTO users (id, school_id, first_name, last_name, gender, date_of_birth, status)
        SELECT uid, sch, 'Mwanafunzi' || g, 'Familia' || (g % 97), gender, DATE '2010-01-01' + (g % 1500), 'NO_LOGIN' FROM kids;
        INSERT INTO students (id, school_id, user_id, admission_no, status, admission_date)
        SELECT sid, sch, uid, 'SY-2026-' || lpad(g::text, 5, '0'), 'ACTIVE', DATE '2026-01-12' FROM kids;
        INSERT INTO users (id, school_id, first_name, last_name, gender, status)
        SELECT guid, sch, 'Mzazi' || g, 'Familia' || (g % 97), 'M', 'NO_LOGIN' FROM kids;
        INSERT INTO guardians (id, school_id, user_id) SELECT gid, sch, guid FROM kids;
        INSERT INTO student_guardians (school_id, student_id, guardian_id, relationship, is_primary, receives_sms)
        SELECT sch, sid, gid, 'FATHER', true, true FROM kids;
        INSERT INTO enrolments (school_id, student_id, stream_id, academic_year_id, status, started_on)
        SELECT sch, sid, stream_id, yr, 'ACTIVE', DATE '2026-01-12' FROM kids;

        CREATE TEMP TABLE days ON COMMIT DROP AS
        SELECT d::date AS day FROM generate_series(DATE '2026-03-02', DATE '2026-05-29', INTERVAL '1 day') d
        WHERE extract(isodow FROM d) < 6 LIMIT n_days;
        CREATE TEMP TABLE regs ON COMMIT DROP AS
        SELECT gen_random_uuid() AS id, day, st AS stream_id FROM days CROSS JOIN unnest(streams) st;
        INSERT INTO attendance_sessions (id, school_id, session_date, kind, stream_id, taken_by)
        SELECT id, sch, day, 'REGISTER', stream_id, admin FROM regs;
        INSERT INTO attendance_records (school_id, session_id, student_id, status, captured_at, client_record_id, recorded_by)
        SELECT sch, r.id, k.sid,
               CASE WHEN random() < 0.9 THEN 'PRESENT' WHEN random() < 0.5 THEN 'LATE' ELSE 'ABSENT' END,
               r.day + time '07:45', gen_random_uuid(), admin
        FROM regs r JOIN kids k ON k.stream_id = r.stream_id;

        INSERT INTO invoices (school_id, invoice_no, student_id, term_id, issued_at, due_date, total_tzs, paid_tzs, status)
        SELECT sch, 'INV-2026-' || lpad(g::text, 6, '0'), sid, t1, TIMESTAMPTZ '2026-01-08 09:00+03', DATE '2026-02-15',
               600000, CASE WHEN g % 5 = 0 THEN 0 ELSE 600000 END, CASE WHEN g % 5 = 0 THEN 'UNPAID' ELSE 'FULLY_PAID' END
        FROM kids;
        INSERT INTO payments (school_id, student_id, channel, external_ref, amount_tzs, status, received_at, confirmed_at)
        SELECT sch, sid, 'MPESA', 'SY' || s || 'X' || g, 600000, 'CONFIRMED',
               TIMESTAMPTZ '2026-01-20 10:00+03' + (g % 60) * INTERVAL '1 day', TIMESTAMPTZ '2026-01-20 10:00+03'
        FROM kids WHERE g % 5 <> 0;
        DROP TABLE kids; DROP TABLE days; DROP TABLE regs;
    END LOOP;
END $$;

SET session_replication_role = origin;
ANALYZE;
SELECT 'schools=' || count(*) FROM schools;
SELECT 'students=' || count(*) FROM students;
SELECT 'attendance_records=' || count(*) FROM attendance_records;
