"""Pydantic response models for STAC API endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class StacLink(BaseModel):
    """A single STAC link object."""

    href: str
    rel: str
    type: str | None = None
    method: str | None = None


class StacCatalog(BaseModel):
    """STAC Catalog / landing page response."""

    type: str = "Catalog"
    id: str
    stac_version: str = "1.1.0"
    title: str
    description: str
    conformsTo: list[str]
    links: list[StacLink]


class StacConformance(BaseModel):
    """STAC conformance response."""

    conformsTo: list[str]


class StacItemCollection(BaseModel):
    """STAC ItemCollection (search / items listing) response."""

    type: str = "FeatureCollection"
    features: list[dict]
    links: list[StacLink]
    numberMatched: int
    numberReturned: int
    context: dict


class StacCollectionListResponse(BaseModel):
    """STAC collections list response."""

    collections: list[dict]
    links: list[StacLink]
