"""fix(#1359): every ingest path must land the source's real attribute columns.

The reported symptom was ``column_info == ['id']`` on an ArcGIS
FeatureServer import whose preview listed ~29 fields. The stored value was
not wrong about the table — the TABLE only had one attribute column,
because ``build_gdal_source`` composed the ArcGIS ``/query`` URL without
``outFields``. An ArcGIS ``/query`` with no ``outFields`` answers with the
layer's display field alone, so ogr2ogr faithfully loaded geometry plus
that one field and every other attribute was dropped before PostGIS ever
saw it.

The two other symptoms in the issue follow from that one:

* the materialized analysis output showed the same single column because
  it carries its source's live columns, and its source was the broken
  import (``test_materialize_output_column_info_matches_carried_columns``
  pins that the carry itself is sound);
* refresh-from-source "did not repopulate" because it re-fetched through
  the same builder and recomputed the same one-column answer — the swap
  has always rewritten ``column_info``.
"""

import uuid as _uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.sources.preview import build_gdal_source
from app.platform.jobs.models import IngestJob

from tests.factories import get_user_id
from tests.test_analysis_preview import _create_polygon_dataset

# The attribute columns a real ArcGIS layer answers with once the query asks
# for them. `id` is the display field — the ONE column the pre-fix URL got
# back, which is why the "no attribute columns at all" fallback in
# `_finalize_ingest` never fired to cover for it.
_DISPLAY_FIELD = "id"
_ATTRIBUTE_COLUMNS = ("id", "mag", "eventtype", "place", "depth")


def _requests_all_fields(gdal_source: str) -> bool:
    """Does this ESRIJSON source ask the service for every field?"""
    query = parse_qs(urlsplit(gdal_source.removeprefix("ESRIJSON:")).query)
    return query.get("outFields") == ["*"]


def _columns_for(gdal_source: str) -> tuple[str, ...]:
    """The columns the service would answer this query with.

    Mirrors the live behaviour verified against
    ``services9.arcgis.com/.../USGS_Seismic_Data_v1/FeatureServer/0``: with
    ``outFields=*`` the response carries every field; without it, only the
    layer's display field comes back.
    """
    return (
        _ATTRIBUTE_COLUMNS if _requests_all_fields(gdal_source) else (_DISPLAY_FIELD,)
    )


def _create_table_sql(schema: str, table: str, columns: tuple[str, ...]) -> str:
    cols = ", ".join(f'"{c}" text' for c in columns)
    return f'CREATE TABLE "{schema}"."{table}" (gid serial PRIMARY KEY, {cols})'


# ---------------------------------------------------------------------------
# 1. The builder — the single site every service path composes its URL at
# ---------------------------------------------------------------------------


def test_arcgis_gdal_source_requests_every_field():
    """The ArcGIS query must name ``outFields``; the default is not "all"."""
    source, layer_name = build_gdal_source(
        "ArcGIS FeatureServer",
        "https://services.example.com/svc/FeatureServer",
        "quakes",
        layer_id=0,
    )

    assert layer_name == ""
    # urlencode renders `*` as %2A, which the service decodes back to `*`.
    assert "outFields=%2A" in source
    assert _requests_all_fields(source)


def test_arcgis_gdal_source_requests_every_field_when_paging():
    """A chunked import asks for all fields on every page, not just the first."""
    source, _ = build_gdal_source(
        "ArcGIS FeatureServer",
        "https://services.example.com/svc/FeatureServer",
        "quakes",
        layer_id=0,
        order_field="OBJECTID",
        result_limit=2000,
        result_offset=4000,
    )

    assert _requests_all_fields(source)
    assert "resultOffset=4000" in source


