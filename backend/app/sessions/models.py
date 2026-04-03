from __future__ import annotations

from pydantic import BaseModel


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
    day_of_week: int  # 0=Monday … 6=Sunday
    location: str | None = None


class SessionTemplateRead(BaseModel):
    id: str
    session_type_id: str
    title: str
    start_date: str
    start_time: str
    duration_minutes: int
    recurrence: str
    day_of_week: int
    location: str | None = None


class SessionInstanceCreate(BaseModel):
    session_type_id: str
    date: str  # "YYYY-MM-DD"
    start_time: str  # "HH:MM"
    duration_minutes: int
    notes: str | None = None
    template_id: str | None = None


class SessionInstanceRead(BaseModel):
    id: str
    session_type_id: str
    date: str
    start_time: str
    duration_minutes: int
    notes: str | None = None
    template_id: str | None = None
    cancelled: bool = False


class GenerateRequest(BaseModel):
    horizon: str  # "YYYY-MM-DD" — generate instances up to this date
