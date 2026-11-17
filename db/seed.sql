-- =====================================================================
--  Sample data for a fictional school: "Shule ya Sekondari Mfano", Dodoma
--  File: db/seed.sql
--  Run after db/schema.sql on an EMPTY database: rows are inserted in
--  order, so the generated IDs below (1, 2, 3 ...) are predictable.
--  Demo password for every account: Mfano@2026  (change after first login)
--  Amounts are illustrative for a fee-paying school. Government schools
--  are fee-free for tuition, so their fee_structures hold only contributions.
-- =====================================================================

-- ---------- NECTA scales (verify against the current NECTA regulations) ----------
INSERT INTO exam_scales (exam_scale, name_en, name_sw, best_n_subjects) VALUES
 ('PSLE',  'Primary School Leaving Examination',                      'Mtihani wa Kumaliza Elimu ya Msingi', NULL),
 ('CSEE',  'Certificate of Secondary Education Examination',          'Mtihani wa Kidato cha Nne',           7),
 ('ACSEE', 'Advanced Certificate of Secondary Education Examination', 'Mtihani wa Kidato cha Sita',          3);

INSERT INTO grading_scales (exam_scale, grade, min_score, max_score, points, remark_en, remark_sw) VALUES
 ('CSEE','A', 75, 100,   1, 'Excellent',    'Bora'),
 ('CSEE','B', 65, 74.99, 2, 'Very Good',    'Vizuri Sana'),
 ('CSEE','C', 45, 64.99, 3, 'Good',         'Vizuri'),
 ('CSEE','D', 30, 44.99, 4, 'Satisfactory', 'Inaridhisha'),
 ('CSEE','F',  0, 29.99, 5, 'Fail',         'Hafifu'),
 ('ACSEE','A', 80, 100,   1, 'Excellent',    'Bora'),
 ('ACSEE','B', 70, 79.99, 2, 'Very Good',    'Vizuri Sana'),
 ('ACSEE','C', 60, 69.99, 3, 'Good',         'Vizuri'),
 ('ACSEE','D', 50, 59.99, 4, 'Average',      'Wastani'),
 ('ACSEE','E', 40, 49.99, 5, 'Satisfactory', 'Inaridhisha'),
 ('ACSEE','S', 35, 39.99, 6, 'Subsidiary',   'Ufaulu Hafifu'),
 ('ACSEE','F',  0, 34.99, 7, 'Fail',         'Hafifu'),
 ('PSLE','A', 81, 100,   1, 'Excellent',    'Bora'),
 ('PSLE','B', 61, 80.99, 2, 'Very Good',    'Vizuri Sana'),
 ('PSLE','C', 41, 60.99, 3, 'Good',         'Vizuri'),
 ('PSLE','D', 21, 40.99, 4, 'Satisfactory', 'Inaridhisha'),
 ('PSLE','E',  0, 20.99, 5, 'Fail',         'Hafifu');

INSERT INTO division_scales (exam_scale, division, min_points, max_points) VALUES
 ('CSEE','I',7,17), ('CSEE','II',18,21), ('CSEE','III',22,25), ('CSEE','IV',26,33), ('CSEE','0',34,35),
 ('ACSEE','I',3,9), ('ACSEE','II',10,12), ('ACSEE','III',13,17), ('ACSEE','IV',18,19), ('ACSEE','0',20,21);

-- ---------- Calendar and levels ----------
INSERT INTO academic_years (name, start_date, end_date, is_current) VALUES
 ('2026', '2026-01-01', '2026-12-31', TRUE);                                      -- id 1

INSERT INTO terms (academic_year_id, term_no, name_en, name_sw, start_date, end_date) VALUES
 (1, 1, 'Term One', 'Muhula wa Kwanza', '2026-01-12', '2026-06-05'),              -- id 1
 (1, 2, 'Term Two', 'Muhula wa Pili',   '2026-07-06', '2026-12-04');              -- id 2

