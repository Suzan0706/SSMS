# 14. UI Wireframes

These are low-fidelity text wireframes. They apply to every screen:

- **Language.** Kiswahili is the default; the toggle `[SW|EN]` sits in the top bar.
- **Touch targets.** At least 48 px; every flow works at a width of 360 px.
- **Navigation.** Desktop shows a left sidebar; on phones it becomes a bottom bar with up to 5 items plus "Zaidi / More".
- **Offline state.** A top banner says "Uko nje ya mtandao — kazi zitahifadhiwa / You are offline — work will be saved". Badges ● Imehifadhiwa nje ya mtandao / ● Imesawazishwa / ⚠ Mgongano.
- **Change pattern.** Every create, edit and delete uses Add → **Thibitisha / Confirm** → Save; deletes ask for a reason.

## 14.1 Shared screens

```text
┌──────────────────────────────┐   ┌──────────────────────────────┐
│ [logo] SSMS          [SW|en] │   │ ← Ingia kwa simu (Wazazi)    │
│ Shule: mfano-sec  (kutoka URL)│   │ Namba ya simu                │
│ Jina la mtumiaji             │   │ [ 0754 000 021            ]  │
│ [ tch.mwita               ]  │   │ [   TUMA NAMBA YA SIRI   ]   │
│ Nenosiri                     │   │ ──────────────────────────── │
│ [ ••••••••••          👁 ]   │   │ Weka namba 6 uliyotumiwa     │
│ [        INGIA          ]    │   │ [ 4 ][ 8 ][ 2 ][ 9 ][ 1 ][ 3 ]│
│ Mzazi? Ingia kwa simu →      │   │ Inaisha baada ya 04:31       │
│ ⚠ Jina au nenosiri si sahihi │   │ Chagua shule:                │
│ 🔒 Imefungwa hadi 10:15      │   │ (●) Sekondari Mfano, Dodoma  │
└──────────────────────────────┘   │ ( ) Msingi Upendo, Arusha    │
                                   │ [        ENDELEA        ]    │
                                   └──────────────────────────────┘
```

## 14.2 Admin portal (desktop, responsive)

