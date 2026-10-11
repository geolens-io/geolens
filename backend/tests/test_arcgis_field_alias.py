"""ArcGIS field aliases and descriptions become attribute titles and descriptions."""

import json as _json
import uuid
from unittest.mock import AsyncMock, patch

import httpx
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.models import AttributeMetadata
from app.modules.catalog.sources.adapters.arcgis import fetch_arcgis_layer_preview
from app.modules.catalog.sources.field_labels import arcgis_field_labels
from app.platform.jobs.models import IngestJob
from app.processing.ingest.tasks_common import IngestContext, _finalize_ingest
from app.processing.ingest.metadata_attributes import (
    apply_source_field_labels,
    refresh_attribute_metadata,
)
from tests.factories import get_user_id
from tests.test_attribute_metadata import _create_dataset_with_attributes

_COLUMNS = [
    {"name": "name", "type": "text", "ordinal_position": 2, "is_nullable": True},
    {"name": "pop_2020", "type": "integer", "ordinal_position": 3, "is_nullable": True},
]

_LAYER = {
    "fields": [
        {"name": "OBJECTID", "type": "esriFieldTypeOID", "alias": "OBJECTID"},
        {
            "name": "POP_2020",
            "type": "esriFieldTypeInteger",
            "alias": "Population (2020 census)",
            "description": "People counted on census day.",
        },
        {"name": "name", "type": "esriFieldTypeString", "alias": "name"},
        {"name": "SHAPE", "type": "esriFieldTypeGeometry", "alias": "Shape"},
    ]
}


def test_only_an_informative_alias_or_description_is_kept() -> None:
    assert arcgis_field_labels(_LAYER) == {
        "pop_2020": {
            "alias": "Population (2020 census)",
            "description": "People counted on census day.",
        }
    }


def test_labels_are_keyed_by_the_name_each_field_is_stored_under() -> None:
    meta = {
        "fields": [
            {"name": "geom", "type": "esriFieldTypeString", "alias": "Outline"},
            {"name": "src_geom", "type": "esriFieldTypeString"},
        ]
    }
    # `geom` is reserved, so it is stored as `src_geom_2` beside the real `src_geom`.
    assert arcgis_field_labels(meta) == {"src_geom_2": {"alias": "Outline"}}


def test_a_name_longer_than_postgres_allows_is_keyed_by_its_truncation() -> None:
    long_name = "a_very_long_field_name_" * 4
    meta = {
        "fields": [{"name": long_name, "type": "esriFieldTypeString", "alias": "Long"}]
    }
    assert arcgis_field_labels(meta) == {long_name[:63]: {"alias": "Long"}}


def test_characters_postgres_cannot_store_are_dropped() -> None:
    meta = {
        "fields": [
            {"name": "a", "alias": "Al\x00ias\ud800", "description": "\x00"},
        ]
    }
    assert arcgis_field_labels(meta) == {"a": {"alias": "Alias"}}


def test_odd_field_entries_are_ignored() -> None:
    meta = {
        "fields": [
            "text",
            {"name": 5, "alias": "x"},
            {"name": "a", "alias": ["list"], "description": "   "},
        ]
    }
    assert arcgis_field_labels(meta) == {}
    assert arcgis_field_labels({"fields": None}) == {}


async def _attrs(session: AsyncSession, dataset_id) -> dict[str, AttributeMetadata]:
    await session.rollback()
    rows = await session.execute(
        select(AttributeMetadata).where(AttributeMetadata.dataset_id == dataset_id)
    )
    return {row.field_name: row for row in rows.scalars().all()}


class TestAliasesOnImport:
    async def test_alias_replaces_the_humanized_title_and_description_fills(
        self, test_db_session: AsyncSession
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)

        await apply_source_field_labels(
            test_db_session, ds.id, {"field_labels": arcgis_field_labels(_LAYER)}
        )
        await test_db_session.commit()

        attrs = await _attrs(test_db_session, ds.id)
        assert attrs["pop_2020"].title == "Population (2020 census)"
        assert attrs["pop_2020"].description == "People counted on census day."
        assert attrs["name"].title == "Name"
        assert attrs["name"].description is None

    async def test_no_labels_leaves_the_humanized_titles(
        self, test_db_session: AsyncSession
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)

        await apply_source_field_labels(test_db_session, ds.id, {})
        await test_db_session.commit()

        attrs = await _attrs(test_db_session, ds.id)
        assert attrs["pop_2020"].title == "Pop 2020"