INSERT INTO class_levels (code, name_en, name_sw, education_level, exam_scale, sort_order) VALUES
 ('F1','Form One',  'Kidato cha Kwanza','O_LEVEL','CSEE', 11),                    -- id 1
 ('F2','Form Two',  'Kidato cha Pili',  'O_LEVEL','CSEE', 12),                    -- id 2
 ('F3','Form Three','Kidato cha Tatu',  'O_LEVEL','CSEE', 13),                    -- id 3
 ('F4','Form Four', 'Kidato cha Nne',   'O_LEVEL','CSEE', 14),                    -- id 4
 ('F5','Form Five', 'Kidato cha Tano',  'A_LEVEL','ACSEE',15),                    -- id 5
 ('F6','Form Six',  'Kidato cha Sita',  'A_LEVEL','ACSEE',16),                    -- id 6
 ('STD1','Standard One',  'Darasa la Kwanza','PRIMARY','PSLE',1),
 ('STD2','Standard Two',  'Darasa la Pili',  'PRIMARY','PSLE',2),
 ('STD3','Standard Three','Darasa la Tatu',  'PRIMARY','PSLE',3),
 ('STD4','Standard Four', 'Darasa la Nne',   'PRIMARY','PSLE',4),
 ('STD5','Standard Five', 'Darasa la Tano',  'PRIMARY','PSLE',5),
 ('STD6','Standard Six',  'Darasa la Sita',  'PRIMARY','PSLE',6),
 ('STD7','Standard Seven','Darasa la Saba',  'PRIMARY','PSLE',7);

-- ---------- Departments, designations, subjects ----------
INSERT INTO departments (code, name_en, name_sw) VALUES
 ('SCI', 'Science',     'Sayansi'),                                               -- id 1
 ('LANG','Languages',   'Lugha'),                                                 -- id 2
 ('HUM', 'Humanities',  'Masomo ya Sanaa'),                                       -- id 3
 ('MATH','Mathematics', 'Hisabati');                                              -- id 4

INSERT INTO designations (code, name_en, name_sw) VALUES
 ('HEAD_OF_SCHOOL',   'Head of School',          'Mkuu wa Shule'),               -- id 1
 ('ACADEMIC_MASTER',  'Academic Master/Mistress','Mwalimu wa Taaluma'),          -- id 2
 ('HOD',              'Head of Department',      'Mkuu wa Idara'),               -- id 3
 ('CLASS_TEACHER',    'Class Teacher',           'Mwalimu wa Darasa'),           -- id 4
 ('DISCIPLINE_MASTER','Discipline Master/Mistress','Mwalimu wa Nidhamu'),        -- id 5
 ('SUBJECT_TEACHER',  'Subject Teacher',         'Mwalimu wa Somo');             -- id 6

INSERT INTO subjects (subject_code, necta_code, name_en, name_sw, department_id, room_type_required) VALUES
 ('CIV',   '011','Civics',               'Uraia',              3,'CLASSROOM'),    -- id 1
 ('HIST',  '012','History',              'Historia',           3,'CLASSROOM'),    -- id 2
 ('GEO',   '013','Geography',            'Jiografia',          3,'CLASSROOM'),    -- id 3
 ('KISW',  '021','Kiswahili',            'Kiswahili',          2,'CLASSROOM'),    -- id 4
 ('ENG',   '022','English Language',     'Kiingereza',         2,'CLASSROOM'),    -- id 5
 ('PHY',   '031','Physics',              'Fizikia',            1,'LABORATORY'),   -- id 6
 ('CHEM',  '032','Chemistry',            'Kemia',              1,'LABORATORY'),   -- id 7
 ('BIO',   '033','Biology',              'Biolojia',           1,'LABORATORY'),   -- id 8
 ('BMATH', '041','Basic Mathematics',    'Hisabati za Msingi', 4,'CLASSROOM'),    -- id 9
 ('GS',    '111','General Studies',      'Maarifa ya Jumla',   3,'CLASSROOM'),    -- id 10
 ('PHY-A', '131','Physics (Advanced)',   'Fizikia (Juu)',      1,'LABORATORY'),   -- id 11
 ('CHEM-A','132','Chemistry (Advanced)', 'Kemia (Juu)',        1,'LABORATORY'),   -- id 12
 ('AMATH', '142','Advanced Mathematics', 'Hisabati ya Juu',    4,'CLASSROOM');    -- id 13

