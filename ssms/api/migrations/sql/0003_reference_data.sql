-- Reference data (global, not tenant data): the 11 system roles, 54 permissions and the default
-- role -> permission map (design/15-security.md#152-rbac). Fixed role ids match design/sql/seed.sql.
-- Idempotent: the demo seed inserts the same rows with ON CONFLICT DO NOTHING.
SET ROLE ssms_owner;

INSERT INTO roles (id, code, name_en, name_sw) VALUES
 ('00000003-0000-4000-8000-000000000001'::uuid,  'school_admin',      'School administrator', 'Msimamizi wa shule'),
 ('00000003-0000-4000-8000-000000000002'::uuid,  'bursar',            'Bursar',               'Mhasibu'),
 ('00000003-0000-4000-8000-000000000003'::uuid,  'teacher',           'Teacher',              'Mwalimu'),
 ('00000003-0000-4000-8000-000000000004'::uuid,  'department_head',   'Head of department',   'Mkuu wa idara'),
 ('00000003-0000-4000-8000-000000000005'::uuid,  'parent',            'Parent / guardian',    'Mzazi / mlezi'),
 ('00000003-0000-4000-8000-000000000006'::uuid,  'student',           'Student',              'Mwanafunzi'),
 ('00000003-0000-4000-8000-000000000007'::uuid,  'gatekeeper',        'Gatekeeper',           'Mlinzi wa geti'),
 ('00000003-0000-4000-8000-000000000008'::uuid,  'bank_officer',      'Bank officer',         'Afisa wa benki'),
 ('00000003-0000-4000-8000-000000000009'::uuid,  'hostel_master',     'Hostel master',        'Mlezi wa bweni'),
 ('00000003-0000-4000-8000-00000000000a'::uuid, 'transport_officer', 'Transport officer',    'Afisa usafiri'),
 ('00000003-0000-4000-8000-00000000000b'::uuid, 'librarian',         'Librarian',            'Mkutubi')
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

RESET ROLE;
