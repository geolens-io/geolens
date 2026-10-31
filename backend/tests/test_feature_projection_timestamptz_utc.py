"""Every feature projection writes a timestamptz as UTC text, whatever the session's TimeZone."""

import uuid

import pytest
from sqlalchemy import text

from app.modules.catalog.datasets.domain.service_relationships import (
    _fetch_target_rows,
)
from app.modules.catalog.features.service import (
    get_feature_by_id,
    get_features,
    get_features_geojson_z,
)
from app.standards.ogc.filtering import compile_feature_cql2

_SEEN = {"a": "2024-03-01T17:00:00+00:00", "b": "2024-07-01T04:30:00.25+00:00"}


@pytest.fixture
async def new_york_table(test_db_session):
    """A two-row table, read in a transaction whose TimeZone is America/New_York."""
    table = f"tz_{uuid.uuid4().hex[:10]}"
    point = "ST_SetSRID(ST_MakePoint(1, 2), 4326)"
    await test_db_session.execute(
        text(
            f'CREATE TABLE data."{table}" (gid serial PRIMARY KEY, '
            "geom geometry(Point, 3857), geom_4326 geometry(Point, 4326), "
            "name text, seen timestamptz)"
        )
    )
    await test_db_session.execute(
        text(
            f'INSERT INTO data."{table}" (geom, geom_4326, name, seen) VALUES '
            f"(ST_Transform({point}, 3857), {point}, 'a', '2024-03-01 17:00:00+00'), "
            f"(ST_Transform({point}, 3857), {point}, 'b', '2024-07-01 04:30:00.25+00')"
        )
    )
    await test_db_session.commit()
    # LOCAL ends with the transaction, so the zone cannot outlive the test.
    await test_db_session.execute(text("SET LOCAL TIME ZONE 'America/New_York'"))
    assert (
        await test_db_session.scalar(
            text("SELECT to_jsonb('2024-03-01 17:00:00+00'::timestamptz)")
        )
        == "2024-03-01T12:00:00-05:00"
    )
    try:
        yield table
    finally:
        await test_db_session.rollback()
        await test_db_session.execute(text(f'DROP TABLE IF EXISTS data."{table}"'))
        await test_db_session.commit()


def _seen_by_name(rows: list[dict]) -> dict:
    return {r["properties"]["name"]: r["properties"]["seen"] for r in rows}


async def test_every_projection_writes_utc_text(test_db_session, new_york_table):
    table = new_york_table
    gid_b = await test_db_session.scalar(
        text(f"SELECT gid FROM data.\"{table}\" WHERE name = 'b'")
    )

    page = await get_features(test_db_session, table)
    assert _seen_by_name(page.rows) == _SEEN

    no_geometry = await get_features(test_db_session, table, include_geometry=False)
    assert _seen_by_name(no_geometry.rows) == _SEEN

    one = await get_feature_by_id(test_db_session, table, gid_b)
    assert one is not None and one["properties"]["seen"] == _SEEN["b"]

    rows, _, _ = await get_features_geojson_z(test_db_session, table)
    assert _seen_by_name(rows) == _SEEN

    related = await _fetch_target_rows(test_db_session, table, "name", "b", 10, 0)
    assert [r["seen"] for r in related] == [_SEEN["b"]]


async def test_filters_compare_the_stored_timestamptz(test_db_session, new_york_table):
    """A filter still compares instants, though the projected column is text."""
    table = new_york_table
    cql2_where, cql2_binds = compile_feature_cql2(
        "seen > TIMESTAMP('2024-05-01T00:00:00Z')",
        "cql2-text",
        {"name": "text", "seen": "timestamp with time zone"},
    )
    by_cql2 = await get_features(
        test_db_session, table, cql2_where=cql2_where, cql2_binds=cql2_binds
    )
    assert _seen_by_name(by_cql2.rows) == {"b": _SEEN["b"]}
    assert by_cql2.total == 1

    by_property = await get_features(
        test_db_session,
        table,
        property_filters={"seen": "2024-03-01T12:00:00-05:00"},
        allowed_columns={"seen"},
    )
    assert _seen_by_name(by_property.rows) == {"a": _SEEN["a"]}
