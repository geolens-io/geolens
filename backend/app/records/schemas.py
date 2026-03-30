"""Pydantic schemas for record sub-resources: contacts, keywords, distributions."""

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr


# --- Contacts ---


class ContactCreate(BaseModel):
    role: str  # Validated by DB CHECK constraint (full ISO CI_RoleCode codelist)
    name: str | None = None
    email: EmailStr | None = None
    organization: str | None = None
    phone: str | None = None
    extra_json: dict[str, Any] | None = None  # JSONB for unmapped/extra fields
    sort_order: int = 0


class ContactUpdate(BaseModel):
    role: str | None = None
    name: str | None = None
    email: EmailStr | None = None
    organization: str | None = None
    phone: str | None = None
    extra_json: dict[str, Any] | None = None
    sort_order: int | None = None


class ContactResponse(BaseModel):
    id: uuid.UUID
    record_id: uuid.UUID
    role: str
    name: str | None
    email: str | None
    organization: str | None
    phone: str | None
    extra_json: dict[str, Any] | None
    sort_order: int

    model_config = ConfigDict(from_attributes=True)


class ContactListResponse(BaseModel):
    contacts: list[ContactResponse]
    total: int


# --- Keywords ---


class KeywordCreate(BaseModel):
    keyword: str
    vocabulary_uri: str | None = None
    keyword_type: str = (
        "theme"  # DB CHECK: full ISO MD_KeywordTypeCode codelist (15 values)
    )


class KeywordResponse(BaseModel):
    id: uuid.UUID
    record_id: uuid.UUID
    keyword: str
    vocabulary_uri: str | None
    keyword_type: str

    model_config = ConfigDict(from_attributes=True)


class KeywordListResponse(BaseModel):
    keywords: list[KeywordResponse]
    total: int


# --- Distributions ---


class DistributionCreate(BaseModel):
    distribution_type: str
    format: str
    url: str
    title: str | None = None
    description: str | None = None
    protocol: str | None = None
    media_type: str | None = None
    is_primary: bool = False


class DistributionUpdate(BaseModel):
    distribution_type: str | None = None
    format: str | None = None
    url: str | None = None
    title: str | None = None
    description: str | None = None
    protocol: str | None = None
    media_type: str | None = None
    is_primary: bool | None = None


class DistributionResponse(BaseModel):
    id: uuid.UUID
    record_id: uuid.UUID
    distribution_type: str
    format: str
    url: str
    title: str | None
    description: str | None
    protocol: str | None
    media_type: str | None
    is_primary: bool
    auto_generated: bool

    model_config = ConfigDict(from_attributes=True)


class DistributionListResponse(BaseModel):
    distributions: list[DistributionResponse]
    total: int
