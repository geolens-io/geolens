"""Requests read a raster's stored CRS facts and never hand its CRS text to PROJ."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
import rasterio
import rasterio.crs
from sqlalchemy import select

from app.core import geo
from app.core.geo import crs_columns, wkt_crs_facts
from app.platform.jobs.models import IngestJob
from app.processing.raster.models import RasterAsset

from tests.factories import create_raster_dataset, get_user_id
from tests.test_raster_probe import _geotiff
from tests.test_raster_replace_1221 import raster_storage as raster_storage

pytestmark = pytest.mark.anyio

# NAD83 is geographic but not EPSG:4326, so the tile path's EPSG fallback would
# read its degree resolution as metres (maxzoom 22). Only the stored facts give 7.
_NAD83_WKT = rasterio.crs.CRS.from_epsg(4269).to_wkt(version="WKT2_2019")
_NAD83_FACTS = wkt_crs_facts(_NAD83_WKT)
_RES = 1.0 / 60.0


@pytest.fixture
def crs_parses(monkeypatch) -> list[str]:
    """Record, and refuse, every CRS text parse in this process."""
    attempts: list[str] = []

    def _refuse(name: str):
        def _parse(cls, *args, **kwargs):
            attempts.append(name)
            raise AssertionError(f"CRS text parsed through {name}")

        return classmethod(_parse)

    recording = type(
        "RecordingCRS",
        (rasterio.crs.CRS,),
        {
            name: _refuse(name)
            for name in (
                "from_wkt",
                "from_user_input",
                "from_string",
                "from_proj4",
                "from_dict",
            )
        },
    )
    monkeypatch.setattr(rasterio.crs, "CRS", recording)
    monkeypatch.setattr(rasterio, "CRS", recording)

    def _parse_crs(crs_wkt):
        attempts.append("_parse_crs")
        raise AssertionError("stored CRS text parsed")

    monkeypatch.setattr(geo, "_parse_crs", _parse_crs)
    return attempts


async def _nad83_raster(session):
    admin_id = await get_user_id(session, "admin")
    return await create_raster_dataset(
        session,
        created_by=admin_id,
        name=f"CRS facts {uuid.uuid4().hex[:10]}",
        srid=4269,
        create_raster_asset=True,
        raster_asset_kwargs={
            "epsg": 4269,
            **crs_columns({"crs_wkt": _NAD83_WKT, **_NAD83_FACTS}),
            "res_x": _RES,
            "res_y": _RES,
            "width": 21600,
            "height": 10800,
            "band_count": 1,
            "dtype": "int16",
        },
    )


class TestRequestsReadStoredFacts:
    async def test_no_request_parses_the_stored_crs_text(
        self, client, admin_auth_header, viewer_auth_header, test_db_session, crs_parses
    ):
        dataset = await _nad83_raster(test_db_session)
        dataset_id = str(dataset.id)

        detail = await client.get(f"/datasets/{dataset_id}", headers=admin_auth_header)
        assert detail.status_code == 200, detail.text
        assert detail.json()["raster"]["crs_is_geographic"] is True

        listing = await client.get(
            "/datasets/", params={"limit": 200}, headers=viewer_auth_header
        )
        assert listing.status_code == 200, listing.text
        (listed,) = [d for d in listing.json()["datasets"] if d["id"] == dataset_id]
        assert listed["raster"]["crs_is_geographic"] is True

        record = await client.get(
            f"/collections/datasets/items/{dataset_id}", headers=admin_auth_header
        )
        assert record.status_code == 200, record.text
        assert record.json()["properties"]["crs_is_geographic"] is True

        search = await client.get(
            "/search/datasets/",
            params={"q": dataset.record.title},
            headers=admin_auth_header,
        )
        assert search.status_code == 200, search.text
        (found,) = [f for f in search.json()["features"] if f["id"] == dataset_id]
        assert found["properties"]["crs_is_geographic"] is True

        item = await client.get(f"/stac/items/{dataset_id}", headers=admin_auth_header)
        assert item.status_code == 200, item.text
        assert item.json()["properties"]["proj:code"] == "EPSG:4269"

        token = await client.get(f"/tiles/token/{dataset_id}/")
        assert token.status_code == 200, token.text
        assert token.json()["maxzoom"] == 7

        batch = await client.post("/tiles/tokens/", json={"dataset_ids": [dataset_id]})
        assert batch.status_code == 200, batch.text
        assert batch.json()["tokens"][dataset_id]["maxzoom"] == 7

        assert crs_parses == []


class TestWritersStoreTheFacts:
    async def test_ingest_stores_the_facts_of_the_cogs_crs_text(
        self, test_db_session, raster_storage, tmp_path
    ):
        from app.processing.ingest.tasks_raster import ingest_raster

        source = _geotiff(
            tmp_path / "feet.tif", epsg=2263, bounds=(980000, 190000, 990000, 200000)
        )
        job = IngestJob(
            source_filename="feet.tif",
            file_path=source,
            created_by=await get_user_id(test_db_session, "admin"),
            status="pending",
            user_metadata={"file_type": "raster", "title": "CRS facts ingest"},
        )
        test_db_session.add(job)
        await test_db_session.commit()
        await test_db_session.refresh(job)
        job_id = job.id

        with patch(
            "app.processing.embeddings.helpers.defer_embedding", new=AsyncMock()
        ):
            await ingest_raster.func(
                job_id=str(job_id),
                file_path=source,
                user_id=str(job.created_by),
                attempt_id=str(job.attempt_id),
            )

        test_db_session.expire_all()
        dataset_id = await test_db_session.scalar(
            select(IngestJob.dataset_id).where(IngestJob.id == job_id)
        )
        asset = await test_db_session.scalar(
            select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
        )
        assert asset.epsg == 2263
        assert (
            asset.crs_is_geographic,
            asset.crs_has_degree_unit,
            asset.crs_metres_per_unit,
        ) == (False, False, pytest.approx(0.3048006))

    def test_the_column_helper_carries_every_fact(self):
        assert set(crs_columns({})) == {"crs_wkt", *wkt_crs_facts(None)}

    def test_set_crs_replaces_the_text_and_its_facts_together(self):
        asset = RasterAsset(crs_wkt="old", crs_is_geographic=True)

        asset.set_crs({"crs_wkt": _NAD83_WKT, **_NAD83_FACTS})

        assert {column: getattr(asset, column) for column in crs_columns({})} == {
            "crs_wkt": _NAD83_WKT,
            **_NAD83_FACTS,
        }