# ---------------------------------------------------------------------------
# 2. First import — the path the issue was filed against
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_arcgis_service_import_lands_every_attribute_column(
    client: AsyncClient,  # ensures app.core.db.async_session points at the test DB
    test_db_session: AsyncSession,
    monkeypatch,
):
    """A service import stores the layer's full attribute list, not one column.

    Drives the real ``ingest_service`` worker with a stand-in for ogr2ogr
    that materialises exactly the columns the composed URL asked for, so the
    assertion below fails with ``['id']`` whenever the URL stops requesting
    every field.
    """
    from app.processing.ingest import tasks_vector

    admin_id = await get_user_id(test_db_session, "admin")
    table_name = f"tbl_quakes_{_uuid.uuid4().hex[:8]}"

    job = IngestJob(
        source_filename="USGS Earthquakes",
        source_url="https://services.example.com/svc/FeatureServer",
        source_layer="0",
        created_by=admin_id,
        status="pending",
        user_metadata={
            "title": "USGS Earthquakes",
            "visibility": "private",
            "service_type": "ArcGIS FeatureServer",
            "layer_id": "0",
            # Non-spatial keeps the fixture to the attribute contract under
            # test; the geometry pipeline has its own coverage.
            "geometry_type": None,
            # What the preview stored. It lists every field, which is exactly
            # the promise the import used to break — and the fallback in
            # `_finalize_ingest` only consults it when the table has NO
            # attribute columns, so a one-column table slips past it.
            "source_columns": [
                {"name": c, "type": "esriFieldTypeString"} for c in _ATTRIBUTE_COLUMNS
            ],
        },
    )
    test_db_session.add(job)
    await test_db_session.flush()
    await test_db_session.commit()
    job_id = job.id
    attempt_id = job.attempt_id
    assert attempt_id is not None

    class _FakeProcessingPort:
        def __getattr__(self, name):
            from app.platform.extensions.defaults_processing_port import (
                DefaultProcessingPort,
            )

            return getattr(DefaultProcessingPort(), name)

        def build_gdal_source(self, *args, **kwargs):
            return build_gdal_source(*args, **kwargs)

    async def _validate_url_noop(_url: str) -> None:
        return None

    async def _fake_generate_table_name(*args, **kwargs):
        return table_name, None

    async def _fake_page_info(*args, **kwargs):
        return None, 1000, False, "OBJECTID"

    async def _fake_run_ogr2ogr_service(
        gdal_source: str,
        layer_name: str,
        target_table: str,
        db_conn_str: str,
        service_type: str,
        **kwargs,
    ) -> None:
        import app.core.db as db_module

        async with db_module.async_session() as session:
            await session.execute(text(f'DROP TABLE IF EXISTS data."{target_table}"'))
            await session.execute(
                text(_create_table_sql("data", target_table, _columns_for(gdal_source)))
            )
            await session.execute(
                text(
                    f'INSERT INTO data."{target_table}" '  # noqa: S608
                    f"DEFAULT VALUES"
                )
            )
            await session.commit()

    async def _fake_emit_billing_event(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.modules.catalog.sources.security.validate_url_for_ssrf",
        _validate_url_noop,
    )
    monkeypatch.setattr(
        "app.platform.extensions.get_processing_port",
        lambda: _FakeProcessingPort(),
    )
    monkeypatch.setattr("app.processing.ingest.ogr.build_pg_conn_str", lambda: "PG:")
    monkeypatch.setattr(
        "app.processing.ingest.service.generate_table_name",
        _fake_generate_table_name,
    )
    monkeypatch.setattr(tasks_vector, "_fetch_arcgis_import_page_info", _fake_page_info)
    monkeypatch.setattr(
        "app.processing.ingest.ogr.run_ogr2ogr_service", _fake_run_ogr2ogr_service
    )
    monkeypatch.setattr(tasks_vector, "_emit_billing_event", _fake_emit_billing_event)

    try:
        await tasks_vector.ingest_service.func(
            job_id=str(job_id),
            attempt_id=str(attempt_id),
            source_url="https://services.example.com/svc/FeatureServer",
            source_layer="0",
            user_id=str(admin_id),
        )

        dataset = (
            await test_db_session.execute(
                select(Dataset).where(Dataset.table_name == table_name)
            )
        ).scalar_one()

        names = [c["name"] for c in (dataset.column_info or [])]
        assert names == list(_ATTRIBUTE_COLUMNS), (
            "the import stored only what the URL asked the service for"
        )
    finally:
        await test_db_session.rollback()
        await test_db_session.execute(
            text(f'DROP TABLE IF EXISTS data."{table_name}" CASCADE')
        )
        await test_db_session.commit()


