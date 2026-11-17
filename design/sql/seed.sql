-- =====================================================================
--  SSMS sample data — two schools to prove tenant isolation
--  File: design/sql/seed.sql
--  Run AFTER schema.sql, as the owner (never as ssms_app, never as superuser):
--      psql -d ssms -c "SET ROLE ssms_owner" -f design/sql/seed.sql   (or SET ROLE inside, as below)
--  Each school block runs in its own transaction with SET LOCAL app.school_id, because
--  RLS is FORCED even for the owner.
--
--  School A  Shule ya Sekondari Mfano, Dodoma   (O-Level + A-Level PCM)   ids ...-0000000000xx
--  School B  Shule ya Msingi Upendo, Arusha     (Primary, Std I-VII)      ids ...-0000000001xx
--
--  Demo password for every account: Mfano@2026 (Argon2id hash below).
--  *_enc columns hold FAKE TEST BYTES (0xFA4E + a hash), not real ciphertext.
--  *_hash columns use an UNKEYED SHA-256 stand-in; production uses HMAC-SHA256 with a secret key.
--  Same cash receipt number 'RCT-BOOK-0001' is used in both schools (per-school idempotency, F3).
--  Same guardian phone 255754000021 exists in both schools (parent OTP resolver returns two schools).
-- =====================================================================
SET ROLE ssms_owner;

-- Readable fixed UUIDs: u(table_code, n) -> 0000000t-0000-4000-8000-00000000000n
CREATE FUNCTION pg_temp.u(t INTEGER, n INTEGER) RETURNS UUID LANGUAGE sql IMMUTABLE AS
$$ SELECT (lpad(to_hex(t), 8, '0') || '-0000-4000-8000-' || lpad(to_hex(n), 12, '0'))::uuid $$;
CREATE FUNCTION pg_temp.bidx(p TEXT) RETURNS BYTEA LANGUAGE sql IMMUTABLE AS            -- blind index stand-in
$$ SELECT sha256(convert_to('demo-only:' || p, 'UTF8')) $$;
CREATE FUNCTION pg_temp.fake_enc(p TEXT) RETURNS BYTEA LANGUAGE sql IMMUTABLE AS        -- fake ciphertext
$$ SELECT decode('fa4e', 'hex') || sha256(convert_to('fake:' || p, 'UTF8')) $$;
-- Other-income and expense accounts, their categories and the fine fee item (same as migration 0016 and onboarding).
CREATE FUNCTION pg_temp.finance_defaults(p_school UUID, p_actor UUID) RETURNS VOID LANGUAGE sql AS $$
    INSERT INTO ledger_accounts (school_id, code, name_en, name_sw, kind, created_by)
    SELECT p_school, a.code, a.en, a.sw, a.kind, p_actor
    FROM (VALUES
        ('4060', 'Fines income', 'Mapato ya faini', 'INCOME'), ('4800', 'Other income', 'Mapato mengine', 'INCOME'),
        ('4810', 'Donations', 'Michango', 'INCOME'), ('5000', 'Salaries and wages', 'Mishahara', 'EXPENSE'),
        ('5100', 'Utilities', 'Maji na umeme', 'EXPENSE'), ('5200', 'Supplies and stationery', 'Vifaa na shajara', 'EXPENSE'),
        ('5300', 'Repairs and maintenance', 'Matengenezo', 'EXPENSE'), ('5900', 'Other expenses', 'Matumizi mengine', 'EXPENSE')
    ) AS a(code, en, sw, kind)
    ON CONFLICT (school_id, code) DO NOTHING;
    INSERT INTO finance_categories (school_id, kind, name_en, name_sw, ledger_account_id, created_by)
    SELECT school_id, kind, name_en, name_sw, id, p_actor FROM ledger_accounts
    WHERE school_id = p_school AND code IN ('4800','4810','5000','5100','5200','5300','5900');
    INSERT INTO fee_items (school_id, code, name_en, name_sw, income_account_id, created_by)
    SELECT school_id, 'FINE', 'Late payment fine', 'Faini ya kuchelewa kulipa', id, p_actor FROM ledger_accounts
    WHERE school_id = p_school AND code = '4060';
$$;
CREATE FUNCTION pg_temp.pw() RETURNS TEXT LANGUAGE sql IMMUTABLE AS
$$ SELECT '$argon2id$v=19$m=65536,t=3,p=4$2JZvF1O+TsM6DnwjGpd33w$SfH+MNK3OfkgDVia5a+o99MhicDtpTVk/2+CrGeLQ5Q'::text $$;

-- =====================================================================
-- PLATFORM (global tables, no tenant context)
-- =====================================================================
INSERT INTO platform_admins (id, full_name, email, password_hash) VALUES
 (pg_temp.u(50,1), 'Platform Operator', 'ops@ssms.co.tz', pg_temp.pw());

INSERT INTO roles (id, code, name_en, name_sw) VALUES
 (pg_temp.u(3,1),  'school_admin',      'School administrator', 'Msimamizi wa shule'),
 (pg_temp.u(3,2),  'bursar',            'Bursar',               'Mhasibu'),
 (pg_temp.u(3,3),  'teacher',           'Teacher',              'Mwalimu'),
 (pg_temp.u(3,4),  'department_head',   'Head of department',   'Mkuu wa idara'),
 (pg_temp.u(3,5),  'parent',            'Parent / guardian',    'Mzazi / mlezi'),
 (pg_temp.u(3,6),  'student',           'Student',              'Mwanafunzi'),
 (pg_temp.u(3,7),  'gatekeeper',        'Gatekeeper',           'Mlinzi wa geti'),
 (pg_temp.u(3,8),  'bank_officer',      'Bank officer',         'Afisa wa benki'),
 (pg_temp.u(3,9),  'hostel_master',     'Hostel master',        'Mlezi wa bweni'),
 (pg_temp.u(3,10), 'transport_officer', 'Transport officer',    'Afisa usafiri'),
 (pg_temp.u(3,11), 'librarian',         'Librarian',            'Mkutubi')
ON CONFLICT DO NOTHING;

INSERT INTO permissions (code, module, description_en, description_sw) VALUES
 ('settings.update','settings','Update school information and settings','Kubadilisha taarifa za shule'),
 ('users.read','users','View user accounts','Kuona akaunti'),
 ('users.manage','users','Create, disable and reset accounts','Kusimamia akaunti'),
 ('roles.assign','users','Grant and revoke roles','Kutoa na kuondoa majukumu'),
 ('students.read','students','View student records','Kuona taarifa za wanafunzi'),
 ('students.create','students','Register students','Kusajili wanafunzi'),
 ('students.update','students','Update student records','Kubadilisha taarifa za wanafunzi'),
 ('students.status','students','Change student status (promote, transfer, graduate)','Kubadilisha hali ya mwanafunzi'),
 ('students.import','students','Bulk import students, guardians and staff','Kuingiza data kwa wingi'),
 ('guardians.manage','students','Manage guardians and SMS consent','Kusimamia wazazi'),
 ('enrolment.manage','enrolment','Create and follow applications','Kusimamia maombi ya usajili'),
 ('enrolment.validate','enrolment','Validate enrolment documents','Kuhakiki nyaraka za usajili'),
 ('enrolment.decide','enrolment','Approve, reject or cancel applications','Kuidhinisha au kukataa maombi'),
 ('staff.read','staff','View staff records','Kuona taarifa za watumishi'),
 ('staff.manage','staff','Manage staff, departments and designations','Kusimamia watumishi'),
 ('payroll.read','staff','View salaries','Kuona mishahara'),
 ('academics.configure','academics','Configure levels, classes, streams, subjects, rooms, grading','Kusanidi masuala ya taaluma'),
 ('timetable.read','timetable','View timetables','Kuona ratiba'),
 ('timetable.manage','timetable','Create timetable slots and generate timetables','Kupanga ratiba'),
 ('exams.read','exams','View exam timetable','Kuona ratiba ya mitihani'),
 ('exams.manage','exams','Set exams','Kupanga mitihani'),
 ('marks.enter','results','Enter and upload marks for own classes','Kuingiza alama'),
 ('results.read','results','View results and analytics','Kuona matokeo'),
 ('results.publish','results','Publish results','Kutoa matokeo'),
 ('results.amend_request','results','Request a result amendment','Kuomba marekebisho ya matokeo'),
 ('results.amend_approve','results','Approve or reject result amendments','Kuidhinisha marekebisho ya matokeo'),
 ('attendance.take','attendance','Take class registers','Kuchukua mahudhurio'),
 ('attendance.read','attendance','View attendance and reports','Kuona mahudhurio'),
 ('attendance.device','attendance','Operate gate devices and register cards','Kuendesha vifaa vya geti'),
 ('fees.configure','finance','Configure fee items, structures and discounts','Kusanidi ada'),
 ('invoices.manage','finance','Issue and cancel invoices, request control numbers','Kusimamia ankara'),
 ('payments.record','finance','Record cash and bank payments','Kurekodi malipo'),
 ('payments.reverse_request','finance','Request a payment reversal','Kuomba kubatilisha malipo'),
 ('payments.reverse_approve','finance','Approve a payment reversal','Kuidhinisha kubatilisha malipo'),
 ('payments.confirm_bank','finance','Confirm bank deposits','Kuthibitisha amana za benki'),
 ('reconciliation.run','finance','Run and resolve reconciliation','Kufanya ulinganisho wa malipo'),
 ('finance.read','finance','View finance reports and statements','Kuona ripoti za fedha'),
 ('hostel.manage','facilities','Manage hostels and allocations','Kusimamia mabweni'),
 ('transport.manage','facilities','Manage buses, routes and assignments','Kusimamia usafiri'),
 ('venues.manage','facilities','Book venues','Kusimamia kumbi'),
 ('library.manage','facilities','Manage books and loans','Kusimamia maktaba'),
 ('discipline.read','student_life','View discipline records','Kuona kumbukumbu za nidhamu'),
 ('discipline.manage','student_life','Record incidents and actions','Kurekodi matukio ya nidhamu'),
 ('activities.manage','student_life','Manage clubs and memberships','Kusimamia vilabu'),
 ('health.read','student_life','View health records','Kuona kumbukumbu za afya'),
 ('health.manage','student_life','Record health information','Kurekodi taarifa za afya'),
 ('announcements.send','communication','Send announcements and SMS','Kutuma matangazo'),
 ('sms.manage','communication','Manage templates and SMS credit','Kusimamia SMS'),
 ('reports.read','reports','View reports and dashboards','Kuona ripoti'),
 ('reports.export','reports','Export reports and compliance files','Kupakua ripoti'),
 ('audit.read','security','Read the audit log','Kusoma kumbukumbu za ukaguzi'),
 ('privacy.manage','security','Handle data subject requests','Kushughulikia maombi ya taarifa binafsi'),
 ('portal.parent','portal','Use the parent portal for own children','Kutumia lango la mzazi'),
 ('portal.student','portal','Use the student portal','Kutumia lango la mwanafunzi')
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
JOIN permissions p ON
     (r.code = 'school_admin' AND p.code NOT IN ('attendance.device','payments.confirm_bank','portal.parent','portal.student'))
  OR (r.code = 'bursar' AND p.code IN ('students.read','fees.configure','invoices.manage','payments.record',
        'payments.reverse_request','reconciliation.run','finance.read','reports.read','reports.export'))
  OR (r.code = 'teacher' AND p.code IN ('students.read','timetable.read','exams.read','marks.enter','results.read',
        'results.amend_request','attendance.take','attendance.read','enrolment.validate','discipline.manage','reports.read'))
  OR (r.code = 'department_head' AND p.code IN ('students.read','timetable.read','exams.read','exams.manage','marks.enter',
        'results.read','results.amend_request','attendance.read','staff.read','reports.read'))
  OR (r.code = 'parent' AND p.code = 'portal.parent')
  OR (r.code = 'student' AND p.code = 'portal.student')
  OR (r.code = 'gatekeeper' AND p.code = 'attendance.device')
  OR (r.code = 'bank_officer' AND p.code = 'payments.confirm_bank')
  OR (r.code = 'hostel_master' AND p.code IN ('hostel.manage','students.read'))
  OR (r.code = 'transport_officer' AND p.code IN ('transport.manage','students.read'))
  OR (r.code = 'librarian' AND p.code IN ('library.manage','students.read'))
ON CONFLICT DO NOTHING;

-- =====================================================================
-- SCHOOL A — Shule ya Sekondari Mfano, Dodoma
-- =====================================================================
BEGIN;
SELECT set_config('app.school_id', pg_temp.u(1,1)::text, true);

