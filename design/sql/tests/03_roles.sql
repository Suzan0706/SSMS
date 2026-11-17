-- =====================================================================
--  Roles of the extension (migration 0012) — run as the RUNTIME role, never as a superuser:
--      psql -v ON_ERROR_STOP=1 -d ssms_test -f design/sql/tests/03_roles.sql
--  Everything is rolled back. A block raises SQLSTATE TF001 when a rule does not hold.
-- =====================================================================
BEGIN;
SET ROLE ssms_app;

-- TEST R01 the receptionist role exists and has no permission on marks, results, money or health
SAVEPOINT test_block;
DO $$
DECLARE v_bad text;
BEGIN
    IF current_user <> 'ssms_app' THEN RAISE EXCEPTION 'R01 running as %', current_user USING ERRCODE = 'TF001'; END IF;
    IF NOT EXISTS (SELECT 1 FROM roles WHERE code = 'receptionist') THEN
        RAISE EXCEPTION 'R01 receptionist role missing' USING ERRCODE = 'TF001';
    END IF;
    SELECT string_agg(p.code, ', ') INTO v_bad
    FROM roles r JOIN role_permissions rp ON rp.role_id = r.id JOIN permissions p ON p.id = rp.permission_id
    WHERE r.code = 'receptionist'
      AND (p.code LIKE 'marks.%' OR p.code LIKE 'results.%' OR p.code LIKE 'fees.%' OR p.code LIKE 'payments.%'
           OR p.code LIKE 'finance.%' OR p.code LIKE 'health.%' OR p.code LIKE 'accounts.%' OR p.code LIKE 'invoices.%');
    IF v_bad IS NOT NULL THEN RAISE EXCEPTION 'R01 receptionist has %', v_bad USING ERRCODE = 'TF001'; END IF;
    RAISE NOTICE 'PASS R01 receptionist exists without marks, results, fees, payments, invoices, accounts or health';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST R02 the receptionist holds exactly the front-desk permissions of design/20 §20.2
SAVEPOINT test_block;
DO $$
DECLARE v_got text; v_want text := 'calendar.manage, cards.print, enrolment.manage, inquiries.manage, leave.request, students.read';
BEGIN
    SELECT string_agg(p.code, ', ' ORDER BY p.code) INTO v_got
    FROM roles r JOIN role_permissions rp ON rp.role_id = r.id JOIN permissions p ON p.id = rp.permission_id
    WHERE r.code = 'receptionist';
    IF v_got IS DISTINCT FROM v_want THEN RAISE EXCEPTION 'R02 receptionist has [%], expected [%]', v_got, v_want USING ERRCODE = 'TF001'; END IF;
    RAISE NOTICE 'PASS R02 receptionist permissions: %', v_got;
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST R03 every extension permission is granted to at least one role, and no role was left without permissions
SAVEPOINT test_block;
DO $$
DECLARE v_orphans text; v_empty text;
BEGIN
    SELECT string_agg(p.code, ', ') INTO v_orphans FROM permissions p
    WHERE p.code IN ('inquiries.manage','calendar.manage','staff_attendance.take','staff_attendance.read','leave.request',
                     'leave.decide','exams.admit_cards','accounts.record','accounts.approve','accounts.read','fines.configure',
                     'materials.publish','homework.manage','homework.submit','certificates.issue','cards.print',
                     'students.export','email.manage')
      AND NOT EXISTS (SELECT 1 FROM role_permissions rp WHERE rp.permission_id = p.id);
    IF v_orphans IS NOT NULL THEN RAISE EXCEPTION 'R03 not granted: %', v_orphans USING ERRCODE = 'TF001'; END IF;
    IF (SELECT count(*) FROM permissions WHERE code IN ('inquiries.manage','calendar.manage','staff_attendance.take',
        'staff_attendance.read','leave.request','leave.decide','exams.admit_cards','accounts.record','accounts.approve',
        'accounts.read','fines.configure','materials.publish','homework.manage','homework.submit','certificates.issue',
        'cards.print','students.export','email.manage')) <> 18 THEN
        RAISE EXCEPTION 'R03 expected 18 extension permissions' USING ERRCODE = 'TF001';
    END IF;
    SELECT string_agg(r.code, ', ') INTO v_empty FROM roles r WHERE NOT EXISTS (SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id);
    IF v_empty IS NOT NULL THEN RAISE EXCEPTION 'R03 roles without permissions: %', v_empty USING ERRCODE = 'TF001'; END IF;
    RAISE NOTICE 'PASS R03 18 extension permissions, all granted; every role has permissions';
END $$;
ROLLBACK TO SAVEPOINT test_block;

ROLLBACK;
