# 8. Activity Diagrams (with swimlanes)

Mermaid has no UML activity diagram, so each swimlane is a subgraph. Notation: `((●))` is the initial node, `(((◉)))` the final node, diamonds are decisions/merges, and rounded boxes are actions. The text under each diagram lists every guard condition.

## 8.0 Baseline — Enrolment Requirements (reproduced)

```mermaid
flowchart TB
    subgraph ST["Student"]
        S0((●))
        S1(Inquire enrolment)
        S2(Comply with requirements)
        S3("Some of your requirements are invalid")
        S4("Your requirements are completed!")
        S5(((◉)))
    end
    subgraph SY["School Management System"]
        Y1(Show list of requirements)
        Y2(Save compliance)
        Y3(Save validated files)
        Y4{Are all files valid?}
    end
    subgraph FA["School Faculty"]
        F1(Check validity of files)
    end
    S0 --> S1 --> Y1 --> S2 --> Y2 --> F1 --> Y3 --> Y4
    Y4 -->|No| S3 --> S2
    Y4 -->|Yes| S4 --> S5
```

**Problems.**

- Files are "saved" before anyone checks their type or size.
- Validity is all-or-nothing, so the student re-uploads every file even if only one is invalid and is never told which one.
- There is no "all mandatory documents uploaded?" check before the faculty is involved.
- There is no deadline or cancel path, so the loop can run forever.
- "Save validated files" saves files that have already been saved; what should be saved is the validation result.

## 8.1 Corrected — Enrolment Requirements

```mermaid
flowchart TB
    subgraph ST["Student · Mwanafunzi"]
        S0((●))
        S1(Inquire enrolment)
        S2(Upload a document for each requirement)
        S3("Show file error:<br/>only PDF/JPG/PNG ≤ 5 MB")
        S4(Submit requirements)
        S5("Some of your requirements are invalid<br/>Baadhi ya mahitaji yako si sahihi<br/>(remarks per document)")
        S6(Re-upload only the INVALID documents)
        S7("Your requirements are completed!<br/>Mahitaji yako yamekamilika!")
        S8(((◉)))
    end
    subgraph SY["School Management System"]
        Y1(Show requirements for the<br/>offering's education level)
        Y2{File type, size<br/>and checksum OK?}
        Y3(Save document as PENDING<br/>enrolment_documents)
        Y4{All mandatory<br/>requirements uploaded?}
        Y5(Set enrolment SUBMITTED,<br/>notify faculty)
        Y6(Save VALID / INVALID,<br/>validator and time)
        Y7{Any document<br/>still PENDING?}
        Y8{All mandatory<br/>documents VALID?}
        Y9(Set enrolment INVALID)
        Y10(Set enrolment VALIDATED,<br/>notify registrar)
        Y11{Enrolment deadline<br/>passed?}
        Y12(Cancel enrolment,<br/>notify student)
    end
    subgraph FA["School Faculty · Mwalimu"]
        F1(Open next PENDING document)
        F2{Is the document<br/>genuine and readable?}
        F3(Mark VALID)
        F4(Mark INVALID with remarks)
    end

    S0 --> S1 --> Y1 --> S2 --> Y2
    Y2 -->|No| S3 --> S2
    Y2 -->|Yes| Y3 --> Y4
    Y4 -->|No| S2
    Y4 -->|Yes| S4 --> Y5 --> F1 --> F2
    F2 -->|Yes| F3 --> Y6
    F2 -->|No| F4 --> Y6
    Y6 --> Y7
    Y7 -->|Yes| F1
    Y7 -->|No| Y8
    Y8 -->|Yes| Y10 --> S7 --> S8
    Y8 -->|No| Y9 --> S5 --> Y11
    Y11 -->|No| S6 --> Y2
    Y11 -->|Yes| Y12 --> S8
```

**Fixes.**

- Files are checked (type by magic bytes, size, SHA-256) before they are saved.
- Faculty validates each document separately, and INVALID requires remarks.
- The student re-uploads only the invalid documents.
- The enrolment status is derived: VALIDATED only when every mandatory document is VALID.
- A deadline ends the loop.
- Optional documents (e.g. a transfer letter) never block validation.

## 8.2 Class Scheduling

