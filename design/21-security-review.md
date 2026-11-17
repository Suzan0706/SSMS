# 21. Security Review and Results-Day Load Test (Extension Phase 12)

Date: 2026-11-02. Scope: the whole SSMS extension (`ssms/`), with extra attention to the plan's Phase 12 focus
(design/20 §20.7): uploads, exports and results day. The v1 project (`backend/`, `db/`, `docs/`) is out of scope.

Method: every item of the brief's security list (§8) was traced to the code that enforces it and to a test that would
fail if it broke. Where no test existed, one was written first and run against the unchanged code; the defects below
were all found that way or by reading the code paths for uploads and exports. Dependencies were checked against the
public advisory databases (`npm audit`, `pip-audit` inside the API image).

## 21.1 Controls and evidence

| Brief §8 item | Control | Evidence (test) |
|---|---|---|
| Secure password hashing | Argon2id via `app/core/security.py`; temporary passwords must be changed at first sign-in | `test_core.py`, `test_auth.py` |
| JWT authentication | Short-lived access token in memory, refresh token in an httpOnly SameSite=Strict cookie, rotation with reuse detection; console tokens have their own audience | `test_auth.py`, `test_platform.py` |
| Every route needs a sign-in | All routes except a named public list and five signed machine endpoints answer 401 without a token | `test_security_review.py::test_every_route_needs_a_sign_in_except_the_public_list` (sweeps the whole OpenAPI document, > 300 operations) |
| Role-based access control | Permission per route (`require_permission`), menus from the same permissions | `test_design_alignment.py`, `test_front_office.py` (receptionist), `test_years_dashboards.py`, role tests in every module |
| School-level data isolation | Forced RLS on every tenant table, runtime role `ssms_app` without BYPASSRLS, composite keys `(school_id, id)` | `design/sql/tests/*.sql` (run as `ssms_app` by `test_schema.py`), cross-school tests in `test_auth.py`, `test_files.py`, `test_communication.py`, `test_portal_extension.py` and others; Phase 11 in `test_another_schools_certificates_and_cards_are_out_of_reach` |
| Input validation | Pydantic schemas with lengths and formats; links shown to students must be https | `test_study_material_links_cannot_carry_script` and module tests |
| SQL injection protection | SQLAlchemy bound parameters everywhere; no string-built SQL from input | `test_search_inputs_cannot_change_a_query` |
| CORS configuration | Only `SSMS_CORS_ORIGINS`, credentials allowed only for them | `test_cors_answers_only_the_configured_origin` |
| Rate limiting | Login per user and per address, console login 5 per email per 15 min, SMS codes per phone with an attempt cap, webhooks per source | `test_auth.py`, `test_core.py` |
| Secure file uploads | Type read from the content (not the name), size limit and upload permission per purpose, random storage keys, cleaned display names, `nosniff`, only the uploader or allowed readers; a file in use cannot be discarded | `test_files.py`, `test_a_file_in_use_cannot_be_discarded` |
| Audit logging | `fn_audit_row` trigger on every tenant table plus explicit events (sign-in, OTP failures, exports) | `test_analytics.py`, `test_auth.py`, schema tests |
| Secure environment variables | Production refuses to start with development secrets or missing keys, and names the setting without printing a value; images and the web bundle carry no secrets | `test_production_refuses_to_start_with_development_settings`; build contexts limited by `api/Dockerfile.dockerignore` and `web/.dockerignore` |
| Sensitive data never exposed | No response schema contains a password, hash, encrypted field, key or secret, except values shown once to their creator | `test_no_response_can_carry_a_secret` |
| Security headers | API: `nosniff`, `DENY` framing, CSP `default-src 'none'`, HSTS in production; pages and assets: nginx CSP `default-src 'self'` and `DENY` framing (corrected in Phase 13, F8); HSTS at the edge | `test_core.py` (API); CI `images` job checks pages and assets of the built web image |

## 21.2 Findings

All findings are fixed and covered by a test unless marked otherwise.

