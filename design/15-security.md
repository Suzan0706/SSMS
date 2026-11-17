# 15. Security Design

## 15.1 Threats and controls at a glance

| Threat | Control |
|---|---|
| A user of school A sees or changes school B data | Tenant dependency + **forced RLS** + composite FKs; runtime role `ssms_app` cannot bypass RLS (tests I01–I07) |
| A lookup before login leaks data | Five **resolver** functions return ids only (I11–I16) |
| Credential stuffing / brute force | Argon2id, lockout after 5 failures, Nginx and Redis rate limits, OTP throttling, generic messages |
| Token theft | 15-minute access JWT; refresh token httpOnly + Secure + SameSite=Strict cookie; rotation with reuse detection |
| Mass assignment / injection | Pydantic v2 schemas with explicit fields; SQLAlchemy bound parameters; no string-built SQL |
| XSS / CSRF | React escaping, strict CSP, no inline scripts; bearer header (not cookie) for API calls; refresh endpoint checks `Origin` and SameSite |
| Fraudulent payment callbacks | Signature verification, IP allow-list, idempotent insert per school, amount and bill cross-check, daily reconciliation |
| Insider tampering with marks or money | Frozen results + amendments with maker-checker; append-only ledger with balanced journals; reversals by two people; append-only audit log |
| Data breach through backups or dumps | Application-level encryption of phones, NIDA, birth-certificate numbers and health notes; encrypted backups |
| Abuse of exports | `reports.export` permission, `EXPORT` audit rows, watermark with user and time |

## 15.2 RBAC

- **Model.** Roles are a global catalogue, permissions are `module.action`, and users hold roles **per school** (`user_roles.school_id`).
- **Backend check.** Every route declares `require_permission(code)`. The JWT carries only `sub` and `sch` (plus informational `roles`). The user's status, the school's status and the permissions are loaded on every request, so a revoked role, a disabled user or a suspended school stops working immediately ([ADR 0011](adr/0011-permissions-per-request.md)).
- **Ownership on top of permissions.**
  - Parents (`portal.parent`) see only students linked through `student_guardians`.
  - Students (`portal.student`) see only themselves.
  - Teachers enter marks only for their `teaching_assignments`; class teachers comment only on their stream.
  - Anything that fails an ownership check returns 404, not 403.
- **Super admin** is a platform operator (`platform_admins`, separate console, role `ssms_platform`). It is not in this matrix and never appears in a school's user list.
- **Matrix.** The table below is **generated from the seeded `role_permissions`**, so it is exactly what the database grants.

