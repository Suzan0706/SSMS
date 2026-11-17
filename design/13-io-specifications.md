# 13. Input and Output Specifications

## 13.1 Shared validation messages

Each field below lists the messages it can raise by code. The API returns them in `details[]` with the field name; the UI shows the text in the user's language under the field.

| Code | Rule | Kiswahili | English |
|---|---|---|---|
| E01 | required | Sehemu hii ni lazima. | This field is required. |
| E02 | max length n | Isizidi herufi {n}. | At most {n} characters. |
| E03 | phone `07XXXXXXXX`/`+2557…` → `255XXXXXXXXX` | Namba ya simu si sahihi. Mfano: 0754 123 456. | Invalid phone number. Example: 0754 123 456. |
| E04 | email | Barua pepe si sahihi. | Invalid email address. |
| E05 | date not in the future | Tarehe haiwezi kuwa ya baadaye. | Date cannot be in the future. |
| E06 | age 3–30 for students | Umri wa mwanafunzi si sahihi (miaka 3–30). | Student age must be 3–30 years. |
| E07 | NIDA 20 digits (**VERIFY**) | Namba ya NIDA iwe tarakimu 20. | NIDA number must be 20 digits. |
| E08 | duplicate | Taarifa hii tayari ipo. | This record already exists. |
| E09 | amount > 0, max 2 decimals | Kiasi si sahihi. | Invalid amount. |
| E10 | file type | Faili liwe PDF, JPG au PNG. | File must be PDF, JPG or PNG. |
| E11 | file size | Faili lisizidi MB {n}. | File must not exceed {n} MB. |
| E12 | score range | Alama iwe kati ya 0 na {max}. | Score must be between 0 and {max}. |
| E13 | time end > start | Muda wa kumaliza uwe baada ya kuanza. | End time must be after start time. |
| E14 | clash | Kuna mgongano: {detail}. | Clash: {detail}. |
| E15 | capacity | Nafasi zimejaa ({n}). | No places left ({n}). |
| E16 | password policy (≥ 10, letter + digit) | Nenosiri liwe na herufi 10+, herufi na tarakimu. | Password: 10+ characters with letters and digits. |
| E17 | reason required | Tafadhali eleza sababu. | Please give a reason. |
| E18 | not allowed in current state | Kitendo hiki hakiruhusiwi sasa. | This action is not allowed now. |
| E19 | reference already used | Kumbukumbu hii imeshatumika. | This reference has already been used. |
| E20 | weights ≠ 100 | Uzito wa tathmini ni {n}; lazima uwe 100. | Component weights total {n}; must be 100. |

## 13.2 Input forms

Types: `text`, `int`, `dec` (decimal string), `date`, `time`, `tel`, `email`, `select`, `multi`, `file`, `bool`. "Req" Y = required, C = conditional.

### F-01 Login (Ingia)

| Field | Type | Req | Validation | Errors |
|---|---|---|---|---|
| school_code | text | Y (pre-filled from the URL) | `^[a-z0-9-]{3,20}$`, must resolve | E01, "Shule haipatikani / School not found" |
| username | text | Y | ≤ 50 | E01 |
| password | password | Y | — | 401 "Jina la mtumiaji au nenosiri si sahihi / Invalid username or password"; 423 "Akaunti imefungwa hadi {time} / Account locked until {time}" |

### F-02 Parent OTP (Ingia kwa simu)

| Field | Type | Req | Validation | Errors |
|---|---|---|---|---|
| phone | tel | Y | E03 | E03; 429 "Jaribu tena baada ya dakika {n} / Try again in {n} minutes" |
| code | text | Y | `^[0-9]{6}$`, ≤ 5 attempts, 5-min expiry | "Namba si sahihi au imeisha muda / Code invalid or expired" |
| school | select | C (several schools) | one of the listed schools | E01 |

### F-03 School information (Taarifa za shule)

