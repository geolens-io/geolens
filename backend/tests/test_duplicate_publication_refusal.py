"""The publication-time duplicate check in _finalize_ingest.

A second job for one origin can pass the doors while the first is still
running, and a retried job can arrive after the source was imported again.
The finalize step must refuse to publish a copy of it. These tests call
the refusal helper directly against a real session.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import pytest

from app.platform.dataset_origin import KEEP, SourceBinding, restamp
from app.platform.jobs.models import IngestJob
from app.processing.ingest.tasks_common import (
    DuplicateSourcePublicationError,
    IngestContext,
    _refuse_duplicate_publication,
)
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio

_BASE = (
    "https://services6.arcgis.com/EbVsqZ18sv1kVJ3k/arcgis/rest/services/"
    "TestService/FeatureServer"
)


async def _service_dataset(session, *, created_by, layer_id="0"):
    dataset = await create_dataset(
        session,
        created_by=created_by,
        name="Existing Service Layer",
        source_format="arcgis_featureserver",
        source_url=f"{_BASE}/{layer_id}",
    )
    restamp(
        dataset,
        SourceBinding.service(
            "arcgis_featureserver",
            url=_BASE,
            layer_id=layer_id,
            enriched_uri=f"{_BASE}/{layer_id}",
        ),
        contacted_at=None,
        refreshed_at=KEEP,
    )
    await session.commit()
    return dataset


async def _database_dataset(session, *, created_by):
    dataset = await create_dataset(
        session,
        created_by=created_by,
        name="Parcels",
        source_format="database",
    )
    restamp(
        dataset,
        SourceBinding.database("gis", schema="dbo", table="parcels"),
        contacted_at=None,
        refreshed_at=KEEP,
    )
    await session.commit()
    return dataset


def _ctx(session, *, user_id, source_format, origin_ref):
    return IngestContext(
        session=session,
        job=IngestJob(status="running", created_by=user_id),
        table_name="ds_test",
        user_id=str(user_id),
        has_geometry=None,
        effective_srid=4326,
        source_format=source_format,
        source_filename="TestService",
        original_srid=None,
        user_metadata={},
        origin_ref=origin_ref,
    )


def _service_ref(layer_id):
    return {
        "service_type": "arcgis_featureserver",
        "url": _BASE,
        "layer_id": layer_id,
    }


async def test_service_publication_refused_when_dataset_exists(test_db_session):
    """A second service job for a published layer fails instead of copying it."""
    admin_id = await get_user_id(test_db_session, "admin")
    await _service_dataset(test_db_session, created_by=admin_id, layer_id="0")
    ctx = _ctx(
        test_db_session,
        user_id=admin_id,
        source_format="arcgis_featureserver",
        origin_ref=_service_ref("0"),
    )

    with pytest.raises(DuplicateSourcePublicationError, match="already imported"):
        await _refuse_duplicate_publication(test_db_session, ctx)


async def test_service_publication_allowed_for_a_different_layer(test_db_session):
    """A different layer of the same service still publishes."""
    admin_id = await get_user_id(test_db_session, "admin")
    await _service_dataset(test_db_session, created_by=admin_id, layer_id="0")
    ctx = _ctx(
        test_db_session,
        user_id=admin_id,
        source_format="arcgis_featureserver",
        origin_ref=_service_ref("1"),
    )

    await _refuse_duplicate_publication(test_db_session, ctx)


async def test_service_publication_allowed_for_a_different_user(test_db_session):
    """The same layer owned by another user still publishes."""
    admin_id = await get_user_id(test_db_session, "admin")
    editor_id = await get_user_id(test_db_session, "editor")
    await _service_dataset(test_db_session, created_by=admin_id, layer_id="0")
    ctx = _ctx(
        test_db_session,
        user_id=editor_id,
        source_format="arcgis_featureserver",
        origin_ref=_service_ref("0"),
    )

    await _refuse_duplicate_publication(test_db_session, ctx)


async def test_database_publication_refused_when_dataset_exists(test_db_session):
    """A second database job for a published table fails instead of copying it."""
    admin_id = await get_user_id(test_db_session, "admin")
    await _database_dataset(test_db_session, created_by=admin_id)
    ctx = _ctx(
        test_db_session,
        user_id=admin_id,
        source_format="database",
        origin_ref={"connection": "gis", "schema": "dbo", "table": "parcels"},
    )

    with pytest.raises(DuplicateSourcePublicationError, match="already imported"):
        await _refuse_duplicate_publication(test_db_session, ctx)


async def test_file_upload_skips_the_check(test_db_session):
    """A file upload carries no remote origin, so the check does not apply."""
    admin_id = await get_user_id(test_db_session, "admin")
    ctx = _ctx(
        test_db_session,
        user_id=admin_id,
        source_format="geojson",
        origin_ref={"filename": "test.geojson"},
    )

    await _refuse_duplicate_publication(test_db_session, ctx)