-- ---------- Courses (programmes / combinations) ----------
INSERT INTO courses (course_code, course_name, course_name_sw, course_desc, education_level) VALUES
 ('OLG','O-Level General Secondary','Elimu ya Sekondari ya Kawaida',
        'Form I-IV general curriculum leading to CSEE', 'O_LEVEL'),               -- id 1
 ('PCM','Physics, Chemistry and Advanced Mathematics','Fizikia, Kemia na Hisabati ya Juu',
        'Form V-VI science combination leading to ACSEE', 'A_LEVEL');             -- id 2

INSERT INTO course_subjects (course_id, level_id, subject_id, is_compulsory, periods_per_week)
SELECT 1, lvl, sub, TRUE, ppw
FROM (VALUES (1),(2)) AS l(lvl)
CROSS JOIN (VALUES (1,2),(2,3),(3,3),(4,4),(5,5),(6,3),(7,3),(8,3),(9,6)) AS s(sub, ppw);
INSERT INTO course_subjects (course_id, level_id, subject_id, is_compulsory, periods_per_week) VALUES
 (2,5,11,TRUE,6), (2,5,12,TRUE,6), (2,5,13,TRUE,6), (2,5,10,TRUE,3);

INSERT INTO course_offerings (course_id, academic_year_id, level_id, capacity) VALUES
 (1,1,1,160),                                                                     -- id 1  OLG Form I 2026
 (1,1,2,160),                                                                     -- id 2  OLG Form II 2026
 (2,1,5, 45);                                                                     -- id 3  PCM Form V 2026

INSERT INTO rooms (room_code, name, room_type, capacity) VALUES
 ('F1A',     'Form I A Classroom',  'CLASSROOM', 45),                             -- id 1
 ('F2A',     'Form II A Classroom', 'CLASSROOM', 45),                             -- id 2
 ('F5PCM',   'Form V PCM Classroom','CLASSROOM', 45),                             -- id 3
 ('LAB-PHY', 'Physics Laboratory',  'LABORATORY',40),                             -- id 4
 ('LAB-CHEM','Chemistry Laboratory','LABORATORY',40),                             -- id 5
 ('HALL',    'Assembly Hall',       'HALL',     400);                             -- id 6

-- ---------- Users (one table, role column, Argon2id hashes) ----------
INSERT INTO users (username, password_hash, role, first_name, middle_name, last_name,
                   gender, date_of_birth, phone, email, preferred_language)
SELECT v.username, h.hash, v.role, v.fn, v.mn, v.ln, v.g, v.dob::date, v.phone, v.email, v.lang
FROM (VALUES
 ('admin',      'ADMIN',      'Halima',   'Juma',     'Mrisho',   'F','1985-04-02','255754000001','admin@mfano.sc.tz',     'en'),  -- 1
 ('registrar',  'REGISTRAR',  'Joseph',   NULL,       'Mwakyusa', 'M','1980-09-17','255754000002','registrar@mfano.sc.tz', 'sw'),  -- 2
 ('bursar',     'BURSAR',     'Rehema',   NULL,       'Kileo',    'F','1988-01-25','255754000003','bursar@mfano.sc.tz',    'sw'),  -- 3
 ('tch.mwita',  'INSTRUCTOR', 'Daudi',    NULL,       'Mwita',    'M','1987-06-11','255754000004','d.mwita@mfano.sc.tz',   'sw'),  -- 4
 ('tch.salma',  'INSTRUCTOR', 'Salma',    NULL,       'Abdallah', 'F','1990-12-03','255754000005','s.abdallah@mfano.sc.tz','en'),  -- 5
 ('tch.kimaro', 'INSTRUCTOR', 'Peter',    NULL,       'Kimaro',   'M','1984-03-29','255754000006','p.kimaro@mfano.sc.tz',  'sw'),  -- 6
 ('s2025-0014', 'STUDENT',    'Amani',    'John',     'Massawe',  'M','2012-03-14',NULL,          NULL,                    'sw'),  -- 7
 ('s2025-0027', 'STUDENT',    'Zawadi',   'Ally',     'Hassan',   'F','2012-08-02',NULL,          NULL,                    'sw'),  -- 8
 ('s2026-0003', 'STUDENT',    'Baraka',   'Emmanuel', 'Lyimo',    'M','2009-11-21','255683000009',NULL,                    'en'),  -- 9
 ('p.massawe',  'PARENT',     'John',     NULL,       'Massawe',  'M','1978-05-12','255754000010',NULL,                    'sw'),  -- 10
 ('p.hassan',   'PARENT',     'Mwanaisha',NULL,       'Hassan',   'F','1983-10-30','255715000011',NULL,                    'sw')   -- 11
) AS v(username, role, fn, mn, ln, g, dob, phone, email, lang)
CROSS JOIN (SELECT '$argon2id$v=19$m=65536,t=3,p=4$2JZvF1O+TsM6DnwjGpd33w$SfH+MNK3OfkgDVia5a+o99MhicDtpTVk/2+CrGeLQ5Q'::text AS hash) AS h;

