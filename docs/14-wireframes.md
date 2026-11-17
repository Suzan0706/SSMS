# 14. UI Wireframes

These are low-fidelity text wireframes for the React + Tailwind PWA. They apply to every screen:

- **Layout.** A top bar holds the school name, a language toggle **SW | EN** and the user menu. On desktop a left navigation lists only the modules the role may use. Below 768 px the navigation collapses into a bottom tab bar.
- **Labels.** Each label is shown in the selected language, with the other language as a tooltip. Fields marked `*` are required. Errors appear under the field in the selected language.
- **Formats.** Money is shown as `TZS 1,250,000`, dates as `dd/mm/yyyy`, phones as `+255 754 000 001`.
- **Accessibility.** WCAG AA contrast, 44 px touch targets, and all actions reachable by keyboard.

## 14.1 Login — *Ingia*

```text
┌───────────────────────────────────────────┐
│            [logo]                         │
│   SHULE YA SEKONDARI MFANO                │
│   Mfumo wa Usimamizi wa Shule             │
│                         [ SW | en ]       │
│                                           │
│   Jina la mtumiaji / Username *           │
│   [ s2025-0014                       ]    │
│   Nenosiri / Password *                   │
│   [ ••••••••••                    👁 ]    │
│                                           │
│   [        INGIA / LOG IN             ]   │
│                                           │
│   ⚠ Jina la mtumiaji au nenosiri si       │
│     sahihi  (shown on 401)                │
│   🔒 Akaunti imefungwa hadi 10:15         │
│     (shown on 423)                        │
│                                           │
│   Umesahau nenosiri? Wasiliana na ofisi   │
│   ya shule / Forgot password? Contact     │
│   the school office.                      │
└───────────────────────────────────────────┘
```

## 14.2 Admin dashboard — *Dashibodi*

```text
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ SHULE YA SEKONDARI MFANO        2026 · Muhula wa Pili ▾      [SW|en]   Halima Mrisho ▾   │
├───────────────┬──────────────────────────────────────────────────────────────────────────┤
│ ▣ Dashibodi   │  ┌─────────────┐ ┌─────────────┐ ┌──────────────┐ ┌───────────────────┐  │
│ 👥 Wanafunzi  │  │ Wanafunzi   │ │ Maombi mapya│ │ Ada iliyolipwa│ │ Migongano ya     │  │
│ 📚 Kozi/Masomo│  │ hai         │ │ ya usajili  │ │ (muhula huu)  │ │ ratiba           │  │
│ 🧑‍🏫 Walimu    │  │   612       │ │   14  →     │ │ TZS 182.4M    │ │   0 ✓            │  │
│ 🗓 Ratiba     │  │ ACTIVE      │ │ SUBMITTED   │ │ 71% of billed │ │ Clashes          │  │
│ 📝 Usajili    │  └─────────────┘ └─────────────┘ └──────────────┘ └───────────────────┘  │
│ 💰 Miamala    │                                                                          │
│ 📊 Ripoti     │  Kazi zinazosubiri / Pending work            Malipo ya karibuni / Recent │
│ 🛡 Ukaguzi    │  • 14 maombi yanasubiri uthibitisho  [Fungua] • TXN-2026-000412 MPESA     │
│   (Audit)     │  • 9 nyaraka zinasubiri uhakiki      [Fungua]   TZS 300,000 · 10:42      │
│ ⚙ Mipangilio  │  • 3 ankara bila namba ya malipo     [Omba]   • TXN-2026-000411 GEPG      │
│               │                                               TZS 680,000 · 10:15        │
│               │  Wanafunzi kwa kidato / Students by form (bar): F1 ███ F2 ███ F3 ██ ...  │
└───────────────┴──────────────────────────────────────────────────────────────────────────┘
```

## 14.3 Student registration — *Usajili wa Mwanafunzi*

