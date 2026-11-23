from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.core.partial_update import PartialUpdate


def _validate_url(v: str | None) -> str | None:
    if v is None:
        return None
    from urllib.parse import urlparse

    parsed = urlparse(v)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("website must be a valid http/https URL")
    return v


class FederationCreate(BaseModel):
    name: str = Field(max_length=255)
    abbreviation: str | None = Field(default=None, max_length=50)
    iso_code: str | None = Field(default=None, max_length=10)
    website: str | None = None
    continental_grouping: str | None = Field(default=None, max_length=100)
    type: str | None = Field(default=None, max_length=50)
    is_pinned: bool = False
    is_active: bool = True

    @field_validator("website", mode="before")
    @classmethod
    def validate_website(cls, v: str | None) -> str | None:
        return _validate_url(v)


class FederationUpdate(PartialUpdate):
    not_null = frozenset({"name", "is_pinned", "is_active"})

    name: str | None = Field(default=None, max_length=255)
    abbreviation: str | None = Field(default=None, max_length=50)
    iso_code: str | None = Field(default=None, max_length=10)
    website: str | None = None
    continental_grouping: str | None = Field(default=None, max_length=100)
    type: str | None = Field(default=None, max_length=50)
    is_pinned: bool | None = None
    is_active: bool | None = None

    @field_validator("website", mode="before")
    @classmethod
    def validate_website(cls, v: str | None) -> str | None:
        return _validate_url(v)


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
