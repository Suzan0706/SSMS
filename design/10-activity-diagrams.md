# 10. Activity Diagrams (swimlanes)

Mermaid has no UML activity diagram, so each swimlane is a subgraph. Notation: `((●))` is the start, `(((◉)))` the end, diamonds are decisions, and rounded boxes are actions. Guards are written on the arrows.

## 10.1 Enrolment

```mermaid
flowchart TB
    subgraph AP["Parent / Student · Mzazi / Mwanafunzi"]
        A0((●))
        A1(Inquire: open classes and places)
        A2{Pursue this class?<br/>Endelea?}
        A3(Fill application:<br/>applicant, guardians, SMS consent)
        A4(Upload a document per requirement)
        A5("Show: Some requirements are invalid<br/>Baadhi ya mahitaji si sahihi + comments")
        A6("Show: Requirements completed<br/>Mahitaji yamekamilika")
        A7("SMS: Enrolled, admission no. MF-2027-0012<br/>Usajili umekamilika")
        A8("SMS: Enrolment cancelled<br/>Usajili umesitishwa")
        AE(((◉)))
    end
    subgraph SY["SSMS"]
        S1(List classes open for the year<br/>with requirements)
        S2{File type, size,<br/>checksum OK?}
        S3(Save document PENDING)
        S4{All required<br/>documents uploaded?}
        S5(Application UNDER_REVIEW,<br/>notify teachers)
        S6{All required<br/>documents VALID?}
        S7(Back to REQUIREMENTS_PENDING)
        S8(One transaction: admission no.,<br/>student ACTIVE, enrolment,<br/>login, invoice)
        S9{Stream has<br/>places?}
        S10(Application REJECTED / CANCELLED<br/>with reason)
    end
    subgraph TE["Teacher · Mwalimu"]
        T1(Check validity of each document)
        T2(Mark VALID or INVALID + comment)
    end
    subgraph AD["School Admin"]
        H1{Confirm enrolment?<br/>Thibitisha usajili?}
        H2(Choose stream)
    end

    A0 --> A1 --> S1 --> A2
    A2 -->|No| A1
    A2 -->|Yes| A3 --> A4 --> S2
    S2 -->|No| A4
    S2 -->|Yes| S3 --> S4
    S4 -->|No| A4
    S4 -->|Yes| S5 --> T1 --> T2 --> S6
    S6 -->|No| S7 --> A5 --> A4
    S6 -->|Yes| A6 --> H1
    H1 -->|Yes| H2 --> S9
    S9 -->|Yes| S8 --> A7 --> AE
    S9 -->|No, choose another stream| H2
    H1 -->|No| S10 --> A8 --> AE
```

Compared with the baseline, the main changes are:

- files are checked before saving;
- validity is decided per document, and only the invalid ones are re-uploaded;
- the confirm/cancel decision is made by the school, after validation;
- approval is atomic, including the capacity check.

## 10.2 Fee payment

```mermaid
flowchart TB
    subgraph BU["Bursar · Mhasibu"]
        B0((●))
        B1(Approve fee structure)
        B2(Generate term invoices)
        B3(Record cash / confirm bank deposit)
        B4(Resolve reconciliation exceptions)
    end
    subgraph SY["SSMS"]
        S1(Invoices: lines, discounts,<br/>installments, journal)
        S2(Request GePG control number)
        S3{Signature and<br/>IP valid?}
        S4{external_ref already<br/>recorded for this school?}
        S5(Insert payment CONFIRMED,<br/>ACK in under 2 s)
        S6(Lock invoices FOR UPDATE,<br/>allocate oldest due first)
        S7{Money left over?}
        S8(Credit to student account 2100)
        S9(Journal, receipt RCT-YYYY-NNNNNN,<br/>SMS receipt)
        S10{Balance > 0<br/>and near due?}
        S11(Reminder SMS: 7 days before,<br/>3 days after due)
        S12(Daily reconciliation per channel)
        S13{Statement =<br/>system?}
        S14(Run BALANCED)
        S15(ACK only, no new row)
        S16(Reject 401 + alert)
    end
    subgraph PA["Parent · Mzazi"]
        P1(Receives SMS: amount,<br/>control no., due date)
        P2{Pay how?}
        P3(Pay with control no. via M-Pesa,<br/>Mixx by Yas, Airtel Money, HaloPesa, bank)
        P4(Pay cash at school)
        P5(Receives receipt SMS)
        PE(((◉)))
    end
    subgraph GW["GePG / Mobile Money"]
        G1(Issue control number)
        G2(Send payment callback)
    end

    B0 --> B1 --> B2 --> S1 --> S2 --> G1 --> P1 --> P2
    P2 -->|Mobile money / bank| P3 --> G2 --> S3
    S3 -->|No| S16
    S3 -->|Yes| S4
    S4 -->|Yes| S15
    S4 -->|No| S5 --> S6
    P2 -->|Cash| P4 --> B3 --> S6
    S6 --> S7
    S7 -->|Yes| S8 --> S9
    S7 -->|No| S9
    S9 --> P5 --> S10
    S10 -->|Yes| S11 --> P2
    S10 -->|No| PE
    S12 --> S13
    S13 -->|Yes| S14
    S13 -->|No| B4
```

