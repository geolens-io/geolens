"""fix(#1778): property filters on non-text columns must work, and must not 503.

`get_features` bound every property-filter value as the raw query-string
string, so SQLAlchemy typed the bind VARCHAR and PostgreSQL had no
`bigint = character varying` operator. Every non-text property filter failed
with 42883, and the OGC items handler classified that as
`503 Dataset table is temporarily unavailable` because its caller-fault branch
was gated on a CQL2 `filter=` being present. Clients retried forever against
what is a query-shape bug, and the Part 3 queryables document advertises those
columns as integer/number/boolean/date, so a conformant client was led
straight into it.

Requires the Docker test database.
"""

import uuid
from datetime import date, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.modules.catalog.datasets.domain.models import Dataset, Record

from tests.factories import get_user_id

pytestmark = pytest.mark.anyio


async def _create_typed_dataset(session, *, created_by: uuid.UUID) -> Dataset:
    """A table with one column per advertised queryable family, plus a uuid.

    ``ref`` (uuid) is deliberately outside the mapped set: it exercises the
    fallback, where the raw string bind still reaches the database and the
    router has to classify the resulting sqlstate.
    """
    table_name = f"test_pf_{uuid.uuid4().hex[:8]}"
    await session.execute(
        text(
            f"CREATE TABLE data.{table_name} ("
            "gid SERIAL PRIMARY KEY, "
            "geom geometry(Point, 4326), "
            "geom_4326 geometry(Point, 4326), "
            "era TEXT, "
            "construction_year INTEGER, "
            "height_roof DOUBLE PRECISION, "
            "ratio REAL, "
            "price NUMERIC(12, 2), "
            "landmark BOOLEAN, "
            "surveyed DATE, "
            "built TIMESTAMP, "
            "ref UUID)"
        )
    )
    await session.execute(text(f"GRANT SELECT ON data.{table_name} TO geolens_reader"))

    rows = [
        ("Art Deco", 1931, 100.0, 0.5, 19.99, True, "1931-05-01", 40.70),
        ("Art Deco", 1931, 100.0, 0.5, 19.99, True, "1931-05-01", 40.71),
        ("Brutalist", 1968, 42.5, 0.25, 20.00, False, "1968-02-02", 40.72),
    ]
    for era, year, height, ratio, price, landmark, surveyed, lat in rows:
        await session.execute(
            text(
                f"INSERT INTO data.{table_name} "
                "(geom, geom_4326, era, construction_year, height_roof, ratio, "
                "price, landmark, surveyed, built, ref) VALUES ("
                "ST_SetSRID(ST_MakePoint(-74.0, :lat), 4326), "
                "ST_SetSRID(ST_MakePoint(-74.0, :lat), 4326), "
                ":era, :year, :height, :ratio, :price, :landmark, :surveyed, "
                ":built, gen_random_uuid())"
            ).bindparams(
                lat=lat,
                era=era,
                year=year,
                height=height,
                ratio=ratio,
                price=price,
                landmark=landmark,
                surveyed=date.fromisoformat(surveyed),
                built=datetime.fromisoformat(f"{surveyed}T09:30:00"),
            )
        )

    record = Record(
        title=f"Property filter types {table_name}",
        summary="Typed property filters",
        theme_category=["test"],
        visibility="public",
        record_status="published",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="POINT",
        feature_count=len(rows),
        column_info=[
            {"name": "era", "type": "text"},
            {"name": "construction_year", "type": "integer"},
            {"name": "height_roof", "type": "double precision"},
            {"name": "ratio", "type": "real"},
            {"name": "price", "type": "numeric"},
            {"name": "landmark", "type": "boolean"},
            {"name": "surveyed", "type": "date"},
            {"name": "built", "type": "timestamp without time zone"},
            {"name": "ref", "type": "uuid"},
        ],
        source_format="created",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


@pytest.fixture
async def typed_dataset(client: AsyncClient, test_db_session):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_typed_dataset(test_db_session, created_by=admin_id)
    yield dataset
    await test_db_session.execute(
        text(f"DROP TABLE IF EXISTS data.{dataset.table_name}")
    )
    await test_db_session.commit()


def _items_url(dataset: Dataset) -> str:
    return f"/collections/{dataset.id}/items"


@pytest.mark.parametrize(
    ("param", "value", "expected"),
    [
        ("era", "Art Deco", 2),
        ("construction_year", "1931", 2),
        ("height_roof", "100", 2),
        ("ratio", "0.5", 2),
        ("price", "19.99", 2),
        ("landmark", "true", 2),
        ("surveyed", "1968-02-02", 1),
        ("built", "1968-02-02T09:30:00", 1),
    ],
)
async def test_ogc_property_filter_matches_on_every_queryable_type(
    client: AsyncClient, typed_dataset: Dataset, param, value, expected
):
    """Each type the queryables document advertises is actually filterable."""
    resp = await client.get(_items_url(typed_dataset), params={param: value})

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["numberMatched"] == expected
    assert data["numberReturned"] == expected


async def test_ogc_property_filter_rejects_an_unparseable_value(
    client: AsyncClient, typed_dataset: Dataset
):
    """A value that is not an integer is the caller's 400, naming the property."""
    resp = await client.get(
        _items_url(typed_dataset), params={"construction_year": "not-a-year"}
    )

    assert resp.status_code == 400
    assert "construction_year" in resp.json()["detail"]


async def test_ogc_property_filter_on_unmapped_type_is_a_400_not_a_503(
    client: AsyncClient, typed_dataset: Dataset
):
    """A uuid column keeps the raw bind; the type-shaped failure is not an outage."""
    resp = await client.get(_items_url(typed_dataset), params={"ref": "1931"})

    assert resp.status_code == 400
    assert "Property filter" in resp.json()["detail"]


async def test_native_features_property_filter_matches_an_integer(
    client: AsyncClient, typed_dataset: Dataset, admin_auth_header
):
    """The native /datasets/{id}/features/ path binds the same way."""
    resp = await client.get(
        f"/datasets/{typed_dataset.id}/features/",
        params={"construction_year": "1931"},
        headers=admin_auth_header,
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["numberMatched"] == 2


async def test_native_features_property_filter_rejects_an_unparseable_value(
    client: AsyncClient, typed_dataset: Dataset, admin_auth_header
):
    resp = await client.get(
        f"/datasets/{typed_dataset.id}/features/",
        params={"construction_year": "not-a-year"},
        headers=admin_auth_header,
    )

    assert resp.status_code == 400
    assert "construction_year" in resp.json()["detail"]


async def test_cql2_filter_fault_message_is_unchanged(
    client: AsyncClient, typed_dataset: Dataset
):
    """Widening the caller-fault gate must not re-label the CQL2 message."""
    resp = await client.get(
        _items_url(typed_dataset),
        params={"filter": "ref = 'not-a-uuid'"},
    )

    assert resp.status_code == 400
    assert "CQL2 filter" in resp.json()["detail"]