INSERT INTO schools (id, code, name, registration_no, ownership, district_id, status, created_by)
SELECT pg_temp.u(1,1), 'mfano-sec', 'Shule ya Sekondari Mfano', 'S.4521', 'PRIVATE', d.id, 'ACTIVE', pg_temp.u(50,1)
FROM districts d JOIN regions r ON r.id = d.region_id WHERE r.name = 'Dodoma' AND d.name = 'Dodoma City';

-- People: staff
INSERT INTO users (id, school_id, first_name, middle_name, last_name, gender, date_of_birth, phone_enc, phone_hash, phone_last4,
                   email, username, password_hash, preferred_language, status)
SELECT pg_temp.u(2,n), pg_temp.u(1,1), fn, mn, ln, g, dob::date,
       pg_temp.fake_enc(ph), pg_temp.bidx(ph), right(ph, 4), em, un, pg_temp.pw(), lang, 'ACTIVE'
FROM (VALUES
 (1, 'Halima',  'Juma', 'Mrisho',   'F', '1981-04-02', '255754000001', 'head@mfano.sc.tz',    'admin',      'sw'),
 (2, 'Rehema',  NULL,   'Kileo',    'F', '1988-01-25', '255754000002', 'bursar@mfano.sc.tz',  'bursar',     'sw'),
 (3, 'Daudi',   NULL,   'Mwita',    'M', '1987-06-11', '255754000003', 'd.mwita@mfano.sc.tz', 'tch.mwita',  'sw'),
 (4, 'Salma',   NULL,   'Abdallah', 'F', '1990-12-03', '255754000004', 's.abdallah@mfano.sc.tz','tch.salma','en'),
 (5, 'Peter',   NULL,   'Kimaro',   'M', '1984-03-29', '255754000005', 'p.kimaro@mfano.sc.tz','tch.kimaro', 'sw'),
 (6, 'Juma',    NULL,   'Omari',    'M', '1979-08-14', '255754000006', NULL,                  'gate.juma',  'sw'),
 (7, 'Grace',   NULL,   'Mushi',    'F', '1986-02-17', '255754000007', 'g.mushi@crdb.example','bank.grace', 'en'),
 (8, 'Neema',   NULL,   'Laizer',   'F', '1991-09-09', '255754000008', 'n.laizer@mfano.sc.tz','tch.laizer', 'sw'),
 (9, 'Asha',    NULL,   'Mbwana',   'F', '1985-07-21', '255754000009', 'registrar@mfano.sc.tz','registrar', 'sw')
) AS v(n, fn, mn, ln, g, dob, ph, em, un, lang);

SELECT set_config('app.user_id', pg_temp.u(2,1)::text, true);        -- seed actor for audit_logs

INSERT INTO school_settings (school_id, motto, postal_address, physical_address, phone, email, medium_of_instruction,
                             default_language, sms_sender_id, gepg_sp_code, absence_sms_cutoff, is_open_for_enrolment, created_by)
VALUES (pg_temp.u(1,1), 'Elimu ni Ufunguo', 'S.L.P. 100, Dodoma', 'Kisasa, Dodoma', '255262321000', 'info@mfano.sc.tz',
        'ENGLISH', 'sw', 'MFANO-SS', 'SP1023', '08:30', TRUE, pg_temp.u(2,1));

-- Students and guardians (user rows)
INSERT INTO users (id, school_id, first_name, middle_name, last_name, gender, date_of_birth, phone_enc, phone_hash, phone_last4,
                   username, password_hash, preferred_language, status, created_by)
SELECT pg_temp.u(2,n), pg_temp.u(1,1), fn, mn, ln, g, dob::date,
       CASE WHEN ph IS NULL THEN NULL ELSE pg_temp.fake_enc(ph) END,
       CASE WHEN ph IS NULL THEN NULL ELSE pg_temp.bidx(ph) END,
       CASE WHEN ph IS NULL THEN NULL ELSE right(ph, 4) END,
       un, CASE WHEN st = 'NO_LOGIN' OR un IS NULL THEN NULL ELSE pg_temp.pw() END, lang, st, pg_temp.u(2,1)
FROM (VALUES
 (11, 'Amani',    'John',     'Massawe', 'M', '2012-03-14', NULL,           'mf-2025-0014', 'sw', 'ACTIVE'),
 (12, 'Zawadi',   'Ally',     'Hassan',  'F', '2012-08-02', NULL,           'mf-2025-0027', 'sw', 'ACTIVE'),
 (13, 'Baraka',   'Joseph',   'Lyimo',   'M', '2012-05-19', NULL,           'mf-2025-0031', 'sw', 'ACTIVE'),
 (14, 'Rehema',   'Saidi',    'Swai',    'F', '2011-12-01', NULL,           'mf-2025-0035', 'sw', 'ACTIVE'),
 (15, 'Juma',     'Ali',      'Kombo',   'M', '2012-01-22', NULL,           'mf-2025-0040', 'sw', 'ACTIVE'),
 (16, 'Mariam',   'Ali',      'Said',    'F', '2012-07-07', NULL,           'mf-2025-0044', 'sw', 'ACTIVE'),
 (17, 'Emmanuel', 'Joseph',   'Lyimo',   'M', '2009-11-21', '255683000017', 'mf-2026-0003', 'en', 'ACTIVE'),
 (18, 'Neema',    'Joseph',   'Mollel',  'F', '2013-02-10', NULL,           NULL,           'sw', 'NO_LOGIN'),
 (21, 'John',     NULL,       'Massawe', 'M', '1978-05-12', '255754000021', NULL,           'sw', 'ACTIVE'),
 (22, 'Mwanaisha',NULL,       'Hassan',  'F', '1983-10-30', '255715000022', NULL,           'sw', 'ACTIVE'),
 (23, 'Joseph',   NULL,       'Lyimo',   'M', '1975-04-18', '255765000023', NULL,           'en', 'ACTIVE'),
 (24, 'Saidi',    NULL,       'Swai',    'M', '1980-06-06', '255786000024', NULL,           'sw', 'ACTIVE'),
 (25, 'Fatuma',   NULL,       'Kombo',   'F', '1985-03-03', '255622000025', NULL,           'sw', 'ACTIVE'),
 (26, 'Ali',      NULL,       'Said',    'M', '1982-09-15', '255713000026', NULL,           'sw', 'ACTIVE'),
 (27, 'Joseph',   NULL,       'Mollel',  'M', '1979-11-30', '255754000027', NULL,           'sw', 'ACTIVE')
) AS v(n, fn, mn, ln, g, dob, ph, un, lang, st);

INSERT INTO students (id, school_id, user_id, admission_no, birth_cert_no_enc, birth_cert_no_hash, prem_number, status, admission_date, created_by)
SELECT pg_temp.u(6,n), pg_temp.u(1,1), pg_temp.u(2,n), adm,
       pg_temp.fake_enc('BC-' || adm), pg_temp.bidx('BC-' || adm), NULL, st, ad::date, pg_temp.u(2,1)
FROM (VALUES
 (11, 'MF-2025-0014', 'ACTIVE',    '2025-01-13'),
 (12, 'MF-2025-0027', 'ACTIVE',    '2025-01-13'),
 (13, 'MF-2025-0031', 'ACTIVE',    '2025-01-13'),
 (14, 'MF-2025-0035', 'ACTIVE',    '2025-01-13'),
 (15, 'MF-2025-0040', 'ACTIVE',    '2025-01-14'),
 (16, 'MF-2025-0044', 'ACTIVE',    '2025-01-14'),
 (17, 'MF-2026-0003', 'ACTIVE',    '2026-01-06'),
 (18, 'MF-2026-0010', 'APPLICANT', NULL)
) AS v(n, adm, st, ad);

INSERT INTO student_status_history (school_id, student_id, old_status, new_status, reason, effective_date, created_by)
SELECT pg_temp.u(1,1), pg_temp.u(6,n), 'APPLICANT', 'ACTIVE', 'Enrolment confirmed', d::date, pg_temp.u(2,1)
FROM (VALUES (11,'2025-01-13'),(12,'2025-01-13'),(13,'2025-01-13'),(14,'2025-01-13'),(15,'2025-01-14'),(16,'2025-01-14'),(17,'2026-01-06')) v(n, d);

INSERT INTO guardians (id, school_id, user_id, nida_enc, nida_hash, occupation, address, created_by)
SELECT pg_temp.u(7,n), pg_temp.u(1,1), pg_temp.u(2,n),
       CASE WHEN nida IS NULL THEN NULL ELSE pg_temp.fake_enc(nida) END,
       CASE WHEN nida IS NULL THEN NULL ELSE pg_temp.bidx(nida) END, occ, addr, pg_temp.u(2,1)
FROM (VALUES
 (21, '19780512141230000123', 'Farmer',        'Kisasa, Dodoma'),
 (22, NULL,                   'Businesswoman', 'Area D, Dodoma'),
 (23, '19750418141230000777', 'Engineer',      'Njedengwa, Dodoma'),
 (24, NULL,                   'Driver',        'Makole, Dodoma'),
 (25, NULL,                   'Tailor',        'Chang''ombe, Dodoma'),
 (26, NULL,                   'Trader',        'Nkuhungu, Dodoma'),
 (27, NULL,                   'Teacher',       'Iyumbu, Dodoma')
) AS v(n, nida, occ, addr);

INSERT INTO student_guardians (school_id, student_id, guardian_id, relationship, is_primary, receives_sms, created_by)
SELECT pg_temp.u(1,1), pg_temp.u(6,s), pg_temp.u(7,g), rel, TRUE, TRUE, pg_temp.u(2,1)
FROM (VALUES (11,21,'FATHER'),(12,22,'MOTHER'),(13,23,'FATHER'),(17,23,'FATHER'),(14,24,'FATHER'),
             (15,25,'MOTHER'),(16,26,'FATHER'),(18,27,'FATHER')) v(s, g, rel);

INSERT INTO consent_records (school_id, guardian_id, purpose, granted, channel, recorded_at, created_by)
SELECT pg_temp.u(1,1), pg_temp.u(7,g), 'SMS', TRUE, 'PAPER', '2025-01-13 09:00+03', pg_temp.u(2,1)
FROM generate_series(21, 27) g;

-- Departments, designations, staff
INSERT INTO departments (id, school_id, code, name_en, name_sw, created_by) VALUES
 (pg_temp.u(9,1), pg_temp.u(1,1), 'SCI',  'Science',     'Sayansi',         pg_temp.u(2,1)),
 (pg_temp.u(9,2), pg_temp.u(1,1), 'LANG', 'Languages',   'Lugha',           pg_temp.u(2,1)),
 (pg_temp.u(9,3), pg_temp.u(1,1), 'HUM',  'Humanities',  'Masomo ya Sanaa', pg_temp.u(2,1)),
 (pg_temp.u(9,4), pg_temp.u(1,1), 'MATH', 'Mathematics', 'Hisabati',        pg_temp.u(2,1)),
 (pg_temp.u(9,5), pg_temp.u(1,1), 'ADM',  'Administration','Utawala',       pg_temp.u(2,1));

INSERT INTO designations (id, school_id, code, name_en, name_sw, created_by) VALUES
 (pg_temp.u(10,1), pg_temp.u(1,1), 'HEAD_TEACHER',    'Head teacher',      'Mkuu wa shule',     pg_temp.u(2,1)),
 (pg_temp.u(10,2), pg_temp.u(1,1), 'ACADEMIC_MASTER', 'Academic master',   'Mwalimu wa taaluma',pg_temp.u(2,1)),
 (pg_temp.u(10,3), pg_temp.u(1,1), 'SUBJECT_TEACHER', 'Subject teacher',   'Mwalimu wa somo',   pg_temp.u(2,1)),
 (pg_temp.u(10,4), pg_temp.u(1,1), 'BURSAR',          'Bursar',            'Mhasibu',           pg_temp.u(2,1)),
 (pg_temp.u(10,5), pg_temp.u(1,1), 'GATEKEEPER',      'Gatekeeper',        'Mlinzi',            pg_temp.u(2,1));

INSERT INTO staff (id, school_id, user_id, staff_no, check_no, department_id, designation_id, employment_type, employment_date,
                   salary_tzs, max_periods_per_week, created_by)