<!-- BEGIN rbac -->
| Permission | Admin | HoD | Teacher | Bursar | Bank | Gate | Hostel | Transport | Library | Parent | Student |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `academics.configure` | ✔ |  |  |  |  |  |  |  |  |  |  |
| `attendance.device` |  |  |  |  |  | ✔ |  |  |  |  |  |
| `attendance.read` | ✔ | ✔ | ✔ |  |  |  |  |  |  |  |  |
| `attendance.take` | ✔ |  | ✔ |  |  |  |  |  |  |  |  |
| `announcements.send` | ✔ |  |  |  |  |  |  |  |  |  |  |
| `sms.manage` | ✔ |  |  |  |  |  |  |  |  |  |  |
| `enrolment.decide` | ✔ |  |  |  |  |  |  |  |  |  |  |
| `enrolment.manage` | ✔ |  |  |  |  |  |  |  |  |  |  |
| `enrolment.validate` | ✔ |  | ✔ |  |  |  |  |  |  |  |  |
| `exams.manage` | ✔ | ✔ |  |  |  |  |  |  |  |  |  |
| `exams.read` | ✔ | ✔ | ✔ |  |  |  |  |  |  |  |  |
| `hostel.manage` | ✔ |  |  |  |  |  | ✔ |  |  |  |  |
| `library.manage` | ✔ |  |  |  |  |  |  |  | ✔ |  |  |
| `transport.manage` | ✔ |  |  |  |  |  |  | ✔ |  |  |  |
| `venues.manage` | ✔ |  |  |  |  |  |  |  |  |  |  |
| `fees.configure` | ✔ |  |  | ✔ |  |  |  |  |  |  |  |
| `finance.read` | ✔ |  |  | ✔ |  |  |  |  |  |  |  |
| `invoices.manage` | ✔ |  |  | ✔ |  |  |  |  |  |  |  |
| `payments.confirm_bank` |  |  |  |  | ✔ |  |  |  |  |  |  |
| `payments.record` | ✔ |  |  | ✔ |  |  |  |  |  |  |  |
| `payments.reverse_approve` | ✔ |  |  |  |  |  |  |  |  |  |  |
| `payments.reverse_request` | ✔ |  |  | ✔ |  |  |  |  |  |  |  |
| `reconciliation.run` | ✔ |  |  | ✔ |  |  |  |  |  |  |  |
| `portal.parent` |  |  |  |  |  |  |  |  |  | ✔ |  |
| `portal.student` |  |  |  |  |  |  |  |  |  |  | ✔ |
| `reports.export` | ✔ |  |  | ✔ |  |  |  |  |  |  |  |
| `reports.read` | ✔ | ✔ | ✔ | ✔ |  |  |  |  |  |  |  |
| `marks.enter` | ✔ | ✔ | ✔ |  |  |  |  |  |  |  |  |
| `results.amend_approve` | ✔ |  |  |  |  |  |  |  |  |  |  |
| `results.amend_request` | ✔ | ✔ | ✔ |  |  |  |  |  |  |  |  |
| `results.publish` | ✔ |  |  |  |  |  |  |  |  |  |  |
| `results.read` | ✔ | ✔ | ✔ |  |  |  |  |  |  |  |  |
| `audit.read` | ✔ |  |  |  |  |  |  |  |  |  |  |
| `privacy.manage` | ✔ |  |  |  |  |  |  |  |  |  |  |
| `settings.update` | ✔ |  |  |  |  |  |  |  |  |  |  |
| `payroll.read` | ✔ |  |  |  |  |  |  |  |  |  |  |
| `staff.manage` | ✔ |  |  |  |  |  |  |  |  |  |  |
| `staff.read` | ✔ | ✔ |  |  |  |  |  |  |  |  |  |
| `activities.manage` | ✔ |  |  |  |  |  |  |  |  |  |  |
| `discipline.manage` | ✔ |  | ✔ |  |  |  |  |  |  |  |  |
| `discipline.read` | ✔ |  |  |  |  |  |  |  |  |  |  |
| `health.manage` | ✔ |  |  |  |  |  |  |  |  |  |  |
| `health.read` | ✔ |  |  |  |  |  |  |  |  |  |  |
| `guardians.manage` | ✔ |  |  |  |  |  |  |  |  |  |  |
| `students.create` | ✔ |  |  |  |  |  |  |  |  |  |  |
| `students.import` | ✔ |  |  |  |  |  |  |  |  |  |  |
| `students.read` | ✔ | ✔ | ✔ | ✔ |  |  | ✔ | ✔ | ✔ |  |  |
| `students.status` | ✔ |  |  |  |  |  |  |  |  |  |  |
| `students.update` | ✔ |  |  |  |  |  |  |  |  |  |  |
| `timetable.manage` | ✔ |  |  |  |  |  |  |  |  |  |  |
| `timetable.read` | ✔ | ✔ | ✔ |  |  |  |  |  |  |  |  |
| `roles.assign` | ✔ |  |  |  |  |  |  |  |  |  |  |
| `users.manage` | ✔ |  |  |  |  |  |  |  |  |  |  |
| `users.read` | ✔ |  |  |  |  |  |  |  |  |  |  |
<!-- END rbac -->

**Sensitive permissions:**

- `payroll.read` (salaries), `health.read` (health notes, logged as `VIEW_SENSITIVE`), `audit.read` and `privacy.manage` belong to `school_admin` only.
- `results.amend_approve` and `payments.reverse_approve` also require a **different user** from the requester, enforced by the database.

## 15.3 Row-level security and resolvers

**Roles:**

| Role | Login | Bypass RLS | Used by | Privileges |
|---|---|---|---|---|
| `ssms_owner` | no | no (RLS is FORCED) | migrations, seeds | owns objects |
| `ssms_app` | yes | **no** | API, Celery | SELECT/INSERT/UPDATE; DELETE only on `otp_codes`, `refresh_tokens`, `idempotency_keys`, `notifications`; no UPDATE on ledgers, frozen results, `audit_logs`; no access to `platform_admins` |
| `ssms_resolver` | no | yes | owns the 6 resolver functions only | SELECT on the few columns they read |
| `ssms_platform` | via a console login | yes | super-admin console | SELECT/INSERT/UPDATE, no DELETE |
| `ssms_reporting` | via a read-only login | no | analytics replica | SELECT, no credentials, tokens or health data |

**Policy on all 94 tenant tables and `schools`:**