```text
┌────────────────────────────────────────────────────────────────────────────────┐
│ ← Wanafunzi   /  Mwanafunzi mpya / New student                 Hatua 1 ya 2    │
├────────────────────────────────────────────────────────────────────────────────┤
│ TAARIFA ZA MWANAFUNZI / STUDENT DETAILS                                        │
│ Jina la kwanza *        Jina la kati            Jina la ukoo *                 │
│ [ Neema          ]      [ Joseph       ]        [ Mollel           ]           │
│ Jinsi * (●) Ke/F ( ) Me/M     Tarehe ya kuzaliwa * [ 10/02/2013 📅 ]  Umri: 13 │
│ Namba ya cheti cha kuzaliwa [ BC-ARU-2013-...  ]  Namba ya NECTA [           ] │
│ Mkoa [ Arusha ▾ ]   Wilaya [ Meru ▾ ]   Anwani [ Usa River               ]     │
│                                                                                │
│ MZAZI / MLEZI — GUARDIAN                                         [+ Ongeza]    │
│ Jina *  [ Joseph ] [ Mollel ]  Jinsi (●)Me ( )Ke  Uhusiano [ Baba/Father ▾ ]   │
│ Simu *  [ 0754 111 222 ]  → 255754111222 ✓    NIDA [                    ]      │
│ ☑ Mzazi mkuu (anapokea SMS) / Primary contact                                  │
│                                                                                │
│                              [ Ghairi / Cancel ]  [ Hifadhi / Save → ]         │
├────────────────────────────────────────────────────────────────────────────────┤
│ ✓ Mwanafunzi amesajiliwa: S2026-0101 · Jina: s2026-0101 · Nenosiri la muda:    │
│   x7Kp2Q_9a1a   [ 🖨 Chapisha karatasi ya kuingia / Print login slip ]          │
│   SMS imetumwa kwa mzazi.                                                      │
└────────────────────────────────────────────────────────────────────────────────┘
```

## 14.4 Course & subject management — *Kozi na Masomo*

```text
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ Kozi / Courses   [ Masomo / Subjects ]   [ Kozi zinazotolewa / Offerings ]           │
├──────────────────────────────┬───────────────────────────────────────────────────────┤
│ 🔍 [ Tafuta...       ] [+Kozi]│ PCM — Fizikia, Kemia na Hisabati ya Juu   A_LEVEL ✓  │
│ ▸ OLG  Sekondari ya Kawaida  │ Kidato: [ F5 ▾ ]                                      │
│ ▸ PCM  Fizikia, Kemia, Hisab.│ ┌────────┬──────────────────────┬────────┬──────────┐ │
│ ▸ HGL  Historia, Jiografia...│ │ Msimbo │ Somo / Subject       │ Lazima │ Vipindi/w│ │
│   (inactive)                 │ ├────────┼──────────────────────┼────────┼──────────┤ │
│                              │ │ PHY-A  │ Fizikia (Juu)        │  ☑     │  [ 6 ]   │ │
│                              │ │ CHEM-A │ Kemia (Juu)          │  ☑     │  [ 6 ]   │ │
│                              │ │ AMATH  │ Hisabati ya Juu      │  ☑     │  [ 6 ]   │ │
│                              │ │ GS     │ Maarifa ya Jumla     │  ☑     │  [ 3 ]   │ │
│                              │ └────────┴──────────────────────┴────────┴──────────┘ │
│                              │ [+ Ongeza somo]                  [ Hifadhi / Save ]    │
│                              │ Offering 2026 · F5: nafasi 45 · wamethibitishwa 0 ·    │
│                              │ ☑ Iko wazi kwa usajili / Open for enrolment            │
└──────────────────────────────┴───────────────────────────────────────────────────────┘
```

## 14.5 Instructor management — *Walimu*

```text
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ Walimu / Instructors      🔍 [ Tafuta ]  Idara [ Zote ▾ ]  Somo [ Yote ▾ ]  [+Mwalimu]│
├──────────┬──────────────────┬─────────┬───────────────────────┬────────┬─────────────┤
│ Namba    │ Jina             │ Idara   │ Masomo                │ Mzigo  │ Hali        │
├──────────┼──────────────────┼─────────┼───────────────────────┼────────┼─────────────┤
│ TCH-0101 │ Daudi Mwita      │ MATH    │ BMATH, AMATH          │ 18/30  │ ACTIVE      │
│ TCH-0102 │ Salma Abdallah   │ LANG    │ ENG, KISW             │ 14/30  │ ACTIVE      │
│ TCH-0103 │ Peter Kimaro     │ SCI     │ PHY, CHEM, PHY-A, ... │ 22/30  │ ACTIVE      │
└──────────┴──────────────────┴─────────┴───────────────────────┴────────┴─────────────┘
 Daudi Mwita ▸ [Taarifa] [Masomo anayofundisha] [Nyadhifa/Designations] [Ratiba]
 Nyadhifa 2026:  • Mkuu wa Idara — Hisabati (05/01/2026)      [+ Ongeza wadhifa]
                 Wadhifa [ Mwalimu wa Darasa ▾ ] Kidato [ F2 ▾ ] Mkondo [ A ] [Hifadhi]
```

