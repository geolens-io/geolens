"""The per-dataset OGC items route refuses an invalid datetime."""

import pytest
from httpx import AsyncClient

from tests.factories import get_user_id
from tests.test_ogc_features import _cleanup_table, _create_test_table_and_dataset

pytestmark = pytest.mark.anyio


@pytest.fixture
async def points(test_db_session):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_test_table_and_dataset(
        test_db_session, created_by=admin_id, with_features=3
    )
    yield dataset
    await _cleanup_table(test_db_session, dataset.table_name)


@pytest.mark.parametrize(
    "datetime_value",
    [
        "garbage",
        "2026-13-45T00:00:00Z",
        "2026-01-01/garbage",
        "2026-02-30",
        "2016-12-31T23:59:60.9Z/2016-12-31T23:59:60.1Z",
        "2026-01-01T24:00:00Z",
        "2026-01-01T00:00:00Z/2026-01-01T24:00:00Z",
        "2026-01-01T24:00:00Z/..",
        "2016-12-31T23:59:60.1Z/2016-12-31T23:59:59.9Z",
        "2016-12-31T23:59:60Z/2016-12-31T23:59:59.5Z",
        "",
        "2026-01-01T00:00:00+01:60",
        "2026-01-01T00:00:00-24:00",
        "2026-13-45",
        "2026-03-01/2026-02-01",
        "2020-01-01Tgarbage",
        "2020-01-01T25:00:00Z",
        "../..",
        "2021-01-01T00:00:00Z/2020-01-01T00:00:00Z",
    ],
)
async def test_an_invalid_datetime_is_refused(
    client: AsyncClient, points, datetime_value: str
) -> None:
    resp = await client.get(
        f"/collections/{points.id}/items", params={"datetime": datetime_value}
    )

    assert resp.status_code == 400, resp.text
    assert "datetime" in resp.json()["detail"].lower()


@pytest.mark.parametrize(
    "datetime_value",
    [
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:00Z/2026-12-31T23:59:59Z",
        "../2026-12-31T00:00:00Z",
        "2026-01-01T00:00:00Z/..",
        "2026-01-01T00:00:00Z/",
        "2016-12-31T23:59:60.1Z/2016-12-31T23:59:60.9Z",
        "2016-12-31T23:59:59.9Z/2016-12-31T23:59:60.1Z",
        "2016-12-31T23:59:59.5Z/2016-12-31T23:59:60Z",
        "2016-12-31T23:59:60Z",
        "1990-12-31T23:59:60Z/..",
        "2017-01-01T00:59:60+01:00",
        "2026-01-01T00:00:00-05:30",
        "2026-02-01",
        "2026-02-01/2026-03-01",
        "2026-02-01/..",
        "../2026-03-01",
        "/2026-12-31T00:00:00+02:00",
    ],
)
async def test_a_valid_datetime_still_returns_every_feature(
    client: AsyncClient, points, datetime_value: str
) -> None:
    resp = await client.get(
        f"/collections/{points.id}/items", params={"datetime": datetime_value}
    )

    assert resp.status_code == 200, resp.text
    assert len(resp.json()["features"]) == 3


async def test_an_omitted_datetime_still_returns_every_feature(
    client: AsyncClient, points
) -> None:
    resp = await client.get(f"/collections/{points.id}/items")

    assert resp.status_code == 200, resp.text
    assert len(resp.json()["features"]) == 3


@pytest.mark.parametrize(
    ("datetime_value", "expected"),
    [
        ("2016-12-31T23:59:60Z", 200),
        ("2016-12-31T23:59:60.1Z/2016-12-31T23:59:60.9Z", 200),
        ("2016-12-31T23:59:60.9Z/2016-12-31T23:59:60.1Z", 400),
        ("2026-01-01T24:00:00Z", 400),
        ("2026-01-01T00:00:00Z/2026-01-01T24:00:00Z", 400),
        ("2016-12-31T23:59:59.9Z/2016-12-31T23:59:60.1Z", 200),
        ("2016-12-31T23:59:60.1Z/2016-12-31T23:59:59.9Z", 400),
        ("2026-01-01T00:00:00-05:30/..", 200),
        ("2026-01-01T00:00:00+01:60", 400),
    ],
)
async def test_stac_search_shares_the_leap_second_and_offset_rules(
    client: AsyncClient, datetime_value: str, expected: int
) -> None:
    resp = await client.get("/stac/search", params={"datetime": datetime_value})

    assert resp.status_code == expected, resp.text
