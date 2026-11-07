import uuid

from pydantic import BaseModel, Field


class AttendanceRead(BaseModel):
    id: str
    session_id: str
    member_id: str | None = None
    visitor_name: str | None = None
    checked_in_at: str
    recorded_by: str
    display_name: str | None = None


class MemberAttendanceRead(AttendanceRead):
    """A record in a Member's Attendance history, with the Session it was at."""

    session_title: str
    session_date: str


class MarkAttendedRequest(BaseModel):
    member_id: uuid.UUID


class AddVisitorRequest(BaseModel):
    visitor_name: str = Field(..., max_length=100)