INSERT INTO staff (user_id, employee_no, job_title, hired_on) VALUES
 (1,'EMP-0001','System Administrator','2019-01-07'),
 (2,'EMP-0002','Registrar',           '2015-07-01'),
 (3,'EMP-0003','Bursar',              '2020-02-03');

INSERT INTO instructors (user_id, employee_no, department_id, qualification, employment_date) VALUES
 (4,'TCH-0101',4,'B.Ed. Mathematics',               '2018-01-10'),                -- id 1
 (5,'TCH-0102',2,'B.A. Ed. English and Kiswahili',  '2019-07-01'),                -- id 2
 (6,'TCH-0103',1,'B.Sc. Ed. Physics and Chemistry', '2016-01-11');                -- id 3

INSERT INTO instructor_subjects (instructor_id, subject_id) VALUES
 (1,9),(1,13),(2,4),(2,5),(3,6),(3,7),(3,11),(3,12);

INSERT INTO instructor_designations (instructor_id, designation_id, academic_year_id, department_id, level_id, stream, assigned_on, assigned_by) VALUES
 (1,3,1,4,NULL,NULL,'2026-01-05',1),     -- Mwita: HOD Mathematics
 (2,4,1,NULL,2,'A', '2026-01-05',1),     -- Salma: Class Teacher Form II A
 (3,2,1,NULL,NULL,NULL,'2026-01-05',1);  -- Kimaro: Academic Master

INSERT INTO guardians (user_id, nida_no, occupation, address) VALUES
 (10,'19780512141230000123','Farmer',      'Kisasa, Dodoma'),                     -- id 1
 (11,'19831030141230000456','Businesswoman','Area D, Dodoma');                    -- id 2

INSERT INTO students (user_id, admission_no, birth_cert_no, necta_index_no, admission_date,
                      current_status, region, district, home_address) VALUES
 (7,'S2025-0014','BC-DOD-2012-004411',NULL,             '2025-01-13','ACTIVE',   'Dodoma','Dodoma City','Kisasa, Dodoma'),  -- id 1
 (8,'S2025-0027','BC-DOD-2012-007920',NULL,             '2025-01-13','ACTIVE',   'Dodoma','Dodoma City','Area D, Dodoma'),  -- id 2
 (9,'S2026-0003','BC-ARU-2009-001276','S0334/0045/2025','2026-01-06','APPLICANT','Arusha','Arusha City','Njiro, Arusha');   -- id 3

INSERT INTO student_guardians (student_id, guardian_id, relationship, is_primary) VALUES
 (1,1,'FATHER',TRUE), (2,2,'MOTHER',TRUE);

INSERT INTO student_status_history (student_id, old_status, new_status, reason, effective_date, changed_by, changed_at) VALUES
 (1,'APPLICANT','ACTIVE','Enrolment confirmed - Form I 2025','2025-01-13',2,'2025-01-13 09:00+03'),
 (2,'APPLICANT','ACTIVE','Enrolment confirmed - Form I 2025','2025-01-13',2,'2025-01-13 09:05+03');

-- ---------- Enrolment requirements ----------
INSERT INTO enrolment_requirements (code, name_en, name_sw, education_level, is_mandatory) VALUES
 ('BIRTH_CERT',     'Birth certificate',              'Cheti cha kuzaliwa',               NULL,     TRUE),   -- id 1
 ('PASSPORT_PHOTO', 'Passport-size photograph',       'Picha ya pasipoti',                NULL,     TRUE),   -- id 2
 ('MEDICAL_FORM',   'Medical examination form',       'Fomu ya uchunguzi wa afya',        NULL,     TRUE),   -- id 3
 ('PSLE_RESULTS',   'Standard VII (PSLE) results slip','Matokeo ya Darasa la Saba',       'O_LEVEL',TRUE),   -- id 4
 ('CSEE_RESULTS',   'Form IV (CSEE) results slip',    'Matokeo ya Kidato cha Nne',        'A_LEVEL',TRUE),   -- id 5
 ('TRANSFER_LETTER','Transfer letter (if transferring)','Barua ya uhamisho (kama unahamia)',NULL,   FALSE);  -- id 6

