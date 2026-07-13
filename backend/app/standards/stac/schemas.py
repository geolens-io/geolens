"""Pydantic response models for STAC API endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.catalog.features.schemas import GeoJSONGeometryLike


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


class StacItemAsset(BaseModel):
    """A STAC asset attached to an Item."""

    href: str = Field(description="URL of the asset resource.")
    type: str | None = Field(default=None, description="Asset media type.")
    title: str | None = Field(default=None, description="Human-readable asset title.")
    description: str | None = Field(
        default=None, description="Human-readable asset description."
    )
    roles: list[str] | None = Field(
        default=None, description="Semantic roles such as data or visual."
    )

    model_config = ConfigDict(extra="allow")


class StacItemProperties(BaseModel):
    """Core STAC Item properties plus extension-defined fields."""

    datetime: str | None = Field(
        description="Item timestamp, or null when a temporal interval is supplied."
    )
    start_datetime: str | None = Field(
        default=None, description="Start of the item's temporal interval."
    )
    end_datetime: str | None = Field(
        default=None, description="End of the item's temporal interval."
    )
    title: str | None = Field(default=None, description="Human-readable item title.")
    description: str | None = Field(
        default=None, description="Human-readable item description."
    )

    model_config = ConfigDict(extra="allow")


class StacItemResponse(BaseModel):
    """A GeoJSON Feature conforming to the STAC Item specification."""

    type: Literal["Feature"] = "Feature"
    stac_version: str = Field(description="STAC specification version.")
    stac_extensions: list[str] = Field(
        default_factory=list, description="STAC extension schema URIs in use."
    )
    id: str = Field(description="Stable item identifier.")
    geometry: GeoJSONGeometryLike | None = Field(
        description="Item footprint as GeoJSON, or null when unavailable."
    )
    bbox: (
        tuple[float, float, float, float]
        | tuple[float, float, float, float, float, float]
        | None
    ) = Field(
        default=None,
        description="Item bounding box with exactly four 2D or six 3D coordinates.",
    )
    properties: StacItemProperties
    links: list[StacLink]
    assets: dict[str, StacItemAsset]
    collection: str | None = Field(
        default=None, description="Identifier of the containing STAC Collection."
    )

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "examples": [
                {
                    "type": "Feature",
                    "stac_version": "1.0.0",
                    "id": "0190f4c8-8c6a-7a21-9a34-13bc2f31dc02",
                    "geometry": None,
                    "properties": {"datetime": "2026-01-15T00:00:00Z"},
                    "links": [],
                    "assets": {},
                    "collection": "geolens-unassigned",
                }
            ]
        },
    )


class StacContext(BaseModel):
    """Paging metadata emitted with STAC ItemCollections."""

    limit: int
    returned: int
    matched: int

    model_config = ConfigDict(extra="allow")


class StacItemCollectionResponse(BaseModel):
    """Typed OpenAPI representation of a STAC ItemCollection."""

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[StacItemResponse]
    links: list[StacLink]
    numberMatched: int
    numberReturned: int
    context: StacContext

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "examples": [
                {
                    "type": "FeatureCollection",
                    "features": [],
                    "links": [],
                    "numberMatched": 0,
                    "numberReturned": 0,
                    "context": {"limit": 10, "returned": 0, "matched": 0},
                }
            ]
        },
    )


class StacItemCollection(StacItemCollectionResponse):
    """Runtime-compatible name for the fully typed STAC ItemCollection model."""


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

    collections: list[StacCollection] = Field(description="List of STAC collections.")
    links: list[StacLink] = Field(description="Top-level collection navigation links.")