## 14.6 Scheduling — *Ratiba*

```text
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ Muhula [ 2026 · Kwanza ▾ ]  Tazama: (●) Darasa ( ) Mwalimu ( ) Chumba   [ OLG F2 ▾ ][A ▾]│
│                                     [ ⚙ Tengeneza ratiba / Auto-generate ]  [ 🖨 PDF ] │
├─────────────┬────────────────┬────────────────┬────────────────┬──────────┬──────────────┤
│ Muda        │ Jumatatu       │ Jumanne        │ Jumatano       │ Alhamisi │ Ijumaa       │
├─────────────┼────────────────┼────────────────┼────────────────┼──────────┼──────────────┤
│ 08:00-08:40 │ B.MATH Mwita   │ KISW Salma     │ B.MATH Mwita   │  [ + ]   │  [ + ]       │
│             │ F2A            │ F2A            │ F2A            │          │              │
│ 08:40-09:20 │ ENG Salma F2A  │  [ + ]         │  [ + ]         │  [ + ]   │  [ + ]       │
│ 10:00-10:20 │ ─────────────── MAPUMZIKO / BREAK ──────────────────────────────────────── │
│ 10:20-11:40 │  [ + ]         │ PHY Kimaro     │  [ + ]         │  [ + ]   │  [ + ]       │
│             │                │ LAB-PHY (×2)   │                │          │              │
├─────────────┴────────────────┴────────────────┴────────────────┴──────────┴──────────────┤
│ Kipindi kipya (Alhamisi 08:00-08:40)                                                     │
│ Somo [ CHEM ▾ ]  Mwalimu [ Peter Kimaro ▾ ] (waliohitimu tu)  Chumba [ LAB-CHEM ▾ ]      │
│ ✓ Hakuna mgongano  (live POST /schedules/check)        [ Ghairi ]  [ Hifadhi ]           │
│ ✗ Mgongano: Mwalimu tayari anafundisha F1 A (Kipindi #12)  — Suggested: Thu 09:20 ▸      │
│ Masomo yasiyopangwa / Unplaced (from auto-generate): GEO ×1, CIV ×2  [Panga mwenyewe]    │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

## 14.7 Enrolment — *Usajili wa Masomo* (student view and registrar view)

```text
STUDENT (mobile)                         REGISTRAR (desktop)
┌───────────────────────────────┐       ┌──────────────────────────────────────────────────┐
│ ← Usajili 2026                │       │ Maombi / Applications  Hali [ VALIDATED ▾ ]       │
│ ① Kozi ② Mahitaji ③ Thibitisha│       ├────────────────┬──────────────┬─────────┬───────┤
│                               │       │ ENR-2026-000003│ Baraka Lyimo │ PCM F5  │ ✓ 4/4 │
│ Kozi zinazotolewa:            │       │ ENR-2026-000015│ Neema Mollel │ OLG F1  │ ⏳ 2/4│
│ ┌───────────────────────────┐ │       └────────────────┴──────────────┴─────────┴───────┘
│ │ PCM · Kidato cha Tano     │ │       │ ENR-2026-000003 — Baraka Emmanuel Lyimo           │
│ │ Fizikia, Kemia, Hisabati  │ │       │ Nyaraka:  Cheti cha kuzaliwa ✓  Picha ✓           │
│ │ Nafasi zilizobaki: 45     │ │       │           Fomu ya afya ✓  Matokeo CSEE ✓          │
│ │ [ Angalia / View ]        │ │       │ Mkondo / Stream [ A ▾ ]                           │
│ └───────────────────────────┘ │       │ [ Sitisha / Cancel… ]  [ ✓ Thibitisha / Confirm ] │
│ Endelea na kozi hii?          │       │ → Vipindi 2 vimeunganishwa · Ankara INV-2026-...  │
│ [ Hapana ]   [ Ndiyo ]        │       └──────────────────────────────────────────────────┘
│                               │
│ Mahitaji / Requirements:      │       FACULTY — Uhakiki wa nyaraka / Validation queue
│ ✓ Cheti cha kuzaliwa  VALID   │       ┌──────────────────────────────────────────────────┐
│ ✗ Fomu ya afya  INVALID       │       │ [ preview of medical.pdf ]                        │
│   "Haijasainiwa na daktari"   │       │ (●) Sahihi/VALID  ( ) Si sahihi/INVALID           │
│   [ 📎 Pakia tena / Re-upload]│       │ Maoni (lazima kama si sahihi) [               ]   │
│ ⏳ Matokeo CSEE   PENDING     │       │                          [ Hifadhi / Save ]       │
│ [ Wasilisha / Submit ]        │       └──────────────────────────────────────────────────┘
└───────────────────────────────┘
```

## 14.8 Transactions — *Miamala*

```text
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ Pokea malipo / Record payment                                                        │
│ Mwanafunzi * [ 🔍 S2025-0027 Zawadi Hassan  ]                                         │
│ Ankara      [ INV-2026-000002 · Muhula 1 · Salio TZS 480,000 ▾ ]                      │
│ Kiasi (TZS) * [ 100,000      ]  Njia * [ M-Pesa ▾ ]  (Cash · Bank · M-Pesa ·          │
│                                          Tigo Pesa · Airtel Money)                   │
│ Namba ya kumbukumbu * [ RKT55XQ1ZP ]  (required unless cash)                         │
│ Aliyelipa [ Mwanaisha Hassan ]  Simu [ 0715 000 011 ]  Tarehe [ 22/10/2026 10:42 ]   │
│                                   [ Hifadhi na chapisha risiti / Save & print ]      │
│ ✓ TXN-2026-000005 imehifadhiwa. Salio jipya: TZS 380,000.  SMS imetumwa.             │
│ ✗ 409: Muamala huu tayari umerekodiwa (reference already posted)                     │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ Historia / History  Kuanzia [01/10/2026] Hadi [22/10/2026] Njia [Zote▾]  [⤓ Excel]   │
│ TXN-2026-000005 │ 22/10 10:42 │ Zawadi Hassan │ MPESA │ RKT55XQ1ZP │ 100,000 │ ✓     │
│ TXN-2026-000004 │ 15/01 16:45 │ Zawadi Hassan │ AIRTEL│ MP2601...  │ 100,000 │ FAILED│
│ (Admin only) [ ↺ Batilisha / Reverse… ] — reason required, original stays unchanged  │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