| Field | Type | Req | Validation | Errors |
|---|---|---|---|---|
| name, motto | text | Y / N | ≤ 150 | E01, E02 |
| registration_no | text | N | ≤ 30 (e.g. S.4521, EM.11873) | E02, E08 |
| region, district | select | Y | Tanzania regions/districts list | E01 |
| postal / physical address | text | N | ≤ 150 / 200 | E02 |
| phone, email | tel, email | N | E03, E04 | E03, E04 |
| medium of instruction | select | Y | KISWAHILI / ENGLISH | E01 |
| SMS sender ID | text | N | `^[A-Za-z0-9 -]{3,11}$`, registered with the provider | E02 |
| GePG SP code | text | N | ≤ 10 (**VERIFY**) | E02 |
| absence SMS cut-off | time | Y | 06:00–12:00 | "Muda kati ya 06:00 na 12:00 / Time between 06:00 and 12:00" |
| logo | file | N | PNG/JPG ≤ 500 KB | E10, E11 |

### F-04 Student registration (Usajili wa mwanafunzi)

| Field | Type | Req | Validation | Errors |
|---|---|---|---|---|
| first, middle, last name | text | Y, N, Y | letters, spaces, `'` and `-`; ≤ 50 | E01, E02 |
| gender | select | Y | M / F | E01 |
| date_of_birth | date | Y | E05, E06 | E05, E06 |
| birth certificate no. (RITA) | text | Y for new entrants | ≤ 30, unique per school (blind index) — format **VERIFY** | E08 |
| NIDA no. | text | N (optional for minors) | E07 | E07, E08 |
| PReM number | text | N (primary) | ≤ 20 — format **VERIFY** | E02 |
| photo | file | N | JPG/PNG ≤ 1 MB, face visible | E10, E11 |
| class, stream | select | Y (direct admission) | stream has places | E15 |
| guardians (1–4) | sub-form F-05 | Y (≥ 1, exactly 1 primary) | | "Weka mzazi mmoja mkuu / Choose one primary guardian" |

### F-05 Guardian (Mzazi / Mlezi)

| Field | Type | Req | Validation | Errors |
|---|---|---|---|---|
| first, last name | text | Y | ≤ 50 | E01 |
| gender | select | Y | M / F | E01 |
| phone | tel | Y | E03; reuses the existing guardian with the same phone in the school | E03 |
| relationship | select | Y | FATHER, MOTHER, GUARDIAN, SPONSOR, SIBLING, OTHER | E01 |
| NIDA | text | N | E07 | E07 |
| primary contact | bool | Y | exactly one per student | — |
| SMS consent | bool | Y | records `consent_records` (channel PAPER/PORTAL) | — |

### F-06 Enrolment application and documents (Maombi ya kujiunga)

| Field | Type | Req | Validation | Errors |
|---|---|---|---|---|
| class / combination | select | Y / C (A-Level) | open for the year | "Darasa halipo wazi / Class not open" |
| applicant | F-04 subset | Y | no open application this year | E08 |
| guardian | F-05 | Y | | |
| document per requirement | file | Y for required | PDF/JPG/PNG (magic bytes), ≤ 5 MB | E10, E11 |
| validation (teacher) | select + text | Y | VALID / INVALID; comment required if INVALID | E17 |
| decision (admin) | select | Y | APPROVE (stream) / REJECT / CANCEL + reason | E15, E17 |

### F-07 Staff (Mtumishi)

| Field | Type | Req | Validation | Errors |
|---|---|---|---|---|
| person fields | as F-04 | Y | phone E03 required, email E04 | |
| staff no. / check no. | text | Y / N | ≤ 20, unique per school | E08 |
| department, designation | select | N | | |
| employment type, date | select, date | Y, N | E05 | |
| salary (TZS) | dec | N | ≥ 0; visible with `payroll.read` | E09 |
| max periods / week | int | Y | 1–50 (default 30) | "Kati ya 1 na 50 / Between 1 and 50" |
| qualifications | rows | N | level, title, institution, year 1950–now | E01 |

### F-08 Academic setup (classes, streams, subjects, rooms, combinations)

| Form | Fields (validation) | Errors |
|---|---|---|
| Class | level, code (`F1`…`F6`, `STD1`…`STD7`), names sw/en, order, next class | E01, E08 |
| Stream | class, name (`A`…), capacity 1–200, home room | E08 |
| Subject | code, NECTA code (**VERIFY**), names, department, room type | E08 |
| Room | code, name, type, capacity > 0, equipment ≤ 300 | E08 |
| Combination | code (PCM…), names, subjects (≥ 2) | E08 |

All of them follow Add → Confirm → Save; Update → Confirm; Delete → Confirm with reason (E17).

