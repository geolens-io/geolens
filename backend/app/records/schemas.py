"""Pydantic schemas for record sub-resources: contacts, keywords, distributions."""

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# --- Contacts ---


class ContactCreate(BaseModel):
    role: str = Field(description="ISO CI_RoleCode, e.g. pointOfContact, author")
    name: str | None = None
    email: EmailStr | None = None
    organization: str | None = None
    phone: str | None = None
    extra_json: dict[str, Any] | None = Field(default=None, description="Arbitrary extra fields stored as JSON")
    sort_order: int = Field(default=0, description="Display ordering (lower first)")


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
    vocabulary_uri: str | None = Field(default=None, description="URI of the controlled vocabulary")
    keyword_type: str = Field(
        default="theme",
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
    distribution_type: str = Field(description="e.g. download, api, ogc_wms, ogc_wfs")
    format: str = Field(description="File or service format, e.g. GeoJSON, SHP, WMS")
    url: str = Field(description="Access URL for this distribution")
    title: str | None = None
    description: str | None = None
    protocol: str | None = Field(default=None, description="Transfer protocol, e.g. HTTPS, OGC:WFS")
    media_type: str | None = Field(default=None, description="IANA media type, e.g. application/geo+json")
    is_primary: bool = Field(default=False, description="Mark as the preferred distribution")


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
    auto_generated: bool = Field(description="True if created automatically by the system")

    model_config = ConfigDict(from_attributes=True)


class DistributionListResponse(BaseModel):
    distributions: list[DistributionResponse]
    total: int