# ---------------------------------------------------------------------------
# 3. Refresh — the repopulation the issue asked for
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_service_refresh_repopulates_wrong_stored_column_info(
    client: AsyncClient,  # ensures app.core.db.async_session points at the test DB
    test_db_session: AsyncSession,
):
    """Refresh rewrites ``column_info`` from the fetch it just installed.

    Seeded with the exact broken value from the issue, so a dataset already
    stored with ``['id']`` is repaired by a refresh rather than keeping it
    forever.
    """
    from app.modules.catalog.datasets.domain.models import Record
    from app.processing.ingest.tasks import reupload_service

    admin_id = await get_user_id(test_db_session, "admin")

    table_name = f"ds_{_uuid.uuid4().hex[:12]}"
    record = Record(
        title="Stale Service Dataset",
        summary="stored with the display field alone",
        visibility="private",
        record_status="published",
        created_by=admin_id,
    )
    test_db_session.add(record)
    await test_db_session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        feature_count=1,
        source_format="arcgis_featureserver",
        source_filename="quakes",
        source_url="https://services.example.com/svc/FeatureServer/0",
        column_info=[
            {
                "name": _DISPLAY_FIELD,
                "type": "text",
                "ordinal_position": 2,
                "is_nullable": True,
            }
        ],
    )
    test_db_session.add(dataset)
    await test_db_session.commit()
    await test_db_session.refresh(dataset)
    dataset_id = dataset.id

    job = IngestJob(
        dataset_id=dataset_id,
        source_filename="quakes",
        source_url="https://services.example.com/svc/FeatureServer",
        source_layer="0",
        created_by=admin_id,
        status="pending",
        user_metadata={
            "reupload": True,
            "dataset_id": str(dataset_id),
            "service_type": "ArcGIS FeatureServer",
            "layer_id": 0,
            "source_type": "service_url",
        },
    )
    test_db_session.add(job)
    await test_db_session.commit()
    await test_db_session.refresh(job)

    async def _fake_run_ogr2ogr_service(
        gdal_source: str,
        layer_name: str,
        staging_table: str,
        db_conn_str: str,
        service_type: str,
        **kwargs,
    ) -> None:
        on_spawn = kwargs.get("on_spawn")
        if on_spawn is not None:
            on_spawn()
        import app.core.db as db_module

        async with db_module.async_session() as session:
            await session.execute(text(f'DROP TABLE IF EXISTS data."{staging_table}"'))
            await session.execute(
                text(
                    _create_table_sql("data", staging_table, _columns_for(gdal_source))
                )
            )
            await session.execute(
                text(f'INSERT INTO data."{staging_table}" DEFAULT VALUES')  # noqa: S608
            )
            await session.commit()

    try:
        with (
            patch(
                "app.modules.catalog.sources.security.validate_url_for_ssrf",
                new=AsyncMock(),
            ),
            patch(
                "app.processing.ingest.ogr.run_ogr2ogr_service",
                new=_fake_run_ogr2ogr_service,
            ),
            patch(
                "app.processing.ingest.tasks_reupload.invalidate_catalog_cache",
                new_callable=AsyncMock,
            ),
        ):
            await reupload_service(
                job_id=str(job.id),
                attempt_id=str(job.attempt_id),
                dataset_id=str(dataset_id),
                source_url=job.source_url or "",
                source_layer=job.source_layer or "",
                user_id=str(admin_id),
            )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message
        await test_db_session.refresh(dataset)

        names = [c["name"] for c in (dataset.column_info or [])]
        assert names == list(_ATTRIBUTE_COLUMNS)
    finally:
        await test_db_session.rollback()
        await test_db_session.execute(
            text(f'DROP TABLE IF EXISTS data."{table_name}" CASCADE')
        )
        await test_db_session.commit()


