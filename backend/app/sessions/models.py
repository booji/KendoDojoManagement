from __future__ import annotations

from pydantic import BaseModel, Field


class SessionTypeCreate(BaseModel):
    name: str


class SessionTypeRead(BaseModel):
    id: str
    name: str


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
