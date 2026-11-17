"""Enrolment, requirement documents and the student <-> session link."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CHAR, BigInteger, DateTime, ForeignKey, Identity, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.academic import CourseOffering
from app.models.enums import DocumentStatus, EducationLevel, EnrolmentStatus
from app.models.people import Student


class EnrolmentRequirement(Base):
    __tablename__ = "enrolment_requirements"

    requirement_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(20))
    name_en: Mapped[str] = mapped_column(String(100))
    name_sw: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    education_level: Mapped[EducationLevel | None]
    is_mandatory: Mapped[bool] = mapped_column(server_default=text("true"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class Enrolment(Base):
    __tablename__ = "enrolments"

    enrolment_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    enrolment_no: Mapped[str] = mapped_column(String(20))
    student_id: Mapped[int] = mapped_column(ForeignKey("students.student_id"))
    offering_id: Mapped[int] = mapped_column(ForeignKey("course_offerings.offering_id"))
    stream: Mapped[str | None] = mapped_column(String(5))
    status: Mapped[EnrolmentStatus] = mapped_column(server_default=EnrolmentStatus.PENDING.value)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    student: Mapped[Student] = relationship(lazy="joined")
    offering: Mapped[CourseOffering] = relationship(lazy="joined")
    documents: Mapped[list[EnrolmentDocument]] = relationship(back_populates="enrolment")


class EnrolmentDocument(Base):
    __tablename__ = "enrolment_documents"

    document_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    enrolment_id: Mapped[int] = mapped_column(ForeignKey("enrolments.enrolment_id"))
    requirement_id: Mapped[int] = mapped_column(ForeignKey("enrolment_requirements.requirement_id"))
    file_name: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(50))
    file_size_bytes: Mapped[int]
    sha256: Mapped[str] = mapped_column(CHAR(64))
    status: Mapped[DocumentStatus] = mapped_column(server_default=DocumentStatus.PENDING.value)
    remarks: Mapped[str | None] = mapped_column(String(300))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    validated_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    enrolment: Mapped[Enrolment] = relationship(back_populates="documents")
    requirement: Mapped[EnrolmentRequirement] = relationship(lazy="joined")


class EnrolmentSchedule(Base):
    __tablename__ = "enrolment_schedules"

    enrolment_id: Mapped[int] = mapped_column(ForeignKey("enrolments.enrolment_id"), primary_key=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("schedules.schedule_id"), primary_key=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
