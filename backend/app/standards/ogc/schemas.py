from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, model_serializer

from app.modules.catalog.features.schemas import GeoJSONGeometry


class OGCLink(BaseModel):
    href: str = Field(description="Target URL of the link.")
    rel: str = Field(
        description="Link relation type per RFC 8288 (e.g. 'self', 'next', 'prev', 'data', 'collection')."
    )
    type: str = Field(
        description="Media type of the linked resource (e.g. 'application/json', 'application/geo+json')."
    )
    title: str | None = Field(
        default=None, description="Optional human-readable label for the link."
    )

    @model_serializer
    def serialize_model(self):
        return {k: v for k, v in self.__dict__.items() if v is not None}


class LandingPage(BaseModel):
    title: str = Field(description="OGC API landing page title.")
    description: str = Field(description="Human-readable API description.")
    links: list[OGCLink] = Field(
        description="Top-level navigation links to conformance, collections, and API document."
    )


class ConformanceResponse(BaseModel):
    conformsTo: list[str] = Field(
        description="List of conformance class URIs declaring which OGC API standards this server implements."
    )


# Per-dataset collection metadata per OGC API Features
class OGCCollectionMetadata(BaseModel):
    """Per-dataset collection metadata per OGC API Features."""

    id: str = Field(
        description="Stable collection identifier (typically the dataset ID)."
    )
    title: str = Field(description="Human-readable collection title.")
    description: str | None = Field(default=None, description="Collection description.")
    extent: dict | None = Field(
        default=None,
        description="Spatial and temporal extent (OGC API Features extent object).",
    )
    itemType: str = Field(
        default="feature",
        description="Type of items in the collection. Always 'feature' for OGC API Features.",
    )
    crs: list[str] = Field(
        default=["http://www.opengis.net/def/crs/OGC/1.3/CRS84"],
        description="Coordinate reference systems supported for items in this collection.",
    )
    links: list[OGCLink] = Field(
        description="Collection navigation links (self, items, queryables, etc.)."
    )


# Feature collection response for /collections/{id}/items
class OGCFeatureItemsResponse(BaseModel):
    """OGC API Features compliant feature collection response."""

    type: Literal["FeatureCollection"] = Field(
        default="FeatureCollection", description="GeoJSON object type."
    )
    timeStamp: str = Field(
        default_factory=lambda: (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        ),
        description="ISO 8601 timestamp the response was generated.",
    )
    numberMatched: int = Field(
        description="Total number of features matching the query (across all pages)."
    )
    numberReturned: int = Field(description="Number of features in this response page.")
    features: list[dict] = Field(description="GeoJSON features returned by the query.")
    links: list[OGCLink] = Field(description="Pagination and self-reference links.")


# Single feature response for /collections/{id}/items/{featureId}
class OGCSingleFeatureResponse(BaseModel):
    """Single GeoJSON Feature response."""

    type: Literal["Feature"] = Field(
        default="Feature", description="GeoJSON object type."
    )
    id: int = Field(description="Feature identifier within the collection.")
    geometry: GeoJSONGeometry | None = Field(
        description="GeoJSON geometry of the feature, or null for geometry-less features."
    )
    properties: dict | None = Field(description="Feature attributes as a JSON object.")
    links: list[OGCLink] = Field(
        default=[], description="Self-reference and related-resource links."
    )
