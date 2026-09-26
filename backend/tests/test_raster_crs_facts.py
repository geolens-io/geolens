"""Requests read a raster's stored CRS facts and never hand its CRS text to PROJ."""

from __future__ import annotations

import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import rasterio
import rasterio.crs
from sqlalchemy import select

from app.core import geo
from app.core.geo import crs_columns, raster_crs_facts, wkt_crs_facts
from app.platform.jobs.models import IngestJob
from app.processing.raster import probe
from app.processing.raster.models import RasterAsset
from app.processing.raster.validation import compare_crs
from app.processing.tiles.router import _DEFAULT_RASTER_MAXZOOM

from tests.factories import create_raster_dataset, get_user_id
from tests.test_raster_probe import _geotiff, _stalling_child
from tests.test_raster_replace_1221 import raster_storage as raster_storage

pytestmark = pytest.mark.anyio

# NAD83 is geographic but not EPSG:4326, so the tile path's EPSG fallback would
# read its degree resolution as metres (maxzoom 22). Only the stored facts give 7.
_NAD83_WKT = rasterio.crs.CRS.from_epsg(4269).to_wkt(version="WKT2_2019")
_NAD83_FACTS = wkt_crs_facts(_NAD83_WKT)
_RES = 1.0 / 60.0

_UTM_18N = rasterio.crs.CRS.from_epsg(32618)
_UTM_18N_WKT1 = _UTM_18N.to_wkt()
_UTM_18N_WKT2 = _UTM_18N.to_wkt(version="WKT2_2019")
_UTM_19N_WKT2 = rasterio.crs.CRS.from_epsg(32619).to_wkt(version="WKT2_2019")


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


