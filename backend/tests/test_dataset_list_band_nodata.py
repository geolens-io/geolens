"""The dataset list reads a band's stored nodata as text, whatever JSON type holds it."""

import uuid

import pytest
from sqlalchemy import delete

from app.modules.catalog.datasets.domain.models import Dataset, Record

from tests.factories import create_raster_dataset, get_user_id

pytestmark = pytest.mark.anyio


@pytest.fixture
async def numeric_nodata_raster(test_db_session):
    """A public raster whose band_info holds nodata as JSON numbers and a stray object."""
    dataset = await create_raster_dataset(
        test_db_session,
        created_by=await get_user_id(test_db_session, "admin"),
        name=f"Numeric Nodata {uuid.uuid4().hex[:10]}",
        create_raster_asset=True,
        raster_asset_kwargs=dict(
            band_count=4,
            dtype="float32",
            nodata="0",
            band_info=[
                {"index": 1, "dtype": "float32", "nodata": 0},
                {"index": 2, "dtype": "float32", "nodata": 0.5},
                {"index": 3, "dtype": "float32", "nodata": "nan"},
                {"index": 4, "dtype": "float32", "nodata": {"value": 0}},
            ],
        ),
    )
    dataset_id, record_id = dataset.id, dataset.record_id
    try:
        yield dataset_id
    finally:
        await test_db_session.rollback()
        await test_db_session.execute(delete(Dataset).where(Dataset.id == dataset_id))
        await test_db_session.execute(delete(Record).where(Record.id == record_id))
        await test_db_session.commit()


async def test_a_numeric_band_nodata_lists_as_text(
    client, admin_auth_header, numeric_nodata_raster
):
    resp = await client.get("/datasets/?limit=200", headers=admin_auth_header)

    assert resp.status_code == 200, resp.text
    listed = {d["id"]: d for d in resp.json()["datasets"]}
    bands = listed[str(numeric_nodata_raster)]["raster"]["bands"]
    assert [band["nodata"] for band in bands] == ["0", "0.5", "nan", None]
