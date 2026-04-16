"""Pydantic response models for STAC API endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class StacLink(BaseModel):
    """A single STAC link object."""

    href: str = Field(description="Target URL of the link.")
    rel: str = Field(
        description="Link relation type (e.g. 'self', 'root', 'parent', 'item', 'data')."
    )
    type: str | None = Field(
        default=None,
        description="Media type of the linked resource (e.g. 'application/json').",
    )
    method: str | None = Field(
        default=None, description="HTTP method to use (defaults to GET)."
    )


class StacCatalog(BaseModel):
    """STAC Catalog / landing page response."""

    type: str = Field(
        default="Catalog",
        description="STAC object type. Always 'Catalog' for the landing page.",
    )
    id: str = Field(description="Stable identifier for the catalog.")
    stac_version: str = Field(
        default="1.0.0", description="STAC specification version implemented."
    )
    title: str = Field(description="Catalog title.")
    description: str = Field(description="Human-readable catalog description.")
    conformsTo: list[str] = Field(
        description="List of conformance URIs declaring which STAC and OGC API standards the catalog implements."
    )
    links: list[StacLink] = Field(
        description="Catalog navigation links (self, root, search, collections, etc.)."
    )


class StacConformance(BaseModel):
    """STAC conformance response."""

    conformsTo: list[str] = Field(description="List of conformance class URIs.")


class StacItemCollection(BaseModel):
    """STAC ItemCollection (search / items listing) response."""

    type: str = Field(
        default="FeatureCollection", description="GeoJSON feature collection type."
    )
    features: list[dict] = Field(description="STAC items returned by the query.")
    links: list[StacLink] = Field(description="Pagination and self-reference links.")
    numberMatched: int = Field(
        description="Total number of items matching the query (across all pages)."
    )
    numberReturned: int = Field(description="Number of items in this response page.")
    context: dict = Field(
        description="STAC context extension fields (paging metadata)."
    )


class StacCollection(BaseModel):
    """A single STAC Collection response (permissive — allows extra STAC fields)."""

    type: str = Field(default="Collection", description="STAC object type.")
    stac_version: str = Field(
        default="1.0.0", description="STAC specification version."
    )
    id: str = Field(description="Stable collection identifier.")
    title: str | None = Field(
        default=None, description="Human-readable collection title."
    )
    description: str = Field(default="", description="Collection description.")
    license: str = Field(
        default="proprietary", description="SPDX license identifier or 'proprietary'."
    )
    extent: dict = Field(
        description="Spatial and temporal extent of items in the collection."
    )
    links: list[StacLink] = Field(description="Collection navigation links.")

    model_config = {"extra": "allow"}


class StacCollectionListResponse(BaseModel):
    """STAC collections list response."""

    collections: list[dict] = Field(description="List of STAC collections.")
    links: list[StacLink] = Field(description="Top-level collection navigation links.")