async def _nad83_raster(session, *, stored_facts: bool = True, epsg: int | None = 4269):
    admin_id = await get_user_id(session, "admin")
    facts = _NAD83_FACTS if stored_facts else {}
    return await create_raster_dataset(
        session,
        created_by=admin_id,
        name=f"CRS facts {uuid.uuid4().hex[:10]}",
        srid=4269,
        create_raster_asset=True,
        raster_asset_kwargs={
            "epsg": epsg,
            **crs_columns({"crs_wkt": _NAD83_WKT, **facts}),
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


class TestRowsTheRepairHasNotReached:
    async def test_a_row_with_an_epsg_code_reads_that_codes_facts(
        self, client, admin_auth_header, test_db_session, crs_parses
    ):
        dataset = await _nad83_raster(test_db_session, stored_facts=False)
        dataset_id = str(dataset.id)

        detail = await client.get(f"/datasets/{dataset_id}", headers=admin_auth_header)
        assert detail.json()["raster"]["crs_is_geographic"] is True
        record = await client.get(
            f"/collections/datasets/items/{dataset_id}", headers=admin_auth_header
        )
        assert record.json()["properties"]["crs_is_geographic"] is True
        token = await client.get(f"/tiles/token/{dataset_id}/")
        assert token.json()["maxzoom"] == 7
        batch = await client.post("/tiles/tokens/", json={"dataset_ids": [dataset_id]})
        assert batch.json()["tokens"][dataset_id]["maxzoom"] == 7
        assert crs_parses == []

    def test_stac_gsd_converts_by_the_epsg_code(self):
        asset = RasterAsset(epsg=2263, res_x=10.0, res_y=-10.0)

        assert asset.to_stac_properties()["gsd"] == pytest.approx(3.048006, rel=1e-4)

    async def test_a_row_with_only_crs_text_gets_the_default_maxzoom(
        self, client, test_db_session, crs_parses
    ):
        dataset = await _nad83_raster(test_db_session, stored_facts=False, epsg=None)

        token = await client.get(f"/tiles/token/{dataset.id}/")

        assert token.json()["maxzoom"] == _DEFAULT_RASTER_MAXZOOM
        assert crs_parses == []

    def test_stored_facts_win_over_the_epsg_code(self):
        stored = {
            "crs_is_geographic": False,
            "crs_has_degree_unit": False,
            "crs_metres_per_unit": 1.0,
        }

        assert raster_crs_facts(SimpleNamespace(epsg=4326, **stored)) == stored

    def test_missing_facts_come_from_the_epsg_code(self):
        row = SimpleNamespace(epsg=4269, **dict.fromkeys(_NAD83_FACTS))

        assert raster_crs_facts(row) == _NAD83_FACTS

    @pytest.mark.parametrize("epsg", [None, "4269", True, 0, -4269, 999999999])
    def test_without_a_usable_code_the_facts_stay_unknown(self, epsg):
        row = SimpleNamespace(epsg=epsg, **dict.fromkeys(_NAD83_FACTS))

        assert raster_crs_facts(row) == dict.fromkeys(_NAD83_FACTS)


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


async def _vrt_source(session, crs_wkt: str) -> tuple[str, str]:
    """A mosaic-compatible raster source: its dataset id and raster asset id."""
    dataset = await create_raster_dataset(
        session,
        created_by=await get_user_id(session, "admin"),
        name=f"VRT CRS source {uuid.uuid4().hex[:8]}",
        visibility="private",
        create_raster_asset=True,
        raster_asset_kwargs={
            "crs_wkt": crs_wkt,
            "dtype": "uint8",
            "band_count": 1,
            "res_x": 10.0,
            "res_y": 10.0,
            "width": 100,
            "height": 100,
            "is_rotated": False,
        },
    )
    asset_id = await session.scalar(
        select(RasterAsset.id).where(RasterAsset.dataset_id == dataset.id)
    )
    return str(dataset.id), str(asset_id)


async def _create_vrt(client, headers, sources: list[tuple[str, str]]):
    task = MagicMock()
    task.defer_async = AsyncMock(return_value=None)
    with patch("app.processing.ingest.tasks.ingest_vrt", task):
        return await client.post(
            "/ingest/vrt/create",
            json={
                "source_dataset_ids": [dataset_id for dataset_id, _ in sources],
                "vrt_type": "mosaic",
                "resolution_strategy": "finest",
                "title": f"CRS VRT {uuid.uuid4().hex[:6]}",
            },
            headers=headers,
        )


class TestVrtSourcesCompareCrsInTheChild:
    async def test_the_same_crs_in_other_text_is_accepted(
        self, client, admin_auth_header, test_db_session, crs_parses
    ):
        sources = [
            await _vrt_source(test_db_session, _UTM_18N_WKT1),
            await _vrt_source(test_db_session, _UTM_18N_WKT2),
        ]

        resp = await _create_vrt(client, admin_auth_header, sources)

        assert resp.status_code == 202, resp.text
        assert crs_parses == []

    async def test_a_different_crs_is_a_mismatch(
        self, client, admin_auth_header, test_db_session
    ):
        sources = [
            await _vrt_source(test_db_session, _UTM_18N_WKT2),
            await _vrt_source(test_db_session, _UTM_19N_WKT2),
        ]

        resp = await _create_vrt(client, admin_auth_header, sources)

        assert resp.status_code == 422, resp.text
        # Either source can be the reference: the lookup doesn't keep request order.
        ((code, flagged),) = [
            (e["code"], e["source_id"]) for e in resp.json()["detail"]
        ]
        assert code == "crs_mismatch"
        assert flagged in {asset_id for _, asset_id in sources}

    async def test_a_comparison_that_stalls_is_refused_as_unverified(
        self, client, admin_auth_header, test_db_session, monkeypatch, tmp_path
    ):
        sources = [
            await _vrt_source(test_db_session, _UTM_18N_WKT1),
            await _vrt_source(test_db_session, _UTM_18N_WKT2),
        ]
        _stalling_child(monkeypatch, tmp_path)
        monkeypatch.setattr(probe, "CRS_FACTS_TIMEOUT_SECONDS", 1)

        started = time.monotonic()
        resp = await _create_vrt(client, admin_auth_header, sources)

        assert time.monotonic() - started < 5
        assert resp.status_code == 422, resp.text
        ((code, flagged),) = [
            (e["code"], e["source_id"]) for e in resp.json()["detail"]
        ]
        assert code == "crs_unverified"
        assert flagged in {asset_id for _, asset_id in sources}

    @pytest.mark.parametrize(
        "raised",
        [
            OSError(24, "Too many open files"),
            UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
        ],
    )
    def test_a_child_that_cannot_run_leaves_the_comparison_unverified(
        self, monkeypatch, raised
    ):
        def _fail(*args, **kwargs):
            raise raised

        monkeypatch.setattr(probe.subprocess, "run", _fail)

        assert compare_crs([_UTM_18N_WKT2, _UTM_19N_WKT2]) == {
            _UTM_18N_WKT2: True,
            _UTM_19N_WKT2: None,
        }

    async def test_an_unreadable_crs_is_blamed_on_its_own_source(
        self, client, admin_auth_header, test_db_session
    ):
        unreadable = await _vrt_source(test_db_session, "NOT A CRS")
        readable = await _vrt_source(test_db_session, _UTM_18N_WKT2)

        resp = await _create_vrt(client, admin_auth_header, [unreadable, readable])

        assert resp.status_code == 422, resp.text
        assert [(e["code"], e["source_id"]) for e in resp.json()["detail"]] == [
            ("crs_unverified", unreadable[1])
        ]

    def test_the_reference_is_the_first_text_proj_can_read(self):
        assert compare_crs(["NOT A CRS", _UTM_18N_WKT2, _UTM_19N_WKT2]) == {
            "NOT A CRS": None,
            _UTM_18N_WKT2: True,
            _UTM_19N_WKT2: False,
        }

    def test_identical_text_starts_no_child(self, monkeypatch):
        def _no_child(*args, **kwargs):
            raise AssertionError("a probe child was started")

        monkeypatch.setattr(probe, "_run", _no_child)

        assert compare_crs([_UTM_18N_WKT2, None, _UTM_18N_WKT2]) == {
            _UTM_18N_WKT2: True
        }

    def test_text_the_child_cannot_read_is_unverified(self):
        assert compare_crs([_UTM_18N_WKT2, "NOT A CRS", _UTM_18N_WKT1]) == {
            _UTM_18N_WKT2: True,
            "NOT A CRS": None,
            _UTM_18N_WKT1: True,
        }
