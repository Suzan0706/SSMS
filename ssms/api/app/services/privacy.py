"""Data-subject requests (FR-70, PDPA 2022): export, correct, delete — tracked with a due date.

EXPORT writes one JSON file with what the school holds about the person (profile, student record, enrolments,
results, attendance, fees, discipline, library, health, consents, guardians or children, SMS sent to them) and
completes the request. CORRECT is done in the normal screens, then completed with a note. DELETE anonymises: names,
contacts, identifiers and the login are removed, consents withdrawn, health notes destroyed — while ledgers, receipts
and published results stay, because the law requires them; an active staff member cannot be anonymised.
The answer is due 30 days after the request (VERIFY the PDPA regulations' time limit).
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.crypto import get_cipher
from app.core.errors import AppError
from app.core.storage import get_storage
from app.models import (
    ConsentRecord,
    DataSubjectRequest,
    Guardian,
    HealthRecord,
    RefreshToken,
    Staff,
    Student,
    StudentGuardian,
    User,
)
from app.models.enums import DsrStatus, DsrType, StaffStatus, UserStatus
from app.services import audit, crud
from app.services.people import decrypt_phone, now
from app.services.student_life import HEALTH_FIELD, _notes

DUE_DAYS = 30
OPEN = (DsrStatus.RECEIVED, DsrStatus.IN_PROGRESS)


async def create(
    session: AsyncSession, principal: Principal, subject_user_id: uuid.UUID, kind: DsrType, details: str | None
):
    await crud.get_live(session, User, subject_user_id)
    item = DataSubjectRequest(
        school_id=principal.school_id,
        subject_user_id=subject_user_id,
        request_type=kind,
        details=details,
        due_at=now() + timedelta(days=DUE_DAYS),
        created_by=principal.user_id,
    )
    session.add(item)
    await session.commit()
    return item


async def set_status(
    session: AsyncSession, principal: Principal, request_id: uuid.UUID, status: DsrStatus, note: str | None
):
    item = await crud.get_live(session, DataSubjectRequest, request_id, lock=True)
    if item.status not in OPEN:
        raise AppError(409, "NOT_ALLOWED", [{"field": "status", "code": "invalid_value"}])
    if status == DsrStatus.COMPLETED and item.request_type != DsrType.CORRECT:
        raise AppError(
            422, "VALIDATION_ERROR", [{"field": "status", "code": "invalid_value"}]
        )  # export/delete complete themselves
    item.status, item.handled_by = status, principal.user_id
    if note:
        item.details = (f"{item.details or ''}\n{note}").strip()[:500]
    if status in (DsrStatus.COMPLETED, DsrStatus.REJECTED):
        item.completed_at = now()
    await session.commit()
    return item


def _rows(result) -> list[dict]:
    return [
        {
            k: (str(v) if v is not None and not isinstance(v, int | float | bool | str) else v)
            for k, v in r._mapping.items()
        }
        for r in result
    ]


async def _q(session: AsyncSession, sql: str, **params) -> list[dict]:
    return _rows((await session.execute(text(sql), params)).all())


async def collect(session: AsyncSession, user_id: uuid.UUID) -> dict:
    user = await crud.get_live(session, User, user_id)
    data: dict = {
        "generated_at": now().isoformat(),
        "profile": {
            "first_name": user.first_name,
            "middle_name": user.middle_name,
            "last_name": user.last_name,
            "gender": user.gender,
            "date_of_birth": user.date_of_birth.isoformat() if user.date_of_birth else None,
            "phone": decrypt_phone(user),
            "email": user.email,
            "username": user.username,
            "language": user.preferred_language,
            "status": user.status,
        },
    }
    student = (await session.execute(text("SELECT id FROM students WHERE user_id = :u"), {"u": user_id})).scalar()
    if student:
        s = {"student": student}
        data["student"] = (
            await _q(
                session,
                "SELECT admission_no, status, admission_date, prem_number FROM students WHERE id = :student",
                **s,
            )
        )[0]
        data["enrolments"] = await _q(
            session,
            "SELECT y.name AS year, c.code AS class, st.name AS stream, e.status, e.started_on, e.ended_on FROM "
            "enrolments e "
            "JOIN academic_years y ON y.id = e.academic_year_id JOIN streams st ON st.id = e.stream_id "
            "JOIN classes c ON c.id = st.class_id WHERE e.student_id = :student ORDER BY e.started_on",
            **s,
        )
        data["results"] = await _q(
            session,
            "SELECT t.name_en AS term, ts.average_score, ts.total_points, ts.division, ts.class_position "
            "FROM student_term_summaries ts JOIN enrolments e ON e.id = ts.enrolment_id "
            "JOIN result_publications p ON p.id = ts.publication_id JOIN terms t ON t.id = p.term_id "
            "WHERE e.student_id = :student AND NOT EXISTS "
            "(SELECT 1 FROM student_term_summaries x WHERE x.supersedes_id = ts.id) ORDER BY t.start_date",
            **s,
        )
        data["attendance"] = await _q(
            session,
            "SELECT a.session_date, a.kind, r.status FROM attendance_records r JOIN attendance_sessions a "
            "ON a.id = r.session_id WHERE r.student_id = :student ORDER BY a.session_date",
            **s,
        )
        data["invoices"] = await _q(
            session,
            "SELECT invoice_no, due_date, total_tzs, paid_tzs, balance_tzs, status FROM invoices WHERE student_id = "
            ":student",
            **s,
        )
        data["payments"] = await _q(
            session,
            "SELECT p.received_at, p.channel, p.external_ref, p.amount_tzs, p.status, r.receipt_no FROM payments p "
            "LEFT JOIN receipts r ON r.payment_id = p.id WHERE p.student_id = :student ORDER BY p.received_at",
            **s,
        )
        data["discipline"] = await _q(
            session,
            "SELECT incident_date, category, description, action_taken, resolution, status FROM discipline_records "
            "WHERE student_id = :student AND deleted_at IS NULL",
            **s,
        )
        health = (
            await session.execute(
                text(
                    "SELECT record_date, kind, notes_enc FROM health_records WHERE student_id = :student AND "
                    "deleted_at IS NULL"
                ),
                s,
            )
        ).all()
        data["health"] = [{"date": str(d), "kind": k, "notes": _notes(n)} for d, k, n in health]
        data["guardians"] = await _q(
            session,
            "SELECT u.first_name, u.last_name, sg.relationship, sg.is_primary, sg.receives_sms FROM "
            "student_guardians sg "
            "JOIN guardians g ON g.id = sg.guardian_id JOIN users u ON u.id = g.user_id "
            "WHERE sg.student_id = :student AND sg.deleted_at IS NULL",
            **s,
        )
    data["library_loans"] = await _q(
        session,
        "SELECT b.title, l.loaned_at, l.due_date, l.returned_at FROM library_loans l JOIN library_books b ON b.id = "
        "l.book_id "
        "WHERE l.borrower_user_id = :u",
        u=user_id,
    )
    guardian = (await session.execute(text("SELECT id FROM guardians WHERE user_id = :u"), {"u": user_id})).scalar()
    if guardian:
        data["children"] = await _q(
            session,
            "SELECT st.admission_no, u.first_name, u.last_name, sg.relationship FROM student_guardians sg "
            "JOIN students st ON st.id = sg.student_id JOIN users u ON u.id = st.user_id "
            "WHERE sg.guardian_id = :g AND sg.deleted_at IS NULL",
            g=guardian,
        )
        data["consents"] = await _q(
            session,
            "SELECT purpose, granted, channel, recorded_at, withdrawn_at FROM consent_records WHERE guardian_id = :g",
            g=guardian,
        )
    data["sms_received"] = await _q(
        session,
        "SELECT queued_at, template_key, body, status FROM sms_messages WHERE to_user_id = :u ORDER BY queued_at",
        u=user_id,
    )
    return data


async def export(session: AsyncSession, principal: Principal, request_id: uuid.UUID) -> DataSubjectRequest:
    item = await crud.get_live(session, DataSubjectRequest, request_id, lock=True)
    if item.request_type != DsrType.EXPORT or item.status not in OPEN:
        raise AppError(409, "NOT_ALLOWED", [{"field": "request_type", "code": "invalid_value"}])
    data = await collect(session, item.subject_user_id)
    key = f"{principal.school_id}/privacy/{item.id}/export.json"
    get_storage().put(key, json.dumps(data, ensure_ascii=False, indent=1).encode())
    item.result_file_key, item.status, item.completed_at, item.handled_by = (
        key,
        DsrStatus.COMPLETED,
        now(),
        principal.user_id,
    )
    await audit.record(session, "EXPORT", "data_subject_requests", item.id, {"sections": sorted(data)})
    await session.commit()
    return item


async def anonymise(session: AsyncSession, principal: Principal, request_id: uuid.UUID) -> DataSubjectRequest:
    item = await crud.get_live(session, DataSubjectRequest, request_id, lock=True)
    if item.request_type != DsrType.DELETE or item.status not in OPEN:
        raise AppError(409, "NOT_ALLOWED", [{"field": "request_type", "code": "invalid_value"}])
    user_id = item.subject_user_id
    if user_id == principal.user_id:
        raise AppError(409, "NOT_ALLOWED", [{"field": "subject_user_id", "code": "invalid_value"}])
    active_staff = (
        await session.execute(
            text("SELECT 1 FROM staff WHERE user_id = :u AND status = :s AND deleted_at IS NULL"),
            {"u": user_id, "s": StaffStatus.ACTIVE.value},
        )
    ).first()
    if active_staff:
        raise AppError(409, "NOT_ALLOWED", [{"field": "subject_user_id", "code": "in_use"}])
    tag = user_id.hex[:8].upper()
    await session.execute(
        update(User)
        .where(User.id == user_id)
        .values(
            first_name="Aliyefutwa",
            middle_name=None,
            last_name=f"#{tag}",
            date_of_birth=None,
            phone_enc=None,
            phone_hash=None,
            phone_last4=None,
            email=None,
            username=None,
            password_hash=None,
            status=UserStatus.NO_LOGIN,
            must_change_password=False,
        )
    )
    await session.execute(update(RefreshToken).where(RefreshToken.user_id == user_id).values(revoked_at=now()))
    await session.execute(
        update(Student)
        .where(Student.user_id == user_id)
        .values(birth_cert_no_enc=None, birth_cert_no_hash=None, nida_enc=None, nida_hash=None, photo_file_key=None)
    )
    students = (
        (await session.execute(text("SELECT id FROM students WHERE user_id = :u"), {"u": user_id})).scalars().all()
    )
    if students:
        await session.execute(
            update(HealthRecord)
            .where(HealthRecord.student_id.in_(students), HealthRecord.deleted_at.is_(None))
            .values(notes_enc=get_cipher().encrypt("[deleted]", HEALTH_FIELD), deleted_at=now())
        )
    guardian_ids = (
        (await session.execute(text("SELECT id FROM guardians WHERE user_id = :u"), {"u": user_id})).scalars().all()
    )
    if guardian_ids:
        await session.execute(
            update(Guardian)
            .where(Guardian.id.in_(guardian_ids))
            .values(nida_enc=None, nida_hash=None, address=None, occupation=None)
        )
        await session.execute(
            update(ConsentRecord)
            .where(ConsentRecord.guardian_id.in_(guardian_ids), ConsentRecord.withdrawn_at.is_(None))
            .values(withdrawn_at=now())
        )
        await session.execute(
            update(StudentGuardian).where(StudentGuardian.guardian_id.in_(guardian_ids)).values(receives_sms=False)
        )
    await session.execute(update(Staff).where(Staff.user_id == user_id).values(salary_tzs=None, check_no=None))
    item.status, item.completed_at, item.handled_by = DsrStatus.COMPLETED, now(), principal.user_id
    await audit.record(session, "DELETE", "users", user_id, {"anonymised_by_request": str(item.id)})
    await session.commit()
    return item


def is_overdue(item: DataSubjectRequest) -> bool:
    return item.status in OPEN and item.due_at < datetime.now(UTC)