| # | Severity | Finding | Fix |
|---|---|---|---|
| F1 | High | **Spreadsheet formula injection.** `/exports` escaped formulas, but the report exports (CSV and XLSX), the import error and result workbooks and the compliance workbook did not. A name typed as `=HYPERLINK(...)` became a live formula in the head teacher's spreadsheet; in XLSX openpyxl stores any `=` text as a formula. | One module, `app/core/sheets.py`, for every CSV and XLSX: CSV cells get a leading apostrophe, XLSX cells are stored as text. Numbers stay numbers. |
| F2 | Medium | **A file in use could be discarded.** `DELETE /files/{id}` deleted the bytes of a staff photo, homework attachment, study material, expense receipt or certificate background still in use: data loss and broken pages. | `files.in_use()` checks every record that points at a file; such a file is refused with 409 `FILE_IN_USE`. |
| F3 | Medium | **Email recorded as sent when it was not.** In production with the default console provider, email was only logged but marked SENT. | In production, email is off unless `SSMS_EMAIL_PROVIDER=smtp` (nothing queued, the test button says so); `smtp` without `SSMS_SMTP_HOST` stops the server at start. |
| F4 | High | **axios 1.7.9** had 33 published advisories, 13 of them rated high. | Pinned to 1.20.0, the oldest release fixing all of them (2026-08-26). |
| F5 | High | **react-router-dom 6.28.0**: XSS through open redirects and related advisories. | Pinned to 6.30.6. Two moderate advisories are fixed only in v7 and are **not reachable** here: one needs server-side rendering (not used), the other a navigation target taken from input (every `Link`/`navigate` uses a fixed path or a server id). Moving to v7 is a remaining task. |
| F6 | Low | **Docker build contexts unfiltered.** The API image is built from the whole project, which holds `ssms/.env.local` and `ssms/backups/*.dump` (personal data); the web build copied the host's `node_modules` and test traces. Nothing leaked into an image, but one careless `COPY` would have. | Allowlist `api/Dockerfile.dockerignore`; `web/.dockerignore`. Build contexts fell to 45 KB and 109 KB. |

### Found by the Phase 13 install drill (design/18 §18.10)

A production-mode stack built from empty volumes, behind the HTTPS edge, with the real ClamAV and an object store,
showed problems no unit test could. All are fixed and re-checked on that stack.

| # | Severity | Finding | Fix |
|---|---|---|---|
| F7 | High | **Client address could be forged.** nginx appended the client's own `X-Forwarded-For` and the API trusted every proxy (`'*'`), so it took the leftmost address, which the client writes. 35 sign-in attempts against 35 accounts with forged addresses: none blocked (per-address limit 30 a minute bypassed); the forged address went into the audit log. The per-account limit still held. | nginx accepts `X-Forwarded-For` only from `SSMS_TRUSTED_PROXY` (the edge proxy's fixed address) and passes exactly one address. Same probe afterwards: blocked after 30; the audit log shows the real address. Through the edge, a forged header is replaced by the real one. |
| F8 | Medium | **Pages had no clickjacking or CSP protection.** nginx drops server-level `add_header` lines in any location that has its own (`Cache-Control`), so `/`, the app routes, `/sw.js` and `/assets/` carried no `X-Frame-Options` and no CSP; API responses carried them twice. §21.1 claimed them for the web in Phase 12 because only the API was tested. | `web/security-headers.conf` included in each static location; `img-src` gains `blob:` (photos are shown through blob URLs, which the policy would otherwise block). A browser walk through 14 pages as admin and student under the policy: no violations, no errors. CI checks the built image. |
| F9 | High | **Console lost its database role.** The engine ran `SET ROLE ssms_platform` on connect inside psycopg's implicit transaction and never committed it, so the next rollback undid it; the console login `ssms_console` has no privileges of its own, so every console request failed (`permission denied`, shown as 404) until the API restarted. Hidden in tests and local runs, which connect differently. | The role switch is committed on connect; `test_the_runtime_role_survives_a_rolled_back_request` uses the real engine and a login without privileges. |
| F10 | Medium | **Backups.** The daily loop slept 24 h after each dump: on a host that sleeps it slipped by days (newest local backup was about 32 h old), and every restart reset it. On a first install it dumped the database before migrations, so the day's only backup was empty (also the 803-byte dump of 27 October). | One dump per calendar day, checked every 10 minutes; never before the schema exists; written under a temporary name and renamed when complete; the restore drill warns about a backup older than 26 h and fails clearly on an empty one. |
| F11 | Low | **Uploads over 11 MB failed at nginx** with a bare 413 although study materials and homework allow 20 MB; and **nginx kept the API's old address** after the API container was recreated (502 until web was restarted, since Phase 10). | Body limit 21 MB (the API checks each purpose); the API name is resolved at request time. Proven by moving the API to a new address: the site kept working. |

