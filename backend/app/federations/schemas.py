from __future__ import annotations

from pydantic import BaseModel


class FederationCreate(BaseModel):
    name: str
    abbreviation: str | None = None
    iso_code: str | None = None
    website: str | None = None
    continental_grouping: str | None = None
    type: str | None = None
    is_pinned: bool = False
    is_active: bool = True


class FederationUpdate(BaseModel):
    name: str | None = None
    abbreviation: str | None = None
    iso_code: str | None = None
    website: str | None = None
    continental_grouping: str | None = None
    type: str | None = None
    is_pinned: bool | None = None
    is_active: bool | None = None


class FederationResponse(BaseModel):
    id: str
    name: str
    abbreviation: str | None
    iso_code: str | None
    website: str | None
    continental_grouping: str | None
    type: str | None
    is_pinned: bool
    is_active: bool