## 14.9 Reports — *Ripoti*

```text
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ Ripoti / Reports                                                                     │
├───────────────────────────────┬──────────────────────────────────────────────────────┤
│ ○ Orodha ya wanafunzi         │ Ripoti ya Maendeleo (Report card)                    │
│ ○ Ratiba ya vipindi           │ Muhula [ 2026 · Kwanza ▾ ]  Mtihani [ Katikati ▾ ]    │
│ ○ Ripoti ya usajili           │ Darasa [ OLG F2 ▾ ] Mkondo [ A ▾ ]  Lugha (●)SW ( )EN │
│ ○ Historia ya miamala         │ [ Onyesha / Preview ]  [ ⤓ PDF ] [ ⤓ Excel ] [ CSV ]  │
│ ○ Hali za wanafunzi           ├──────────────────────────────────────────────────────┤
│ ● Ripoti ya maendeleo         │ Nafasi │ Mwanafunzi     │ Wastani │ Pointi │ Daraja  │
│                               │   1    │ Amani Massawe  │ 69.38   │   7    │ INC     │
│ Ripoti zangu / My reports     │   2    │ Zawadi Hassan  │ 58.13   │  12    │ INC     │
│ • report-card-F2A.pdf  ✓ ⤓    │ (Large class → "Inaandaliwa… utaarifiwa" · 202)      │
└───────────────────────────────┴──────────────────────────────────────────────────────┘
```