### Found while preparing go-live (2026-11-12)

| # | Severity | Finding | Fix |
|---|---|---|---|
| F12 | High | **Mail server certificate not verified.** `starttls()` was called without an SSL context, and Python then does not check the server's certificate: anyone on the path could read mail and the SMTP password. Messages also had no `Date` or `Message-ID`, and the password could go out without TLS if STARTTLS was turned off. | Verified TLS context (optional `SSMS_SMTP_CA_FILE` for a private CA), implicit TLS (`SSMS_SMTP_IMPLICIT_TLS`, automatic on port 465), no login without TLS, production refuses unencrypted SMTP, `Date` and `Message-ID` set. Tested against a real SMTP server (Mailpit) with STARTTLS and implicit TLS: delivered, headers present, an untrusted certificate refused. |
| F13 | Medium | **Password hashing blocked the worker.** Argon2 (about 0.4 s) ran on the request's event loop, so every other request on that worker waited while someone signed in. Six checks at once stalled other work for 1.5 s. | Hashing and checking run in a thread (the library releases the interpreter lock): other work waited at most 27–77 ms. On the stack, result pages during a burst of 18 sign-ins: median 1.95 s → 1.0–1.5 s, worst 3.75 s → 2.2–2.8 s. `test_passwords_are_checked_off_the_event_loop`. |

Python packages of the API image: **no known vulnerabilities** (`pip-audit -l` in the image, 2026-11-02).

## 21.3 Results-day load test

Scenario `results-day` in `ssms/api/scripts/loadtest.py`: each virtual student repeatedly opens the home page, their
results, their progress and the announcements, and downloads the report-card PDF every fifth round. Six seeded
students with published results; 30 s per level; the generator ran inside the Docker network (from Windows, Docker
Desktop's port forwarding itself became the limit and halved throughput).

Local stack: one laptop (8 vCPU, 4 GB for Docker), nginx, API with 2 workers (`WEB_CONCURRENCY=2` in `.env.local`),
PostgreSQL 16, the load generator on the same machine.

| Concurrent students | Requests/s | p50 | p95 | p99 | Errors |
|---|---|---|---|---|---|
| 20 | 70 | 0.22 s | 0.56 s | 0.66 s | 0 |
| 50 | 64 | 0.67 s | 1.23 s | 1.53 s | 0 |
| 100 | 63 | 1.49 s | 2.15 s | 2.61 s | 0 |

Throughput holds steady as load grows and nothing fails; latency rises only by queueing. Single requests take 20–45 ms
(report card about 46 ms) with 5–19 SQL statements each, three of them the per-request sign-in checks; there are no
per-row query loops. Raising the API to 4 workers did not help on this machine (the database, the generator and the API
share the same CPUs), and drawing the report card in a thread made no measurable difference (the PDF library holds the
interpreter lock), so that change was not kept.

What it means for one school: results day for 1,000 students is about 5,000 requests. Even if every student opened
the results within 10 minutes, that is 8–9 requests per second, well below the 63–70 measured here.

**VERIFY:** the target in design/11 §11.4 (p95 < 1 s for a spike to 5,000 virtual users across schools) is for the
hosted multi-school service and can only be checked with k6 (`ssms/loadtest/results_day.js`) on staging hardware.
A laptop cannot show it.

## 21.4 Remaining risks and tasks

- ~~Uploads not virus-scanned~~ — done in Phase 13: ClamAV scans every upload before it is stored; an infected
  file is refused and a scanner outage refuses uploads rather than storing them unscanned. Imports (CSV/XLSX) are
  parsed, never served to others, and are not scanned.
- ~~`/metrics` open at the edge~~ — closed by the `edge` Caddy service and not proxied by nginx (Phase 13).
- ~~react-router 6 advisories~~ — moved to react-router 7.18.4: `npm audit` reports 0 vulnerabilities.
- Run the k6 results-day test on staging (§21.3). The script now also reads progress and the report-card PDF;
  a short run against the local stack passed every page check. Sign-in is the expensive step (Argon2, about 0.4 s
  of CPU each), so the first minutes after results are published are bound by sign-ins: size the API for them.
- Run the UAT checklist per role (design/16 §16.5) with school staff before go-live.
