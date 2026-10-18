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
            "tags json[], loc point, seen date, doc jsonb, geom geometry(Point, 4326))"
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
            # information_schema reports json[] as ARRAY, hiding the element type.
            {"name": "tags", "type": "ARRAY"},
            {"name": "loc", "type": "point"},
            {"name": "seen", "type": "date"},
            {"name": "doc", "type": "jsonb"},
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


@pytest.mark.parametrize(
    "column", ["nope", "geom", "meta", "doc", "tags", "loc", 'value" desc --']
)
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


async def test_sortable_columns_are_exactly_the_accepted_sorts(
    client: AsyncClient, admin_auth_header: dict, sort_dataset
):
    url = f"/datasets/{sort_dataset.id}/rows/"
    listed = (await client.get(url, headers=admin_auth_header)).json()[
        "sortable_columns"
    ]
    assert listed == ["gid", "name", "value", "seen"]
    for column in [*listed, "meta", "doc", "tags", "loc", "geom"]:
        resp = await client.get(url, params={"sort": column}, headers=admin_auth_header)
        assert (resp.status_code == 200) == (column in listed), column


async def test_page_after_a_deleted_cursor_row_is_empty(
    client: AsyncClient, admin_auth_header: dict, sort_dataset, test_db_session
):
    url = f"/datasets/{sort_dataset.id}/rows/"
    # The cursor row (c, gid 3) sorts before a NULL row with a higher gid (e).
    params = {"limit": 1, "sort": "value"}
    first = (await client.get(url, params=params, headers=admin_auth_header)).json()
    await test_db_session.execute(
        text(f"DELETE FROM data.{sort_dataset.table_name} WHERE gid = :g").bindparams(
            g=first["next_cursor"]
        )
    )
    await test_db_session.commit()
    resp = await client.get(
        url, params={**params, "after": first["next_cursor"]}, headers=admin_auth_header
    )
    assert resp.status_code == 200
    assert resp.json()["rows"] == []
    assert resp.json()["next_cursor"] is None


# (column, information_schema data_type, SQL type, four values; NULL included)
TYPED_COLUMNS = [
    ("iv", "interval", "interval", ["1 day", "2 hours", None, "1 day"]),
    ("ip", "inet", "inet", ["10.0.0.2", "10.0.0.1", None, "10.0.0.2"]),
    ("cd", "cidr", "cidr", ["10.1.0.0/16", "10.0.0.0/8", None, "10.1.0.0/16"]),
    (
        "u",
        "uuid",
        "uuid",
        [
            "00000000-0000-0000-0000-000000000002",
            "00000000-0000-0000-0000-000000000001",
            None,
            "00000000-0000-0000-0000-000000000002",
        ],
    ),
    ("by", "bytea", "bytea", ["\\x02", "\\x01", None, "\\x02"]),
    ("nm", "numeric", "numeric", ["2.5", "1.25", None, "2.5"]),
    ("ch", "character", "character(2)", ["b", "a", None, "b"]),
    ("bo", "boolean", "boolean", ["true", "false", None, "true"]),
    ("rl", "real", "real", ["2.5", "1.5", None, "2.5"]),
    ("dt", "date", "date", ["2024-02-01", "2024-01-01", None, "2024-02-01"]),
    ("tm", "time without time zone", "time", ["12:00", "08:00", None, "12:00"]),
    (
        "ttz",
        "time with time zone",
        "timetz",
        ["12:00+00", "08:00+00", None, "12:00+00"],
    ),
    (
        "ts",
        "timestamp with time zone",
        "timestamptz",
        ["2024-02-01 00:00+00", "2024-01-01 00:00+00", None, "2024-02-01 00:00+00"],
    ),
]


@pytest.fixture
async def typed_dataset(test_db_session):
    table = f"test_rows_types_{uuid.uuid4().hex[:8]}"
    cols = ", ".join(f"{name} {sql_type}" for name, _, sql_type, _ in TYPED_COLUMNS)
    await test_db_session.execute(
        text(f"CREATE TABLE data.{table} (gid serial PRIMARY KEY, {cols})")
    )
    names = ", ".join(name for name, *_ in TYPED_COLUMNS)
    for i in range(4):
        casts = ", ".join(
            f"CAST(:{name} AS {sql_type})" for name, _, sql_type, _ in TYPED_COLUMNS
        )
        await test_db_session.execute(
            text(f"INSERT INTO data.{table} ({names}) VALUES ({casts})").bindparams(
                **{name: values[i] for name, _, _, values in TYPED_COLUMNS}
            )
        )
    await test_db_session.commit()

    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(
        test_db_session,
        created_by=admin_id,
        name="Typed Rows Dataset",
        table_name=table,
        visibility="public",
        column_info=[
            {"name": "gid", "type": "integer"},
            *({"name": name, "type": dtype} for name, dtype, _, _ in TYPED_COLUMNS),
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


@pytest.mark.parametrize("order", ["asc", "desc"])
@pytest.mark.parametrize("column", [name for name, *_ in TYPED_COLUMNS])
async def test_each_sortable_type_binds_back_as_the_next_page_anchor(
    client: AsyncClient,
    admin_auth_header: dict,
    typed_dataset,
    test_db_session,
    column,
    order,
):
    """One-row pages make every row's value the anchor the next page binds."""
    direction = "DESC" if order == "desc" else "ASC"
    expected = (
        (
            await test_db_session.execute(
                text(
                    f"SELECT gid FROM data.{typed_dataset.table_name} "
                    f"ORDER BY {column} {direction} NULLS LAST, gid"
                )
            )
        )
        .scalars()
        .all()
    )

    gids: list[int] = []
    after = 0
    for _ in range(len(expected) + 1):
        resp = await client.get(
            f"/datasets/{typed_dataset.id}/rows/",
            params={"limit": 1, "after": after, "sort": column, "order": order},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        gids.extend(r["gid"] for r in data["rows"])
        if data["next_cursor"] is None:
            break
        after = data["next_cursor"]
    assert gids == expected