SELECT pg_temp.u(8,n), pg_temp.u(1,1), pg_temp.u(2,n), sno, chk, pg_temp.u(9,d), pg_temp.u(10,des), typ, ed::date, sal, load, pg_temp.u(2,1)
FROM (VALUES
 (1, 'MF-STF-001', '11223344', 5, 1, 'PERMANENT', '2015-07-01', 2400000.00, 10),
 (2, 'MF-STF-002', NULL,       5, 4, 'PERMANENT', '2020-02-03', 1500000.00, 1),
 (3, 'MF-STF-003', '11223355', 4, 3, 'PERMANENT', '2018-01-10', 1350000.00, 30),
 (4, 'MF-STF-004', NULL,       2, 3, 'CONTRACT',  '2019-07-01', 1100000.00, 30),
 (5, 'MF-STF-005', '11223366', 1, 2, 'PERMANENT', '2016-01-11', 1450000.00, 28),
 (6, 'MF-STF-006', NULL,       5, 5, 'CONTRACT',  '2021-03-01',  450000.00, 1),
 (8, 'MF-STF-008', NULL,       3, 3, 'CONTRACT',  '2023-01-09',  950000.00, 30)
) AS v(n, sno, chk, d, des, typ, ed, sal, load);

UPDATE departments SET head_staff_id = pg_temp.u(8,3) WHERE id = pg_temp.u(9,4);
UPDATE departments SET head_staff_id = pg_temp.u(8,5) WHERE id = pg_temp.u(9,1);

INSERT INTO staff_qualifications (school_id, staff_id, level, title, institution, year_awarded, created_by) VALUES
 (pg_temp.u(1,1), pg_temp.u(8,3), 'DEGREE',  'B.Ed. Mathematics',               'University of Dodoma',     2017, pg_temp.u(2,1)),
 (pg_temp.u(1,1), pg_temp.u(8,4), 'DEGREE',  'B.A. Ed. English and Kiswahili',  'University of Dar es Salaam', 2018, pg_temp.u(2,1)),
 (pg_temp.u(1,1), pg_temp.u(8,5), 'MASTERS', 'M.Sc. Physics Education',         'University of Dodoma',     2021, pg_temp.u(2,1)),
 (pg_temp.u(1,1), pg_temp.u(8,8), 'DIPLOMA', 'Diploma in Secondary Education',  'Butimba Teachers College', 2022, pg_temp.u(2,1));

INSERT INTO user_roles (school_id, user_id, role_id, created_by)
SELECT pg_temp.u(1,1), pg_temp.u(2,un), pg_temp.u(3,rn), pg_temp.u(2,1)
FROM (VALUES (1,1),(2,2),(3,3),(3,4),(4,3),(5,3),(8,3),(6,7),(7,8),(9,12),
             (11,6),(12,6),(13,6),(14,6),(15,6),(16,6),(17,6),
             (21,5),(22,5),(23,5),(24,5),(25,5),(26,5),(27,5)) v(un, rn);

-- One demo account per role card on the front page (2026-11-12): librarian and receptionist (a role from
-- migration 0012, so looked up by code), and a password for one parent. Real parents sign in by phone and SMS code.
INSERT INTO users (id, school_id, first_name, last_name, gender, date_of_birth, phone_enc, phone_hash, phone_last4,
                   email, username, password_hash, preferred_language, status, created_by)
SELECT pg_temp.u(2,n), pg_temp.u(1,1), fn, ln, g, dob::date,
       pg_temp.fake_enc(ph), pg_temp.bidx(ph), right(ph, 4), em, un, pg_temp.pw(), 'sw', 'ACTIVE', pg_temp.u(2,1)
FROM (VALUES
 (30, 'Zuhura', 'Mfinanga', 'F', '1989-05-14', '255754000030', 'maktaba@mfano.sc.tz',   'librarian'),
 (31, 'Lucy',   'Kessy',    'F', '1993-11-02', '255754000031', 'mapokezi@mfano.sc.tz',  'reception')
) AS v(n, fn, ln, g, dob, ph, em, un);

INSERT INTO staff (id, school_id, user_id, staff_no, employment_type, employment_date, created_by) VALUES
 (pg_temp.u(8,30), pg_temp.u(1,1), pg_temp.u(2,30), 'MF-STF-030', 'PERMANENT', '2022-01-10', pg_temp.u(2,1)),
 (pg_temp.u(8,31), pg_temp.u(1,1), pg_temp.u(2,31), 'MF-STF-031', 'CONTRACT',  '2024-02-01', pg_temp.u(2,1));

INSERT INTO user_roles (school_id, user_id, role_id, created_by)
SELECT pg_temp.u(1,1), pg_temp.u(2,30), r.id, pg_temp.u(2,1) FROM roles r WHERE r.code = 'librarian'
UNION ALL
SELECT pg_temp.u(1,1), pg_temp.u(2,31), r.id, pg_temp.u(2,1) FROM roles r WHERE r.code = 'receptionist';

-- John Massawe, Amani's father: the demo parent who signs in with a password.
UPDATE users SET username = 'mzazi', password_hash = pg_temp.pw() WHERE id = pg_temp.u(2,21);

-- Academic configuration
INSERT INTO education_levels (id, school_id, code, name_en, name_sw, sort_order, created_by) VALUES
 (pg_temp.u(11,1), pg_temp.u(1,1), 'O_LEVEL', 'Ordinary level', 'Elimu ya sekondari ya kawaida', 3, pg_temp.u(2,1)),
 (pg_temp.u(11,2), pg_temp.u(1,1), 'A_LEVEL', 'Advanced level', 'Elimu ya sekondari ya juu',     4, pg_temp.u(2,1));

INSERT INTO academic_years (id, school_id, name, start_date, end_date, is_current, created_by) VALUES
 (pg_temp.u(12,1), pg_temp.u(1,1), '2026', '2026-01-01', '2026-12-31', TRUE, pg_temp.u(2,1));

INSERT INTO terms (id, school_id, academic_year_id, term_no, name_en, name_sw, start_date, end_date, created_by) VALUES
 (pg_temp.u(13,1), pg_temp.u(1,1), pg_temp.u(12,1), 1, 'Term One', 'Muhula wa Kwanza', '2026-01-12', '2026-06-05', pg_temp.u(2,1)),
 (pg_temp.u(13,2), pg_temp.u(1,1), pg_temp.u(12,1), 2, 'Term Two', 'Muhula wa Pili',   '2026-07-06', '2026-12-04', pg_temp.u(2,1));

INSERT INTO public_holidays (school_id, holiday_date, name_en, name_sw, kind, created_by) VALUES
 (pg_temp.u(1,1), '2026-01-12', 'Zanzibar Revolution Day', 'Siku ya Mapinduzi ya Zanzibar', 'NATIONAL', pg_temp.u(2,1)),
 (pg_temp.u(1,1), '2026-04-07', 'Karume Day',              'Siku ya Karume',                'NATIONAL', pg_temp.u(2,1)),
 (pg_temp.u(1,1), '2026-04-26', 'Union Day',               'Siku ya Muungano',              'NATIONAL', pg_temp.u(2,1)),
 (pg_temp.u(1,1), '2026-07-07', 'Saba Saba',               'Sabasaba',                      'NATIONAL', pg_temp.u(2,1)),
 (pg_temp.u(1,1), '2026-12-09', 'Independence Day',        'Siku ya Uhuru',                 'NATIONAL', pg_temp.u(2,1));

-- Grading schemes (defaults: VERIFY against current NECTA regulations before launch)
INSERT INTO grading_schemes (id, school_id, education_level_id, academic_year_id, name, version, best_n_subjects, created_by) VALUES
 (pg_temp.u(14,1), pg_temp.u(1,1), pg_temp.u(11,1), pg_temp.u(12,1), 'NECTA CSEE scale', 1, 7, pg_temp.u(2,1)),
 (pg_temp.u(14,2), pg_temp.u(1,1), pg_temp.u(11,2), pg_temp.u(12,1), 'NECTA ACSEE scale', 1, 3, pg_temp.u(2,1));

INSERT INTO grade_bands (school_id, grading_scheme_id, letter, min_score, max_score, points, remark_en, remark_sw, created_by)
SELECT pg_temp.u(1,1), pg_temp.u(14,s), l, mn, mx, p, re, rs, pg_temp.u(2,1)
FROM (VALUES
 (1,'A',75,100,1,'Excellent','Bora'), (1,'B',65,74,2,'Very good','Vizuri sana'), (1,'C',45,64,3,'Good','Vizuri'),
 (1,'D',30,44,4,'Satisfactory','Inaridhisha'), (1,'F',0,29,5,'Fail','Hafifu'),
 (2,'A',80,100,1,'Excellent','Bora'), (2,'B',70,79,2,'Very good','Vizuri sana'), (2,'C',60,69,3,'Good','Vizuri'),
 (2,'D',50,59,4,'Average','Wastani'), (2,'E',40,49,5,'Satisfactory','Inaridhisha'), (2,'S',35,39,6,'Subsidiary','Ufaulu hafifu'),
 (2,'F',0,34,7,'Fail','Hafifu')
) v(s, l, mn, mx, p, re, rs);

INSERT INTO division_rules (school_id, grading_scheme_id, division, min_points, max_points, created_by)
SELECT pg_temp.u(1,1), pg_temp.u(14,s), d, mn, mx, pg_temp.u(2,1)
FROM (VALUES (1,'I',7,17),(1,'II',18,21),(1,'III',22,25),(1,'IV',26,33),(1,'0',34,35),
             (2,'I',3,9),(2,'II',10,12),(2,'III',13,17),(2,'IV',18,19),(2,'0',20,21)) v(s, d, mn, mx);

INSERT INTO subjects (id, school_id, code, necta_code, name_en, name_sw, department_id, room_type, created_by)
SELECT pg_temp.u(15,n), pg_temp.u(1,1), c, nc, ne, ns, pg_temp.u(9,d), rt, pg_temp.u(2,1)
FROM (VALUES
 (1,'CIV','011','Civics','Uraia',3,'CLASSROOM'), (2,'HIST','012','History','Historia',3,'CLASSROOM'),
 (3,'GEO','013','Geography','Jiografia',3,'CLASSROOM'), (4,'KISW','021','Kiswahili','Kiswahili',2,'CLASSROOM'),
 (5,'ENG','022','English Language','Kiingereza',2,'CLASSROOM'), (6,'PHY','031','Physics','Fizikia',1,'LABORATORY'),
 (7,'CHEM','032','Chemistry','Kemia',1,'LABORATORY'), (8,'BIO','033','Biology','Biolojia',1,'LABORATORY'),
 (9,'BMATH','041','Basic Mathematics','Hisabati za Msingi',4,'CLASSROOM'),
 (10,'GS','111','General Studies','Maarifa ya Jumla',3,'CLASSROOM'),
 (11,'PHY-A','131','Physics (Advanced)','Fizikia (Juu)',1,'LABORATORY'),
 (12,'CHEM-A','132','Chemistry (Advanced)','Kemia (Juu)',1,'LABORATORY'),
 (13,'AMATH','142','Advanced Mathematics','Hisabati ya Juu',4,'CLASSROOM')
) v(n, c, nc, ne, ns, d, rt);

INSERT INTO classes (id, school_id, education_level_id, code, name_en, name_sw, sort_order, next_class_id, created_by) VALUES
 (pg_temp.u(16,6), pg_temp.u(1,1), pg_temp.u(11,2), 'F6', 'Form Six',   'Kidato cha Sita',   16, NULL,            pg_temp.u(2,1)),
 (pg_temp.u(16,5), pg_temp.u(1,1), pg_temp.u(11,2), 'F5', 'Form Five',  'Kidato cha Tano',   15, pg_temp.u(16,6), pg_temp.u(2,1)),
 (pg_temp.u(16,4), pg_temp.u(1,1), pg_temp.u(11,1), 'F4', 'Form Four',  'Kidato cha Nne',    14, NULL,            pg_temp.u(2,1)),
 (pg_temp.u(16,3), pg_temp.u(1,1), pg_temp.u(11,1), 'F3', 'Form Three', 'Kidato cha Tatu',   13, pg_temp.u(16,4), pg_temp.u(2,1)),
 (pg_temp.u(16,2), pg_temp.u(1,1), pg_temp.u(11,1), 'F2', 'Form Two',   'Kidato cha Pili',   12, pg_temp.u(16,3), pg_temp.u(2,1)),
 (pg_temp.u(16,1), pg_temp.u(1,1), pg_temp.u(11,1), 'F1', 'Form One',   'Kidato cha Kwanza', 11, pg_temp.u(16,2), pg_temp.u(2,1));

