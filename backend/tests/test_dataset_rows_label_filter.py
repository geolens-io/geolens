"""The rows filter matches a coded column by the label users see.

Requires the Docker test database.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.modules.catalog.datasets.domain.models import AttributeMetadata

from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio

LABELS = {"1": "Hospital", "2": None, "3": "Shelter", "13": "Fire Shelter Annex"}
# (kind, name) inserted in this order, so gid 1..4 follows the list. kind_codes
# holds "c-<name>"; its name is the label filter's old bind name for kind.
ROWS = [(1, "north"), (3, "south"), (13, "east"), (2, "west")]


@pytest.fixture
async def coded_dataset(test_db_session):
    table = f"test_rows_label_{uuid.uuid4().hex[:8]}"
    await test_db_session.execute(
        text(
            f"CREATE TABLE data.{table} (gid serial PRIMARY KEY, kind integer, kind_codes text, depth double precision, ratio real, name text)"
        )
    )
    for kind, name in ROWS:
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table} (kind, kind_codes, name) VALUES (:k, :c, :n)"
            ).bindparams(k=kind, c=f"c-{name}", n=name)
        )
    # PostgreSQL reads 1e16 back as "1e+16"; its label key has every digit.
    await test_db_session.execute(
        text(
            f"UPDATE data.{table} SET depth = CASE WHEN gid = 1 THEN 1e16 ELSE 0.5 END,"
            " ratio = CASE WHEN gid = 1 THEN 0.5 ELSE 0.25 END"
        )
    )
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(
        test_db_session,
        created_by=admin_id,
        name="Coded Rows Dataset",
        table_name=table,
        visibility="public",
        column_info=[
            {"name": "gid", "type": "integer"},
            {"name": "kind", "type": "integer"},
            {"name": "kind_codes", "type": "text"},
            {"name": "depth", "type": "double precision"},
            {"name": "ratio", "type": "real"},
            {"name": "name", "type": "text"},
        ],
    )
    test_db_session.add(
        AttributeMetadata(
            dataset_id=ds.id,
            field_name="kind",
            data_type="integer",
            value_labels=LABELS,
        )
    )
    test_db_session.add(
        AttributeMetadata(
            dataset_id=ds.id,
            field_name="depth",
            data_type="double precision",
            # Python reads the Arabic-Indic digit as 1; PostgreSQL refuses it.
            value_labels={
                "10000000000000000": "Deep",
                "n/a": "Deep, unknown",
                "\u0661": "Deep, written as \u0661",
            },
        )
    )
    test_db_session.add(
        AttributeMetadata(
            dataset_id=ds.id,
            field_name="ratio",
            data_type="real",
            # 1e40 overflows real, so casting it would fail the request.
            value_labels={"0.5": "Half", "1e40": "Huge ratio"},
        )
    )
    # Labels cleared from a column are stored as JSON null.
    test_db_session.add(
        AttributeMetadata(
            dataset_id=ds.id, field_name="name", data_type="text", value_labels=None
        )
    )
    await test_db_session.commit()

    yield ds

    await test_db_session.execute(
        text(
            "DELETE FROM catalog.records WHERE id IN "
            "(SELECT record_id FROM catalog.datasets WHERE table_name = :t)"
        ).bindparams(t=table)
    )
    await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table}"))
    await test_db_session.commit()


@pytest.mark.parametrize(
    ("column", "term", "expected"),
    [
        ("kind", "shelter", ["south", "east"]),
        # A code still matches as text: "3" is a substring of codes 3 and 13.
        ("kind", "3", ["south", "east"]),
        ("kind", "2", ["west"]),
        # A null label is no label, not the text "None".
        ("kind", "none", []),
        # Another column's labels never match.
        ("name", "shelter", []),
        ("name", "OR", ["north"]),
        # Matched as a number; the code that isn't one is dropped, not an error.
        ("depth", "deep", ["north"]),
        ("ratio", "half", ["north"]),
        ("ratio", "huge", []),
    ],
)
async def test_rows_filter_matches_codes_and_their_labels(
    client: AsyncClient, admin_auth_header: dict, coded_dataset, column, term, expected
):
    resp = await client.get(
        f"/datasets/{coded_dataset.id}/rows/",
        params={f"filter[{column}]": term},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    assert [r["name"] for r in resp.json()["rows"]] == expected


async def test_label_codes_and_a_column_named_like_them_filter_together(
    client: AsyncClient, admin_auth_header: dict, coded_dataset
):
    resp = await client.get(
        f"/datasets/{coded_dataset.id}/rows/",
        params={"filter[kind]": "shelter", "filter[kind_codes]": "c-s"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    assert [r["name"] for r in resp.json()["rows"]] == ["south"]