-- ---------- Enrolments ----------
INSERT INTO enrolments (enrolment_no, student_id, offering_id, stream, status, applied_at, submitted_at, confirmed_at, confirmed_by) VALUES
 ('ENR-2026-000001',1,2,'A','CONFIRMED','2025-12-01 10:00+03','2025-12-01 10:30+03','2026-01-08 09:00+03',2),  -- id 1
 ('ENR-2026-000002',2,2,'A','CONFIRMED','2025-12-02 11:00+03','2025-12-02 11:20+03','2026-01-08 09:10+03',2),  -- id 2
 ('ENR-2026-000003',3,3,NULL,'SUBMITTED','2026-01-06 08:30+03','2026-01-06 09:15+03',NULL,NULL);                -- id 3

INSERT INTO enrolment_documents (enrolment_id, requirement_id, file_name, storage_key, mime_type, file_size_bytes, sha256, status, validated_by, validated_at) VALUES
 (3,1,'cheti_kuzaliwa.pdf','enrolments/3/BIRTH_CERT/7f3a.pdf','application/pdf',284113,encode(sha256('doc-3-1'::bytea),'hex'),'VALID',  6,'2026-01-07 10:00+03'),
 (3,2,'picha.jpg',         'enrolments/3/PASSPORT_PHOTO/91bc.jpg','image/jpeg', 98112,encode(sha256('doc-3-2'::bytea),'hex'),'VALID',  6,'2026-01-07 10:02+03'),
 (3,3,'medical.pdf',       'enrolments/3/MEDICAL_FORM/0d44.pdf','application/pdf',412880,encode(sha256('doc-3-3'::bytea),'hex'),'PENDING',NULL,NULL),
 (3,5,'csee_slip.png',     'enrolments/3/CSEE_RESULTS/c2e1.png','image/png',  1022331,encode(sha256('doc-3-5'::bytea),'hex'),'PENDING',NULL,NULL);

-- ---------- Timetable, Term One (Mon=1). Mwita's 08:00-08:40 and 08:40-10:00 do not clash: '[)' ----------
INSERT INTO schedules (offering_id, stream, term_id, subject_id, instructor_id, room_id, day_of_week, time_start, time_end, created_by) VALUES
 (2,'A',1, 9,1,2,1,'08:00','08:40',1),     -- id 1  Form II A  Basic Maths   Mon
 (2,'A',1, 5,2,2,1,'08:40','09:20',1),     -- id 2  Form II A  English       Mon
 (2,'A',1, 6,3,4,2,'10:20','11:40',1),     -- id 3  Form II A  Physics (lab) Tue double
 (2,'A',1, 4,2,2,2,'08:00','08:40',1),     -- id 4  Form II A  Kiswahili     Tue
 (2,'A',1, 9,1,2,3,'08:00','08:40',1),     -- id 5  Form II A  Basic Maths   Wed
 (3,'A',1,13,1,3,1,'08:40','10:00',1),     -- id 6  Form V PCM Adv. Maths    Mon double
 (3,'A',1,11,3,4,1,'10:20','11:40',1);     -- id 7  Form V PCM Physics (lab) Mon double

INSERT INTO enrolment_schedules (enrolment_id, schedule_id)
SELECT e, s FROM (VALUES (1),(2)) AS en(e) CROSS JOIN (VALUES (1),(2),(3),(4),(5)) AS sc(s);

-- ---------- Results (Term One mid-term) and attendance ----------
INSERT INTO results (enrolment_id, subject_id, term_id, assessment_type, score, is_published, entered_by) VALUES
 (1, 9,1,'MIDTERM',78.50,TRUE,4), (1,5,1,'MIDTERM',66.00,TRUE,5), (1,6,1,'MIDTERM',52.00,TRUE,6), (1,4,1,'MIDTERM',81.00,TRUE,5),
 (2, 9,1,'MIDTERM',44.00,TRUE,4), (2,5,1,'MIDTERM',71.00,TRUE,5), (2,6,1,'MIDTERM',29.50,TRUE,6), (2,4,1,'MIDTERM',88.00,TRUE,5);

