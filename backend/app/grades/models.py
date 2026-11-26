from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, field_validator

_DISPLAY_NAMES: dict[str, str] = {
    "MUKYUU": "Mukyū",
    "ROKKYUU": "Rokkyū (6-kyu)",
    "GOKYUU": "Gokyū (5-kyu)",
    "YONKYUU": "Yonkyū (4-kyu)",
    "SANKYUU": "Sankyū (3-kyu)",
    "NIKYUU": "Nikyū (2-kyu)",
    "IKKYUU": "Ikkyū (1-kyu)",
    "SHODAN": "Shodan (1-dan)",
    "NIDAN": "Nidan (2-dan)",
    "SANDAN": "Sandan (3-dan)",
    "YONDAN": "Yondan (4-dan)",
    "GODAN": "Godan (5-dan)",
    "ROKUDAN": "Rokudan (6-dan)",
    "NANADAN": "Nanadan (7-dan)",
    "HACHIDAN": "Hachidan (8-dan)",
}


class Grade(StrEnum):
    MUKYUU = "MUKYUU"
    ROKKYUU = "ROKKYUU"
    GOKYUU = "GOKYUU"
    YONKYUU = "YONKYUU"
    SANKYUU = "SANKYUU"
    NIKYUU = "NIKYUU"
    IKKYUU = "IKKYUU"
    SHODAN = "SHODAN"
    NIDAN = "NIDAN"
    SANDAN = "SANDAN"
    YONDAN = "YONDAN"
    GODAN = "GODAN"
    ROKUDAN = "ROKUDAN"
    NANADAN = "NANADAN"
    HACHIDAN = "HACHIDAN"

    @property
    def display_name(self) -> str:
        return _DISPLAY_NAMES[self.value]

    @property
    def short_name(self) -> str:
        """display_name without its bracketed helper: "Shodan", "Mukyū"."""
        return self.display_name.split(" (")[0]

    @property
    def number(self) -> int:
        """A sortable number: kyu negative, dan positive, Mukyū below 6-kyu.

        Mukyū -7, Rokkyū -6 … Ikkyū -1, Shodan 1 … Hachidan 8. Read off the
        enum's order, which is the Grade order.
        """
        index = list(Grade).index(self)
        shodan = list(Grade).index(Grade.SHODAN)
        return index - shodan if index < shodan else index - shodan + 1


class GradeHistoryEntry(BaseModel):
    id: str
    member_id: str
    grade: str
    display_name: str
    promoted_at: str
    assigned_by: str | None
    status: str


class SetGradeRequest(BaseModel):
    grade: Grade
    # An offset is required: promoted_at is a timestamptz (#433), and a naive
    # value names no instant.
    awarded_at: AwareDatetime | None = None

    @field_validator("awarded_at")
    @classmethod
    def no_future_dates(cls, v: datetime | None) -> datetime | None:
        if v is not None and v > datetime.now(v.tzinfo):
            raise ValueError("awarded_at cannot be in the future")
        return v


class SetGradeResponse(BaseModel):
    id: str
    member_id: str
    grade: str
    display_name: str
    awarded_at: str
    assigned_by: str | None
    status: str


class CurrentGradeResponse(BaseModel):
    grade: str
    display_name: str
    awarded_at: str


class PendingGradeEntry(BaseModel):
    id: str
    member_id: str
    member_name: str
    grade: str
    display_name: str
    promoted_at: str
    status: str
