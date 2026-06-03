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

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset, Record


async def get_user_id(session: AsyncSession, username: str) -> uuid.UUID:
    """Look up a user's ID by username."""
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one()
    return user.id


async def create_dataset(
    session: AsyncSession,
    *,
    created_by: uuid.UUID,
    name: str = "Test Dataset",
    table_name: str | None = None,
    visibility: str = "public",
    srid: int = 4326,
    geometry_type: str = "MultiPolygon",
    feature_count: int = 42,
    description: str | None = "A test dataset",
    source_format: str = "geojson",
    source_filename: str = "test.geojson",
    record_status: str = "published",
    theme_category: list[str] | None = None,
    column_info: list[dict] | None = None,
) -> Dataset:
    """Insert a Record + Dataset pair directly into the DB.

    Superset of the per-file ``_create_dataset`` helpers found across 20+
    test files. Callers that only need a minimal dataset can rely on defaults.
    """
    if table_name is None:
        table_name = f"ds_{uuid.uuid4().hex[:12]}"
    if theme_category is None:
        theme_category = ["test"]

    record = Record(
        title=name,
        summary=description,
        theme_category=theme_category,
        visibility=visibility,
        record_status=record_status,
        created_by=created_by,
    )
    session.add(record)
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
    dataset = Dataset(**ds_kwargs)
    session.add(dataset)
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