```sql
ALTER TABLE x ENABLE ROW LEVEL SECURITY;
ALTER TABLE x FORCE ROW LEVEL SECURITY;               -- applies to the owner too
CREATE POLICY tenant_isolation ON x
    USING (school_id = app_school_id())
    WITH CHECK (school_id = app_school_id());
-- app_school_id() = NULLIF(current_setting('app.school_id', true), '')::uuid  → unset = no rows
```

**Request context.**

- The API runs `SET LOCAL app.school_id = <jwt.sch>` (plus `app.user_id`, `app.request_id`, `app.client_ip`) at the start of every transaction. Celery does the same per job.
- `SET LOCAL` is transaction-scoped, so it is safe with PgBouncer in transaction mode and can never leak to the next request on the same connection.

**Resolvers** are the only cross-tenant reads. Each is `SECURITY DEFINER`, `SET search_path = pg_catalog, public`, owned by `ssms_resolver`, with EXECUTE revoked from PUBLIC and granted only to `ssms_app`:

| Function | Input | Output | Used for | Test |
|---|---|---|---|---|
| `resolve_school_by_code(code)` | URL sub-domain or login field | `school_id` (ACTIVE/ONBOARDING only) | login, public enrolment pages | I11 |
| `resolve_device(api_key_hash)` | SHA-256 of `X-Device-Key` | `(school_id, device_id)` (active devices) | gate taps | I12 |
| `resolve_gepg_bill(control_number \| bill_ref)` | GePG callback fields | `(school_id, bill_id)` | payment and bill callbacks | I13 |
| `resolve_refresh_token(token_hash)` | SHA-256 of the cookie | `(school_id, user_id, family_id)`, also for revoked tokens so reuse can be detected | token refresh | I14 |
| `resolve_users_by_phone(phone_hash)` | HMAC blind index of the phone | list of `(school_id, user_id)`, **guardians only**, active schools | parent OTP login | I15 |
| `list_active_school_ids()` | — | school ids | Celery beat fan-out | — |

Each returns identifiers only. The caller then sets the tenant context and reads everything else under RLS. Test I11 also proves that calling a resolver does not open table access.

## 15.4 Authentication

| Item | Design |
|---|---|
| Passwords | Argon2id (pwdlib defaults m=64 MiB, t=3, p=4); re-hash on login when parameters change; policy ≥ 10 characters with letters and digits; breached-password check (k-anonymity range API) — optional, **VERIFY** connectivity |
| Lockout | 5 consecutive failures → `locked_until = now + 15 min` → 423; audited |
| Enumeration | Same 401 body for unknown user and wrong password; dummy hash for unknown users; OTP request always answers "code sent" |
| Access JWT | HS256 with a 64-byte secret (or RS256 when other services verify); claims `sub`, `sch`, `roles`, `typ`, `aud` (`ssms-app`; the console uses `ssms-platform`), `iat`, `exp` (15 min), `jti`; kept in memory only, never in localStorage |
| Refresh token | 64 random bytes; SHA-256 stored in `refresh_tokens` with `family_id`; httpOnly Secure SameSite=Strict cookie, path `/api/v1/auth`; 7-day lifetime (30 days for parents, **VERIFY** with schools); **rotation on every use**; reuse of a rotated token revokes the whole family and audits `TOKEN_REUSE` |
| Parent OTP | 6 digits, `SHA-256(code ‖ user_id)` stored, 5-min expiry, ≤ 5 attempts, ≤ 3 requests per phone per 15 min and 20 per IP per hour; the SMS template says "Usimpe mtu namba hii / do not share" |
| Multi-school parent | One code; after verification a short-lived (5 min) selection token lists the schools; choosing one issues tokens scoped to that school |
| Platform admins | Password + TOTP MFA (`mfa_secret_enc`), separate console and domain, IP allow-list |
| Devices | API key shown once at registration; SHA-256 stored; rotated yearly or when lost |

## 15.5 Input, transport and infrastructure

- **TLS.** TLS 1.2+ only; HSTS for 1 year; certificates via ACME.
- **Headers.** CSP (`default-src 'self'`; images also from object storage), `X-Content-Type-Options`, `Referrer-Policy: no-referrer`, `Permissions-Policy`.
- **CORS.** Allow-list of the school and portal domains only.
- **Rate limits** (Nginx + Redis):

  | Endpoint | Limit |
  |---|---|
  | Login | 10/min per IP |
  | OTP | 3 per phone per 15 min |
  | General API | 600/min per user |
  | Webhooks | provider IPs only |