### F-09 Grading scheme and assessment components

| Field | Type | Req | Validation | Errors |
|---|---|---|---|---|
| level, year, name | select, select, text | Y | | E01 |
| best n subjects | int | N | 1–12 (O-Level 7, A-Level 3) | |
| bands [letter, min, max, points, remarks sw/en] | rows | Y | 0 ≤ min ≤ max ≤ 100, no overlaps, points 0–9 | "Viwango vinaingiliana / Bands overlap" |
| divisions [division, min, max points] | rows | N | no overlaps | same |
| component [term, level, subject?, code, names, max, weight] | rows | Y | max > 0, 0 < weight ≤ 100; totals checked live | E20 |

### F-10 Timetable slot (Kipindi)

| Field | Type | Req | Validation | Errors |
|---|---|---|---|---|
| term, stream, subject | select | Y | subject in class curriculum | E01 |
| teacher | select | Y | assigned to stream + subject; load ≤ max | "Mwalimu amezidi vipindi / Teacher over load" |
| room | select | Y | type fits subject; capacity ≥ class size | "Chumba hakifai / Room unsuitable" |
| day, start, end | select, time, time | Y | Mon–Sat; E13 | E13, E14 |

### F-11 Exam paper (Weka mtihani)

session, class, subject, date (within session dates), start/end (E13), room (no class or room clash: E14).

### F-12 Mark entry grid (Kuingiza alama)

| Field | Type | Req | Validation | Errors |
|---|---|---|---|---|
| score per cell | dec | N (blank = not entered) | 0 – component max, 2 decimals | E12 |
| absent | bool | N | absent ⇒ score blank | — |
| version | hidden | Y | must equal the server version | 409 "Alama imebadilishwa na mtumiaji mwingine / Changed by another user" |
| upload | file | — | template XLSX, same rules per row | error report |

### F-13 Amendment request (Ombi la marekebisho)

published result (read-only), new score 0–100 (E12), reason (E17, ≤ 300). Approval: a different user (E18 when maker = checker).

### F-14 Attendance register (Mahudhurio)

One row per student. Status PRESENT (default) / ABSENT / LATE / EXCUSED, optional note ≤ 100. Offline save; date = today (back-dating needs `attendance.read` + reason).

### F-15 Fee structure, invoices, payments

| Form | Fields (validation) | Errors |
|---|---|---|
| Fee structure | year, class, name; lines: item, term (blank = annual), amount ≥ 0 (dec), optional | E09, E08 |
| Discount rule | code, names, kind, **either** percent (0–100] **or** amount > 0 | "Chagua asilimia au kiasi / Choose percent or amount" |
| Generate invoices | term, classes, due date ≥ today, installments (sum = total) | "Jumla ya awamu ≠ ankara / Installments ≠ total" |
| Record payment | student, channel CASH/BANK, reference (receipt-book or bank ref, unique per channel), amount, payer name, payer phone (E03), received date (E05) | E09, E19 |
| Bank deposit | bank reference, deposit date, amount, student, depositor | E19 |
| Reversal request | payment, reason (E17); approver ≠ requester | E18 |
| Mobile-money push (parent) | invoice, phone (E03), channel | "Ombi limetumwa, thibitisha kwenye simu / Request sent, confirm on your phone" |

### F-16 Facilities, discipline, communication, import

| Form | Fields (validation) | Errors |
|---|---|---|
| Accommodation request | term, preferred hostel | E08 (open request exists) |
| Hostel allocation | request, room (capacity) | E15 |
| Bus / route / stop | plate `T 123 ABC`, capacity 1–100, driver; route name, term fee ≥ 0; stop seq, name, pickup time | E01, E15 |
| Transport assignment | student, route, stop, bus, term | E15 |
| Venue booking | venue, name, date, start, end, seats ≤ venue seats | E13, E14, E15 |
| Discipline | student, date (E05), category, description ≤ 1000, action, resolution (required when RESOLVED) | E01 |
| Announcement | title ≤ 120, body ≤ 2000, language, audience + target, send SMS (credit check) | "Salio la SMS halitoshi / Not enough SMS credit" |
| Bulk import | kind, XLSX/CSV ≤ 10 MB, template headers | E10, E11, error report |