class TestAliasesOnRefresh:
    async def test_a_refresh_keeps_the_alias_title_and_description(
        self, test_db_session: AsyncSession
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)
        await apply_source_field_labels(
            test_db_session, ds.id, {"field_labels": arcgis_field_labels(_LAYER)}
        )
        await test_db_session.commit()

        await refresh_attribute_metadata(
            test_db_session, ds.id, _COLUMNS, geometry_type="POINT"
        )
        await test_db_session.commit()

        attrs = await _attrs(test_db_session, ds.id)
        assert attrs["pop_2020"].title == "Population (2020 census)"
        assert attrs["pop_2020"].description == "People counted on census day."

    async def test_a_user_edit_survives_a_refresh(
        self, test_db_session: AsyncSession
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)
        dataset_id = ds.id
        await apply_source_field_labels(
            test_db_session, dataset_id, {"field_labels": arcgis_field_labels(_LAYER)}
        )
        attrs = await _attrs(test_db_session, dataset_id)
        attrs["pop_2020"].title = "Residents"
        attrs["pop_2020"].description = "Edited by hand."
        attrs["pop_2020"].user_modified_fields = ["description", "title"]
        await test_db_session.commit()
        test_db_session.expunge_all()

        await refresh_attribute_metadata(
            test_db_session, dataset_id, _COLUMNS, geometry_type="POINT"
        )
        await test_db_session.commit()

        attrs = await _attrs(test_db_session, dataset_id)
        assert attrs["pop_2020"].title == "Residents"
        assert attrs["pop_2020"].description == "Edited by hand."


class TestAliasesThroughTheFinalizePipeline:
    async def test_a_service_import_titles_columns_from_the_preview_labels(
        self, test_db_session: AsyncSession, clean_tables
    ) -> None:
        user_id = await get_user_id(test_db_session, "admin")
        table_name = f"alias_{uuid.uuid4().hex[:10]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table_name} "
                "(gid serial PRIMARY KEY, pop_2020 integer, name text)"
            )
        )
        await test_db_session.commit()
        job = IngestJob(
            source_filename="Census",
            created_by=user_id,
            status="running",
            user_metadata={
                "title": "Census",
                "visibility": "private",
                "field_labels": arcgis_field_labels(_LAYER),
            },
        )
        test_db_session.add(job)
        await test_db_session.flush()

        try:
            with (
                patch(
                    "app.processing.ingest.publish_followups.invalidate_catalog_cache",
                    new=AsyncMock(),
                ),
                patch(
                    "app.processing.embeddings.helpers.defer_embedding",
                    new=AsyncMock(),
                ),
            ):
                dataset = await _finalize_ingest(
                    IngestContext(
                        session=test_db_session,
                        job=job,
                        table_name=table_name,
                        user_id=str(user_id),
                        has_geometry=False,
                        effective_srid=None,
                        source_format="arcgis_featureserver",
                        source_filename="Census",
                        original_srid=None,
                        user_metadata=job.user_metadata,
                    )
                )
            attrs = await _attrs(test_db_session, dataset.id)
            assert attrs["pop_2020"].title == "Population (2020 census)"
            assert attrs["name"].title == "Name"
        finally:
            await test_db_session.execute(
                text(f'DROP TABLE IF EXISTS data."{table_name}" CASCADE')
            )
            await test_db_session.commit()


def _stream(data: dict) -> httpx.Response:
    raw = _json.dumps(data).encode()

    async def _chunks():
        yield raw

    return httpx.Response(200, content=_chunks())


class TestThePreviewCarriesTheLabels:
    async def test_the_layer_preview_reports_field_labels(self) -> None:
        meta = {"currentVersion": 11.3, "name": "Census", **_LAYER}

        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/0"):
                return _stream(meta)
            return _stream({"features": [], "count": 0})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            preview = await fetch_arcgis_layer_preview(
                "https://example.com/arcgis/rest/services/C/FeatureServer", 0, client
            )

        assert preview["field_labels"] == arcgis_field_labels(_LAYER)

    async def test_the_preview_job_keeps_them_for_the_import(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ) -> None:
        preview = {
            "srid": 4326,
            "geometry_type": "Point",
            "layer_name": "Census",
            "feature_count": 1,
            "columns": [{"name": "POP_2020", "type": "Integer"}],
            "sample_rows": [],
            "field_labels": arcgis_field_labels(_LAYER),
        }
        with (
            patch(
                "app.modules.catalog.sources.router.validate_url_for_ssrf",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.catalog.sources.router.fetch_arcgis_layer_preview",
                new_callable=AsyncMock,
                return_value=preview,
            ),
        ):
            resp = await client.post(
                "/services/preview/",
                json={
                    "url": "https://example.com/arcgis/rest/services/C/FeatureServer",
                    "service_type": "ArcGIS FeatureServer",
                    "layer_name": "Census",
                    "layer_id": 0,
                },
                headers=admin_auth_header,
            )

        assert resp.status_code == 200
        job = await test_db_session.get(IngestJob, uuid.UUID(resp.json()["job_id"]))
        assert job is not None
        assert job.user_metadata["field_labels"] == arcgis_field_labels(_LAYER)


class TestRenamingAColumn:
    async def test_an_automatic_title_follows_the_new_name(
        self, test_db_session: AsyncSession
    ) -> None:
        from app.modules.catalog.layers.service import rename_column

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)
        dataset_id = ds.id
        await apply_source_field_labels(
            test_db_session, dataset_id, {"field_labels": {"name": {"alias": "Label"}}}
        )

        await rename_column(test_db_session, ds, "pop_2020", "residents")
        await rename_column(test_db_session, ds, "name", "nickname")
        await test_db_session.commit()

        attrs = await _attrs(test_db_session, dataset_id)
        assert attrs["residents"].title == "Residents"
        assert attrs["nickname"].title == "Label"
