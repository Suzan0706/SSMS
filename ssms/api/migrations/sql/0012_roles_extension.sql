-- Phase 4 of the extension (design/20 §20.7): reference data taken unchanged from design/sql/extension.sql §11.
-- roles, permissions and role_permissions are global tables, written by the migration login.
INSERT INTO roles (code, name_en, name_sw) VALUES ('receptionist', 'Receptionist', 'Mpokezi') ON CONFLICT DO NOTHING;
UPDATE roles SET name_en = 'Accountant (bursar)', name_sw = 'Mhasibu' WHERE code = 'bursar';

INSERT INTO permissions (code, module, description_en, description_sw) VALUES
 ('inquiries.manage',     'enrolment',  'Record and follow up admission inquiries',   'Kurekodi na kufuatilia maulizo ya kujiunga'),
 ('calendar.manage',      'school',     'Manage school events',                       'Kusimamia matukio ya shule'),
 ('staff_attendance.take','staff',      'Record staff attendance',                    'Kurekodi mahudhurio ya wafanyakazi'),
 ('staff_attendance.read','staff',      'View staff attendance',                      'Kuona mahudhurio ya wafanyakazi'),
 ('leave.request',        'staff',      'Request leave',                              'Kuomba likizo'),
 ('leave.decide',         'staff',      'Approve or reject leave',                    'Kuidhinisha au kukataa likizo'),
 ('exams.admit_cards',    'exams',      'Number candidates and print admit cards',    'Kupanga namba za watahiniwa na kuchapisha kadi'),
 ('accounts.record',      'finance',    'Record other income and expenses',           'Kurekodi mapato na matumizi mengine'),
 ('accounts.approve',     'finance',    'Approve reversals of income and expenses',   'Kuidhinisha kubatilisha mapato na matumizi'),
 ('accounts.read',        'finance',    'View income, expenses and statements',       'Kuona mapato, matumizi na taarifa'),
 ('fines.configure',      'finance',    'Set fine rules and waive fines',             'Kuweka kanuni za faini na kusamehe faini'),
 ('materials.publish',    'teaching',   'Publish study materials',                    'Kuchapisha nyenzo za kujifunzia'),
 ('homework.manage',      'teaching',   'Set and mark homework',                      'Kutoa na kusahihisha kazi za nyumbani'),
 ('homework.submit',      'teaching',   'Submit homework',                            'Kuwasilisha kazi za nyumbani'),
 ('certificates.issue',   'documents',  'Issue and revoke certificates',              'Kutoa na kubatilisha vyeti'),
 ('cards.print',          'documents',  'Print ID and library cards',                 'Kuchapisha vitambulisho na kadi za maktaba'),
 ('students.export',      'students',   'Export student lists',                       'Kupakua orodha za wanafunzi'),
 ('email.manage',         'communication','Send email and view its history',          'Kutuma barua pepe na kuona historia yake')
ON CONFLICT (code) DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON (r.code, p.code) IN (
    ('school_admin','inquiries.manage'), ('school_admin','calendar.manage'), ('school_admin','staff_attendance.take'),
    ('school_admin','staff_attendance.read'), ('school_admin','leave.request'), ('school_admin','leave.decide'),
    ('school_admin','exams.admit_cards'), ('school_admin','accounts.read'), ('school_admin','accounts.approve'),
    ('school_admin','certificates.issue'), ('school_admin','cards.print'), ('school_admin','students.export'),
    ('school_admin','email.manage'), ('school_admin','fines.configure'),
    ('bursar','accounts.record'), ('bursar','accounts.read'), ('bursar','fines.configure'), ('bursar','leave.request'),
    ('teacher','materials.publish'), ('teacher','homework.manage'), ('teacher','leave.request'),
    ('department_head','materials.publish'), ('department_head','homework.manage'), ('department_head','leave.request'),
    ('department_head','exams.admit_cards'),
    ('librarian','cards.print'), ('librarian','leave.request'),
    ('student','homework.submit'),
    ('receptionist','inquiries.manage'), ('receptionist','cards.print'), ('receptionist','leave.request'),
    ('receptionist','calendar.manage'), ('receptionist','students.read'), ('receptionist','enrolment.manage'),
    ('registrar','inquiries.manage'), ('registrar','students.export'), ('registrar','certificates.issue'))
ON CONFLICT DO NOTHING;