**Sidebar** (only the items the user's permissions allow):

- Dashibodi
- Taarifa za Shule
- Madarasa
- Masomo
- Watumishi
- Orodha ya Watumishi
- Weka Mitihani
- Angalia Mitihani
- Wanafunzi
- Usajili
- Ratiba
- Matokeo
- Mahudhurio
- Ada
- Bweni
- Usafiri
- Kumbi
- Nidhamu
- Ripoti
- Ukaguzi
- Mipangilio
- Toka

### A-01 Dashboard (Dashibodi)

```text
┌───────────────┬──────────────────────────────────────────────────────────────────────┐
│ SSMS · Mfano  │ 2026 · Muhula wa Kwanza ▾                       [SW|en]  Halima M. ▾ │
│ ▣ Dashibodi   ├──────────────────────────────────────────────────────────────────────┤
│ 🏫 Taarifa    │ ┌Wanafunzi hai┐ ┌Mahudhurio leo┐ ┌Ada iliyokusanywa┐ ┌SMS zilizobaki┐ │
│ 📚 Madarasa   │ │   1,214     │ │ 94% · 73 hawapo│ │ TZS 182.4M (71%)│ │  8,540 ✓    │ │
│ 📖 Masomo     │ └─────────────┘ └──────────────┘ └─────────────────┘ └─────────────┘ │
│ 👥 Watumishi  │ Kazi zinazosubiri                     Mahudhurio wiki hii (chart)    │
│ 📝 Mitihani   │ • 14 maombi ya usajili [Fungua]       ▁▃▅▇▆  Jtt Jnn Jtn Alh Ijm      │
│ 🎓 Wanafunzi  │ • 9 nyaraka za kuhakiki [Fungua]      Wanafunzi wasiofika ≥3 siku: 6  │
│ 🗓 Ratiba     │ • Kidato II: alama 12 hazipo [Ona]    Madeni (aging): 1–30 · 31–60 …  │
│ 📊 Matokeo    │ • Ulinganisho M-Pesa: tofauti 2 [Ona]                                  │
│ 💰 Ada ...    │                                                                      │
└───────────────┴──────────────────────────────────────────────────────────────────────┘
```

### A-02 School information (Taarifa za Shule)

```text
Taarifa za Shule                                              [Hariri]
Jina: Shule ya Sekondari Mfano     Namba ya usajili: S.4521   Umiliki: Binafsi
Kauli mbiu: Elimu ni Ufunguo       Mkoa/Wilaya: Dodoma / Dodoma City
Lugha ya kufundishia: Kiingereza   Simu: 0262 321 000         Barua pepe: info@mfano.sc.tz
SMS sender ID: MFANO-SS            GePG SP code: SP1023       Muda wa SMS za kutokuwepo: 08:30
Nembo: [logo] [Badilisha]          Usajili uko wazi: ☑
```

### A-03 Classes and streams (Madarasa)

```text
Madarasa  [+ Ongeza darasa]          Kiwango: [ O-Level ▾ ]
┌──────┬───────────────────┬──────────┬────────┬────────────────────────┐
│ Code │ Jina              │ Mikondo  │ Nafasi │ Vitendo                │
│ F1   │ Kidato cha Kwanza │ A        │ 45/45  │ [Hariri] [Futa]        │
│ F2   │ Kidato cha Pili   │ A, B     │ 6/90   │ [Hariri] [Mikondo] [Masomo] │
└──────┴───────────────────┴──────────┴────────┴────────────────────────┘
Mkondo F2 B: uwezo [45] chumba [F2B ▾] mwalimu wa darasa 2026 [Neema Laizer ▾] [Thibitisha]
```

### A-04 Subjects (Masomo)

Table: code, NECTA code, name (sw/en), department, room type, classes using it. Plus a class curriculum editor: subject ✓ compulsory · periods per week.

### A-05 Staff (Watumishi / Orodha ya Watumishi)

```text
Orodha ya Watumishi  🔍[ Tafuta ]  Idara [Zote▾]  [+ Mtumishi]  [⇪ Ingiza Excel]
MF-STF-003 │ Daudi Mwita    │ Hisabati (Mkuu wa idara) │ Mwalimu wa somo │ 18/30 vipindi │ ACTIVE
MF-STF-004 │ Salma Abdallah │ Lugha                    │ Mwalimu wa somo │ 14/30         │ ACTIVE
Daudi Mwita ▸ [Taarifa] [Sifa za elimu] [Masomo/mikondo 2026] [Ratiba] [Mshahara 🔒]
```

### A-06 Set exams / View exams (Weka / Angalia Mitihani)

```text
Kipindi cha mitihani: [Mitihani ya katikati Machi 2026 ▾]  [+ Ongeza karatasi]
Tarehe     │ Muda        │ Darasa │ Somo              │ Ukumbi
16/03/2026 │ 08:00–10:30 │ F2     │ Hisabati za Msingi │ HALL
16/03/2026 │ 11:00–13:00 │ F2     │ Kiingereza        │ HALL
⚠ Mgongano: F2 ina mtihani 08:00–10:30 siku hiyo (shown live on save)
```

### A-07 Students (Wanafunzi)

```text
Wanafunzi 🔍[ jina / namba ]  Darasa[F2▾] Mkondo[A▾] Hali[Hai▾]  [+ Sajili] [⇪ Ingiza] [⤓ Excel]
MF-2025-0014 │ Amani J. Massawe │ M │ 14 │ II A │ Hai │ Mzazi ****0021 │ [Fungua]
Amani ▸ [Wasifu] [Wazazi] [Mahudhurio] [Matokeo] [Ada] [Nidhamu] [Historia ya hali]
[Badili hali ▾: Simamisha · Hamisha · Hitimu · Ameacha]  → sababu + tarehe → Thibitisha
```

### A-08 Enrolment (Usajili)

```text
Maombi ya usajili 2027   Hali [Yanasubiri uamuzi ▾]
APP-2026-0001 │ Neema Mollel │ F1 │ Nyaraka 2/3 ✓ 1 ✗ │ [Fungua]
──────────────────────────────────────────────────────────────
Neema Joseph Mollel · F1 · Mzazi: Joseph Mollel ****0027
 ✓ Cheti cha kuzaliwa   ✗ Picha: "Picha haionekani vizuri"   ⏳ Matokeo ya Darasa la Saba
Thibitisha usajili?  Mkondo [A ▾] (nafasi 44)  [✓ Kubali]  [✗ Kataa…]  [Sitisha…]
```

### A-09 Timetable (Ratiba)

```text
Muhula [2026 · 1 ▾]  Ona: (●)Mkondo ( )Mwalimu ( )Chumba  [F2 A ▾]  [⚙ Tengeneza] [🖨 PDF]
Muda        │ Jumatatu        │ Jumanne        │ Jumatano │ Alhamisi │ Ijumaa
08:00–08:40 │ HIS · Mwita F2A │ [+]            │ [+]      │ [+]      │ [+]
08:40–09:20 │ KIING · Salma   │ [+]            │ …
10:20–11:40 │ [+]             │ FIZ · Kimaro LAB-PHY (×2)
[+] → Somo ▾ Mwalimu ▾ (waliopangiwa tu) Chumba ▾ → ✓ Hakuna mgongano / ✗ Mwita yupo F2B 08:40
```

### A-10 Results (Matokeo)

```text
Toa matokeo   Muhula [Kwanza ▾]  Darasa [F5 ▾]  [Kagua]  [Toa matokeo]
✗ Huwezi kutoa matokeo: matatizo 9
 MF-2026-0003 Emmanuel Lyimo · PHY-A · TERMINAL · Peter Kimaro · Alama haijaingizwa
 GS · uzito 110 ≠ 100
[⤓ Pakua orodha kwa walimu]
Maombi ya marekebisho (2): MF-2025-0014 BMATH 81.8 → 90.0 "Kosa la kusahihisha" — Daudi Mwita
  [✓ Idhinisha]  [✗ Kataa]   (huwezi kuidhinisha ombi lako mwenyewe)
```

### A-11 Hostel, transport, venues (Bweni, Usafiri, Kumbi)

```text
Bweni la Kilimanjaro (Wasichana)   Muhula [1 ▾]
K1 [■■□□] 2/4   K2 [■■■■] 4/4   K3 [□□□□] 0/4
Maombi: Zawadi Hassan → [Weka K1 ▾] [Kataa]
Usafiri: Basi T 123 DEF (viti 30, 21 vimejaa) · Njia: Kisasa–Shuleni TZS 120,000/muhula
Kumbi: Ukumbi Mkuu 400 · 30/10 09:00–13:00 Mahafali (350) · [+ Hifadhi]
```

### A-12 Reports, audit, settings (Ripoti, Ukaguzi, Mipangilio)

- **Ripoti:** list of reports with filters, Preview, ⤓ PDF / Excel / CSV; large ones show "Inaandaliwa…" with a progress bar from `/jobs/{id}`.
- **Ukaguzi:** filter by user, table, record, date; before/after JSON diff (no secrets).
- **Mipangilio:** grading schemes and bands editor, assessment components with a live weight total (must equal 100), SMS templates sw/en with placeholder check, roles and users, devices and cards.

## 14.3 Teacher portal (phone)

```text
┌──────────────────────────────┐ ┌──────────────────────────────┐ ┌──────────────────────────────┐
│ Habari Mwl. Salma   ● Online │ │ ← Mahudhurio · II A · 02/03  │ │ ← Alama · II A · KIING · CA  │
│ Leo: Jumatatu 02/03/2026     │ │ Wote wapo ✓  [Weka wote]     │ │ Max 100 · Uzito 30%          │
│ ┌ Madarasa yangu ──────────┐ │ │ Amani Massawe     [P][A][L][E]│ │ Amani Massawe   [ 66 ] ●     │
│ │ II A · Mwalimu wa darasa │ │ │ Baraka Lyimo      [P][A]⦿[L][E]│ │ Baraka Lyimo    [ 71 ] ●     │
│ │ II B · Kiingereza        │ │ │ Rehema Swai       [P][A][L]⦿[E]│ │ Rehema Swai     [    ] ⚠    │
│ └──────────────────────────┘ │ │ Zawadi Hassan     ⦿[A][L][E] │ │ Zawadi Hassan   [120] ✗ max │
│ [📋 Mahudhurio] [✎ Alama]    │ │                              │ │ ● Imehifadhiwa nje ya mtandao│
│ [📄 Nyaraka 3]  [🗓 Ratiba]  │ │ [   HIFADHI (4)   ]          │ │ ⚠ Mgongano: seva 74 · wewe 71│
│ [⚠ Nidhamu]                  │ │ ● Imesawazishwa 07:52        │ │   [Tumia 74] [Tumia 71]      │
└──────────────────────────────┘ └──────────────────────────────┘ └──────────────────────────────┘
┌──────────────────────────────┐ ┌──────────────────────────────┐
│ ← Hakiki nyaraka (3)         │ │ ← Ratiba yangu · Muhula 1    │
│ Neema Mollel · F1            │ │ Jtt 08:00 II B KIING  F2B    │
│ Picha ya pasipoti [Ona 🔍]   │ │ Jtt 08:40 II A KIING  F2A    │
│ (●) Sahihi ( ) Si sahihi     │ │ Jnn 08:00 II A KISW   F2A    │
│ Maoni (lazima kama si sahihi)│ │ …                            │
│ [ Picha haionekani vizuri ]  │ │ Vipindi 14/30 kwa wiki       │
│ [ HIFADHI ]                  │ │                              │
└──────────────────────────────┘ └──────────────────────────────┘
```

Discipline (Nidhamu): student ▾, date, category ▾, description, action → "Mzazi atajulishwa kwa SMS".

## 14.4 Bursar portal

```text
Ada › Ankara   Muhula [1 ▾] Darasa [Yote ▾] Hali [Zote ▾]   [⚙ Tengeneza ankara] [⤓ Excel]
INV-2026-000003 │ Baraka Lyimo │ 635,000 │ Imelipwa 300,000 │ Salio 335,000 │ PARTIALLY_PAID │ 994120…
────────────────────────────────────────────────────────────────────────────────────────────
Rekodi malipo: Mwanafunzi [🔍 MF-2025-0027] Njia (●)Taslimu ( )Benki  Kumbukumbu [RCT-BOOK-0002]
Kiasi [ 200,000 ]  Aliyelipa [Mwanaisha Hassan] Simu [0715 000 022]  [Hifadhi na risiti]
✗ Kumbukumbu hii imeshatumika (E19)
────────────────────────────────────────────────────────────────────────────────────────────
Ulinganisho 31/01/2026 · M-Pesa · Taarifa 380,000 = Mfumo 380,000 ✓ BALANCED
Kubatilisha malipo: QKX1ABCD22 TZS 100,000 · Sababu [ … ] [Omba] → inasubiri idhini ya Mkuu wa shule
Ripoti: Wadaiwa · Umri wa madeni (1–30, 31–60, 61–90, 90+) · Makusanyo kwa njia · Historia ya miamala
```

## 14.5 Parent portal (phone, 2G-friendly, < 5 KB per screen)

```text
┌──────────────────────────────┐ ┌──────────────────────────────┐ ┌──────────────────────────────┐
│ Karibu John Massawe   [SW|en]│ │ ← Amani · Matokeo            │ │ ← Amani · Ada                │
│ ┌ Amani Massawe · II A ────┐ │ │ Muhula wa Kwanza 2026         │ │ INV-2026-000001  ✓ IMELIPWA  │
│ │ Leo: ✓ Yupo (07:31 geti) │ │ │ Wastani 66.97 · Daraja I      │ │ Jumla      TZS 680,000       │
│ │ Ada: ✓ Imelipwa          │ │ │ Nafasi 4/6                    │ │ Imelipwa   TZS 680,000       │
│ │ Matokeo: Daraja I  [Ona] │ │ │ HIS za Msingi  82  A          │ │ Risiti: RCT-2026-000001 ⤓    │
│ └──────────────────────────┘ │ │ Kiingereza     68  B          │ │ ──────────────────────────── │
│ ┌ Lucy Massawe · Std IV ───┐ │ │ Fizikia*       90  A          │ │ Muhula 2: INV-2026-000007    │
│ │ (Msingi Upendo) [Badili] │ │ │ *imerekebishwa                │ │ Salio TZS 630,000            │
│ └──────────────────────────┘ │ │ [⤓ Ripoti (PDF)]              │ │ Namba ya malipo 994120000014 │
│ 📢 Mkutano wa wazazi 14/03   │ │                               │ │ [Lipa kwa M-Pesa]            │
│ [🏠][📅][📊][💰][☰]           │ │                               │ │ Lipa: *150*00# → GePG → namba│
└──────────────────────────────┘ └──────────────────────────────┘ └──────────────────────────────┘
```

Attendance (Mahudhurio): a month calendar with ✓ / ✗ / L per day and a "Siku 3 hakuwepo wiki hii" warning. Announcements (Matangazo): a list.

## 14.6 Student portal (phone)

Home tiles: **Ratiba ya leo** · **Matokeo** · **Salio la ada** · **Ombi la bweni** · **Badili nenosiri**.

```text
┌──────────────────────────────┐
│ ← Ombi la bweni              │
│ Muhula [ Wa Pili ▾ ]         │
│ Bweni unalopendelea          │
│ [ Kilimanjaro (Wasichana) ▾ ]│
│ [  TUMA OMBI  ]              │
│ Hali: ⏳ Linasubiri uamuzi    │
└──────────────────────────────┘
```

## 14.7 Bank interface and gate device

```text
Benki · Thibitisha amana (Grace Mushi, CRDB)
Kumbukumbu       │ Tarehe     │ Kiasi    │ Mwanafunzi        │ Hali
CRDB-2026-77881  │ 10/02/2026 │ 300,000  │ Rehema Swai       │ [✓ Thibitisha] [✗ Kataa]

Gate device (kiosk, full screen)          ┌───────────────────────────┐
                                          │  ✓ Amani Massawe · II A   │
                                          │    07:31  KARIBU          │
                                          │  (offline queue: 0)       │
                                          └───────────────────────────┘
                                          ✗ Kadi haitambuliki — mwone mlinzi
```

## 14.8 Super admin console

Schools list (code, name, region, status, students, last activity) → **+ Shule mpya** (onboarding wizard: details → first admin → defaults → done) · Suspend/Activate with reason · SMS credit top-ups · platform health (queues, error rate).
