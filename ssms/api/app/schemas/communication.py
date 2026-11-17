"""Announcements, in-app notifications, message templates, SMS log and credit."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import Audience


class AnnouncementIn(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    body: str = Field(min_length=3, max_length=2000)
    language: Literal["sw", "en"] = "sw"
    audience: Audience
    class_id: uuid.UUID | None = None
    stream_id: uuid.UUID | None = None
    target_user_id: uuid.UUID | None = None
    send_sms: bool = False
    send_email: bool = Field(default=False, description="Also email recipients who have an email address (FR-98)")
    publish_at: datetime | None = Field(default=None, description="Default now; SMS go out when the job runs")

    @model_validator(mode="after")
    def _audience(self):
        needs = {Audience.CLASS: "class_id", Audience.STREAM: "stream_id", Audience.INDIVIDUAL: "target_user_id"}
        given = {f for f in ("class_id", "stream_id", "target_user_id") if getattr(self, f) is not None}
        expected = {needs[self.audience]} if self.audience in needs else set()
        if given != expected:
            raise ValueError("invalid_value")
        return self


class AnnouncementOut(BaseModel):
    id: uuid.UUID
    title: str
    body: str
    language: str
    audience: str
    class_id: uuid.UUID | None
    stream_id: uuid.UUID | None
    target_user_id: uuid.UUID | None
    send_sms: bool
    publish_at: datetime
    created_at: datetime


class AnnouncementCreated(AnnouncementOut):
    sms_recipients: int = 0
    sms_job_id: uuid.UUID | None = None
    email_recipients: int = 0


class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    body: str
    link: str | None
    read_at: datetime | None
    created_at: datetime


class InboxOut(BaseModel):
    unread: int
    items: list[NotificationOut]


class TemplateOut(BaseModel):
    key: str
    language: str
    body: str
    is_active: bool
    customised: bool = Field(description="False when the built-in default is used")
    placeholders: list[str]


class TemplateIn(BaseModel):
    body: str = Field(min_length=3, max_length=480)
    is_active: bool = True


class SmsRow(BaseModel):
    id: uuid.UUID
    to: str = Field(description="Masked number, ****1234")
    template_key: str | None
    language: str
    body: str
    segments: int
    status: str
    cost_credits: int
    error: str | None
    queued_at: datetime
    sent_at: datetime | None
    delivered_at: datetime | None


class CreditRow(BaseModel):
    kind: str
    credits: int
    note: str | None
    created_at: datetime


class CreditOut(BaseModel):
    credits_left: int
    low: bool
    history: list[CreditRow]


class TopUpIn(BaseModel):
    credits: int = Field(gt=0, le=1_000_000)
    note: str = Field(min_length=3, max_length=200, description="e.g. invoice or receipt of the SMS bundle")