INSERT INTO combinations (id, school_id, education_level_id, code, name_en, name_sw, created_by) VALUES
 (pg_temp.u(17,1), pg_temp.u(1,1), pg_temp.u(11,2), 'PCM', 'Physics, Chemistry and Advanced Mathematics', 'Fizikia, Kemia na Hisabati ya Juu', pg_temp.u(2,1));
INSERT INTO combination_subjects (school_id, combination_id, subject_id, created_by)
SELECT pg_temp.u(1,1), pg_temp.u(17,1), pg_temp.u(15,s), pg_temp.u(2,1) FROM (VALUES (11),(12),(13)) v(s);

INSERT INTO class_subjects (school_id, class_id, subject_id, is_compulsory, periods_per_week, created_by)
SELECT pg_temp.u(1,1), pg_temp.u(16,c), pg_temp.u(15,s), TRUE, p, pg_temp.u(2,1)
FROM (VALUES (1),(2)) cl(c)
CROSS JOIN (VALUES (1,2),(2,3),(3,3),(4,4),(5,5),(6,3),(7,3),(8,3),(9,6)) sv(s, p);
INSERT INTO class_subjects (school_id, class_id, subject_id, is_compulsory, periods_per_week, created_by) VALUES
 (pg_temp.u(1,1), pg_temp.u(16,5), pg_temp.u(15,10), TRUE, 3, pg_temp.u(2,1));

INSERT INTO rooms (id, school_id, code, name, room_type, capacity, created_by) VALUES
 (pg_temp.u(18,1), pg_temp.u(1,1), 'F2A',      'Form II A classroom',  'CLASSROOM',  45, pg_temp.u(2,1)),
 (pg_temp.u(18,2), pg_temp.u(1,1), 'F2B',      'Form II B classroom',  'CLASSROOM',  45, pg_temp.u(2,1)),
 (pg_temp.u(18,3), pg_temp.u(1,1), 'F5PCM',    'Form V PCM classroom', 'CLASSROOM',  40, pg_temp.u(2,1)),
 (pg_temp.u(18,4), pg_temp.u(1,1), 'LAB-PHY',  'Physics laboratory',   'LABORATORY', 40, pg_temp.u(2,1)),
 (pg_temp.u(18,5), pg_temp.u(1,1), 'LAB-CHEM', 'Chemistry laboratory', 'LABORATORY', 40, pg_temp.u(2,1)),
 (pg_temp.u(18,6), pg_temp.u(1,1), 'HALL',     'Assembly hall',        'HALL',      400, pg_temp.u(2,1)),
 (pg_temp.u(18,7), pg_temp.u(1,1), 'F1A',      'Form I A classroom',   'CLASSROOM',  45, pg_temp.u(2,1));

INSERT INTO equipment_items (school_id, name, created_by)
SELECT pg_temp.u(1,1), n, pg_temp.u(2,1)
FROM unnest(ARRAY['Desks','Whiteboard','Benches','Gas taps','Power points','Fume cupboard','PA system']) AS n;

INSERT INTO room_equipment (school_id, room_id, equipment_id, quantity, created_by)
SELECT pg_temp.u(1,1), pg_temp.u(18,v.room), e.id, v.quantity, pg_temp.u(2,1)
FROM (VALUES (1,'Desks',45),(1,'Whiteboard',1),(2,'Desks',45),(2,'Whiteboard',1),
             (4,'Benches',1),(4,'Gas taps',1),(4,'Power points',10),(5,'Fume cupboard',1),(6,'PA system',1)) v(room, name, quantity)
JOIN equipment_items e ON e.name = v.name;

INSERT INTO streams (id, school_id, class_id, name, capacity, home_room_id, created_by) VALUES
 (pg_temp.u(19,1), pg_temp.u(1,1), pg_temp.u(16,1), 'A',   45, pg_temp.u(18,7), pg_temp.u(2,1)),
 (pg_temp.u(19,2), pg_temp.u(1,1), pg_temp.u(16,2), 'A',   45, pg_temp.u(18,1), pg_temp.u(2,1)),
 (pg_temp.u(19,3), pg_temp.u(1,1), pg_temp.u(16,2), 'B',   45, pg_temp.u(18,2), pg_temp.u(2,1)),
 (pg_temp.u(19,4), pg_temp.u(1,1), pg_temp.u(16,5), 'PCM', 40, pg_temp.u(18,3), pg_temp.u(2,1));

INSERT INTO stream_class_teachers (school_id, stream_id, academic_year_id, staff_id, created_by) VALUES
 (pg_temp.u(1,1), pg_temp.u(19,2), pg_temp.u(12,1), pg_temp.u(8,4), pg_temp.u(2,1)),
 (pg_temp.u(1,1), pg_temp.u(19,3), pg_temp.u(12,1), pg_temp.u(8,8), pg_temp.u(2,1)),
 (pg_temp.u(1,1), pg_temp.u(19,4), pg_temp.u(12,1), pg_temp.u(8,5), pg_temp.u(2,1));

INSERT INTO teaching_assignments (school_id, academic_year_id, stream_id, subject_id, staff_id, created_by)
SELECT pg_temp.u(1,1), pg_temp.u(12,1), pg_temp.u(19,st), pg_temp.u(15,s), pg_temp.u(8,t), pg_temp.u(2,1)
FROM (VALUES (2),(3)) sv(st)
CROSS JOIN (VALUES (9,3),(5,4),(4,4),(6,5),(7,5),(8,5),(1,8),(2,8),(3,8)) a(s, t)
UNION ALL
SELECT pg_temp.u(1,1), pg_temp.u(12,1), pg_temp.u(19,4), pg_temp.u(15,s), pg_temp.u(8,t), pg_temp.u(2,1)
FROM (VALUES (13,3),(11,5),(12,5),(10,8)) a(s, t);

-- Assessment components, Term One: O-Level CA 30 + mid-term 20 + terminal 50; A-Level CA 40 + terminal 60
INSERT INTO assessment_components (school_id, term_id, education_level_id, subject_id, code, name_en, name_sw, max_score, weight, created_by) VALUES
 (pg_temp.u(1,1), pg_temp.u(13,1), pg_temp.u(11,1), NULL, 'CA',       'Continuous assessment', 'Tathmini endelevu',  100, 30, pg_temp.u(2,1)),
 (pg_temp.u(1,1), pg_temp.u(13,1), pg_temp.u(11,1), NULL, 'MIDTERM',  'Mid-term test',         'Mtihani wa katikati', 100, 20, pg_temp.u(2,1)),
 (pg_temp.u(1,1), pg_temp.u(13,1), pg_temp.u(11,1), NULL, 'TERMINAL', 'Terminal exam',         'Mtihani wa muhula',   100, 50, pg_temp.u(2,1)),
 (pg_temp.u(1,1), pg_temp.u(13,1), pg_temp.u(11,2), NULL, 'CA',       'Continuous assessment', 'Tathmini endelevu',   40, 40, pg_temp.u(2,1)),
 (pg_temp.u(1,1), pg_temp.u(13,1), pg_temp.u(11,2), NULL, 'TERMINAL', 'Terminal exam',         'Mtihani wa muhula',  100, 60, pg_temp.u(2,1));

-- Enrolment requirements and one application under review
INSERT INTO enrolment_requirements (id, school_id, education_level_id, name_en, name_sw, is_required, created_by) VALUES
 (pg_temp.u(21,1), pg_temp.u(1,1), NULL,             'Birth certificate (RITA)',      'Cheti cha kuzaliwa (RITA)',   TRUE,  pg_temp.u(2,1)),
 (pg_temp.u(21,2), pg_temp.u(1,1), NULL,             'Passport-size photograph',      'Picha ya pasipoti',           TRUE,  pg_temp.u(2,1)),
 (pg_temp.u(21,3), pg_temp.u(1,1), pg_temp.u(11,1),  'Standard VII (PSLE) results',   'Matokeo ya Darasa la Saba',   TRUE,  pg_temp.u(2,1)),
 (pg_temp.u(21,4), pg_temp.u(1,1), pg_temp.u(11,2),  'Form IV (CSEE) results',        'Matokeo ya Kidato cha Nne',   TRUE,  pg_temp.u(2,1)),
 (pg_temp.u(21,5), pg_temp.u(1,1), NULL,             'Transfer letter (if any)',      'Barua ya uhamisho (kama ipo)',FALSE, pg_temp.u(2,1));

INSERT INTO enrolment_applications (id, school_id, application_no, student_id, class_id, academic_year_id, status, submitted_at, created_by)
VALUES (pg_temp.u(22,1), pg_temp.u(1,1),
        'APP-2026-' || lpad(next_document_no(pg_temp.u(1,1), 'APPLICATION', 2026::smallint)::text, 4, '0'),
        pg_temp.u(6,18), pg_temp.u(16,1), pg_temp.u(12,1), 'UNDER_REVIEW', '2026-01-04 10:15+03', pg_temp.u(2,1));

INSERT INTO enrolment_documents (school_id, application_id, requirement_id, file_key, file_name, mime_type, size_bytes, sha256,
                                 validation_status, validated_by, validated_at, comment, created_by) VALUES
 (pg_temp.u(1,1), pg_temp.u(22,1), pg_temp.u(21,1), 'mfano-sec/enrolment/app1/bc.pdf',    'cheti.pdf', 'application/pdf', 284113,
  encode(sha256('doc-1'::bytea), 'hex'), 'VALID',   pg_temp.u(2,4), '2026-01-05 09:00+03', NULL, pg_temp.u(2,1)),
 (pg_temp.u(1,1), pg_temp.u(22,1), pg_temp.u(21,2), 'mfano-sec/enrolment/app1/photo.jpg', 'picha.jpg', 'image/jpeg',       98112,
  encode(sha256('doc-2'::bytea), 'hex'), 'INVALID', pg_temp.u(2,4), '2026-01-05 09:05+03', 'Picha haionekani vizuri / Photo is blurred', pg_temp.u(2,1)),
 (pg_temp.u(1,1), pg_temp.u(22,1), pg_temp.u(21,3), 'mfano-sec/enrolment/app1/psle.pdf',  'psle.pdf',  'application/pdf', 512330,
  encode(sha256('doc-3'::bytea), 'hex'), 'PENDING', NULL, NULL, NULL, pg_temp.u(2,1));

INSERT INTO enrolments (id, school_id, student_id, stream_id, academic_year_id, combination_id, status, started_on, created_by)
SELECT pg_temp.u(24,s), pg_temp.u(1,1), pg_temp.u(6,s), pg_temp.u(19,st), pg_temp.u(12,1),
       CASE WHEN st = 4 THEN pg_temp.u(17,1) END, 'ACTIVE', '2026-01-12', pg_temp.u(2,1)
FROM (VALUES (11,2),(12,2),(13,2),(14,2),(15,3),(16,3),(17,4)) v(s, st);

-- Timetable (Term One) and exams
INSERT INTO timetable_slots (school_id, term_id, stream_id, subject_id, staff_id, room_id, day_of_week, time_start, time_end, created_by)
SELECT pg_temp.u(1,1), pg_temp.u(13,1), pg_temp.u(19,st), pg_temp.u(15,s), pg_temp.u(8,t), pg_temp.u(18,r), d, ts::time, te::time, pg_temp.u(2,1)
FROM (VALUES
 (2,  9, 3, 1, 1, '08:00', '08:40'),   -- F2A Basic Maths, Mwita
 (2,  5, 4, 1, 1, '08:40', '09:20'),   -- F2A English, Salma
 (2,  6, 5, 4, 2, '10:20', '11:40'),   -- F2A Physics double, lab
 (3,  5, 4, 2, 1, '08:00', '08:40'),   -- F2B English, Salma (before her F2A lesson)
 (3,  9, 3, 2, 1, '08:40', '09:20'),   -- F2B Basic Maths, Mwita (after his F2A lesson)
 (4, 13, 3, 3, 1, '09:20', '10:40')    -- F5 PCM Advanced Maths double
) v(st, s, t, r, d, ts, te);

INSERT INTO exam_sessions (id, school_id, term_id, name_en, name_sw, kind, start_date, end_date, created_by) VALUES
 (pg_temp.u(26,1), pg_temp.u(1,1), pg_temp.u(13,1), 'Mid-term examinations March 2026', 'Mitihani ya katikati Machi 2026',
  'MIDTERM', '2026-03-16', '2026-03-20', pg_temp.u(2,1));
