from pydantic import BaseModel


class AttendanceRead(BaseModel):
    id: str
    session_id: str
    member_id: str
    checked_in_at: str
    recorded_by: str


class CheckinTokenRead(BaseModel):
    token: str
    session_id: str
    expires_at: str
