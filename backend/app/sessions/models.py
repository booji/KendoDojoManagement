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


class SessionTemplateCreate(BaseModel):
    session_type_id: str
    title: str
    start_date: str  # "YYYY-MM-DD"
    start_time: str  # "HH:MM"
    duration_minutes: int
    recurrence: str = "weekly"
    day_of_week: int | None = None  # kept for backwards compat; nullable
    location: str | None = None
    recurrence_days: list[int] = []
    interval_weeks: int = Field(default=1, ge=1)
    info: str | None = None
    coach_notes: str | None = None


class SessionTemplateRead(BaseModel):
    id: str
    session_type_id: str
    title: str
    start_date: str
    start_time: str
    duration_minutes: int
    recurrence: str
    day_of_week: int | None = None
    location: str | None = None
    recurrence_days: list[int] = []
    interval_weeks: int = 1
    info: str | None = None
    coach_notes: str | None = None


class SessionInstanceCreate(BaseModel):
    session_type_id: str
    date: str  # "YYYY-MM-DD"
    start_time: str  # "HH:MM"
    duration_minutes: int
    notes: str | None = None
    template_id: str | None = None
    location: str | None = None
    info: str | None = None
    coach_notes: str | None = None
    checkin_url: str | None = None


class SessionInstanceRead(BaseModel):
    id: str
    session_type_id: str
    date: str
    start_time: str
    duration_minutes: int
    notes: str | None = None
    template_id: str | None = None
    cancelled: bool = False
    location: str | None = None
    info: str | None = None
    coach_notes: str | None = None
    checkin_url: str | None = None
    attendance_count: int = 0
    is_checked_in: bool = False


class GenerateRequest(BaseModel):
    horizon: str  # "YYYY-MM-DD" — generate instances up to this date


class SessionInstanceUpdate(BaseModel):
    location: str | None = None
    info: str | None = None
    coach_notes: str | None = None
    start_time: str | None = None
    duration_minutes: int | None = None


class SessionTemplateUpdate(BaseModel):
    location: str | None = None
    info: str | None = None
    coach_notes: str | None = None
    start_time: str | None = None
    duration_minutes: int | None = None
    title: str | None = None
    session_type_id: str | None = None
    recurrence_days: list[int] | None = None
    interval_weeks: int | None = None