- **Uploads.**
  - Type from magic bytes, size limits, random storage keys.
  - Served via 5-minute signed URLs with `Content-Disposition: attachment`.
  - ClamAV scan in Celery before a file becomes visible.
  - Images re-encoded to strip EXIF/GPS.
- **Secrets.** Environment variables from the host secret store: JWT, encryption and HMAC keys, provider credentials, GePG private key. Never in git or images; rotated yearly.
- **Dependencies.** `pip-audit`, `npm audit`, Renovate; container images scanned (Trivy).
- **Logging.** Structured JSON with request id. Phones, tokens and passwords are redacted by a log filter; no request bodies for auth or payment routes.

## 15.6 Payments security

1. **Verify the sender.** GePG XML signature with the GePG public certificate (**VERIFY** algorithm and canonicalisation); mobile-money HMAC/signature per provider; source IP allow-list at Nginx.
2. **Route.** `resolve_gepg_bill` or the account reference → school; mismatched amount or bill → stored as a reconciliation exception, not allocated.
3. **Idempotency.** `UNIQUE (school_id, channel, external_ref)` + `ON CONFLICT DO NOTHING`; replays only get the acknowledgement.
4. **Integrity.** Invoice rows locked `FOR UPDATE` during allocation; allocation guard trigger; balanced journals checked at commit; reversals need two people.
5. **Detection.** Daily reconciliation per channel; alerts on unmatched items, refunds and reversals over a threshold.

## 15.7 Audit trail

- **Trigger.** `fn_audit_row` on 31 tables: students, guardians, users, user roles, staff, consent, enrolment, documents, marks, publications, results, amendments, summaries, attendance, fee structures, discounts, invoices, lines, GePG bills, payments, allocations, reversals, bank deposits, discipline, health, grading schemes, bands and components.
- **What a row holds.** School, actor (`app.user_id` or `app.platform_admin_id`), action, entity, id, before/after JSON, IP and request id.
- **Redaction.** `fn_redact` drops every `*_enc`, `*_hash` and `password_hash` key (test F9b).
- **Security events written by the API:** LOGIN, LOGIN_FAILED, LOGOUT, OTP_SENT, OTP_FAILED, TOKEN_REUSE, PASSWORD_CHANGE, ROLE_GRANT, ROLE_REVOKE, EXPORT, VIEW_SENSITIVE, PUBLISH.
- **Append-only.** A statement trigger blocks UPDATE, DELETE and TRUNCATE, and `ssms_app` has no UPDATE grant (test F9c). A nightly job exports the day's audit rows with a hash chained to the previous day, copied off-site.
- **Retention.** Audit and finance records at least 10 years; partition by month at scale.

## 15.8 Personal Data Protection Act, 2022 (Tanzania)

| Obligation | Design |
|---|---|
| Registration | Each school (controller) and the platform operator (processor) register with the Personal Data Protection Commission; a data-processing agreement sits in the school contract |
| Lawful basis and consent | Education contract for core records; guardian consent recorded per purpose in `consent_records` (SMS, data processing, photo publication, health data); no SMS without SMS consent |
| Minimisation for minors | NIDA optional for students; only fields needed for enrolment, teaching, exams and fees; health data restricted |
| Security | Encryption of identifiers, RLS, RBAC, audit, backups, breach monitoring |
| Data-subject rights | `data_subject_requests` (export, correct, delete) with `due_at` 30 days (**VERIFY**). Delete = anonymise personal fields and keep results and ledgers required by law, with the reason recorded. |
| Cross-border transfer | Host in Tanzania where possible; otherwise documented safeguards and Commission approval as the regulations require (**VERIFY**) |
| Breach notification | Incident runbook: detect (alerts on TOKEN_REUSE spikes, mass exports, RLS errors), contain, assess, notify the Commission and affected guardians within the regulatory period (**VERIFY**), post-mortem |
| Retention | Applicant documents of rejected applications deleted after 12 months; inactive accounts disabled after 12 months; schedule per table in the Phase 1 privacy notice |

## 15.x Registrar role (added 2026-10-31)

`registrar` holds `students.read/create/update/status/import`, `guardians.manage`, `enrolment.manage/validate/decide`,
`staff.read`, `academics.configure`, `timetable.read/manage`, `exams.read`, `attendance.read`, `reports.read`. It has no
finance, marks, results, payroll, health, privacy or audit permission, and cannot grant `school_admin`.
Audit logs are kept for at least 7 years (§18.9).
