"""Centralized test data factories — canonical source for test entity creation.

Provides reusable helpers for creating test entities (datasets, maps,
collections, users) to reduce duplication across test files.

Usage:
    from tests.factories import create_dataset, get_user_id

For test-specific variants that need extra parameters (e.g. extent_wkt,
column_info), either pass them through ``**kwargs`` or define a thin
wrapper in the test file that calls ``create_dataset`` and then applies
additional mutations.
"""

import uuid
from datetime import date, datetime

from geoalchemy2 import WKTElement
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    Record,
    RecordContact,
    RecordKeyword,
)
from app.processing.raster.models import RasterAsset


async def get_user_id(session: AsyncSession, username: str) -> uuid.UUID:
    """Look up a user's ID by username."""
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one()
    return user.id


async def create_dataset(
    session: AsyncSession,
    *,
    created_by: uuid.UUID | None,
    name: str = "Test Dataset",
    table_name: str | None = None,
    visibility: str = "public",
    srid: int = 4326,
    geometry_type: str = "MultiPolygon",
    feature_count: int = 42,
    description: str | None = "A test dataset",
    source_format: str = "geojson",
    source_filename: str = "test.geojson",
    source_url: str | None = None,
    record_status: str = "published",
    record_type: str | None = None,
    theme_category: list[str] | None = None,
    column_info: list[dict] | None = None,
    sample_values: dict | None = None,
    temporal_start: date | None = None,
    temporal_end: date | None = None,
    spatial_extent_wkt: str | None = None,
    lineage_summary: str | None = None,
    update_frequency: str | None = None,
    usage_constraints: str | None = None,
    access_constraints: str | None = None,
    source_organization: str | None = None,
    keywords: list[str | tuple[str, str | None]] | None = None,
    contacts: list[dict] | None = None,
    updated_by: uuid.UUID | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> Dataset:
    """Insert a Record + Dataset pair directly into the DB.

    Superset of the per-file ``_create_dataset`` helpers found across 20+
    test files. Callers that only need a minimal dataset can rely on defaults.
    Every field beyond the original minimal set is applied only when passed
    (``is not None`` / truthy), so existing callers are unaffected.
    """
    if table_name is None:
        table_name = f"ds_{uuid.uuid4().hex[:12]}"
    if theme_category is None:
        theme_category = ["test"]

    record_kwargs = dict(
        title=name,
        summary=description,
        theme_category=theme_category,
        visibility=visibility,
        record_status=record_status,
        created_by=created_by,
    )
    for key, value in (
        ("record_type", record_type),
        ("temporal_start", temporal_start),
        ("temporal_end", temporal_end),
        ("lineage_summary", lineage_summary),
        ("update_frequency", update_frequency),
        ("usage_constraints", usage_constraints),
        ("access_constraints", access_constraints),
        ("source_organization", source_organization),
        ("updated_by", updated_by),
        ("created_at", created_at),
        ("updated_at", updated_at),
    ):
        if value is not None:
            record_kwargs[key] = value

    record = Record(**record_kwargs)
    if spatial_extent_wkt is not None:
        record.spatial_extent = WKTElement(spatial_extent_wkt, srid=4326)
    session.add(record)
    await session.flush()

    if keywords:
        for kw in keywords:
            kw_text, vocab_uri = (kw, None) if isinstance(kw, str) else kw
            session.add(
                RecordKeyword(
                    record_id=record.id,
                    keyword=kw_text,
                    keyword_type="theme",
                    vocabulary_uri=vocab_uri,
                )
            )
        await session.flush()

    if contacts:
        for c in contacts:
            session.add(RecordContact(record_id=record.id, **c))
        await session.flush()

    ds_kwargs = dict(
        record_id=record.id,
        table_name=table_name,
        srid=srid,
        geometry_type=geometry_type,
        feature_count=feature_count,
        source_format=source_format,
        source_filename=source_filename,
    )
    if column_info is not None:
        ds_kwargs["column_info"] = column_info
    if source_url is not None:
        ds_kwargs["source_url"] = source_url
    if sample_values is not None:
        ds_kwargs["sample_values"] = sample_values
    dataset = Dataset(**ds_kwargs)
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def create_raster_dataset(
    session: AsyncSession,
    *,
    created_by: uuid.UUID | None,
    name: str = "Test Raster Dataset",
    table_name: str | None = None,
    visibility: str = "public",
    record_status: str = "published",
    record_type: str = "raster_dataset",
    srid: int = 4326,
    geometry_type: str | None = None,
    feature_count: int | None = None,
    description: str | None = None,
    source_format: str = "geotiff",
    source_filename: str | None = None,
    theme_category: list[str] | None = None,
    create_raster_asset: bool = False,
    raster_asset_kwargs: dict | None = None,
) -> Dataset:
    """Insert a raster Record + Dataset pair (optionally + RasterAsset) into the DB.

    Superset of the per-file ``_create_raster_dataset`` helpers found across
    10 test files. Unlike ``create_dataset``, ``geometry_type``/``feature_count``
    default to ``None`` (raster datasets carry no vector geometry) and
    ``theme_category`` is only set when explicitly passed — several callers
    rely on it staying NULL, unlike the vector factory's forced default.
    """
    if table_name is None:
        table_name = f"raster_{uuid.uuid4().hex[:12]}"

    record_kwargs = dict(
        title=name,
        summary=description,
        visibility=visibility,
        record_status=record_status,
        record_type=record_type,
        created_by=created_by,
    )
    if theme_category is not None:
        record_kwargs["theme_category"] = theme_category

    record = Record(**record_kwargs)
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=srid,
        geometry_type=geometry_type,
        feature_count=feature_count,
        source_format=source_format,
        source_filename=source_filename,
    )
    session.add(dataset)
    await session.flush()

    if create_raster_asset:
        asset_kwargs = dict(
            dataset_id=dataset.id,
            asset_uri=f"rasters/{dataset.id}/abc123/source.cog.tif",
            storage_backend="local",
        )
        asset_kwargs.update(raster_asset_kwargs or {})
        session.add(RasterAsset(**asset_kwargs))
        await session.flush()

    await session.commit()
    await session.refresh(dataset)
    return dataset


async def create_map_via_api(
    client: AsyncClient,
    headers: dict,
    name: str | None = None,
    description: str | None = "test description",
) -> dict:
    """Create a map via the API and return the response JSON."""
    map_name = name or f"Test Map {uuid.uuid4().hex[:6]}"
    resp = await client.post(
        "/maps/",
        json={"name": map_name, "description": description},
        headers=headers,
    )
    assert resp.status_code == 201, f"Create map failed: {resp.text}"
    return resp.json()


async def create_collection_via_api(
    client: AsyncClient,
    headers: dict,
    name: str | None = None,
    description: str | None = "test collection",
) -> dict:
    """Create a collection via the API and return the response JSON."""
    coll_name = name or f"Test Collection {uuid.uuid4().hex[:6]}"
    resp = await client.post(
        "/catalog/collections/",
        json={"name": coll_name, "description": description},
        headers=headers,
    )
    assert resp.status_code == 201, f"Create collection failed: {resp.text}"
    return resp.json()