# ---------------------------------------------------------------------------
# 4. Registration — the shared derivation the analysis output goes through
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_register_non_spatial_table_populates_column_info(
    test_db_session: AsyncSession,
):
    """A non-spatial registration derives its columns like every other path.

    ``register_existing_table`` used to run ``extract_metadata`` only for
    tables with a geometry column, so an attribute-only table was catalogued
    with no ``column_info`` and no ``feature_count`` at all — the same
    contradiction the ArcGIS import produced, reached a different way.
    """
    from app.processing.ingest.schemas import RegisterRequest
    from app.processing.ingest.service import register_existing_table

    admin_id = await get_user_id(test_db_session, "admin")
    table_name = f"tbl_plain_{_uuid.uuid4().hex[:10]}"

    await test_db_session.execute(
        text(
            f'CREATE TABLE data."{table_name}" '
            f"(gid serial PRIMARY KEY, code text, population integer)"
        )
    )
    await test_db_session.execute(
        text(
            f'INSERT INTO data."{table_name}" (code, population) '  # noqa: S608
            f"VALUES ('a', 1), ('b', 2)"
        )
    )
    await test_db_session.commit()

    try:
        dataset = await register_existing_table(
            test_db_session,
            RegisterRequest(table_name=table_name, title="Plain Table"),
            SimpleNamespace(id=admin_id),
        )
        await test_db_session.commit()

        assert [c["name"] for c in (dataset.column_info or [])] == [
            "code",
            "population",
        ]
        assert dataset.feature_count == 2
        # A table with no geometry stays a table: the spatial fields the
        # skipped branch used to leave unset are still None.
        assert dataset.geometry_type is None
        assert dataset.srid is None
    finally:
        await test_db_session.rollback()
        await test_db_session.execute(
            text(f'DROP TABLE IF EXISTS data."{table_name}" CASCADE')
        )
        await test_db_session.commit()


# ---------------------------------------------------------------------------
# 5. Analysis materialize — the cascade, pinned
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_materialize_output_column_info_matches_carried_columns(
    test_db_session: AsyncSession,
):
    """A saved analysis output catalogues the columns it actually carried.

    The issue saw ``['id']`` here too, which read as a second defect. It is
    not one: the output carries its SOURCE's live columns, and the source was
    the one-column import. Given a healthy source the carry and the catalogue
    agree, so this is the guard that keeps the two from drifting apart on
    their own.
    """
    from app.processing.analysis.tasks import _materialize

    admin_id = await get_user_id(test_db_session, "admin")
    src = await _create_polygon_dataset(test_db_session, created_by=admin_id)
    await test_db_session.execute(
        text(f'ALTER TABLE data.{src.table_name} ADD COLUMN "mag" REAL')
    )
    await test_db_session.commit()

    job = IngestJob(
        source_filename="analysis-1359",
        created_by=admin_id,
        status="pending",
    )
    test_db_session.add(job)
    await test_db_session.commit()
    await test_db_session.refresh(job)

    await _materialize(
        job_id=str(job.id),
        dataset_id=str(src.id),
        user_id=str(admin_id),
        operation="centroid",
        title=f"Quake centroids {_uuid.uuid4().hex[:6]}",
    )

    await test_db_session.refresh(job)
    assert job.status == "complete", job.error_message

    out = await test_db_session.get(Dataset, job.dataset_id)
    live = (
        (
            await test_db_session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='data' AND table_name=:t "
                    "AND column_name NOT IN ('gid','geom','geom_4326') "
                    "ORDER BY ordinal_position"
                ).bindparams(t=out.table_name)
            )
        )
        .scalars()
        .all()
    )

    assert [c["name"] for c in (out.column_info or [])] == list(live)
    assert set(live) == {"name", "mag"}