INSERT INTO exams (school_id, exam_session_id, class_id, subject_id, room_id, exam_date, time_start, time_end, created_by) VALUES
 (pg_temp.u(1,1), pg_temp.u(26,1), pg_temp.u(16,2), pg_temp.u(15,9), pg_temp.u(18,6), '2026-03-16', '08:00', '10:30', pg_temp.u(2,1)),
 (pg_temp.u(1,1), pg_temp.u(26,1), pg_temp.u(16,2), pg_temp.u(15,5), pg_temp.u(18,6), '2026-03-16', '11:00', '13:00', pg_temp.u(2,1)),
 (pg_temp.u(1,1), pg_temp.u(26,1), pg_temp.u(16,2), pg_temp.u(15,6), pg_temp.u(18,4), '2026-03-17', '08:00', '10:30', pg_temp.u(2,1));

-- Marks: every Form II student, every compulsory subject, every component (deterministic scores 35..95)
INSERT INTO mark_entries (school_id, enrolment_id, subject_id, component_id, score, entered_by, client_updated_at, created_by)
SELECT e.school_id, e.id, cs.subject_id, ac.id,
       35 + abs(hashtext(e.id::text || cs.subject_id::text || ac.code)) % 61,
       sf.user_id, '2026-05-28 15:00+03', sf.user_id
FROM enrolments e
JOIN streams s               ON s.id = e.stream_id AND s.class_id = pg_temp.u(16,2)
JOIN class_subjects cs       ON cs.class_id = s.class_id AND cs.is_compulsory
JOIN assessment_components ac ON ac.term_id = pg_temp.u(13,1) AND ac.education_level_id = pg_temp.u(11,1) AND ac.subject_id IS NULL
JOIN teaching_assignments ta ON ta.stream_id = e.stream_id AND ta.subject_id = cs.subject_id
JOIN staff sf                ON sf.id = ta.staff_id;

-- Form V PCM: only CA entered so far (the validation firewall will block publishing)
INSERT INTO mark_entries (school_id, enrolment_id, subject_id, component_id, score, entered_by, created_by)
SELECT pg_temp.u(1,1), pg_temp.u(24,17), pg_temp.u(15,s), ac.id, sc, pg_temp.u(2,5), pg_temp.u(2,5)
FROM (VALUES (11,31),(12,28),(13,36)) v(s, sc)
JOIN assessment_components ac ON ac.term_id = pg_temp.u(13,1) AND ac.education_level_id = pg_temp.u(11,2) AND ac.code = 'CA';

-- Stage 2: publish Form II Term One (runs the firewall, freezes results, locks the marks)
SELECT publish_results(pg_temp.u(13,1), pg_temp.u(16,2));

INSERT INTO report_card_comments (school_id, publication_id, enrolment_id, class_teacher_comment, head_teacher_comment, created_by)
SELECT p.school_id, p.id, pg_temp.u(24,11), 'Amejitahidi sana. Aongeze bidii kwenye Fizikia.', 'Hongera, endelea hivyo.', pg_temp.u(2,4)
FROM result_publications p WHERE p.class_id = pg_temp.u(16,2) AND p.term_id = pg_temp.u(13,1);

-- Teachers are qualified for what they teach
INSERT INTO staff_subjects (school_id, staff_id, subject_id)
SELECT school_id, staff_id, subject_id FROM teaching_assignments
UNION
SELECT school_id, staff_id, subject_id FROM timetable_slots;

-- Attendance: devices, cards, registers for the week of 2 March 2026, gate taps
INSERT INTO devices (id, school_id, name, kind, api_key_hash, location, status, last_seen_at, created_by) VALUES
 (pg_temp.u(30,1), pg_temp.u(1,1), 'Main gate reader', 'RFID_READER', encode(sha256('demo-device-key-mfano-gate'::bytea), 'hex'),
  'Main gate', 'ACTIVE', '2026-03-02 07:45+03', pg_temp.u(2,1));
INSERT INTO rfid_cards (school_id, student_id, token_hash, kind, created_by)
SELECT pg_temp.u(1,1), pg_temp.u(6,s), encode(sha256(convert_to('card-' || s, 'UTF8')), 'hex'), 'RFID', pg_temp.u(2,1)
FROM generate_series(11, 16) s;

INSERT INTO attendance_sessions (id, school_id, session_date, kind, stream_id, taken_by, opened_at, closed_at, created_by)
SELECT pg_temp.u(32, d), pg_temp.u(1,1), ('2026-03-01'::date + d), 'REGISTER', pg_temp.u(19,2), pg_temp.u(2,4),
       ('2026-03-01'::date + d) + time '07:40', ('2026-03-01'::date + d) + time '08:10', pg_temp.u(2,4)
FROM generate_series(1, 5) d;
INSERT INTO attendance_sessions (id, school_id, session_date, kind, created_by) VALUES
 (pg_temp.u(32,10), pg_temp.u(1,1), '2026-03-02', 'GATE', pg_temp.u(2,6));

INSERT INTO attendance_records (school_id, session_id, student_id, status, source, captured_at, client_record_id, recorded_by, created_by)
SELECT pg_temp.u(1,1), pg_temp.u(32,d), pg_temp.u(6,s),
       CASE WHEN s = 13 AND d <= 3 THEN 'ABSENT' WHEN s = 14 AND d = 2 THEN 'LATE' ELSE 'PRESENT' END,
       'MANUAL', ('2026-03-01'::date + d) + time '07:50', gen_random_uuid(), pg_temp.u(2,4), pg_temp.u(2,4)
FROM generate_series(1, 5) d CROSS JOIN (VALUES (11),(12),(13),(14)) st(s);

INSERT INTO attendance_records (school_id, session_id, student_id, status, source, device_id, captured_at, client_record_id, created_by)
SELECT pg_temp.u(1,1), pg_temp.u(32,10), pg_temp.u(6,s), 'PRESENT', 'RFID', pg_temp.u(30,1),
       timestamptz '2026-03-02 07:20+03' + (s || ' minutes')::interval, gen_random_uuid(), pg_temp.u(2,6)
FROM (VALUES (11),(12),(14),(15),(16)) st(s);

-- Communication: templates, SMS log, credit, absence alert
INSERT INTO message_templates (school_id, key, language, body, created_by) VALUES
 (pg_temp.u(1,1), 'absence_alert',  'sw', '{school}: {student} hakufika shuleni leo {date}. Tafadhali wasiliana na mwalimu wa darasa.', pg_temp.u(2,1)),
 (pg_temp.u(1,1), 'absence_alert',  'en', '{school}: {student} was absent from school today {date}. Please contact the class teacher.', pg_temp.u(2,1)),
 (pg_temp.u(1,1), 'payment_receipt','sw', '{school}: Tumepokea TZS {amount} kwa {student}. Risiti {receipt_no}. Salio TZS {balance}.', pg_temp.u(2,1)),
 (pg_temp.u(1,1), 'payment_receipt','en', '{school}: Received TZS {amount} for {student}. Receipt {receipt_no}. Balance TZS {balance}.', pg_temp.u(2,1)),
 (pg_temp.u(1,1), 'results_ready',  'sw', '{school}: Matokeo ya {term} ya {student} yametoka. Ingia kwenye mfumo kuona ripoti.', pg_temp.u(2,1)),
 (pg_temp.u(1,1), 'results_ready',  'en', '{school}: {student}''s {term} results are out. Log in to see the report card.', pg_temp.u(2,1)),
 (pg_temp.u(1,1), 'invoice_issued', 'sw', '{school}: Ankara {invoice_no} TZS {amount}. Namba ya malipo {control_no}. Mwisho {due}.', pg_temp.u(2,1)),
 (pg_temp.u(1,1), 'invoice_issued', 'en', '{school}: Invoice {invoice_no} TZS {amount}. Control number {control_no}. Due {due}.', pg_temp.u(2,1)),
 (pg_temp.u(1,1), 'otp_login',      'sw', 'Namba yako ya kuingia SSMS ni {code}. Inaisha baada ya dakika 5. Usimpe mtu.', pg_temp.u(2,1)),
 (pg_temp.u(1,1), 'otp_login',      'en', 'Your SSMS login code is {code}. It expires in 5 minutes. Do not share it.', pg_temp.u(2,1));

INSERT INTO sms_credit_transactions (school_id, kind, credits, note, created_by) VALUES
 (pg_temp.u(1,1), 'TOPUP', 1000, 'Initial SMS bundle', pg_temp.u(2,1));

INSERT INTO sms_messages (id, school_id, to_user_id, to_phone_enc, to_phone_last4, template_key, language, body, segments, provider,
                          provider_message_id, status, cost_credits, idempotency_key, related_entity, related_id, queued_at, sent_at, delivered_at)
VALUES
 (pg_temp.u(48,1), pg_temp.u(1,1), pg_temp.u(2,23), pg_temp.fake_enc('255765000023'), '0023', 'absence_alert', 'en',
  'Shule ya Sekondari Mfano: Baraka Lyimo was absent from school today 02/03/2026. Please contact the class teacher.',
  1, 'BEEM', 'beem-000001', 'DELIVERED', 1, 'absence:' || pg_temp.u(6,13) || ':2026-03-02', 'students', pg_temp.u(6,13),
  '2026-03-02 08:30+03', '2026-03-02 08:30+03', '2026-03-02 08:31+03'),
 (pg_temp.u(48,2), pg_temp.u(1,1), pg_temp.u(2,23), pg_temp.fake_enc('255765000023'), '0023', 'absence_alert', 'en',
  'Shule ya Sekondari Mfano: Baraka Lyimo was absent from school today 03/03/2026. Please contact the class teacher.',
  1, 'BEEM', 'beem-000002', 'DELIVERED', 1, 'absence:' || pg_temp.u(6,13) || ':2026-03-03', 'students', pg_temp.u(6,13),
  '2026-03-03 08:30+03', '2026-03-03 08:30+03', '2026-03-03 08:32+03');

INSERT INTO absence_alerts (school_id, student_id, absence_date, sms_message_id, created_by) VALUES
 (pg_temp.u(1,1), pg_temp.u(6,13), '2026-03-02', pg_temp.u(48,1), pg_temp.u(2,1)),
 (pg_temp.u(1,1), pg_temp.u(6,13), '2026-03-03', pg_temp.u(48,2), pg_temp.u(2,1));

INSERT INTO sms_credit_transactions (school_id, kind, credits, sms_message_id, created_by)
SELECT pg_temp.u(1,1), 'DEBIT', 1, id, pg_temp.u(2,1) FROM sms_messages WHERE school_id = pg_temp.u(1,1);

INSERT INTO announcements (school_id, title, body, language, audience, send_sms, publish_at, created_by) VALUES
 (pg_temp.u(1,1), 'Mkutano wa wazazi', 'Mkutano wa wazazi utafanyika Jumamosi 14/03/2026 saa 4 asubuhi ukumbini.', 'sw',
  'PARENTS', TRUE, '2026-03-05 10:00+03', pg_temp.u(2,1));

INSERT INTO notifications (school_id, user_id, kind, title, body, link, created_by) VALUES
 (pg_temp.u(1,1), pg_temp.u(2,21), 'RESULTS_READY', 'Matokeo yametoka', 'Matokeo ya Muhula wa Kwanza ya Amani yametoka.', '/parent/results', pg_temp.u(2,1));

-- Finance: ledger accounts, fee items, structure, discount
INSERT INTO ledger_accounts (id, school_id, code, name_en, name_sw, kind, created_by)
SELECT pg_temp.u(33,n), pg_temp.u(1,1), c, ne, ns, k, pg_temp.u(2,1)
FROM (VALUES
 (1, '1000', 'Cash on hand',              'Fedha taslimu',               'ASSET'),
 (2, '1100', 'GePG clearing',             'Akaunti ya GePG',             'ASSET'),
 (3, '1110', 'Mobile money clearing',     'Akaunti ya pesa za simu',     'ASSET'),
 (4, '1200', 'Bank',                      'Benki',                       'ASSET'),
 (5, '1300', 'Fees receivable',           'Ada zinazodaiwa',             'ASSET'),
 (6, '2100', 'Student credit (prepaid)',  'Malipo ya ziada ya wanafunzi','LIABILITY'),
 (7, '4000', 'Tuition income',            'Mapato ya karo',              'INCOME'),
 (8, '4010', 'Meals income',              'Mapato ya chakula',           'INCOME'),
 (9, '4020', 'Examination fee income',    'Mapato ya ada ya mitihani',   'INCOME'),
 (10,'4030', 'Development levy income',   'Mapato ya ada ya maendeleo',  'INCOME'),
 (11,'4040', 'Transport income',          'Mapato ya usafiri',           'INCOME'),
 (12,'4050', 'Boarding income',           'Mapato ya bweni',             'INCOME'),
 (13,'4900', 'Discounts allowed',         'Punguzo zilizotolewa',        'EXPENSE')
) v(n, c, ne, ns, k);

