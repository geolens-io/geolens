"""Vector tiles write timestamptz properties as UTC text.

The map compares a filter value with the text in the tile, and analysis
compares the same filter in SQL. Both only keep the same features when the
tile text is fixed: independent of the database session's TimeZone, and in
an order that matches time order across a daylight-saving change.
"""

import importlib.util
import math
import uuid
from pathlib import Path

import asyncpg
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.processing.tiles.pool as pool_module
from app.processing.tiles.service import _utc_timestamptz_text
from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset

from tests.factories import get_user_id
from tests.test_analysis_spatial_join import _create_layer

pytestmark = pytest.mark.anyio

_LAT = 0.001

# 2024-11-03 in New York: 05:30Z is 01:30-04 and 06:15Z is 01:15-05, so the
# session-local text of this pair sorts in the reverse of time order.
_ROWS = {
    1: ("'2024-11-03 05:30+00'", "'2024-11-03 05:30'"),
    2: ("'2024-11-03 06:15+00'", "'2024-11-03 06:15'"),
    3: ("'2024-11-03 06:15:00.5+00'", "'2024-11-03 06:15:00.5'"),
    4: ("NULL", "NULL"),
}
_UTC_TEXT = {
    1: "2024-11-03T05:30:00+00:00",
    2: "2024-11-03T06:15:00+00:00",
    3: "2024-11-03T06:15:00.5+00:00",
}


def _tile_xy(z: int) -> tuple[int, int]:
    n = 2**z
    lon = 0.003
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(_LAT))) / math.pi) / 2.0 * n)
    return x, y