A wrong payment is never edited: the bursar requests a **reversal**, a second person approves it, and a reversing journal is posted. Overpayments stay as credit and are applied to the next invoice.

## 10.3 Class scheduling

```mermaid
flowchart TB
    subgraph AD["School Admin / Academic Master"]
        H0((●))
        H1(Choose term and stream)
        H2{Manual or<br/>auto-generate?}
        H3(Pick subject, teacher, room,<br/>day, start, end)
        H4(Review draft and unplaced lessons)
        H5{Accept draft?}
        H6(Publish timetable)
    end
    subgraph SY["SSMS"]
        S1(Load demand: class subjects × periods,<br/>teaching assignments, rooms)
        S2{Teacher assigned to<br/>this stream and subject?}
        S3{Teacher, room or<br/>stream clash?}
        S4(Show conflict and free periods)
        S5{Room type and capacity OK,<br/>teacher load within max?}
        S6(Show reason)
        S7(Insert slot: EXCLUDE<br/>constraints re-check)
        S8{More lessons<br/>to place?}
        S9(Greedy placement, most constrained<br/>first, one-step repair)
        S10(Insert all slots in one transaction)
        S11(Notify teachers, refresh<br/>student timetables)
    end
    subgraph TE["Teacher"]
        T1(Sees teaching timetable)
        TE1(((◉)))
    end

    H0 --> H1 --> S1 --> H2
    H2 -->|Manual| H3 --> S2
    S2 -->|No| S6
    S2 -->|Yes| S3
    S3 -->|Yes| S4 --> H3
    S3 -->|No| S5
    S5 -->|No| S6 --> H3
    S5 -->|Yes| S7 --> S8
    S8 -->|Yes| H3
    S8 -->|No| H6
    H2 -->|Auto| S9 --> H4 --> H5
    H5 -->|No, adjust| H3
    H5 -->|Yes| S10 --> H6
    H6 --> S11 --> T1 --> TE1
```

## 10.4 Publishing results

```mermaid
flowchart TB
    subgraph TE["Teacher · Mwalimu"]
        T0((●))
        T1(Enter marks in the grid,<br/>offline autosave)
        T2(Resolve sync conflicts)
        T3(Fix missing / out-of-range marks)
        T4(Request amendment with reason)
    end
    subgraph SY["SSMS"]
        S1{Version current<br/>and score ≤ max?}
        S2(Save mark, version + 1)
        S3(Run validation firewall)
        S4{Problems?}
        S5(422 INCOMPLETE_GRADES_BLOCK:<br/>admission no., name, subject,<br/>component, teacher — sw/en)
        S6(One transaction: weighted totals,<br/>grades, points, positions, divisions,<br/>freeze results, lock marks)
        S7(Queue report-card PDFs<br/>and results SMS)
        S8(New frozen version,<br/>report card regenerated)
    end
    subgraph AD["School Admin"]
        H1(Publish term results for a class)
        H2{Approve amendment?<br/>approver is not requester}
        H3(Reject with note)
    end
    subgraph PA["Parent / Student"]
        P1(Sees results and report card,<br/>receives SMS)
        PE(((◉)))
    end

    T0 --> T1 --> S1
    S1 -->|No| T2 --> T1
    S1 -->|Yes| S2 --> H1 --> S3 --> S4
    S4 -->|Yes| S5 --> T3 --> T1
    S4 -->|No| S6 --> S7 --> P1 --> PE
    P1 -.->|error found| T4 --> H2
    H2 -->|Yes| S8 --> P1
    H2 -->|No| H3
```