INSERT INTO fee_items (id, school_id, code, name_en, name_sw, gfs_code, income_account_id, created_by)
SELECT pg_temp.u(34,n), pg_temp.u(1,1), c, ne, ns, gfs, pg_temp.u(33,a), pg_temp.u(2,1)
FROM (VALUES
 (1,'TUITION',    'Tuition fee',       'Karo',              '142201', 7),
 (2,'MEALS',      'Meals',             'Chakula',           '142202', 8),
 (3,'EXAMINATION','Examination fee',   'Ada ya mitihani',   '142203', 9),
 (4,'DEVELOPMENT','Development levy',  'Ada ya maendeleo',  '142204', 10),
 (5,'TRANSPORT',  'Transport',         'Usafiri',           '142205', 11),
 (6,'BOARDING',   'Boarding',          'Bweni',             '142206', 12)
) v(n, c, ne, ns, gfs, a);
SELECT pg_temp.finance_defaults(pg_temp.u(1,1), pg_temp.u(2,1));

INSERT INTO fee_structures (id, school_id, academic_year_id, class_id, name, status, approved_by, approved_at, created_by) VALUES
 (pg_temp.u(35,1), pg_temp.u(1,1), pg_temp.u(12,1), pg_temp.u(16,2), 'Form II 2026', 'APPROVED', pg_temp.u(2,1), '2025-12-01 10:00+03', pg_temp.u(2,2));
INSERT INTO fee_structure_lines (school_id, fee_structure_id, fee_item_id, term_id, amount_tzs, created_by)
SELECT pg_temp.u(1,1), pg_temp.u(35,1), pg_temp.u(34,i), t, a, pg_temp.u(2,2)
FROM (VALUES (1, pg_temp.u(13,1), 450000.00), (2, pg_temp.u(13,1), 150000.00), (3, pg_temp.u(13,1), 30000.00),
             (4, NULL::uuid,       50000.00),
             (1, pg_temp.u(13,2), 450000.00), (2, pg_temp.u(13,2), 150000.00), (3, pg_temp.u(13,2), 30000.00)) v(i, t, a);

INSERT INTO discount_rules (id, school_id, code, name_en, name_sw, kind, percent, created_by) VALUES
 (pg_temp.u(49,1), pg_temp.u(1,1), 'SIBLING10', 'Sibling discount 10% of tuition', 'Punguzo la ndugu 10% ya karo', 'SIBLING', 10, pg_temp.u(2,1));
INSERT INTO student_discounts (school_id, student_id, discount_rule_id, academic_year_id, reason, approved_by, created_by) VALUES
 (pg_temp.u(1,1), pg_temp.u(6,13), pg_temp.u(49,1), pg_temp.u(12,1), 'Brother Emmanuel Lyimo is in Form V', pg_temp.u(2,1), pg_temp.u(2,2));

-- Invoices for Term One (Form II), numbered by next_document_no
INSERT INTO invoices (id, school_id, invoice_no, student_id, term_id, issued_at, due_date, created_by)
SELECT pg_temp.u(36,s), pg_temp.u(1,1),
       'INV-2026-' || lpad(next_document_no(pg_temp.u(1,1), 'INVOICE', 2026::smallint)::text, 6, '0'),
       pg_temp.u(6,s), pg_temp.u(13,1), '2026-01-08 12:00+03', '2026-02-15', pg_temp.u(2,2)
FROM generate_series(11, 16) s ORDER BY s;

INSERT INTO invoice_lines (school_id, invoice_id, fee_item_id, kind, description, amount_tzs, created_by)
SELECT pg_temp.u(1,1), pg_temp.u(36,s), fsl.fee_item_id, 'CHARGE', fi.name_en || ' - Term One', fsl.amount_tzs, pg_temp.u(2,2)
FROM generate_series(11, 16) s
JOIN fee_structure_lines fsl ON fsl.fee_structure_id = pg_temp.u(35,1) AND (fsl.term_id = pg_temp.u(13,1) OR fsl.term_id IS NULL)
JOIN fee_items fi ON fi.id = fsl.fee_item_id;
INSERT INTO invoice_lines (school_id, invoice_id, fee_item_id, kind, description, amount_tzs, discount_rule_id, created_by) VALUES
 (pg_temp.u(1,1), pg_temp.u(36,13), pg_temp.u(34,1), 'DISCOUNT', 'Sibling discount 10% of tuition', 45000.00, pg_temp.u(49,1), pg_temp.u(2,2));

INSERT INTO invoice_installments (school_id, invoice_id, seq, due_date, amount_tzs, created_by) VALUES
 (pg_temp.u(1,1), pg_temp.u(36,14), 1, '2026-02-15', 300000.00, pg_temp.u(2,2)),
 (pg_temp.u(1,1), pg_temp.u(36,14), 2, '2026-04-15', 200000.00, pg_temp.u(2,2)),
 (pg_temp.u(1,1), pg_temp.u(36,14), 3, '2026-05-31', 180000.00, pg_temp.u(2,2));

INSERT INTO gepg_bills (id, school_id, invoice_id, bill_ref, control_number, amount_tzs, status, expires_at, request_payload,
                        response_payload, signature_verified, requested_at, issued_at, created_by) VALUES
 (pg_temp.u(37,1), pg_temp.u(1,1), pg_temp.u(36,11), 'mfano-sec-2026-000001', '994120000001', 680000.00, 'ISSUED', '2026-03-31 23:59+03',
  '{"BillId":"mfano-sec-2026-000001","BillAmt":"680000.00","Ccy":"TZS"}', '{"PayCntrNum":"994120000001","TrxSts":"GS"}', TRUE,
  '2026-01-08 12:01+03', '2026-01-08 12:02+03', pg_temp.u(2,2)),
 (pg_temp.u(37,2), pg_temp.u(1,1), pg_temp.u(36,12), 'mfano-sec-2026-000002', '994120000002', 680000.00, 'ISSUED', '2026-03-31 23:59+03',
  '{"BillId":"mfano-sec-2026-000002","BillAmt":"680000.00","Ccy":"TZS"}', '{"PayCntrNum":"994120000002","TrxSts":"GS"}', TRUE,
  '2026-01-08 12:01+03', '2026-01-08 12:02+03', pg_temp.u(2,2));

-- Payments (confirmed ones are allocated oldest-due-first by the service; here explicitly)
INSERT INTO payments (id, school_id, student_id, channel, external_ref, amount_tzs, payer_name, payer_phone_hash, payer_phone_last4,
                      gepg_bill_id, status, received_at, confirmed_at, recorded_by, raw_payload, created_by)
SELECT pg_temp.u(38,n), pg_temp.u(1,1), pg_temp.u(6,s), ch, ref, amt, payer, pg_temp.bidx(ph), right(ph, 4),
       CASE WHEN ch = 'GEPG' THEN pg_temp.u(37,1) END, st, rcv::timestamptz,
       CASE WHEN st <> 'PENDING' THEN rcv::timestamptz END,
       CASE WHEN ch IN ('CASH','BANK') THEN pg_temp.u(2,2) END,
       jsonb_build_object('channel', ch, 'ref', ref, 'payer_phone', '****' || right(ph, 4)), pg_temp.u(2,2)
FROM (VALUES
 (1, 11, 'GEPG',     'PSP-77812345',        400000.00, 'John Massawe',     '255754000021', 'CONFIRMED', '2026-01-20 14:02+03'),
 (2, 11, 'MPESA',    'QKJ7H2LM9P',          280000.00, 'John Massawe',     '255754000021', 'CONFIRMED', '2026-01-25 09:12+03'),
 (3, 12, 'CASH',     'RCT-BOOK-0001',       200000.00, 'Mwanaisha Hassan', '255715000022', 'CONFIRMED', '2026-01-12 09:30+03'),
 (4, 13, 'MPESA',    'QKX1ABCD22',          100000.00, 'Joseph Lyimo',     '255765000023', 'CONFIRMED', '2026-01-15 16:45+03'),
 (5, 13, 'TIGOPESA', 'TP260203.1022.C88',   300000.00, 'Joseph Lyimo',     '255765000023', 'CONFIRMED', '2026-02-03 10:22+03'),
 (6, 14, 'BANK',     'CRDB-2026-77881',     300000.00, 'Saidi Swai',       '255786000024', 'CONFIRMED', '2026-02-10 11:00+03'),
 (7, 16, 'AIRTEL',   'MP260130.0912.A11',   700000.00, 'Ali Said',         '255713000026', 'CONFIRMED', '2026-01-30 09:12+03'),
 (8, 15, 'HALOPESA', 'HP-2026-000045',       50000.00, 'Fatuma Kombo',     '255622000025', 'PENDING',   '2026-02-14 18:40+03')
) v(n, s, ch, ref, amt, payer, ph, st, rcv);

INSERT INTO payment_allocations (school_id, payment_id, invoice_id, amount_tzs, created_by)
SELECT pg_temp.u(1,1), pg_temp.u(38,p), pg_temp.u(36,i), a, pg_temp.u(2,2)
FROM (VALUES (1,11,400000.00),(2,11,280000.00),(3,12,200000.00),(4,13,100000.00),(5,13,300000.00),(6,14,300000.00),(7,16,680000.00)) v(p, i, a);

INSERT INTO bank_deposit_confirmations (school_id, bank_reference, deposit_date, amount_tzs, student_id, depositor_name, status,
                                        submitted_by, confirmed_by, confirmed_at, payment_id, created_by) VALUES
 (pg_temp.u(1,1), 'CRDB-2026-77881', '2026-02-10', 300000.00, pg_temp.u(6,14), 'Saidi Swai', 'MATCHED',
  pg_temp.u(2,2), pg_temp.u(2,7), '2026-02-10 15:00+03', pg_temp.u(38,6), pg_temp.u(2,2));

-- Reversal of payment 4 (paid to the wrong student): maker = bursar, checker = head teacher
INSERT INTO payment_reversals (school_id, payment_id, reason, reversed_by, approved_by, created_by) VALUES
 (pg_temp.u(1,1), pg_temp.u(38,4), 'Paid with the wrong student reference; refunded to payer', pg_temp.u(2,2), pg_temp.u(2,1), pg_temp.u(2,2));

-- Receipts for confirmed payments (gapless per school)
INSERT INTO receipts (school_id, receipt_no, payment_id, issued_at, pdf_file_key, sms_sent_at, created_by)
SELECT pg_temp.u(1,1), 'RCT-2026-' || lpad(next_document_no(pg_temp.u(1,1), 'RECEIPT', 2026::smallint)::text, 6, '0'),
       p.id, p.confirmed_at, 'mfano-sec/receipts/' || p.external_ref || '.pdf', p.confirmed_at + interval '1 minute', pg_temp.u(2,2)
FROM payments p WHERE p.school_id = pg_temp.u(1,1) AND p.confirmed_at IS NOT NULL ORDER BY p.confirmed_at;

-- Double-entry journals: invoices (Dr receivable + Dr discounts / Cr income per fee item)
INSERT INTO journals (id, school_id, journal_no, posted_at, source_type, source_id, memo, posted_by, created_by)
SELECT gen_random_uuid(), i.school_id, 'JNL-2026-' || lpad(next_document_no(i.school_id, 'JOURNAL', 2026::smallint)::text, 6, '0'),
       i.issued_at, 'INVOICE', i.id, 'Invoice ' || i.invoice_no, pg_temp.u(2,2), pg_temp.u(2,2)
FROM invoices i WHERE i.school_id = pg_temp.u(1,1) ORDER BY i.invoice_no;

INSERT INTO ledger_entries (school_id, journal_id, account_id, student_id, debit_tzs, credit_tzs, created_by)
SELECT j.school_id, j.id, pg_temp.u(33,5), i.student_id, i.total_tzs, 0, pg_temp.u(2,2)
FROM journals j JOIN invoices i ON i.id = j.source_id WHERE j.source_type = 'INVOICE'
UNION ALL
SELECT j.school_id, j.id, pg_temp.u(33,13), NULL, SUM(l.amount_tzs), 0, pg_temp.u(2,2)
FROM journals j JOIN invoice_lines l ON l.invoice_id = j.source_id AND l.kind = 'DISCOUNT'
WHERE j.source_type = 'INVOICE' GROUP BY j.school_id, j.id
UNION ALL
SELECT j.school_id, j.id, fi.income_account_id, NULL, 0, SUM(l.amount_tzs), pg_temp.u(2,2)
FROM journals j JOIN invoice_lines l ON l.invoice_id = j.source_id AND l.kind = 'CHARGE'
JOIN fee_items fi ON fi.id = l.fee_item_id
WHERE j.source_type = 'INVOICE' GROUP BY j.school_id, j.id, fi.income_account_id;

