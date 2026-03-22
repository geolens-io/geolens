from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class OGCLink(BaseModel):
    href: str
    rel: str
    type: str
    title: str | None = None


class LandingPage(BaseModel):
    title: str
    description: str
    links: list[OGCLink]


class ConformanceResponse(BaseModel):
    conformsTo: list[str]


# Per-dataset collection metadata per OGC API Features
class OGCCollectionMetadata(BaseModel):
    """Per-dataset collection metadata per OGC API Features."""

    id: str
    title: str
    description: str | None = None
    extent: dict | None = None
    itemType: str = "feature"
    crs: list[str] = ["http://www.opengis.net/def/crs/OGC/1.3/CRS84"]
    links: list[OGCLink]


# Feature collection response for /collections/{id}/items
class OGCFeatureItemsResponse(BaseModel):
    """OGC API Features compliant feature collection response."""

    type: Literal["FeatureCollection"] = "FeatureCollection"
    timeStamp: str = Field(
        default_factory=lambda: (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )
    )
    numberMatched: int
    numberReturned: int
    features: list[dict]
    links: list[OGCLink]


# Single feature response for /collections/{id}/items/{featureId}
class OGCSingleFeatureResponse(BaseModel):
    """Single GeoJSON Feature response."""

    type: Literal["Feature"] = "Feature"
    id: int
    geometry: dict | None
    properties: dict | None
    links: list[OGCLink] = []
