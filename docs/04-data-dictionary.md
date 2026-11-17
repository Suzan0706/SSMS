# 4. Data Dictionary

Generated from the live schema ([db/schema.sql](../db/schema.sql)), so types, lengths and constraints match the DDL exactly. Descriptions and examples come from the seed data.

**Constraint legend:** PK primary key · FK → foreign key target · UK unique · NN not null · DEF default · CK check constraint (rule shown) · ID identity (auto-number) · GEN generated column · EX exclusion constraint.

Tables (35): [exam_scales](#exam_scales) · [grading_scales](#grading_scales) · [division_scales](#division_scales) · [users](#users) · [staff](#staff) · [departments](#departments) · [instructors](#instructors) · [guardians](#guardians) · [students](#students) · [student_guardians](#student_guardians) · [student_status_history](#student_status_history) · [academic_years](#academic_years) · [terms](#terms) · [class_levels](#class_levels) · [subjects](#subjects) · [instructor_subjects](#instructor_subjects) · [designations](#designations) · [instructor_designations](#instructor_designations) · [courses](#courses) · [course_subjects](#course_subjects) · [course_offerings](#course_offerings) · [rooms](#rooms) · [schedules](#schedules) · [enrolment_requirements](#enrolment_requirements) · [enrolments](#enrolments) · [enrolment_documents](#enrolment_documents) · [enrolment_schedules](#enrolment_schedules) · [results](#results) · [attendance](#attendance) · [fee_structures](#fee_structures) · [invoices](#invoices) · [invoice_items](#invoice_items) · [transactions](#transactions) · [refresh_tokens](#refresh_tokens) · [audit_logs](#audit_logs)

## exam_scales

NECTA examination scale used to grade a level.

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| exam_scale | VARCHAR | 5 | PK | Scale code | `CSEE` |
| name_en | VARCHAR | 80 | NN | Name (English) | `Certificate of Secondary Education Examination` |
| name_sw | VARCHAR | 80 | NN | Name (Kiswahili) | `Mtihani wa Kidato cha Nne` |
| best_n_subjects | SMALLINT | — | CK `best_n_subjects BETWEEN 1 AND 10` | Number of best subjects counted for the division | `7` |

## grading_scales

Grade boundaries per scale. Grade = row with the highest min_score ≤ score.

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| grading_scale_id | INTEGER | — | PK; ID | Surrogate key | `1` |
| exam_scale | VARCHAR | 5 | UK (exam_scale, grade); UK (exam_scale, min_score); FK → exam_scales.exam_scale; NN | Scale this boundary belongs to | `CSEE` |
| grade | VARCHAR | 2 | UK (exam_scale, grade); NN | Letter grade | `B` |
| min_score | NUMERIC | 5,2 | CK `(min_score >= 0) AND (max_score <= 100) AND (max_score >= min_score)`; UK (exam_scale, min_score); NN | Lowest score for the grade | `65.00` |
| max_score | NUMERIC | 5,2 | CK `(min_score >= 0) AND (max_score <= 100) AND (max_score >= min_score)`; NN | Highest score for the grade (display) | `74.99` |
| points | SMALLINT | — | CK `points BETWEEN 1 AND 9`; NN | NECTA points (1 = best) | `2` |
| remark_en | VARCHAR | 20 | NN | Remark (English) | `Very Good` |
| remark_sw | VARCHAR | 20 | NN | Remark (Kiswahili) | `Vizuri Sana` |

## division_scales

Division bands by total points.

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| division_scale_id | INTEGER | — | PK; ID | Surrogate key | `1` |
| exam_scale | VARCHAR | 5 | UK (exam_scale, division); FK → exam_scales.exam_scale; NN | Scale | `CSEE` |
| division | VARCHAR | 3 | UK (exam_scale, division); NN | Division | `I` |
| min_points | SMALLINT | — | CK `max_points >= min_points`; NN | Lowest total points | `7` |
| max_points | SMALLINT | — | CK `max_points >= min_points`; NN | Highest total points | `17` |

## users

One row per person who can log in. Holds the abstract Person attributes and the account.

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| user_id | BIGINT | — | PK; ID | Surrogate key | `7` |
| username | VARCHAR | 50 | UK ((lower((username)::text))); NN | Login name (admission no. for students), case-insensitive unique | `s2025-0014` |
| password_hash | VARCHAR | 255 | NN | Argon2id PHC hash, never the password | `$argon2id$v=19$m=65536,t=3,p=4$...` |
| role | VARCHAR | 12 | CK `role IN ('ADMIN', 'REGISTRAR', 'BURSAR', 'INSTRUCTOR', 'STUDENT', 'PARENT')`; NN | Authorisation role | `STUDENT` |
| first_name | VARCHAR | 50 | NN | First name | `Amani` |
| middle_name | VARCHAR | 50 |  | Middle name | `John` |
| last_name | VARCHAR | 50 | NN | Surname | `Massawe` |
| gender | CHAR | 1 | CK `gender IN ('M', 'F'`; NN | M or F | `M` |
| date_of_birth | DATE | — | CK `date_of_birth >= '1920-01-01'` | Date of birth (age is computed) | `2012-03-14` |
| phone | VARCHAR | 12 | CK `phone ~ '^255[0-9]{9}$'` | Mobile, 255XXXXXXXXX | `255754000010` |
| email | VARCHAR | 254 | CK `email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$'`; UK ((lower((email)::text)) WHERE (email IS NOT NULL)) | Email, case-insensitive unique | `admin@mfano.sc.tz` |
| preferred_language | CHAR | 2 | CK `preferred_language IN ('sw', 'en'`; NN; DEF 'sw' | UI/SMS language | `sw` |
| is_active | BOOLEAN | — | NN; DEF true | FALSE disables login | `true` |
| failed_login_count | SMALLINT | — | CK `failed_login_count >= 0`; NN; DEF 0 | Consecutive failed logins | `0` |
| locked_until | TIMESTAMPTZ | — |  | Account locked until this time | `2026-03-02 10:15+03` |
| last_login_at | TIMESTAMPTZ | — |  | Last successful login | `2026-03-02 07:58+03` |
| created_at | TIMESTAMPTZ | — | NN; DEF now() | Row created | `2026-01-05 08:00+03` |
| updated_at | TIMESTAMPTZ | — | NN; DEF now() | Row last changed (trigger) | `2026-03-02 07:58+03` |

## staff

Admin, Registrar and Bursar details (subtype of users).

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| staff_id | BIGINT | — | PK; ID | Surrogate key | `2` |
| user_id | BIGINT | — | UK; FK → users.user_id; NN | Account (1:1) | `2` |
| employee_no | VARCHAR | 20 | UK; NN | Employee / check number | `EMP-0002` |
| job_title | VARCHAR | 80 | NN | Job title | `Registrar` |
| hired_on | DATE | — |  | Date hired | `2015-07-01` |
| created_at | TIMESTAMPTZ | — | NN; DEF now() | Row created | `2026-01-05 08:00+03` |

## departments

Academic departments.

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| department_id | INTEGER | — | PK; ID | Surrogate key | `4` |
| code | VARCHAR | 10 | UK; NN | Short code | `MATH` |
| name_en | VARCHAR | 80 | NN | Name (English) | `Mathematics` |
| name_sw | VARCHAR | 80 | NN | Name (Kiswahili) | `Hisabati` |

## instructors

Teaching staff (subtype of users).

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| instructor_id | BIGINT | — | PK; ID | Surrogate key | `1` |
| user_id | BIGINT | — | UK; FK → users.user_id; NN | Account (1:1) | `4` |
| employee_no | VARCHAR | 20 | UK; NN | Government check number | `TCH-0101` |
| department_id | INTEGER | — | FK → departments.department_id; NN | Home department | `4` |
| qualification | VARCHAR | 100 | NN | Highest qualification | `B.Ed. Mathematics` |
| employment_date | DATE | — |  | First appointment date | `2018-01-10` |
| employment_status | VARCHAR | 12 | CK `employment_status IN ('ACTIVE', 'ON_LEAVE', 'TRANSFERRED', 'RETIRED')`; NN; DEF 'ACTIVE' | Employment status | `ACTIVE` |
| max_periods_per_week | SMALLINT | — | CK `max_periods_per_week BETWEEN 1 AND 50`; NN; DEF 30 | Teaching-load ceiling used by the scheduler | `30` |
| created_at | TIMESTAMPTZ | — | NN; DEF now() | Row created | `2026-01-05 08:00+03` |
| updated_at | TIMESTAMPTZ | — | NN; DEF now() | Row last changed | `2026-01-05 08:00+03` |

## guardians

Parents/guardians (subtype of users).

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| guardian_id | BIGINT | — | PK; ID | Surrogate key | `1` |
| user_id | BIGINT | — | UK; FK → users.user_id; NN | Account (1:1) | `10` |
| nida_no | CHAR | 20 | CK `nida_no ~ '^[0-9]{20}$'`; UK | National ID number, 20 digits | `19780512141230000123` |
| occupation | VARCHAR | 80 |  | Occupation | `Farmer` |
| address | VARCHAR | 200 |  | Physical address | `Kisasa, Dodoma` |
| created_at | TIMESTAMPTZ | — | NN; DEF now() | Row created | `2026-01-05 08:00+03` |

## students

Students (subtype of users).

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| student_id | BIGINT | — | PK; ID | Surrogate key | `1` |
| user_id | BIGINT | — | UK; FK → users.user_id; NN | Account (1:1) | `7` |
| admission_no | VARCHAR | 20 | UK; NN | School admission number | `S2025-0014` |
| birth_cert_no | VARCHAR | 30 |  | Birth certificate number | `BC-DOD-2012-004411` |
| necta_index_no | VARCHAR | 20 | UK | NECTA candidate index number | `S0334/0045/2025` |
| admission_date | DATE | — | NN; DEF CURRENT_DATE | Date first admitted | `2025-01-13` |
| current_status | VARCHAR | 12 | CK `current_status IN ('APPLICANT', 'ACTIVE', 'SUSPENDED', 'TRANSFERRED', 'DROPPED_OUT', 'GRADUATED')`; NN; DEF 'APPLICANT' | Current status (history in student_status_history) | `ACTIVE` |
| region | VARCHAR | 40 |  | Home region | `Dodoma` |
| district | VARCHAR | 40 |  | Home district | `Dodoma City` |
| home_address | VARCHAR | 200 |  | Contact address (baseline contact_add) | `Kisasa, Dodoma` |
| created_at | TIMESTAMPTZ | — | NN; DEF now() | Row created | `2025-01-13 09:00+03` |
| updated_at | TIMESTAMPTZ | — | NN; DEF now() | Row last changed | `2026-01-08 09:00+03` |

## student_guardians

Links students to guardians (M:N).

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| student_id | BIGINT | — | PK; FK → students.student_id; UK ((student_id) WHERE is_primary) | Student | `1` |
| guardian_id | BIGINT | — | PK; FK → guardians.guardian_id | Guardian | `1` |
| relationship | VARCHAR | 10 | CK `relationship IN ('FATHER', 'MOTHER', 'GUARDIAN', 'SPONSOR', 'OTHER')`; NN | Relationship to student | `FATHER` |
| is_primary | BOOLEAN | — | UK ((student_id) WHERE is_primary); NN; DEF false | Primary contact (max one per student) | `true` |

## student_status_history

Every status change with reason (event log).

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| history_id | BIGINT | — | PK; ID | Surrogate key | `1` |
| student_id | BIGINT | — | FK → students.student_id; NN | Student | `1` |
| old_status | VARCHAR | 12 | CK `old_status IS DISTINCT FROM new_status` | Status before | `APPLICANT` |
| new_status | VARCHAR | 12 | CK `new_status IN ('APPLICANT', 'ACTIVE', 'SUSPENDED', 'TRANSFERRED', 'DROPPED_OUT', 'GRADUATED')`; CK `old_status IS DISTINCT FROM new_status`; NN | Status after | `ACTIVE` |
| reason | VARCHAR | 300 | NN | Mandatory reason | `Enrolment confirmed - Form I 2025` |
| effective_date | DATE | — | NN; DEF CURRENT_DATE | Date the change takes effect | `2025-01-13` |
| changed_by | BIGINT | — | FK → users.user_id | User who made the change | `2` |
| changed_at | TIMESTAMPTZ | — | NN; DEF now() | Time recorded | `2025-01-13 09:00+03` |

## academic_years

Academic years (January–December).

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| academic_year_id | INTEGER | — | PK; ID | Surrogate key | `1` |
| name | VARCHAR | 9 | UK; NN | Display name | `2026` |
| start_date | DATE | — | CK `end_date > start_date`; NN | First day | `2026-01-01` |
| end_date | DATE | — | CK `end_date > start_date`; NN | Last day | `2026-12-31` |
| is_current | BOOLEAN | — | UK ((is_current) WHERE is_current); NN; DEF false | The single current year | `true` |

## terms

Terms (mihula) of an academic year; dates cannot overlap.

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| term_id | INTEGER | — | PK; ID | Surrogate key | `1` |
| academic_year_id | INTEGER | — | UK (academic_year_id, term_no); EX ex_terms_overlap; FK → academic_years.academic_year_id; NN | Year | `1` |
| term_no | SMALLINT | — | CK `term_no BETWEEN 1 AND 4`; UK (academic_year_id, term_no); NN | 1–4 | `1` |
| name_en | VARCHAR | 30 | NN | Name (English) | `Term One` |
| name_sw | VARCHAR | 30 | NN | Name (Kiswahili) | `Muhula wa Kwanza` |
| start_date | DATE | — | CK `end_date > start_date`; NN | Opening date | `2026-01-12` |
| end_date | DATE | — | CK `end_date > start_date`; NN | Closing date | `2026-06-05` |

## class_levels

Forms and Standards (replaces "year level").

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| level_id | INTEGER | — | PK; ID | Surrogate key | `2` |
| code | VARCHAR | 5 | UK; NN | Short code | `F2` |
| name_en | VARCHAR | 30 | NN | Name (English) | `Form Two` |
| name_sw | VARCHAR | 30 | NN | Name (Kiswahili) | `Kidato cha Pili` |
| education_level | VARCHAR | 12 | CK `education_level IN ('PRE_PRIMARY', 'PRIMARY', 'O_LEVEL', 'A_LEVEL')`; NN | Cycle | `O_LEVEL` |
| exam_scale | VARCHAR | 5 | FK → exam_scales.exam_scale; NN | Grading scale used | `CSEE` |
| sort_order | SMALLINT | — | UK; NN | Ordering for promotion and lists | `12` |

## subjects

Subjects taught, independent of course.

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| subject_id | INTEGER | — | PK; ID | Surrogate key | `9` |
| subject_code | VARCHAR | 10 | UK; NN | School code | `BMATH` |
| necta_code | VARCHAR | 5 |  | NECTA subject code | `041` |
| name_en | VARCHAR | 80 | NN | Name (English) | `Basic Mathematics` |
| name_sw | VARCHAR | 80 | NN | Name (Kiswahili) | `Hisabati za Msingi` |
| department_id | INTEGER | — | FK → departments.department_id; NN | Owning department | `4` |
| room_type_required | VARCHAR | 12 | CK `room_type_required IN ('CLASSROOM', 'LABORATORY', 'ICT_LAB', 'LIBRARY', 'HALL')`; NN; DEF 'CLASSROOM' | Room type the scheduler must use | `CLASSROOM` |
| description | TEXT | — |  | Notes | — |
| is_active | BOOLEAN | — | NN; DEF true | Available for new offerings | `true` |

## instructor_subjects

Subjects an instructor is qualified to teach (M:N).

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| instructor_id | BIGINT | — | PK; FK → instructors.instructor_id | Instructor | `1` |
| subject_id | INTEGER | — | FK → subjects.subject_id; PK | Subject | `9` |

## designations

Designation types (roles within the school).

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| designation_id | INTEGER | — | PK; ID | Surrogate key | `4` |
| code | VARCHAR | 20 | UK; NN | Code | `CLASS_TEACHER` |
| name_en | VARCHAR | 60 | NN | Name (English) | `Class Teacher` |
| name_sw | VARCHAR | 60 | NN | Name (Kiswahili) | `Mwalimu wa Darasa` |

## instructor_designations

Designation held by an instructor in a given year.

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| instructor_designation_id | BIGINT | — | PK; ID | Surrogate key | `2` |
| instructor_id | BIGINT | — | UK (instructor_id, designation_id, academic_year_id, department_id, level_id, stream); FK → instructors.instructor_id; NN | Instructor | `2` |
| designation_id | INTEGER | — | UK (instructor_id, designation_id, academic_year_id, department_id, level_id, stream); FK → designations.designation_id; NN | Designation | `4` |
| academic_year_id | INTEGER | — | UK (instructor_id, designation_id, academic_year_id, department_id, level_id, stream); FK → academic_years.academic_year_id; NN | Year | `1` |
| department_id | INTEGER | — | UK (instructor_id, designation_id, academic_year_id, department_id, level_id, stream); FK → departments.department_id | Department (for HOD) | `4` |
| level_id | INTEGER | — | CK `(level_id IS NULL) = (stream IS NULL)`; UK (instructor_id, designation_id, academic_year_id, department_id, level_id, stream); FK → class_levels.level_id | Class level (for Class Teacher) | `2` |
| stream | VARCHAR | 5 | CK `(level_id IS NULL) = (stream IS NULL)`; UK (instructor_id, designation_id, academic_year_id, department_id, level_id, stream) | Stream (for Class Teacher) | `A` |
| assigned_on | DATE | — | CK `(ended_on IS NULL) OR (ended_on >= assigned_on)`; NN; DEF CURRENT_DATE | Start date | `2026-01-05` |
| ended_on | DATE | — | CK `(ended_on IS NULL) OR (ended_on >= assigned_on)` | End date if ended early | — |
| assigned_by | BIGINT | — | FK → users.user_id | User who assigned | `1` |

## courses

Programme/combination (e.g. OLG, PCM). No school year here.

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| course_id | INTEGER | — | PK; ID | Surrogate key | `2` |
| course_code | VARCHAR | 10 | UK; NN | Code | `PCM` |
| course_name | VARCHAR | 100 | NN | Name (English) | `Physics, Chemistry and Advanced Mathematics` |
| course_name_sw | VARCHAR | 100 | NN | Name (Kiswahili) | `Fizikia, Kemia na Hisabati ya Juu` |
| course_desc | TEXT | — |  | Description | `Form V-VI science combination` |
| education_level | VARCHAR | 12 | CK `education_level IN ('PRE_PRIMARY', 'PRIMARY', 'O_LEVEL', 'A_LEVEL')`; NN | Cycle | `A_LEVEL` |
| is_active | BOOLEAN | — | NN; DEF true | Can be offered | `true` |
| created_at | TIMESTAMPTZ | — | NN; DEF now() | Row created | `2026-01-05 08:00+03` |
| updated_at | TIMESTAMPTZ | — | NN; DEF now() | Row last changed | `2026-01-05 08:00+03` |

## course_subjects

Subjects in a course at a level (M:N).

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| course_id | INTEGER | — | PK; FK → courses.course_id | Course | `1` |
| level_id | INTEGER | — | PK; FK → class_levels.level_id | Level | `2` |
| subject_id | INTEGER | — | PK; FK → subjects.subject_id | Subject | `9` |
| is_compulsory | BOOLEAN | — | NN; DEF true | Compulsory or optional | `true` |
| periods_per_week | SMALLINT | — | CK `periods_per_week BETWEEN 1 AND 12`; NN; DEF 4 | Weekly periods (scheduler demand) | `6` |

## course_offerings

A course opened for one academic year and level (D2 Course Offers).

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| offering_id | BIGINT | — | PK; ID | Surrogate key | `2` |
| course_id | INTEGER | — | UK (course_id, academic_year_id, level_id); FK → courses.course_id; NN | Course | `1` |
| academic_year_id | INTEGER | — | UK (course_id, academic_year_id, level_id); FK → academic_years.academic_year_id; NN | Year | `1` |
| level_id | INTEGER | — | UK (course_id, academic_year_id, level_id); FK → class_levels.level_id; NN | Level | `2` |
| capacity | SMALLINT | — | CK `capacity > 0`; NN | Maximum confirmed enrolments | `160` |
| is_open | BOOLEAN | — | NN; DEF true | Accepting applications | `true` |
| created_at | TIMESTAMPTZ | — | NN; DEF now() | Row created | `2025-11-01 08:00+03` |

## rooms

Classrooms, laboratories and halls.

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| room_id | INTEGER | — | PK; ID | Surrogate key | `4` |
| room_code | VARCHAR | 10 | UK; NN | Code | `LAB-PHY` |
| name | VARCHAR | 60 | NN | Name | `Physics Laboratory` |
| room_type | VARCHAR | 12 | CK `room_type IN ('CLASSROOM', 'LABORATORY', 'ICT_LAB', 'LIBRARY', 'HALL')`; NN; DEF 'CLASSROOM' | Type | `LABORATORY` |
| capacity | SMALLINT | — | CK `capacity > 0`; NN | Seats | `40` |
| is_active | BOOLEAN | — | NN; DEF true | Available for scheduling | `true` |

## schedules

One weekly class session (no student column).

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| schedule_id | BIGINT | — | PK; ID | Surrogate key | `1` |
| offering_id | BIGINT | — | EX ex_schedules_class; FK → course_offerings.offering_id; NN | Course offering (course + year + level) | `2` |
| stream | VARCHAR | 5 | CK `stream ~ '^[A-Z]{1,5}$'`; EX ex_schedules_class; NN; DEF 'A' | Stream | `A` |
| term_id | INTEGER | — | EX ex_schedules_instructor; EX ex_schedules_room; EX ex_schedules_class; FK → terms.term_id; NN | Term | `1` |
| subject_id | INTEGER | — | FK → subjects.subject_id; NN | Subject | `9` |
| instructor_id | BIGINT | — | FK → instructors.instructor_id; EX ex_schedules_instructor; NN | Instructor | `1` |
| room_id | INTEGER | — | EX ex_schedules_room; FK → rooms.room_id; NN | Room | `2` |
| day_of_week | SMALLINT | — | CK `day_of_week BETWEEN 1 AND 6`; EX ex_schedules_instructor; EX ex_schedules_room; EX ex_schedules_class; NN | 1 = Monday … 6 = Saturday | `1` |
| time_start | TIME | — | CK `time_end > time_start`; NN | Start time | `08:00` |
| time_end | TIME | — | CK `time_end > time_start`; NN | End time (> start) | `08:40` |
| slot | TIMERANGE | — | EX ex_schedules_instructor; EX ex_schedules_room; EX ex_schedules_class; GEN | Generated [start, end) range used by clash constraints | `[08:00,08:40)` |
| created_by | BIGINT | — | FK → users.user_id | User who created | `1` |
| created_at | TIMESTAMPTZ | — | NN; DEF now() | Row created | `2026-01-05 08:00+03` |
| updated_at | TIMESTAMPTZ | — | NN; DEF now() | Row last changed | `2026-01-05 08:00+03` |

## enrolment_requirements

Documents required to enrol.

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| requirement_id | INTEGER | — | PK; ID | Surrogate key | `1` |
| code | VARCHAR | 20 | UK; NN | Code | `BIRTH_CERT` |
| name_en | VARCHAR | 100 | NN | Name (English) | `Birth certificate` |
| name_sw | VARCHAR | 100 | NN | Name (Kiswahili) | `Cheti cha kuzaliwa` |
| description | TEXT | — |  | Instructions to applicants | — |
| education_level | VARCHAR | 12 | CK `education_level IN ('PRE_PRIMARY', 'PRIMARY', 'O_LEVEL', 'A_LEVEL')` | Level it applies to (NULL = all) | `A_LEVEL` |
| is_mandatory | BOOLEAN | — | NN; DEF true | Must be VALID to enrol | `true` |
| is_active | BOOLEAN | — | NN; DEF true | In use | `true` |

## enrolments

A student's application/enrolment in one offering (D6).

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| enrolment_id | BIGINT | — | PK; ID | Surrogate key | `1` |
| enrolment_no | VARCHAR | 20 | UK; NN | Reference number | `ENR-2026-000001` |
| student_id | BIGINT | — | FK → students.student_id; NN | Student | `1` |
| offering_id | BIGINT | — | FK → course_offerings.offering_id; NN | Course offering | `2` |
| stream | VARCHAR | 5 | CK `stream ~ '^[A-Z]{1,5}$'`; CK `(status <> 'CONFIRMED') OR ((confirmed_at IS NOT NULL) AND (stream IS NOT NULL))` | Stream assigned on confirmation | `A` |
| status | VARCHAR | 10 | CK `status IN ('PENDING', 'SUBMITTED', 'INVALID', 'VALIDATED', 'CONFIRMED', 'CANCELLED')`; CK `(status <> 'CONFIRMED') OR ((confirmed_at IS NOT NULL) AND (stream IS NOT NULL))`; CK `(status <> 'CANCELLED') OR ((cancelled_at IS NOT NULL) AND (cancel_reason IS NOT NULL))`; NN; DEF 'PENDING' | PENDING → SUBMITTED → VALIDATED/INVALID → CONFIRMED, or CANCELLED | `CONFIRMED` |
| applied_at | TIMESTAMPTZ | — | NN; DEF now() | Application time | `2025-12-01 10:00+03` |
| submitted_at | TIMESTAMPTZ | — |  | Documents submitted | `2025-12-01 10:30+03` |
| confirmed_at | TIMESTAMPTZ | — | CK `(status <> 'CONFIRMED') OR ((confirmed_at IS NOT NULL) AND (stream IS NOT NULL))` | Confirmation time | `2026-01-08 09:00+03` |
| confirmed_by | BIGINT | — | FK → users.user_id | Registrar who confirmed | `2` |
| cancelled_at | TIMESTAMPTZ | — | CK `(status <> 'CANCELLED') OR ((cancelled_at IS NOT NULL) AND (cancel_reason IS NOT NULL))` | Cancellation time | — |
| cancel_reason | VARCHAR | 300 | CK `(status <> 'CANCELLED') OR ((cancelled_at IS NOT NULL) AND (cancel_reason IS NOT NULL))` | Why cancelled | — |
| created_at | TIMESTAMPTZ | — | NN; DEF now() | Row created | `2025-12-01 10:00+03` |
| updated_at | TIMESTAMPTZ | — | NN; DEF now() | Row last changed | `2026-01-08 09:00+03` |

## enrolment_documents

Uploaded requirement files and their validation.

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| document_id | BIGINT | — | PK; ID | Surrogate key | `1` |
| enrolment_id | BIGINT | — | UK (enrolment_id, requirement_id); FK → enrolments.enrolment_id; NN | Enrolment | `3` |
| requirement_id | INTEGER | — | UK (enrolment_id, requirement_id); FK → enrolment_requirements.requirement_id; NN | Requirement satisfied | `1` |
| file_name | VARCHAR | 255 | NN | Original file name | `cheti_kuzaliwa.pdf` |
| storage_key | VARCHAR | 255 | UK; NN | Object-storage key | `enrolments/3/BIRTH_CERT/7f3a.pdf` |
| mime_type | VARCHAR | 50 | CK `mime_type IN ('application/pdf', 'image/jpeg', 'image/png')`; NN | PDF/JPEG/PNG only | `application/pdf` |
| file_size_bytes | INTEGER | — | CK `file_size_bytes BETWEEN 1 AND 5242880`; NN | Size, max 5 MB | `284113` |
| sha256 | CHAR | 64 | NN | Checksum for tamper detection | `9f86d0…` |
| status | VARCHAR | 8 | CK `status IN ('PENDING', 'VALID', 'INVALID')`; CK `(status = 'PENDING') OR ((validated_by IS NOT NULL) AND (validated_at IS NOT NULL))`; CK `(status <> 'INVALID') OR (remarks IS NOT NULL)`; NN; DEF 'PENDING' | PENDING, VALID or INVALID | `VALID` |
| remarks | VARCHAR | 300 | CK `(status <> 'INVALID') OR (remarks IS NOT NULL)` | Required when INVALID | `Scan is unreadable` |
| uploaded_at | TIMESTAMPTZ | — | NN; DEF now() | Upload time | `2026-01-06 09:10+03` |
| validated_by | BIGINT | — | CK `(status = 'PENDING') OR ((validated_by IS NOT NULL) AND (validated_at IS NOT NULL))`; FK → users.user_id | Instructor who validated | `6` |
| validated_at | TIMESTAMPTZ | — | CK `(status = 'PENDING') OR ((validated_by IS NOT NULL) AND (validated_at IS NOT NULL))` | Validation time | `2026-01-07 10:00+03` |

## enrolment_schedules

Which class sessions an enrolled student attends (M:N).

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| enrolment_id | BIGINT | — | PK; FK → enrolments.enrolment_id | Enrolment | `1` |
| schedule_id | BIGINT | — | PK; FK → schedules.schedule_id | Class session | `1` |
| assigned_at | TIMESTAMPTZ | — | NN; DEF now() | When linked | `2026-01-08 09:00+03` |

## results

Scores per subject, term and assessment. Grade is derived.

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| result_id | BIGINT | — | PK; ID | Surrogate key | `1` |
| enrolment_id | BIGINT | — | UK (enrolment_id, subject_id, term_id, assessment_type); FK → enrolments.enrolment_id; NN | Enrolment (student + year) | `1` |
| subject_id | INTEGER | — | UK (enrolment_id, subject_id, term_id, assessment_type); FK → subjects.subject_id; NN | Subject | `9` |
| term_id | INTEGER | — | UK (enrolment_id, subject_id, term_id, assessment_type); FK → terms.term_id; NN | Term | `1` |
| assessment_type | VARCHAR | 10 | CK `assessment_type IN ('MONTHLY', 'MIDTERM', 'TERMINAL', 'ANNUAL', 'MOCK')`; UK (enrolment_id, subject_id, term_id, assessment_type); NN | MONTHLY, MIDTERM, TERMINAL, ANNUAL, MOCK | `MIDTERM` |
| score | NUMERIC | 5,2 | CK `score BETWEEN 0 AND 100`; NN | Score 0–100 | `78.50` |
| is_published | BOOLEAN | — | NN; DEF false | Visible to student/parent | `true` |
| entered_by | BIGINT | — | FK → users.user_id; NN | Instructor who entered | `4` |
| entered_at | TIMESTAMPTZ | — | NN; DEF now() | Entry time | `2026-03-20 15:00+03` |
| updated_at | TIMESTAMPTZ | — | NN; DEF now() | Row last changed | `2026-03-20 15:00+03` |

## attendance

Attendance per student, session and date.

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| attendance_id | BIGINT | — | PK; ID | Surrogate key | `1` |
| enrolment_id | BIGINT | — | UK (enrolment_id, schedule_id, attendance_date); FK → enrolment_schedules.enrolment_id; NN | Enrolment | `1` |
| schedule_id | BIGINT | — | UK (enrolment_id, schedule_id, attendance_date); FK → enrolment_schedules.schedule_id; NN | Session | `1` |
| attendance_date | DATE | — | UK (enrolment_id, schedule_id, attendance_date); NN | Date of the lesson | `2026-03-02` |
| status | VARCHAR | 8 | CK `status IN ('PRESENT', 'ABSENT', 'LATE', 'EXCUSED')`; NN | PRESENT, ABSENT, LATE, EXCUSED | `PRESENT` |
| remarks | VARCHAR | 200 |  | Notes | `Sick note` |
| recorded_by | BIGINT | — | FK → users.user_id; NN | Instructor | `4` |
| recorded_at | TIMESTAMPTZ | — | NN; DEF now() | Time recorded | `2026-03-02 08:05+03` |

## fee_structures

Fee items per term, level and optional course.

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| fee_structure_id | BIGINT | — | PK; ID | Surrogate key | `1` |
| term_id | INTEGER | — | UK (term_id, level_id, course_id, fee_item); FK → terms.term_id; NN | Term billed | `1` |
| level_id | INTEGER | — | UK (term_id, level_id, course_id, fee_item); FK → class_levels.level_id; NN | Level | `2` |
| course_id | INTEGER | — | UK (term_id, level_id, course_id, fee_item); FK → courses.course_id | Course (NULL = all) | — |
| fee_item | VARCHAR | 12 | CK `fee_item IN ('TUITION', 'BOARDING', 'MEALS', 'EXAMINATION', 'UNIFORM', 'DEVELOPMENT', 'OTHER')`; UK (term_id, level_id, course_id, fee_item); NN | Category | `TUITION` |
| description | VARCHAR | 120 | NN | Line text | `Tuition fee - Term One` |
| amount_tzs | NUMERIC | 14,2 | CK `amount_tzs >= 0`; NN | Amount in TZS | `450000.00` |
| is_mandatory | BOOLEAN | — | NN; DEF true | Mandatory or optional | `true` |

## invoices

Bill to a student for a term (total/balance in v_invoice_balances).

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| invoice_id | BIGINT | — | PK; UK (invoice_id, student_id); ID | Surrogate key | `1` |
| invoice_no | VARCHAR | 20 | UK; NN | Invoice number | `INV-2026-000001` |
| student_id | BIGINT | — | UK (invoice_id, student_id); FK → students.student_id; NN | Student | `1` |
| term_id | INTEGER | — | FK → terms.term_id; NN | Term | `1` |
| gepg_control_no | VARCHAR | 12 | CK `gepg_control_no ~ '^[0-9]{12}$'`; UK | GePG control number, 12 digits | `994120000001` |
| issued_at | TIMESTAMPTZ | — | NN; DEF now() | Issue time | `2026-01-08 12:00+03` |
| due_date | DATE | — | NN | Due date | `2026-02-15` |
| issued_by | BIGINT | — | FK → users.user_id | Bursar | `3` |
| cancelled_at | TIMESTAMPTZ | — | CK `(cancelled_at IS NULL) = (cancel_reason IS NULL)` | Cancellation time | — |
| cancel_reason | VARCHAR | 300 | CK `(cancelled_at IS NULL) = (cancel_reason IS NULL)` | Why cancelled | — |

## invoice_items

Lines of an invoice (snapshot of the fee at billing time).

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| invoice_item_id | BIGINT | — | PK; ID | Surrogate key | `1` |
| invoice_id | BIGINT | — | FK → invoices.invoice_id; NN | Invoice | `1` |
| fee_structure_id | BIGINT | — | FK → fee_structures.fee_structure_id | Source fee item | `1` |
| description | VARCHAR | 120 | NN | Line text | `Tuition fee - Term One` |
| amount_tzs | NUMERIC | 14,2 | CK `amount_tzs >= 0`; NN | Amount in TZS | `450000.00` |

## transactions

Append-only money ledger (baseline Transaction, corrected) (D5).

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| trans_id | BIGINT | — | PK; ID | Surrogate key | `1` |
| trans_no | VARCHAR | 20 | UK; NN | Transaction number | `TXN-2026-000001` |
| trans_type | VARCHAR | 10 | CK `trans_type IN ('PAYMENT', 'REFUND', 'WAIVER', 'REVERSAL')`; CK `(trans_type IN ('WAIVER', 'REVERSAL')) OR (payment_method IS NOT NULL)`; CK `(trans_type = 'REVERSAL') = (reverses_trans_id IS NOT NULL)`; NN | PAYMENT, REFUND, WAIVER, REVERSAL | `PAYMENT` |
| trans_name | VARCHAR | 120 | NN | Description (baseline field) | `School fees Term One (M-Pesa)` |
| student_id | BIGINT | — | FK → students.student_id; FK → invoices.invoice_id; NN | Student | `1` |
| invoice_id | BIGINT | — | FK → invoices.student_id | Invoice settled (optional) | `1` |
| amount_tzs | NUMERIC | 14,2 | CK `amount_tzs > 0`; NN | Amount in TZS (> 0) | `400000.00` |
| payment_method | VARCHAR | 12 | CK `payment_method IN ('CASH', 'BANK', 'MPESA', 'TIGO_PESA', 'AIRTEL_MONEY', 'GEPG')`; CK `(trans_type IN ('WAIVER', 'REVERSAL')) OR (payment_method IS NOT NULL)`; CK `(payment_method IS NULL) OR (payment_method = 'CASH') OR (reference_no IS NOT NULL)`; UK (payment_method, reference_no) | CASH, BANK, MPESA, TIGO_PESA, AIRTEL_MONEY, GEPG | `MPESA` |
| reference_no | VARCHAR | 50 | CK `(payment_method IS NULL) OR (payment_method = 'CASH') OR (reference_no IS NOT NULL)`; UK (payment_method, reference_no) | Receipt/reference from provider | `QKJ7H2LM9P` |
| payer_name | VARCHAR | 100 |  | Who paid | `John Massawe` |
| payer_phone | VARCHAR | 12 | CK `payer_phone ~ '^255[0-9]{9}$'` | Payer phone | `255754000010` |
| status | VARCHAR | 10 | CK `status IN ('PENDING', 'COMPLETED', 'FAILED')`; NN; DEF 'PENDING' | PENDING, COMPLETED, FAILED | `COMPLETED` |
| source | VARCHAR | 10 | CK `source IN ('MANUAL', 'GEPG', 'MOBILE_API')`; CK `(source <> 'MANUAL') OR (recorded_by IS NOT NULL)`; NN; DEF 'MANUAL' | MANUAL, GEPG, MOBILE_API | `MANUAL` |
| reverses_trans_id | BIGINT | — | CK `(trans_type = 'REVERSAL') = (reverses_trans_id IS NOT NULL)`; UK; FK → transactions.trans_id | Original transaction reversed | — |
| trans_date | TIMESTAMPTZ | — | NN; DEF now() | When money moved | `2026-01-10 10:15+03` |
| recorded_by | BIGINT | — | CK `(source <> 'MANUAL') OR (recorded_by IS NOT NULL)`; FK → users.user_id | Bursar (NULL for callbacks) | `3` |
| created_at | TIMESTAMPTZ | — | NN; DEF now() | Row created | `2026-01-10 10:16+03` |

## refresh_tokens

Hashed refresh tokens for JWT rotation (D7).

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| token_id | BIGINT | — | PK; ID | Surrogate key | `1` |
| user_id | BIGINT | — | FK → users.user_id; NN | Owner | `7` |
| token_hash | CHAR | 64 | UK; NN | SHA-256 of the token | `e3b0c442…` |
| family_id | UUID | — | NN | Rotation chain id | `2b1e…` |
| issued_at | TIMESTAMPTZ | — | CK `expires_at > issued_at`; NN; DEF now() | Issued | `2026-03-02 07:58+03` |
| expires_at | TIMESTAMPTZ | — | CK `expires_at > issued_at`; NN | Expiry (7 days) | `2026-03-09 07:58+03` |
| revoked_at | TIMESTAMPTZ | — |  | Revoked (rotation/logout) | — |
| user_agent | VARCHAR | 255 |  | Client | `Mozilla/5.0 (Linux; Android 13)` |
| ip_address | INET | — |  | Client IP | `197.250.1.20` |

## audit_logs

Append-only audit trail of changes and security events.

| Field | Type | Length | Constraints | Description | Example |
|---|---|---|---|---|---|
| audit_id | BIGINT | — | PK; ID | Surrogate key | `1201` |
| occurred_at | TIMESTAMPTZ | — | NN; DEF now() | Event time | `2026-03-02 10:12+03` |
| actor_user_id | BIGINT | — | FK → users.user_id | Who (NULL = system) | `2` |
| actor_role | VARCHAR | 12 |  | Role at the time | `REGISTRAR` |
| action | VARCHAR | 20 | CK `action IN ('INSERT', 'UPDATE', 'DELETE', 'LOGIN', 'LOGIN_FAILED', 'LOGOUT', 'TOKEN_REFRESH', 'TOKEN_REUSE', 'PASSWORD_CHANGE', 'EXPORT', 'VIEW_SENSITIVE')`; NN | INSERT, UPDATE, DELETE, LOGIN … | `UPDATE` |
| entity_type | VARCHAR | 40 | NN | Table/entity | `students` |
| entity_id | VARCHAR | 40 |  | Primary key value | `2` |
| old_values | JSONB | — |  | Row before (no password hash) | `{"current_status":"ACTIVE"}` |
| new_values | JSONB | — |  | Row after (no password hash) | `{"current_status":"SUSPENDED"}` |
| ip_address | INET | — |  | Client IP | `197.250.1.20` |
| user_agent | VARCHAR | 255 |  | Client | `Mozilla/5.0` |
| request_id | UUID | — |  | Correlation id | `8c1d…` |

## Views

| View | Purpose | Key columns |
|---|---|---|
| v_invoice_balances | Invoice total, paid, balance and payment status (UNPAID, PARTIALLY_PAID, PAID, OVERDUE, CANCELLED) | invoice_id, total_tzs, paid_tzs, balance_tzs, payment_status |
| v_student_results | Scores with the NECTA grade, points and bilingual remark for the student's level | student_id, subject_id, term_id, score, grade, points |
| v_class_lists | "List of Students" per class session for instructors | schedule_id, admission_no, names |
| v_student_current_enrolment | Each student's confirmed enrolment in the current academic year | student_id, offering_id, level_id, stream |