-- Payments (Dr clearing account / Cr receivable for the allocated part, Cr student credit for the rest)
INSERT INTO journals (id, school_id, journal_no, posted_at, source_type, source_id, memo, posted_by, created_by)
SELECT gen_random_uuid(), p.school_id, 'JNL-2026-' || lpad(next_document_no(p.school_id, 'JOURNAL', 2026::smallint)::text, 6, '0'),
       p.confirmed_at, 'PAYMENT', p.id, 'Payment ' || p.channel || ' ' || p.external_ref, pg_temp.u(2,2), pg_temp.u(2,2)
FROM payments p WHERE p.school_id = pg_temp.u(1,1) AND p.confirmed_at IS NOT NULL ORDER BY p.confirmed_at;

INSERT INTO ledger_entries (school_id, journal_id, account_id, student_id, debit_tzs, credit_tzs, created_by)
SELECT x.school_id, x.journal_id, x.account_id, x.student_id, x.debit, x.credit, pg_temp.u(2,2)
FROM (
    SELECT j.school_id, j.id AS journal_id,
           CASE p.channel WHEN 'CASH' THEN pg_temp.u(33,1) WHEN 'GEPG' THEN pg_temp.u(33,2)
                          WHEN 'BANK' THEN pg_temp.u(33,4) ELSE pg_temp.u(33,3) END AS account_id,
           NULL::uuid AS student_id, p.amount_tzs AS debit, 0::numeric AS credit
    FROM journals j JOIN payments p ON p.id = j.source_id WHERE j.source_type = 'PAYMENT'
    UNION ALL
    SELECT j.school_id, j.id, pg_temp.u(33,5), p.student_id, 0, a.allocated
    FROM journals j JOIN payments p ON p.id = j.source_id
    JOIN (SELECT payment_id, SUM(amount_tzs) AS allocated FROM payment_allocations GROUP BY payment_id) a ON a.payment_id = p.id
    WHERE j.source_type = 'PAYMENT'
    UNION ALL
    SELECT j.school_id, j.id, pg_temp.u(33,6), p.student_id, 0, p.amount_tzs - COALESCE(a.allocated, 0)
    FROM journals j JOIN payments p ON p.id = j.source_id
    LEFT JOIN (SELECT payment_id, SUM(amount_tzs) AS allocated FROM payment_allocations GROUP BY payment_id) a ON a.payment_id = p.id
    WHERE j.source_type = 'PAYMENT' AND p.amount_tzs - COALESCE(a.allocated, 0) > 0
) x;

-- Reversal journal for payment 4 (Dr receivable / Cr mobile money clearing)
INSERT INTO journals (id, school_id, journal_no, posted_at, source_type, source_id, memo, posted_by, created_by) VALUES
 (pg_temp.u(39,1), pg_temp.u(1,1), 'JNL-2026-' || lpad(next_document_no(pg_temp.u(1,1), 'JOURNAL', 2026::smallint)::text, 6, '0'),
  '2026-01-16 10:00+03', 'REVERSAL', pg_temp.u(38,4), 'Reversal of M-Pesa QKX1ABCD22', pg_temp.u(2,1), pg_temp.u(2,1));
INSERT INTO ledger_entries (school_id, journal_id, account_id, student_id, debit_tzs, credit_tzs, created_by) VALUES
 (pg_temp.u(1,1), pg_temp.u(39,1), pg_temp.u(33,5), pg_temp.u(6,13), 100000.00, 0, pg_temp.u(2,1)),
 (pg_temp.u(1,1), pg_temp.u(39,1), pg_temp.u(33,3), NULL,             0, 100000.00, pg_temp.u(2,1));

INSERT INTO reconciliation_runs (id, school_id, run_date, channel, statement_total_tzs, system_total_tzs,
                                 status, completed_at, created_by) VALUES
 (pg_temp.u(40,1), pg_temp.u(1,1), '2026-01-31', 'MPESA', 380000.00, 380000.00, 'BALANCED', '2026-02-01 06:05+03', pg_temp.u(2,2));
INSERT INTO reconciliation_items (school_id, run_id, external_ref, statement_amount_tzs, payment_id, status, created_by) VALUES
 (pg_temp.u(1,1), pg_temp.u(40,1), 'QKJ7H2LM9P', 280000.00, pg_temp.u(38,2), 'MATCHED', pg_temp.u(2,2)),
 (pg_temp.u(1,1), pg_temp.u(40,1), 'QKX1ABCD22', 100000.00, pg_temp.u(38,4), 'MATCHED', pg_temp.u(2,2));

-- Facilities and student life
INSERT INTO hostels (id, school_id, name, gender, warden_staff_id, created_by) VALUES
 (pg_temp.u(41,1), pg_temp.u(1,1), 'Bweni la Kilimanjaro', 'F', pg_temp.u(8,8), pg_temp.u(2,1));
INSERT INTO hostel_rooms (id, school_id, hostel_id, name, capacity, created_by) VALUES
 (pg_temp.u(42,1), pg_temp.u(1,1), pg_temp.u(41,1), 'K1', 4, pg_temp.u(2,1));
INSERT INTO accommodation_requests (id, school_id, student_id, term_id, preferred_hostel_id, status, decided_by, decided_at, created_by) VALUES
 (pg_temp.u(43,1), pg_temp.u(1,1), pg_temp.u(6,12), pg_temp.u(13,1), pg_temp.u(41,1), 'APPROVED', pg_temp.u(2,1), '2026-01-09 10:00+03', pg_temp.u(2,12));
INSERT INTO hostel_allocations (school_id, student_id, hostel_room_id, term_id, request_id, created_by) VALUES
 (pg_temp.u(1,1), pg_temp.u(6,12), pg_temp.u(42,1), pg_temp.u(13,1), pg_temp.u(43,1), pg_temp.u(2,1));

INSERT INTO buses (id, school_id, bus_no, capacity, status, created_by) VALUES
 (pg_temp.u(44,1), pg_temp.u(1,1), 'T 123 DEF', 30, 'ACTIVE', pg_temp.u(2,1));
INSERT INTO routes (id, school_id, name, description, term_fee_tzs, created_by) VALUES
 (pg_temp.u(45,1), pg_temp.u(1,1), 'Kisasa - Shuleni', 'Kisasa, Nyumba 300, Area D', 120000.00, pg_temp.u(2,1));
INSERT INTO route_stops (id, school_id, route_id, seq, name, pickup_time, created_by) VALUES
 (pg_temp.u(46,1), pg_temp.u(1,1), pg_temp.u(45,1), 1, 'Kisasa sokoni', '06:30', pg_temp.u(2,1)),
 (pg_temp.u(46,2), pg_temp.u(1,1), pg_temp.u(45,1), 2, 'Nyumba 300',    '06:45', pg_temp.u(2,1)),
 (pg_temp.u(46,3), pg_temp.u(1,1), pg_temp.u(45,1), 3, 'Area D',        '07:00', pg_temp.u(2,1));
INSERT INTO transport_assignments (school_id, student_id, bus_id, stop_id, term_id, created_by) VALUES
 (pg_temp.u(1,1), pg_temp.u(6,11), pg_temp.u(44,1), pg_temp.u(46,1), pg_temp.u(13,1), pg_temp.u(2,1));

INSERT INTO venues (id, school_id, name, total_seats, created_by) VALUES
 (pg_temp.u(47,1), pg_temp.u(1,1), 'Ukumbi Mkuu (Main hall)', 400, pg_temp.u(2,1));
INSERT INTO venue_events (school_id, venue_id, name, event_date, time_start, time_end, seats_occupied, organiser_id, created_by) VALUES
 (pg_temp.u(1,1), pg_temp.u(47,1), 'Mahafali ya Kidato cha Nne', '2026-10-30', '09:00', '13:00', 350, pg_temp.u(2,1), pg_temp.u(2,1));

INSERT INTO discipline_records (school_id, student_id, incident_date, category, description, action_taken, resolution, status,
                                parent_notified_at, recorded_by, created_by) VALUES
 (pg_temp.u(1,1), pg_temp.u(6,15), '2026-02-11', 'LATENESS', 'Alichelewa mara tatu wiki hii.', 'Ushauri na mwalimu wa nidhamu',
  'Amekuja kwa wakati tangu 16/02/2026', 'RESOLVED', '2026-02-11 15:00+03', pg_temp.u(2,8), pg_temp.u(2,8));

INSERT INTO extracurricular_activities (id, school_id, name, kind, patron_staff_id, meeting_day, created_by) VALUES
 (pg_temp.u(51,1), pg_temp.u(1,1), 'Debate Club / Klabu ya Mdahalo', 'CLUB', pg_temp.u(8,4), 3, pg_temp.u(2,1));
INSERT INTO student_activities (school_id, student_id, activity_id, academic_year_id, role, created_by) VALUES
 (pg_temp.u(1,1), pg_temp.u(6,12), pg_temp.u(51,1), pg_temp.u(12,1), 'SECRETARY', pg_temp.u(2,4)),
 (pg_temp.u(1,1), pg_temp.u(6,11), pg_temp.u(51,1), pg_temp.u(12,1), 'MEMBER',    pg_temp.u(2,4));

INSERT INTO library_books (id, school_id, isbn, title, author, subject_id, copies, created_by) VALUES
 (pg_temp.u(52,1), pg_temp.u(1,1), '978-9976-60-123-4', 'Basic Mathematics for Secondary Schools Book Two', 'TIE', pg_temp.u(15,9), 3, pg_temp.u(2,1));
INSERT INTO library_loans (school_id, book_id, borrower_user_id, loaned_at, due_date, issued_by, created_by) VALUES
 (pg_temp.u(1,1), pg_temp.u(52,1), pg_temp.u(2,11), '2026-03-02 13:00+03', '2026-03-16', pg_temp.u(2,1), pg_temp.u(2,1));

INSERT INTO consent_records (school_id, guardian_id, student_id, purpose, granted, channel, recorded_at, created_by) VALUES
 (pg_temp.u(1,1), pg_temp.u(7,24), pg_temp.u(6,14), 'HEALTH_DATA', TRUE, 'PAPER', '2025-01-13 09:10+03', pg_temp.u(2,1));
INSERT INTO health_records (school_id, student_id, record_date, kind, notes_enc, recorded_by, created_by) VALUES
 (pg_temp.u(1,1), pg_temp.u(6,14), '2026-01-12', 'ALLERGY', pg_temp.fake_enc('peanut allergy'), pg_temp.u(2,1), pg_temp.u(2,1));

INSERT INTO background_jobs (school_id, kind, status, progress_pct, total_items, processed_items, error_count, input_file_key,
                             error_report_file_key, idempotency_key, requested_by, started_at, finished_at, created_by) VALUES
 (pg_temp.u(1,1), 'IMPORT_STUDENTS', 'SUCCEEDED', 100, 6, 6, 0, 'mfano-sec/imports/students-2025.xlsx', NULL,
  'import-students-2025-01', pg_temp.u(2,1), '2025-01-13 08:00+03', '2025-01-13 08:00+03', pg_temp.u(2,1)),
 (pg_temp.u(1,1), 'REPORT_CARDS', 'SUCCEEDED', 100, 6, 6, 0, NULL, NULL,
  'report-cards-f2-t1', pg_temp.u(2,1), '2026-06-01 10:00+03', '2026-06-01 10:02+03', pg_temp.u(2,1));

INSERT INTO data_subject_requests (school_id, subject_user_id, request_type, status, details, requested_at, due_at, created_by) VALUES
 (pg_temp.u(1,1), pg_temp.u(2,21), 'EXPORT', 'RECEIVED', 'Parent requests a copy of all data held about Amani',
  '2026-03-10 09:00+03', '2026-04-09 09:00+03', pg_temp.u(2,1));

INSERT INTO refresh_tokens (school_id, user_id, token_hash, family_id, issued_at, expires_at) VALUES
 (pg_temp.u(1,1), pg_temp.u(2,1), encode(sha256('demo-refresh-token-mfano-admin'::bytea), 'hex'),
  pg_temp.u(60,1), '2026-03-02 07:58+03', '2026-03-09 07:58+03');

