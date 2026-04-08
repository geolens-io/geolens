"""Pydantic schemas for record sub-resources: contacts, keywords, distributions."""

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# --- Contacts ---


class ContactCreate(BaseModel):
    role: str = Field(
        max_length=100, description="ISO CI_RoleCode, e.g. pointOfContact, author"
    )
    name: str | None = Field(default=None, max_length=500)
    email: EmailStr | None = None
    organization: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=50)
    extra_json: dict[str, Any] | None = Field(
        default=None, description="Arbitrary extra fields stored as JSON"
    )
    sort_order: int = Field(
        default=0, ge=0, le=9999, description="Display ordering (lower first)"
    )


class ContactUpdate(BaseModel):
    role: str | None = Field(default=None, max_length=100)
    name: str | None = Field(default=None, max_length=500)
    email: EmailStr | None = None
    organization: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=50)
    extra_json: dict[str, Any] | None = None
    sort_order: int | None = Field(default=None, ge=0, le=9999)


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
    keyword: str = Field(max_length=500)
    vocabulary_uri: str | None = Field(
        default=None, max_length=2048, description="URI of the controlled vocabulary"
    )
    keyword_type: str = Field(
        default="theme",
        max_length=100,
        description="ISO MD_KeywordTypeCode, e.g. theme, place, discipline",
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
    distribution_type: str = Field(
        max_length=200, description="e.g. download, api, ogc_wms, ogc_wfs"
    )
    format: str | None = Field(
        default=None,
        max_length=200,
        description="File or service format, e.g. GeoJSON, SHP, WMS",
    )
    url: str = Field(max_length=2048, description="Access URL for this distribution")
    title: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=2000)
    protocol: str | None = Field(
        default=None,
        max_length=100,
        description="Transfer protocol, e.g. HTTPS, OGC:WFS",
    )
    media_type: str | None = Field(
        default=None,
        max_length=255,
        description="IANA media type, e.g. application/geo+json",
    )
    is_primary: bool = Field(
        default=False, description="Mark as the preferred distribution"
    )


class DistributionUpdate(BaseModel):
    distribution_type: str | None = Field(default=None, max_length=200)
    format: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=2048)
    title: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=2000)
    protocol: str | None = Field(default=None, max_length=100)
    media_type: str | None = Field(default=None, max_length=255)
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
    auto_generated: bool = Field(
        description="True if created automatically by the system"
    )

    model_config = ConfigDict(from_attributes=True)


class DistributionListResponse(BaseModel):
    distributions: list[DistributionResponse]
    total: int
