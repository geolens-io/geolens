"""Sorted reads of GET /datasets/{id}/rows/ stay globally ordered across pages.

The table holds duplicate and NULL sort values, so page boundaries fall
inside a run of equal values and inside the NULL tail. Requires the Docker
test database.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio

# (name, value) inserted in this order, so gid 1..7 follows the list.
ROWS = [
    ("a", 3),
    ("b", None),
    ("c", 1),
    ("d", 3),
    ("e", None),
    ("f", 2),
    ("g", 1),
]
ASC = ["c", "g", "f", "a", "d", "b", "e"]
DESC = ["a", "d", "f", "c", "g", "b", "e"]


@pytest.fixture
async def sort_dataset(test_db_session):
    table = f"test_rows_sort_{uuid.uuid4().hex[:8]}"
    await test_db_session.execute(
        text(
            f"CREATE TABLE data.{table} "
            "(gid serial PRIMARY KEY, name text, value integer, meta json, "
            "geom geometry(Point, 4326))"
        )
    )
    for name, value in ROWS:
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table} (name, value, meta) "
                "VALUES (:name, :value, '{}')"
            ).bindparams(name=name, value=value)
        )
    await test_db_session.commit()

    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(
        test_db_session,
        created_by=admin_id,
        name="Sorted Rows Dataset",
        table_name=table,
        visibility="public",
        column_info=[
            {"name": "gid", "type": "integer"},
            {"name": "name", "type": "text"},
            {"name": "value", "type": "integer"},
            {"name": "meta", "type": "json"},
            {"name": "geom", "type": "USER-DEFINED"},
        ],
    )

    yield ds

    await test_db_session.execute(
        text(
            "DELETE FROM catalog.records WHERE id IN "
            "(SELECT record_id FROM catalog.datasets WHERE table_name = :t)"
        ).bindparams(t=table)
    )
    await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table}"))
    await test_db_session.commit()


async def _walk(client: AsyncClient, ds, headers, **params) -> list[str]:
    """Follow next_cursor from the first page to the end; return names in order."""
    names: list[str] = []
    after = 0
    for _ in range(len(ROWS) + 1):
        resp = await client.get(
            f"/datasets/{ds.id}/rows/",
            params={"limit": 2, "after": after, **params},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        names.extend(r["name"] for r in data["rows"])
        if data["next_cursor"] is None:
            return names
        after = data["next_cursor"]
    raise AssertionError("pagination did not terminate")


@pytest.mark.parametrize(("order", "expected"), [("asc", ASC), ("desc", DESC)])
async def test_sorted_pages_are_globally_ordered(
    client: AsyncClient, admin_auth_header: dict, sort_dataset, order, expected
):
    names = await _walk(
        client, sort_dataset, admin_auth_header, sort="value", order=order
    )
    assert names == expected


async def test_sorted_pages_respect_filters(
    client: AsyncClient, admin_auth_header: dict, sort_dataset
):
    names = await _walk(
        client,
        sort_dataset,
        admin_auth_header,
        sort="name",
        order="desc",
        **{"filter[value]": "1"},
    )
    assert names == ["g", "c"]


@pytest.mark.parametrize("column", ["nope", "geom", "meta", 'value" desc --'])
async def test_unknown_or_unsortable_column_is_rejected(
    client: AsyncClient, admin_auth_header: dict, sort_dataset, column
):
    resp = await client.get(
        f"/datasets/{sort_dataset.id}/rows/",
        params={"sort": column},
        headers=admin_auth_header,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid sort column"


async def test_invalid_order_is_rejected(
    client: AsyncClient, admin_auth_header: dict, sort_dataset
):
    resp = await client.get(
        f"/datasets/{sort_dataset.id}/rows/",
        params={"sort": "value", "order": "sideways"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422