COMMIT;

-- =====================================================================
-- SCHOOL B — Shule ya Msingi Upendo, Arusha (small)
-- =====================================================================
BEGIN;
SELECT set_config('app.school_id', pg_temp.u(1,2)::text, true);

INSERT INTO schools (id, code, name, registration_no, ownership, district_id, status, created_by)
SELECT pg_temp.u(1,2), 'upendo-pri', 'Shule ya Msingi Upendo', 'EM.11873', 'PRIVATE', d.id, 'ACTIVE', pg_temp.u(50,1)
FROM districts d JOIN regions r ON r.id = d.region_id WHERE r.name = 'Arusha' AND d.name = 'Arusha City';

INSERT INTO users (id, school_id, first_name, last_name, gender, date_of_birth, phone_enc, phone_hash, phone_last4,
                   username, password_hash, preferred_language, status)
SELECT pg_temp.u(2,n), pg_temp.u(1,2), fn, ln, g, dob::date,
       CASE WHEN ph IS NULL THEN NULL ELSE pg_temp.fake_enc(ph) END,
       CASE WHEN ph IS NULL THEN NULL ELSE pg_temp.bidx(ph) END,
       CASE WHEN ph IS NULL THEN NULL ELSE right(ph, 4) END,
       un, CASE WHEN st = 'NO_LOGIN' THEN NULL ELSE pg_temp.pw() END, 'sw', st
FROM (VALUES
 (101, 'Agnes',  'Mollel',  'F', '1980-02-02', '255754000101', 'admin',     'ACTIVE'),     -- same username as school A
 (102, 'Elia',   'Laizer',  'M', '1992-05-05', '255754000102', 'tch.elia',  'ACTIVE'),
 (111, 'Lucy',   'Massawe', 'F', '2016-06-16', NULL,           NULL,        'NO_LOGIN'),   -- Standard IV pupil
 (121, 'John',   'Massawe', 'M', '1978-05-12', '255754000021', NULL,        'ACTIVE')      -- same phone as school A guardian
) v(n, fn, ln, g, dob, ph, un, st);

SELECT set_config('app.user_id', pg_temp.u(2,101)::text, true);

INSERT INTO school_settings (school_id, motto, phone, medium_of_instruction, default_language, sms_sender_id, created_by) VALUES
 (pg_temp.u(1,2), 'Upendo na Bidii', '255272500000', 'KISWAHILI', 'sw', 'UPENDO', pg_temp.u(2,101));

INSERT INTO students (id, school_id, user_id, admission_no, prem_number, status, admission_date, created_by) VALUES
 (pg_temp.u(6,111), pg_temp.u(1,2), pg_temp.u(2,111), 'UP-2023-0007', 'PREM-0204-000117', 'ACTIVE', '2023-01-09', pg_temp.u(2,101));
INSERT INTO guardians (id, school_id, user_id, occupation, created_by) VALUES
 (pg_temp.u(7,121), pg_temp.u(1,2), pg_temp.u(2,121), 'Farmer', pg_temp.u(2,101));
INSERT INTO student_guardians (school_id, student_id, guardian_id, relationship, is_primary, created_by) VALUES
 (pg_temp.u(1,2), pg_temp.u(6,111), pg_temp.u(7,121), 'FATHER', TRUE, pg_temp.u(2,101));
INSERT INTO staff (id, school_id, user_id, staff_no, created_by) VALUES
 (pg_temp.u(8,101), pg_temp.u(1,2), pg_temp.u(2,101), 'UP-STF-001', pg_temp.u(2,101)),
 (pg_temp.u(8,102), pg_temp.u(1,2), pg_temp.u(2,102), 'UP-STF-002', pg_temp.u(2,101));
INSERT INTO user_roles (school_id, user_id, role_id, created_by) VALUES
 (pg_temp.u(1,2), pg_temp.u(2,101), pg_temp.u(3,1), pg_temp.u(2,101)),
 (pg_temp.u(1,2), pg_temp.u(2,102), pg_temp.u(3,3), pg_temp.u(2,101)),
 (pg_temp.u(1,2), pg_temp.u(2,121), pg_temp.u(3,5), pg_temp.u(2,101));

INSERT INTO education_levels (id, school_id, code, name_en, name_sw, sort_order, created_by) VALUES
 (pg_temp.u(11,101), pg_temp.u(1,2), 'PRIMARY', 'Primary', 'Elimu ya msingi', 2, pg_temp.u(2,101));
INSERT INTO academic_years (id, school_id, name, start_date, end_date, is_current, created_by) VALUES
 (pg_temp.u(12,101), pg_temp.u(1,2), '2026', '2026-01-01', '2026-12-31', TRUE, pg_temp.u(2,101));
INSERT INTO terms (id, school_id, academic_year_id, term_no, name_en, name_sw, start_date, end_date, created_by) VALUES
 (pg_temp.u(13,101), pg_temp.u(1,2), pg_temp.u(12,101), 1, 'Term One', 'Muhula wa Kwanza', '2026-01-12', '2026-06-05', pg_temp.u(2,101));

INSERT INTO classes (id, school_id, education_level_id, code, name_en, name_sw, sort_order, created_by)
SELECT pg_temp.u(16,100 + n), pg_temp.u(1,2), pg_temp.u(11,101), 'STD' || n,
       'Standard ' || (ARRAY['One','Two','Three','Four','Five','Six','Seven'])[n],
       'Darasa la ' || (ARRAY['Kwanza','Pili','Tatu','Nne','Tano','Sita','Saba'])[n], n, pg_temp.u(2,101)
FROM generate_series(1, 7) n;
UPDATE classes SET next_class_id = pg_temp.u(16, 100 + sort_order + 1) WHERE school_id = pg_temp.u(1,2) AND sort_order < 7;

INSERT INTO grading_schemes (id, school_id, education_level_id, academic_year_id, name, version, created_by) VALUES
 (pg_temp.u(14,101), pg_temp.u(1,2), pg_temp.u(11,101), pg_temp.u(12,101), 'NECTA PSLE scale', 1, pg_temp.u(2,101));
INSERT INTO grade_bands (school_id, grading_scheme_id, letter, min_score, max_score, points, remark_en, remark_sw, created_by)
SELECT pg_temp.u(1,2), pg_temp.u(14,101), l, mn, mx, p, re, rs, pg_temp.u(2,101)
FROM (VALUES ('A',81,100,1,'Excellent','Bora'), ('B',61,80,2,'Very good','Vizuri sana'), ('C',41,60,3,'Good','Vizuri'),
             ('D',21,40,4,'Satisfactory','Inaridhisha'), ('E',0,20,5,'Fail','Hafifu')) v(l, mn, mx, p, re, rs);

INSERT INTO rooms (id, school_id, code, name, capacity, created_by) VALUES
 (pg_temp.u(18,101), pg_temp.u(1,2), 'STD4A', 'Darasa la Nne A', 50, pg_temp.u(2,101));
INSERT INTO streams (id, school_id, class_id, name, capacity, home_room_id, created_by) VALUES
 (pg_temp.u(19,101), pg_temp.u(1,2), pg_temp.u(16,104), 'A', 50, pg_temp.u(18,101), pg_temp.u(2,101));
INSERT INTO enrolments (id, school_id, student_id, stream_id, academic_year_id, status, started_on, created_by) VALUES
 (pg_temp.u(24,111), pg_temp.u(1,2), pg_temp.u(6,111), pg_temp.u(19,101), pg_temp.u(12,101), 'ACTIVE', '2026-01-12', pg_temp.u(2,101));

INSERT INTO devices (id, school_id, name, kind, api_key_hash, location, created_by) VALUES
 (pg_temp.u(30,101), pg_temp.u(1,2), 'Lango kuu QR', 'QR_SCANNER', encode(sha256('demo-device-key-upendo-gate'::bytea), 'hex'),
  'Main gate', pg_temp.u(2,101));

INSERT INTO ledger_accounts (id, school_id, code, name_en, name_sw, kind, created_by) VALUES
 (pg_temp.u(33,101), pg_temp.u(1,2), '1000', 'Cash on hand',    'Fedha taslimu',     'ASSET',  pg_temp.u(2,101)),
 (pg_temp.u(33,105), pg_temp.u(1,2), '1300', 'Fees receivable', 'Ada zinazodaiwa',   'ASSET',  pg_temp.u(2,101)),
 (pg_temp.u(33,108), pg_temp.u(1,2), '4010', 'Meals income',    'Mapato ya chakula', 'INCOME', pg_temp.u(2,101));
INSERT INTO fee_items (id, school_id, code, name_en, name_sw, income_account_id, created_by) VALUES
 (pg_temp.u(34,102), pg_temp.u(1,2), 'MEALS', 'Meals contribution', 'Mchango wa chakula', pg_temp.u(33,108), pg_temp.u(2,101));
SELECT pg_temp.finance_defaults(pg_temp.u(1,2), pg_temp.u(2,101));
INSERT INTO invoices (id, school_id, invoice_no, student_id, term_id, issued_at, due_date, created_by) VALUES
 (pg_temp.u(36,111), pg_temp.u(1,2), 'INV-2026-' || lpad(next_document_no(pg_temp.u(1,2), 'INVOICE', 2026::smallint)::text, 6, '0'),
  pg_temp.u(6,111), pg_temp.u(13,101), '2026-01-12 09:00+03', '2026-02-28', pg_temp.u(2,101));
INSERT INTO invoice_lines (school_id, invoice_id, fee_item_id, description, amount_tzs, created_by) VALUES
 (pg_temp.u(1,2), pg_temp.u(36,111), pg_temp.u(34,102), 'Mchango wa chakula - Muhula wa Kwanza', 60000.00, pg_temp.u(2,101));

INSERT INTO payments (id, school_id, student_id, channel, external_ref, amount_tzs, payer_name, status, received_at, confirmed_at, recorded_by, created_by) VALUES
 (pg_temp.u(38,101), pg_temp.u(1,2), pg_temp.u(6,111), 'CASH', 'RCT-BOOK-0001', 60000.00, 'John Massawe', 'CONFIRMED',
  '2026-01-15 10:00+03', '2026-01-15 10:00+03', pg_temp.u(2,101), pg_temp.u(2,101));      -- same receipt no. as school A
INSERT INTO payment_allocations (school_id, payment_id, invoice_id, amount_tzs, created_by) VALUES
 (pg_temp.u(1,2), pg_temp.u(38,101), pg_temp.u(36,111), 60000.00, pg_temp.u(2,101));
INSERT INTO receipts (school_id, receipt_no, payment_id, created_by) VALUES
 (pg_temp.u(1,2), 'RCT-2026-' || lpad(next_document_no(pg_temp.u(1,2), 'RECEIPT', 2026::smallint)::text, 6, '0'),
  pg_temp.u(38,101), pg_temp.u(2,101));

INSERT INTO journals (id, school_id, journal_no, posted_at, source_type, source_id, memo, posted_by, created_by) VALUES
 (pg_temp.u(39,101), pg_temp.u(1,2), 'JNL-2026-000001', '2026-01-12 09:00+03', 'INVOICE', pg_temp.u(36,111), 'Invoice meals Term One', pg_temp.u(2,101), pg_temp.u(2,101)),
 (pg_temp.u(39,102), pg_temp.u(1,2), 'JNL-2026-000002', '2026-01-15 10:00+03', 'PAYMENT', pg_temp.u(38,101), 'Cash RCT-BOOK-0001', pg_temp.u(2,101), pg_temp.u(2,101));
INSERT INTO ledger_entries (school_id, journal_id, account_id, student_id, debit_tzs, credit_tzs, created_by) VALUES
 (pg_temp.u(1,2), pg_temp.u(39,101), pg_temp.u(33,105), pg_temp.u(6,111), 60000.00, 0,        pg_temp.u(2,101)),
 (pg_temp.u(1,2), pg_temp.u(39,101), pg_temp.u(33,108), NULL,              0,        60000.00, pg_temp.u(2,101)),
 (pg_temp.u(1,2), pg_temp.u(39,102), pg_temp.u(33,101), NULL,              60000.00, 0,        pg_temp.u(2,101)),
 (pg_temp.u(1,2), pg_temp.u(39,102), pg_temp.u(33,105), pg_temp.u(6,111), 0,        60000.00, pg_temp.u(2,101));

COMMIT;

RESET ROLE;
