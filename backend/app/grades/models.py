from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

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


class Grade(str, Enum):
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


class GradeHistoryEntry(BaseModel):
    id: str
    member_id: str
    grade: str
    display_name: str
    promoted_at: str
    assigned_by: str
    status: str


class PromoteResponse(BaseModel):
    id: str
    member_id: str
    grade: str
    display_name: str
    promoted_at: str
    assigned_by: str
    status: str