## 13.3 Output specifications

All outputs have:

- **Header:** school logo, name, address and motto; title in sw / en; a reference number.
- **Footer:** "Imetolewa na SSMS {date time EAT} · Ukurasa {n}/{m}" and the generating user.
- **Formats:** money as `TZS 1,250,000`; dates as `dd/mm/yyyy`; phones masked except to authorised staff.

### O-01 Report card (Ripoti ya maendeleo)

```text
SHULE YA SEKONDARI MFANO · S.L.P. 100 DODOMA · "Elimu ni Ufunguo"
RIPOTI YA MAENDELEO YA MWANAFUNZI / STUDENT PROGRESS REPORT        Ref: MF-2025-0014/2026/T1
Jina: AMANI JOHN MASSAWE   Namba: MF-2025-0014   Kidato: II A   Muhula: Kwanza 2026
Somo / Subject         CA(30)  Kati(20)  Muhula(50)  Jumla  Daraja  Pointi  Nafasi  Maoni
Basic Mathematics       27.6     15.2      39.0       81.8    A        1     2/6     Bora
English Language        …
Physics (amended*)      …                              90.0    A        1     1/6     Bora
──────────────────────────────────────────────────────────────────────────────────────
Wastani/Average 66.97   Pointi (bora 7) 12   Daraja/Division I   Nafasi darasani 4 kati ya 6
Mahudhurio 58/60 (97%)   Mwalimu wa darasa: ____   Mkuu wa shule: ____   Muhuri
* Imerekebishwa / Amended on 12/06/2026 (approved by Head Teacher)
```

Source: `v_current_results`, `v_current_term_summaries`, `report_card_comments`, `attendance_records`, `grading_schemes` (scheme version printed).

### O-02 Receipt (Risiti)

```text
RISITI / RECEIPT  RCT-2026-000001                 Tarehe 20/01/2026 14:02
Mwanafunzi: Amani Massawe (MF-2025-0014)  Kidato II A
Kiasi: TZS 400,000  (Shilingi laki nne tu)  Njia: GePG · Kumbukumbu: PSP-77812345
Imelipiwa ankara: INV-2026-000001 (TZS 400,000)
Salio la ankara: TZS 280,000   Mkopo (credit): TZS 0
Imepokelewa na: Mfumo (GePG)   [QR: verify URL with receipt hash]
```

The amount is printed in words (Kiswahili, plus English when the language is en).

### O-03 Invoice (Ankara)

Invoice no., student, class, term, lines (item, description, amount), discounts, total, paid, balance, installments (due date, amount, status), **GePG control number** and pay instructions (M-Pesa / Mixx by Yas / Airtel / HaloPesa / bank — **VERIFY** wording with GePG), due date.

### O-04 Class list (Orodha ya darasa)

| Na. | Namba ya usajili | Jina | Jinsi | Umri | Mzazi (simu ****1234) | Hali |
|---|---|---|---|---|---|---|

Grouped by stream, with totals by sex. The class teacher is named in the header.

### O-05 Attendance report (Ripoti ya mahudhurio)

Per stream and date range: one row per student with columns for days, P/A/L/E counts and % present. Chronic-absence rows are highlighted. Per student: a calendar view.

### O-06 Transaction history (Historia ya miamala)

| Tarehe | Na. muamala / risiti | Mwanafunzi | Njia | Kumbukumbu | Kiasi (TZS) | Hali | Aliyerekodi |
|---|---|---|---|---|---|---|---|

Filters: date range, channel, status, student. Totals per channel. Reversals are shown as negative linked rows.

### O-07 Timetable (Ratiba)

Grid with periods as rows (break and lunch rows shown) and Jumatatu–Ijumaa as columns. Each cell shows subject (sw), teacher and room. Variants per stream, teacher and room. Printed A4 landscape.

### O-08 Other outputs

| Output | Content |
|---|---|
| Firewall report | the 422 `INCOMPLETE_GRADES_BLOCK` list as a printable table per teacher |
| Aging / defaulters | `v_invoice_aging` buckets per class with guardian contact |
| Enrolment report | applications by status, class, sex; places left |
| Compliance export | enrolment by sex, age and class; attendance; results; staff — templates per authority (**VERIFY** current formats) |
| Import error report | row, column, value, error sw/en |
