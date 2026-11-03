"""An ArcGIS layer that stores Z keeps it in the staged table; multipatch is refused."""

from __future__ import annotations

import json
import shutil
import uuid
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.modules.catalog.sources.layer_types import (
    reject_unsupported_arcgis_type,
)
from app.modules.catalog.sources.preview import build_gdal_source
from app.processing.ingest import tasks_reupload, tasks_vector

_BASE = "https://services.example.com/arcgis/rest/services/Wells/FeatureServer"

needs_ogr = pytest.mark.skipif(
    shutil.which("ogr2ogr") is None,
    reason="needs a GDAL command line to measure what the PostgreSQL driver stores",
)


def _query(source: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(source.partition(":")[2]).query)


class TestBuildGdalSource:
    def test_return_z_asks_the_server_for_z(self) -> None:
        source, _ = build_gdal_source(
            "ArcGIS FeatureServer", _BASE, "", 0, return_z=True
        )
        assert _query(source)["returnZ"] == ["true"]

    def test_default_does_not_ask(self) -> None:
        source, _ = build_gdal_source("ArcGIS FeatureServer", _BASE, "", 0)
        assert "returnZ" not in _query(source)

    @pytest.mark.parametrize("ids", [[1, 2], [1, (1 << 31) + 5]])
    def test_object_id_chunks_carry_z_in_both_drivers(self, ids) -> None:
        source, _ = build_gdal_source(
            "ArcGIS FeatureServer",
            _BASE,
            "",
            0,
            object_ids=ids,
            return_z=True,
        )
        assert _query(source)["returnZ"] == ["true"]


class TestLayerJson:
    def test_multipatch_is_refused_with_a_coded_422(self) -> None:
        with pytest.raises(HTTPException) as caught:
            reject_unsupported_arcgis_type(
                {"type": "Feature Layer", "geometryType": "esriGeometryMultiPatch"}
            )
        assert caught.value.status_code == 422
        assert caught.value.detail["code"] == "unsupported_geometry"

    def test_other_geometry_passes(self) -> None:
        reject_unsupported_arcgis_type(
            {"type": "Feature Layer", "geometryType": "esriGeometryPoint"}
        )


class TestHasZLookup:
    @pytest.mark.anyio
    async def test_reads_the_flag_from_the_layer_json(self) -> None:
        with patch(
            "app.modules.catalog.sources.adapters.arcgis.fetch_arcgis_layer_meta",
            new=AsyncMock(return_value={"hasZ": True}),
        ):
            assert await tasks_vector._fetch_arcgis_has_z(_BASE, 0, None) is True

    @pytest.mark.anyio
    @pytest.mark.parametrize("flag", [False, "true", None])
    async def test_only_a_true_flag_counts(self, flag) -> None:
        with patch(
            "app.modules.catalog.sources.adapters.arcgis.fetch_arcgis_layer_meta",
            new=AsyncMock(return_value={"hasZ": flag}),
        ):
            assert await tasks_vector._fetch_arcgis_has_z(_BASE, 0, None) is False

    @pytest.mark.anyio
    async def test_unreadable_layer_reads_as_flat(self) -> None:
        with patch(
            "app.modules.catalog.sources.adapters.arcgis.fetch_arcgis_layer_meta",
            new=AsyncMock(side_effect=ValueError("boom")),
        ):
            assert await tasks_vector._fetch_arcgis_has_z(_BASE, 0, None) is False


class TestRefreshPlumbing:
    @pytest.mark.anyio
    async def test_refresh_fetch_asks_for_z_and_stages_3d(self, monkeypatch) -> None:
        async def _page_info(*_a, **_k):
            return 3, 1000, False, "OBJECTID"

        monkeypatch.setattr(tasks_vector, "_fetch_arcgis_import_page_info", _page_info)
        monkeypatch.setattr(
            tasks_vector, "_fetch_arcgis_has_z", AsyncMock(return_value=True)
        )
        run = AsyncMock()
        with patch("app.processing.ingest.ogr.run_ogr2ogr_service", new=run):
            await tasks_reupload._fetch_service_layer_with_paging_guard(
                service_type_raw="ArcGIS FeatureServer",
                service_type="arcgis_featureserver",
                source_url=_BASE,
                layer_name="Wells",
                layer_id=0,
                token=None,
                staging_table="f3_plumbing",
                db_conn_str="PG:",
                schema="data",
                fallback_order_field="OBJECTID",
                on_spawn=None,
                reviews_unknown_count=False,
            )
        source = run.await_args.args[0]
        assert _query(source)["returnZ"] == ["true"]
        assert run.await_args.kwargs["keep_z"] is True


_LAYER = {
    "objectIdFieldName": "OBJECTID",
    "geometryType": "esriGeometryPoint",
    "hasZ": True,
    "spatialReference": {"wkid": 4326},
    "fields": [
        {"name": "OBJECTID", "type": "esriFieldTypeOID"},
        {"name": "label", "type": "esriFieldTypeString", "length": 10},
    ],
    "features": [
        {
            "attributes": {"OBJECTID": 1, "label": "a"},
            "geometry": {"x": -73.9, "y": 40.7, "z": 12.5},
        },
        {
            "attributes": {"OBJECTID": 2, "label": "b"},
            "geometry": {"x": -74.0, "y": 40.8, "z": 30.0},
        },
    ],
}


@needs_ogr
class TestRealGdalStagesZ:
    @pytest.mark.anyio
    async def test_staged_table_keeps_z_only_when_asked(self, tmp_path) -> None:
        from app.core.config import settings
        from app.core.db import async_session
        from app.processing.ingest.ogr import run_ogr2ogr_service

        layer_file = tmp_path / "layer.json"
        layer_file.write_text(json.dumps(_LAYER))
        staged: dict[bool, list] = {}
        # One test, not a parametrisation: the pooled connection cannot move
        # between the event loops of two tests.
        for keep_z in (True, False):
            table = f"f3_z_{uuid.uuid4().hex[:8]}"
            try:
                await run_ogr2ogr_service(
                    f"ESRIJSON:{layer_file}",
                    "",
                    table,
                    settings.ogr_connection_string,
                    "arcgis_featureserver",
                    schema="data",
                    keep_z=keep_z,
                )
                async with async_session() as session:
                    result = await session.execute(
                        text(
                            f'SELECT ST_Z(_geolens_geom) FROM "data"."{table}" ORDER BY gid'
                        )
                    )
                    staged[keep_z] = list(result.scalars().all())
            finally:
                async with async_session() as session:
                    await session.execute(
                        text(f'DROP TABLE IF EXISTS "data"."{table}"')
                    )
                    await session.commit()
        assert staged == {True: [12.5, 30.0], False: [None, None]}