INSERT INTO attendance (enrolment_id, schedule_id, attendance_date, status, recorded_by) VALUES
 (1,1,'2026-03-02','PRESENT',4), (2,1,'2026-03-02','LATE',4),
 (1,2,'2026-03-02','PRESENT',5), (2,2,'2026-03-02','ABSENT',5);

-- ---------- Fees, invoices, transactions ----------
INSERT INTO fee_structures (term_id, level_id, course_id, fee_item, description, amount_tzs) VALUES
 (1,2,NULL,'TUITION',    'Tuition fee - Term One',      450000),   -- id 1
 (1,2,NULL,'MEALS',      'Meals - Term One',            150000),   -- id 2
 (1,2,NULL,'EXAMINATION','Examination fee - Term One',   30000),   -- id 3
 (1,2,NULL,'DEVELOPMENT','Development levy (annual)',    50000),   -- id 4
 (1,5,2,   'TUITION',    'Tuition fee - Term One (PCM)',600000),   -- id 5
 (1,5,2,   'MEALS',      'Meals - Term One',            150000),   -- id 6
 (1,5,2,   'EXAMINATION','Examination fee - Term One',   40000),   -- id 7
 (2,2,NULL,'TUITION',    'Tuition fee - Term Two',      450000),   -- id 8
 (2,2,NULL,'MEALS',      'Meals - Term Two',            150000),   -- id 9
 (2,2,NULL,'EXAMINATION','Examination fee - Term Two',   30000),   -- id 10
 (2,5,2,   'TUITION',    'Tuition fee - Term Two (PCM)',600000),   -- id 11
 (2,5,2,   'MEALS',      'Meals - Term Two',            150000),   -- id 12
 (2,5,2,   'EXAMINATION','Examination fee - Term Two',   40000);   -- id 13

INSERT INTO invoices (invoice_no, student_id, term_id, gepg_control_no, issued_at, due_date, issued_by) VALUES
 ('INV-2026-000001',1,1,'994120000001','2026-01-08 12:00+03','2026-02-15',3),    -- id 1
 ('INV-2026-000002',2,1,'994120000002','2026-01-08 12:05+03','2026-02-15',3);    -- id 2

INSERT INTO invoice_items (invoice_id, fee_structure_id, description, amount_tzs)
SELECT i, f.fee_structure_id, f.description, f.amount_tzs
FROM (VALUES (1),(2)) AS inv(i)
CROSS JOIN fee_structures f
WHERE f.fee_structure_id IN (1,2,3,4);

INSERT INTO transactions (trans_no, trans_type, trans_name, student_id, invoice_id, amount_tzs, payment_method,
                          reference_no, payer_name, payer_phone, status, source, trans_date, recorded_by) VALUES
 ('TXN-2026-000001','PAYMENT','School fees Term One (M-Pesa)',1,1,400000,'MPESA','QKJ7H2LM9P','John Massawe','255754000010','COMPLETED','MANUAL','2026-01-10 10:15+03',3),
 ('TXN-2026-000002','PAYMENT','School fees Term One (GePG)',  1,1,280000,'GEPG', '7712345678','John Massawe','255754000010','COMPLETED','GEPG',  '2026-01-20 14:02+03',NULL),
 ('TXN-2026-000003','PAYMENT','School fees Term One (cash)',  2,2,200000,'CASH', 'RCT-2026-0001','Mwanaisha Hassan','255715000011','COMPLETED','MANUAL','2026-01-12 09:30+03',3),
 ('TXN-2026-000004','PAYMENT','School fees Term One (Airtel)',2,2,100000,'AIRTEL_MONEY','MP260115.1234.A12345','Mwanaisha Hassan','255715000011','FAILED','MOBILE_API','2026-01-15 16:45+03',NULL);

-- ---------- Continue document numbering after the sample rows ----------
SELECT setval('seq_admission_no', 100);
SELECT setval('seq_enrolment_no', 3);
SELECT setval('seq_invoice_no', 2);
SELECT setval('seq_trans_no', 4);
