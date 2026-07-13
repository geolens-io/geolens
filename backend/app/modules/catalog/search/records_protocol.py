"""Protocol helpers for the OGC API Records search surface."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.identity import Identity
from app.modules.catalog.authorization import check_dataset_access_or_anonymous
from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.search.schemas import OGCFeatureCollectionResponse
from app.standards.ogc.utils import (
    build_url,
    content_language_for_record_languages,
    link_header_value,
    normalize_language_tag,
)

_OGC_SORT_MAP = {"title": "name", "created": "date_added", "updated": "last_updated"}


def parse_ogc_sortby(sortby: str) -> tuple[str, bool | None]:
    """Parse OGC sortby syntax into the native sort field and direction."""
    field = sortby.lstrip("+- ")
    sort_desc: bool | None = None
    if sortby.startswith("-"):
        sort_desc = True
    elif sortby.startswith(("+", " ")):
        sort_desc = False
    mapped = _OGC_SORT_MAP.get(field)
    if mapped is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unknown sortby field: {field}. "
                f"Valid values: {', '.join(_OGC_SORT_MAP)}"
            ),
        )
    return mapped, sort_desc


def parse_array_query_values(
    values: list[str] | None,
    *,
    parameter: str,
) -> tuple[str, ...] | None:
    """Parse repeated and comma-separated OGC ``form`` array parameters."""
    if not values:
        return None
    parsed = tuple(
        item.strip() for value in values for item in value.split(",") if item.strip()
    )
    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{parameter} must contain at least one value",
        )
    if len(parsed) > 1000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{parameter} accepts at most 1000 values",
        )
    return parsed


def parse_record_ids(
    values: tuple[str, ...] | None,
    *,
    parameter: str,
) -> tuple[uuid.UUID, ...] | None:
    if values is None:
        return None
    parsed: list[uuid.UUID] = []
    for value in values:
        try:
            parsed.append(uuid.UUID(value))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid {parameter} value: {value}",
            )
    return tuple(dict.fromkeys(parsed))


async def validate_legacy_external_id_access(
    db: AsyncSession,
    external_id: str,
    user: Identity | None,
) -> uuid.UUID:
    """Preserve deprecated singular ``externalId``'s 404 access contract."""
    try:
        record_uuid = uuid.UUID(external_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid externalId value: {external_id}",
        )

    result = await db.execute(
        select(Dataset)
        .options(joinedload(Dataset.record))
        .where(Dataset.id == record_uuid)
    )
    dataset = result.unique().scalar_one_or_none()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Record not found",
        )
    await check_dataset_access_or_anonymous(db, dataset, record_uuid, user)
    return record_uuid


def serialized_feature_language(feature: object) -> str | None:
    properties: object | None
    if isinstance(feature, dict):
        properties = feature.get("properties")
    else:
        properties = getattr(feature, "properties", None)

    language: str | None = None
    if isinstance(properties, dict):
        value = properties.get("language")
        language = value if isinstance(value, str) else None
    elif properties is not None:
        language = getattr(properties, "language", None)
    return normalize_language_tag(language, fallback="en")


def feature_collection_content_language(
    response: OGCFeatureCollectionResponse,
) -> str | None:
    return content_language_for_record_languages(
        [serialized_feature_language(feature) for feature in response.features]
    )


def standard_response_headers(
    links: list[object] | None,
    *,
    language: str | None = None,
) -> dict[str, str]:
    """Build truthful language and RFC 8288 navigation headers."""
    headers = {"Vary": "Accept-Language"}
    if language:
        headers["Content-Language"] = language
    if link_value := link_header_value(links or []):
        headers["Link"] = link_value
    return headers


def collection_search_feature(coll: dict, public_api_url: str) -> dict:
    """Serialize an augmented catalog Collection as a valid Record Feature."""
    created_at = coll["created_at"]
    created_text = (
        created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)
    )
    collection_time = {"timestamp": created_text}
    return {
        "type": "Feature",
        "id": coll["id"],
        "time": collection_time,
        "geometry": None,
        "properties": {
            "type": "collection",
            "title": coll["name"],
            "description": coll["description"] or coll["name"],
            "keywords": [],
            "license": "proprietary",
            "themes": [],
            "contacts": [
                {
                    "name": "GeoLens metadata catalog",
                    "organization": "GeoLens",
                    "roles": ["publisher"],
                }
            ],
            "time": collection_time,
            "record_type": "collection",
            "dataset_count": coll["dataset_count"],
            "created": created_text,
        },
        "links": [
            {
                "rel": "self",
                "href": build_url(
                    f"/catalog/collections/{coll['id']}",
                    base_url=public_api_url,
                ),
                "type": "application/json",
            }
        ],
    }
