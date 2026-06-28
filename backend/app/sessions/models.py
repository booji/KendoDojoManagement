from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator


class SessionTypeCreate(BaseModel):
    name: str


class SessionTypeRead(BaseModel):
    id: str
    name: str
    colour: str | None = None


class SessionTypeUpdate(BaseModel):
    colour: str | None = None

    @field_validator("colour")
    @classmethod
    def validate_hex_colour(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}", v):
            raise ValueError("colour must be a 6-digit hex string e.g. #ff5733")
        return v


# ---------------------------------------------------------------------------
# Segments — shared shape for both SessionInstance and SessionTemplate
# ---------------------------------------------------------------------------


class SegmentCreate(BaseModel):
    start_time: str  # "HH:MM"
    duration_minutes: int
    coach_notes: str | None = None
    type_ids: list[str]

    @field_validator("start_time")
    @classmethod
    def validate_start_time(cls, v: str) -> str:
        # HH:MM, 00:00–23:59. Prevents malformed strings reaching the
        # time-envelope/iCal arithmetic as an unhandled 500.
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
            raise ValueError("start_time must be in HH:MM 24-hour format")
        return v

    @field_validator("duration_minutes")
    @classmethod
    def validate_positive_duration(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("duration_minutes must be greater than 0")
        # Cap at 24h — a single segment longer than a day is incoherent and a
        # huge value is a needless DoS/overflow surface.
        if v > 24 * 60:
            raise ValueError("duration_minutes must not exceed 1440 (24 hours)")
        return v

    @field_validator("type_ids")
    @classmethod
    def validate_at_least_one_type(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("a segment must have at least one type")
        return v


class SegmentRead(BaseModel):
    id: str | None = None
    start_time: str
    duration_minutes: int
    coach_notes: str | None = None
    type_ids: list[str] = []


def _validate_segments_nonempty(segments: list[SegmentCreate]) -> list[SegmentCreate]:
    if not segments:
        raise ValueError("a session must have at least one segment")
    return segments


# ---------------------------------------------------------------------------
# Session templates
# ---------------------------------------------------------------------------


class SessionTemplateCreate(BaseModel):
    title: str
    start_date: str  # "YYYY-MM-DD"
    recurrence: str = "weekly"
    day_of_week: int | None = None  # kept for backwards compat; nullable
    location: str | None = None
    recurrence_days: list[int] = []
    interval_weeks: int = Field(default=1, ge=1)
    info: str | None = None
    coach_notes: str | None = None
    segments: list[SegmentCreate]

    @field_validator("segments")
    @classmethod
    def validate_segments_nonempty(cls, v: list[SegmentCreate]) -> list[SegmentCreate]:
        return _validate_segments_nonempty(v)


class SessionTemplateRead(BaseModel):
    id: str
    title: str
    start_date: str
    start_time: str  # derived envelope value
    duration_minutes: int  # derived envelope value
    recurrence: str
    day_of_week: int | None = None
    location: str | None = None
    recurrence_days: list[int] = []
    interval_weeks: int = 1
    info: str | None = None
    coach_notes: str | None = None
    segments: list[SegmentRead] = []


class SessionTemplateUpdate(BaseModel):
    location: str | None = None
    info: str | None = None
    coach_notes: str | None = None
    title: str | None = None
    recurrence_days: list[int] | None = None
    interval_weeks: int | None = None
    segments: list[SegmentCreate] | None = None

    @field_validator("segments")
    @classmethod
    def validate_segments_nonempty_if_present(
        cls, v: list[SegmentCreate] | None
    ) -> list[SegmentCreate] | None:
        if v is not None:
            return _validate_segments_nonempty(v)
        return v


# ---------------------------------------------------------------------------
# Session instances
# ---------------------------------------------------------------------------


class SessionInstanceCreate(BaseModel):
    title: str
    date: str  # "YYYY-MM-DD"
    notes: str | None = None
    template_id: str | None = None
    location: str | None = None
    info: str | None = None
    coach_notes: str | None = None
    checkin_url: str | None = None
    segments: list[SegmentCreate]

    @field_validator("segments")
    @classmethod
    def validate_segments_nonempty(cls, v: list[SegmentCreate]) -> list[SegmentCreate]:
        return _validate_segments_nonempty(v)


class SessionInstanceRead(BaseModel):
    id: str
    title: str
    date: str
    start_time: str  # derived envelope value
    duration_minutes: int  # derived envelope value
    notes: str | None = None
    template_id: str | None = None
    cancelled: bool = False
    location: str | None = None
    info: str | None = None
    coach_notes: str | None = None
    checkin_url: str | None = None
    attendance_count: int = 0
    is_checked_in: bool = False
    segments: list[SegmentRead] = []


class GenerateRequest(BaseModel):
    horizon: str  # "YYYY-MM-DD" — generate instances up to this date


class SessionInstanceUpdate(BaseModel):
    title: str | None = None
    location: str | None = None
    info: str | None = None
    coach_notes: str | None = None
    segments: list[SegmentCreate] | None = None

    @field_validator("segments")
    @classmethod
    def validate_segments_nonempty_if_present(
        cls, v: list[SegmentCreate] | None
    ) -> list[SegmentCreate] | None:
        if v is not None:
            return _validate_segments_nonempty(v)
        return v