def _varint(buf: bytes, i: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        byte = buf[i]
        i += 1
        result |= (byte & 0x7F) << shift
        if byte < 0x80:
            return result, i
        shift += 7


def _fields(buf: bytes):
    i = 0
    while i < len(buf):
        key, i = _varint(buf, i)
        field, wire = key >> 3, key & 7
        if wire == 0:
            value, i = _varint(buf, i)
        elif wire == 2:
            size, i = _varint(buf, i)
            value, i = buf[i : i + size], i + size
        elif wire == 5:
            value, i = buf[i : i + 4], i + 4
        elif wire == 1:
            value, i = buf[i : i + 8], i + 8
        else:
            raise ValueError(f"unsupported wire type {wire}")
        yield field, value


def _packed(buf: bytes) -> list[int]:
    out, i = [], 0
    while i < len(buf):
        value, i = _varint(buf, i)
        out.append(value)
    return out


def _string_properties(tile: bytes, id_key: str) -> list[dict[str, str | int]]:
    """Each feature's string properties, plus its id under ``id_key``."""
    features = []
    for field, layer in _fields(tile):
        if field != 3:
            continue
        keys, values, raw = [], [], []
        for layer_field, value in _fields(layer):
            if layer_field == 2:
                raw.append(value)
            elif layer_field == 3:
                keys.append(value.decode())
            elif layer_field == 4:
                strings = [v.decode() for f, v in _fields(value) if f == 1]
                values.append(strings[0] if strings else None)
        for feature in raw:
            props: dict[str, str | int] = {}
            for f, v in _fields(feature):
                if f == 1:
                    props[id_key] = v
                elif f == 2:
                    tags = _packed(v)
                    for k, val in zip(tags[::2], tags[1::2], strict=True):
                        if values[val] is not None:
                            props[keys[k]] = values[val]
            features.append(props)
    return features


@pytest.fixture
async def new_york_tile_pool():
    """The tile pool, with sessions in a zone that observes daylight saving."""
    dsn = settings.test_database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(
        dsn=dsn,
        min_size=1,
        max_size=2,
        command_timeout=10,
        server_settings={"timezone": "America/New_York"},
    )
    pool_module._tile_pool = pool
    yield
    await pool.close()
    pool_module._tile_pool = None


async def _create_timestamps(session: AsyncSession):
    admin_id = await get_user_id(session, settings.geolens_admin_username)
    rows = ", ".join(
        f"('p{gid}', {atz}, {at}, ST_SetSRID(ST_MakePoint({gid * 0.001}, {_LAT}), 4326),"
        f" ST_SetSRID(ST_MakePoint({gid * 0.001}, {_LAT}), 4326))"
        for gid, (atz, at) in _ROWS.items()
    )
    return await _create_layer(
        session,
        created_by=admin_id,
        column_type="Point",
        geometry_type="POINT",
        extra_columns="atz TIMESTAMPTZ, at TIMESTAMP,",
        column_info=[
            {"name": "name", "type": "text"},
            {"name": "atz", "type": "timestamp with time zone"},
            {"name": "at", "type": "timestamp without time zone"},
        ],
        feature_count=len(_ROWS),
        values_sql=rows,
    )


async def _tile_atz(client: AsyncClient, path: str, id_key: str) -> dict[int, str]:
    resp = await client.get(path)
    assert resp.status_code == 200, resp.text
    return {
        int(props[id_key]): props["atz"]
        for props in _string_properties(resp.content, id_key)
        if "atz" in props
    }


@pytest.mark.usefixtures("new_york_tile_pool")
async def test_vector_tile_writes_timestamptz_as_utc(
    client: AsyncClient, test_db_session: AsyncSession
):
    dataset = await _create_timestamps(test_db_session)
    x, y = _tile_xy(10)

    resp = await client.get(f"/tiles/data.{dataset.table_name}/10/{x}/{y}.pbf")

    assert resp.status_code == 200, resp.text
    features = {int(p["gid"]): p for p in _string_properties(resp.content, "gid")}
    assert {gid: p.get("atz") for gid, p in features.items()} == {
        **_UTC_TEXT,
        4: None,
    }
    # A plain timestamp keeps PostgreSQL's text form.
    assert features[1]["at"] == "2024-11-03 05:30:00"
    assert features[3]["at"] == "2024-11-03 06:15:00.5"


@pytest.mark.usefixtures("new_york_tile_pool")
async def test_cluster_tile_writes_timestamptz_as_utc(
    client: AsyncClient, test_db_session: AsyncSession
):
    dataset = await _create_timestamps(test_db_session)
    x, y = _tile_xy(15)

    by_gid = await _tile_atz(
        client, f"/tiles/clusters/data.{dataset.table_name}/15/{x}/{y}.pbf", "fid"
    )

    assert sorted(by_gid.values()) == sorted(_UTC_TEXT.values())


@pytest.mark.usefixtures("new_york_tile_pool")
@pytest.mark.parametrize("op", ["<", "<=", "=", ">", ">="])
@pytest.mark.parametrize(
    "literal", ["2024-11-03T06:15:00+00:00", "2024-11-03T05:45:00+00:00"]
)
async def test_analysis_keeps_the_features_the_map_filter_keeps(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    op: str,
    literal: str,
):
    dataset = await _create_timestamps(test_db_session)
    x, y = _tile_xy(10)
    tile_text = await _tile_atz(
        client, f"/tiles/data.{dataset.table_name}/10/{x}/{y}.pbf", "gid"
    )
    # MapLibre compares two strings by code unit, as Python does for ASCII.
    compare = {
        "<": str.__lt__,
        "<=": str.__le__,
        "=": str.__eq__,
        ">": str.__gt__,
        ">=": str.__ge__,
    }[op]
    on_map = sorted(gid for gid, value in tile_text.items() if compare(value, literal))

    # The builder sends the tile's text with the offset written as Z.
    timestamp = literal.removesuffix("+00:00") + "Z"
    resp = await client.post(
        f"/datasets/{dataset.id}/analysis/preview/",
        json={
            "operation": "centroid",
            "filter": {
                "op": op,
                "args": [{"property": "atz"}, {"timestamp": timestamp}],
            },
        },
        headers=admin_auth_header,
    )

    assert resp.status_code == 200, resp.text
    analysed = sorted(
        f["properties"]["gid"] for f in resp.json()["geojson"]["features"]
    )
    assert analysed == on_map


@pytest.mark.usefixtures("new_york_tile_pool")
async def test_tile_text_orders_every_value_like_time_against_a_filter_literal(
    test_db_session: AsyncSession,
):
    values = [
        "-infinity",
        "0044-03-15 12:00:00.5Z BC",
        "0001-12-31 23:00Z BC",
        "0001-01-01 00:00Z",
        "2024-11-03 05:30Z",
        "2024-11-03 06:15Z",
        "2024-11-03 06:15:00.5Z",
        "9999-12-31 23:59:59.999999Z",
        "10000-01-01 00:00Z",
        "infinity",
    ]
    # A filter literal the builder accepts: years 1 to 9999.
    literals = [
        "0001-01-01 00:00Z",
        "0044-03-15 12:00Z",
        "2024-11-03 06:15Z",
        "9999-12-31 23:59:59.999999Z",
    ]
    as_text = _utc_timestamptz_text
    async with pool_module._tile_pool.acquire() as conn:
        rendered = dict(
            await conn.fetch(
                f"SELECT s, {as_text('s::timestamptz')} FROM unnest($1::text[]) s",
                values,
            )
        )
        pairs = await conn.fetch(
            f"SELECT v, l, v::timestamptz < l::timestamptz AS before,"
            f" v::timestamptz = l::timestamptz AS same,"
            f" {as_text('v::timestamptz')} AS vt, {as_text('l::timestamptz')} AS lt"
            " FROM unnest($1::text[]) v, unnest($2::text[]) l",
            values,
            literals,
        )

    assert rendered["0044-03-15 12:00:00.5Z BC"] == "-0043-03-15T12:00:00.5+00:00"
    assert rendered["10000-01-01 00:00Z"] == "infinity"
    assert len(pairs) == len(values) * len(literals)
    for row in pairs:
        assert (row["vt"] < row["lt"]) == row["before"], (row["vt"], row["lt"])
        assert (row["vt"] == row["lt"]) == row["same"], (row["vt"], row["lt"])


async def test_migration_rolls_only_timestamptz_datasets(
    test_db_session: AsyncSession,
):
    path = (
        Path(__file__).parents[1] / "alembic/versions/0080_timestamptz_tile_text_utc.py"
    )
    spec = importlib.util.spec_from_file_location("timestamptz_tile_text", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    session = test_db_session
    with_tz = await _create_timestamps(session)
    admin_id = await get_user_id(session, settings.geolens_admin_username)
    without_tz = await _create_layer(
        session,
        created_by=admin_id,
        column_type="Point",
        geometry_type="POINT",
        extra_columns="at TIMESTAMP,",
        column_info=[{"name": "at", "type": "timestamp without time zone"}],
        values_sql=(
            "('p', '2024-01-01', ST_SetSRID(ST_MakePoint(0, 0), 4326),"
            " ST_SetSRID(ST_MakePoint(0, 0), 4326))"
        ),
    )

    async def versions() -> dict[uuid.UUID, int]:
        rows = await session.execute(
            select(Dataset.id, Dataset.tile_cache_version).where(
                Dataset.id.in_([with_tz.id, without_tz.id])
            )
        )
        return dict(rows.tuples().all())

    before = await versions()

    def upgrade(sync_session):
        with Operations.context(MigrationContext.configure(sync_session.connection())):
            migration.upgrade()

    await session.run_sync(upgrade)

    after = await versions()
    assert after[with_tz.id] == before[with_tz.id] + 1
    assert after[without_tz.id] == before[without_tz.id]
