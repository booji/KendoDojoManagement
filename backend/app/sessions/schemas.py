from __future__ import annotations

import re
import uuid
from datetime import date

from pydantic import (
    BaseModel,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.core.partial_update import PartialUpdate


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

# Public per-segment free-text length caps. Keep the calendar description
# readable and bound the field against abuse with huge text.
_TITLE_MAX_LENGTH = 100


def _normalize_public_text(
    value: str | None, max_length: int, field_name: str
) -> str | None:
    """Trim surrounding whitespace, coerce empty/whitespace-only to None, and
    enforce the length cap on the trimmed value. An accidental space must not
    render a trailing separator in the calendar."""
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    if len(trimmed) > max_length:
        raise ValueError(f"{field_name} must not exceed {max_length} characters")
    return trimmed


class SegmentCreate(BaseModel):
    start_time: str  # "HH:MM"
    duration_minutes: int
    title: str | None = None  # public, optional
    # uuid.UUID so a malformed id is a 422, not a DataError 500 from the uuid
    # column (#586); dumped back to str, the form every record already holds.
    type_ids: list[uuid.UUID]

    @field_validator("title")
    @classmethod
    def normalize_title(cls, v: str | None) -> str | None:
        return _normalize_public_text(v, _TITLE_MAX_LENGTH, "title")

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
    def validate_at_least_one_type(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        if not v:
            raise ValueError("a segment must have at least one type")
        return v

    @field_serializer("type_ids")
    def serialize_type_ids(self, v: list[uuid.UUID]) -> list[str]:
        return [str(type_id) for type_id in v]


class SegmentRead(BaseModel):
    id: str | None = None
    start_time: str
    duration_minutes: int
    title: str | None = None
    type_ids: list[str] = []


def _validate_segments_nonempty(segments: list[SegmentCreate]) -> list[SegmentCreate]:
    if not segments:
        raise ValueError("a session must have at least one segment")
    return segments


# ---------------------------------------------------------------------------
# Session templates
# ---------------------------------------------------------------------------


def _validate_end_date_bounds(start_date: str, end_date: str) -> None:
    from app.sessions.service import TEMPLATE_MAX_HORIZON_MONTHS, add_months

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if end <= start:
        raise ValueError("end_date must be after start_date")
    cap = add_months(start, TEMPLATE_MAX_HORIZON_MONTHS)
    if end > cap:
        raise ValueError(
            f"end_date must not be more than {TEMPLATE_MAX_HORIZON_MONTHS} "
            "months after start_date"
        )


class SessionTemplateCreate(BaseModel):
    title: str
    start_date: str  # "YYYY-MM-DD"
    end_date: str  # "YYYY-MM-DD" — required; start_date < end_date <= start_date+6mo
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

    @model_validator(mode="after")
    def validate_end_date_bounds(self) -> SessionTemplateCreate:
        _validate_end_date_bounds(self.start_date, self.end_date)
        return self


class SessionTemplateRead(BaseModel):
    id: str
    title: str
    start_date: str
    end_date: str
    start_time: str  # derived envelope value
    duration_minutes: int  # derived envelope value
    recurrence: str
    day_of_week: int | None = None
    location: str | None = None
    recurrence_days: list[int] = []
    interval_weeks: int = 1
    info: str | None = None
    coach_notes: str | None = None
    # False once the series is cancelled (DELETE): it cannot be extended.
    is_active: bool = True
    segments: list[SegmentRead] = []


class SessionTemplateUpdate(PartialUpdate):
    not_null = frozenset({"title", "recurrence_days", "interval_weeks", "segments"})

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


class SessionTemplateExtend(BaseModel):
    end_date: str  # "YYYY-MM-DD" — new end_date, capped at 6 months from today


# ---------------------------------------------------------------------------
# Session instances
# ---------------------------------------------------------------------------


def _validate_iso_date(v: str) -> str:
    # Round-trip so only canonical YYYY-MM-DD passes: fromisoformat alone also
    # accepts compact forms like "20260615", which the date columns never hold.
    try:
        canonical = date.fromisoformat(v).isoformat() == v
    except ValueError:
        canonical = False
    if not canonical:
        raise ValueError("date must be a real date in YYYY-MM-DD form")
    return v


class SessionInstanceCreate(BaseModel):
    title: str
    date: str  # "YYYY-MM-DD"
    template_id: uuid.UUID | None = None  # a uuid column, as type_ids are (#586)
    location: str | None = None
    info: str | None = None
    coach_notes: str | None = None
    segments: list[SegmentCreate]

    @field_validator("segments")
    @classmethod
    def validate_segments_nonempty(cls, v: list[SegmentCreate]) -> list[SegmentCreate]:
        return _validate_segments_nonempty(v)

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        return _validate_iso_date(v)

    @field_serializer("template_id")
    def serialize_template_id(self, v: uuid.UUID | None) -> str | None:
        return None if v is None else str(v)


class MemberSessionInstanceRead(BaseModel):
    """A Session as a member reads it: an allowlist, so an admin-only field
    added to SessionInstanceRead cannot reach a member by omission (#619)."""

    id: str
    title: str
    date: str
    start_time: str  # derived envelope value
    duration_minutes: int  # derived envelope value
    template_id: str | None = None
    cancelled: bool = False
    location: str | None = None
    info: str | None = None
    # The session's one check-in link (#191). Public, tokenless and stable;
    # filled in by the read path, which owns the origin.
    checkin_link: str | None = None
    checkin_window_before_minutes: int | None = None
    checkin_window_after_minutes: int | None = None
    attendance_count: int = 0
    is_checked_in: bool = False
    segments: list[SegmentRead] = []


class SessionInstanceRead(MemberSessionInstanceRead):
    """A Session as an admin reads it: the member shape plus admin-only fields."""

    coach_notes: str | None = None


class GenerateRequest(BaseModel):
    horizon: str  # "YYYY-MM-DD" — generate instances up to this date


_CHECKIN_WINDOW_MAX_MINUTES = 1440


def _validate_checkin_window_minutes(v: int | None) -> int | None:
    if v is None:
        return v
    if v < 0:
        raise ValueError("checkin window minutes must not be negative")
    if v > _CHECKIN_WINDOW_MAX_MINUTES:
        raise ValueError(
            f"checkin window minutes must not exceed {_CHECKIN_WINDOW_MAX_MINUTES}"
        )
    return v


class SessionInstanceUpdate(PartialUpdate):
    not_null = frozenset({"title", "date", "segments"})

    title: str | None = None
    date: str | None = None  # "YYYY-MM-DD"
    location: str | None = None
    info: str | None = None
    coach_notes: str | None = None
    segments: list[SegmentCreate] | None = None
    checkin_window_before_minutes: int | None = None
    checkin_window_after_minutes: int | None = None

    @field_validator("segments")
    @classmethod
    def validate_segments_nonempty_if_present(
        cls, v: list[SegmentCreate] | None
    ) -> list[SegmentCreate] | None:
        if v is not None:
            return _validate_segments_nonempty(v)
        return v

    @field_validator("checkin_window_before_minutes", "checkin_window_after_minutes")
    @classmethod
    def validate_checkin_window_minutes(cls, v: int | None) -> int | None:
        return _validate_checkin_window_minutes(v)

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str | None) -> str | None:
        return v if v is None else _validate_iso_date(v)