```mermaid
flowchart TB
    subgraph AD["Admin / Academic Master"]
        A0((●))
        A1(Select term, offering and stream)
        A2{Manual or<br/>automatic?}
        A3(Pick subject, instructor,<br/>room, day, start, end)
        A4(Review draft timetable<br/>and unplaced periods)
        A5{Accept draft?}
        A6(Publish timetable)
    end
    subgraph SY["School Management System"]
        Y1(Load demand: course_subjects × periods,<br/>existing sessions, rooms, instructors)
        Y2{Instructor qualified<br/>for subject?}
        Y3{Instructor, room, class or<br/>student clash?}
        Y4(Show conflicts and<br/>suggest free slots)
        Y5{Room capacity ≥ class size,<br/>room type OK, load OK?}
        Y6(Show reason)
        Y7(Save session — EXCLUDE<br/>constraints re-check)
        Y8(Link confirmed students<br/>of the stream)
        Y9{More periods<br/>to place?}
        Y10(Run schedulingAlgo)
        Y11(Save all draft sessions<br/>in one transaction)
        Y12(Notify instructors and students)
    end
    subgraph IN["Instructor"]
        I1(Receive teaching timetable<br/>and class lists)
        I2(((◉)))
    end

    A0 --> A1 --> Y1 --> A2
    A2 -->|Manual| A3 --> Y2
    Y2 -->|No| Y6
    Y2 -->|Yes| Y3
    Y3 -->|Yes| Y4 --> A3
    Y3 -->|No| Y5
    Y5 -->|No| Y6 --> A3
    Y5 -->|Yes| Y7 --> Y8 --> Y9
    Y9 -->|Yes| A3
    Y9 -->|No| A6
    A2 -->|Automatic| Y10 --> A4 --> A5
    A5 -->|No, adjust| A3
    A5 -->|Yes| Y11 --> A6
    A6 --> Y12 --> I1 --> I2
```

Guards: a session is saved only when the instructor is qualified, there is no clash of any of the four kinds, the room is big enough and of the right type, and the instructor stays within `max_periods_per_week`. The algorithm is described in [section 9.3](09-class-diagram.md#93-scheduling-algorithm-schedulingalgo).

## 8.3 Fee Payment

```mermaid
flowchart TB
    subgraph BU["Bursar · Mhasibu"]
        B0((●))
        B1(Define fee structure<br/>per term, level, course)
        B2(Record cash / bank-slip payment<br/>with receipt or reference no.)
        B3(Correct entry)
    end
    subgraph SY["School Management System"]
        Y1(Generate invoice on enrolment<br/>confirmation or term start)
        Y2(Request GePG control number)
        Y3(Save control number,<br/>SMS invoice to parent)
        Y4{Signature valid?}
        Y5(Reject and alert admin)
        Y6{Reference already<br/>recorded?}
        Y7(Acknowledge only<br/>— idempotent)
        Y8(Insert COMPLETED transaction)
        Y9{Reference given unless CASH,<br/>amount > 0, invoice open?}
        Y10(Recalculate balance<br/>v_invoice_balances)
        Y11(Send SMS receipt<br/>with balance)
        Y12{Balance > 0?}
        Y13(Reminder SMS 7 days<br/>before due date)
        Y14(Invoice shows PAID)
    end
    subgraph PA["Parent / Student · Mzazi"]
        P1{Pay how?}
        P2(Pay with control number via<br/>M-Pesa, Tigo Pesa, Airtel Money or bank)
        P3(Pay at bursar's office)
        P4(Receive receipt)
        P5(((◉)))
    end
    subgraph GW["Payment Gateway · GePG"]
        G1(Issue control number)
        G2(Send signed payment notification)
    end

    B0 --> B1 --> Y1 --> Y2 --> G1 --> Y3 --> P1
    P1 -->|Control number| P2 --> G2 --> Y4
    Y4 -->|No| Y5
    Y4 -->|Yes| Y6
    Y6 -->|Yes| Y7
    Y6 -->|No| Y8
    P1 -->|At school| P3 --> B2 --> Y9
    Y9 -->|No| B3 --> B2
    Y9 -->|Yes| Y6
    Y8 --> Y10 --> Y11 --> P4 --> Y12
    Y12 -->|Yes| Y13 --> P1
    Y12 -->|No| Y14 --> P5
```

A wrong entry is never edited. The bursar posts a **REVERSAL** (with Admin approval), which links to the original transaction and restores the balance. The reversal follows the same path from `Y8`.
