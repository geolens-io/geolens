"""Vector and cluster tiles for a table whose attribute column has capitals.

Registered tables and service imports keep upstream casing, so a column can
be stored as ``"Zone"``. PostgreSQL folds an unquoted identifier to
lowercase, so the tile query has to quote it to reach the column, and the
MVT property has to keep the stored name for styles and filters that
reference it.
"""

import math
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset, Record

from tests.factories import get_user_id

# Fixtures from test_tiles.py, including _init_tile_pool_for_tests.
pytest_plugins = ["tests.test_tiles"]

pytestmark = pytest.mark.usefixtures("_init_tile_pool_for_tests")

_LON, _LAT = 0.1, 0.1


def _tile_xy(z: int) -> tuple[int, int]:
    n = 2**z
    lat = math.radians(_LAT)
    x = int((_LON + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat)) / math.pi) / 2.0 * n)
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


def _keys_and_strings(tile: bytes) -> tuple[set[str], set[str]]:
    """Property names and string values across every layer of an MVT."""
    keys: set[str] = set()
    strings: set[str] = set()
    for field, layer in _fields(tile):
        if field != 3:
            continue
        for layer_field, value in _fields(layer):
            if layer_field == 3:
                keys.add(value.decode())
            elif layer_field == 4:
                strings.update(v.decode() for f, v in _fields(value) if f == 1)
    return keys, strings


@pytest.fixture
async def mixed_case_table(test_db_session):
    table_name = f"mixed_case_{uuid.uuid4().hex[:8]}"
    user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
    await test_db_session.execute(
        text(
            f"CREATE TABLE data.{table_name} ("
            f'  gid SERIAL PRIMARY KEY, "Zone" TEXT, name TEXT,'
            f"  geom_4326 GEOMETRY(Point, 4326))"
        )
    )
    await test_db_session.execute(
        text(
            f'INSERT INTO data.{table_name} ("Zone", name, geom_4326) VALUES '  # noqa: S608
            f"('north', 'a', ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))"
        ),
        {"lon": _LON, "lat": _LAT},
    )
    record = Record(
        title="Mixed case tile test",
        visibility="public",
        record_status="published",
        created_by=user_id,
    )
    test_db_session.add(record)
    await test_db_session.flush()
    test_db_session.add(
        Dataset(
            record_id=record.id,
            table_name=table_name,
            srid=4326,
            geometry_type="Point",
            feature_count=1,
            source_format="geojson",
            source_filename="test.geojson",
            column_info=[
                {"name": "gid", "type": "integer"},
                {"name": "Zone", "type": "text"},
                {"name": "name", "type": "text"},
                {"name": "geom_4326", "type": "geometry"},
            ],
        )
    )
    await test_db_session.commit()
    yield table_name
    await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table_name}"))
    await test_db_session.commit()


async def _tile(client: AsyncClient, path: str) -> tuple[set[str], set[str]]:
    resp = await client.get(path)
    assert resp.status_code == 200, resp.text
    return _keys_and_strings(resp.content)


async def test_vector_tile_projects_mixed_case_column(
    client: AsyncClient, mixed_case_table: str
):
    x, y = _tile_xy(10)
    keys, strings = await _tile(
        client, f"/tiles/data.{mixed_case_table}/10/{x}/{y}.pbf"
    )
    assert {"Zone", "name"} <= keys
    assert "zone" not in keys
    assert "north" in strings


async def test_vector_tile_cols_opt_in_names_mixed_case_column(
    client: AsyncClient, mixed_case_table: str
):
    x, y = _tile_xy(5)
    keys, strings = await _tile(
        client, f"/tiles/data.{mixed_case_table}/5/{x}/{y}.pbf?cols=Zone"
    )
    assert keys == {"Zone"}
    assert "north" in strings


async def test_cluster_tile_projects_mixed_case_column(
    client: AsyncClient, mixed_case_table: str
):
    x, y = _tile_xy(15)
    keys, strings = await _tile(
        client, f"/tiles/clusters/data.{mixed_case_table}/15/{x}/{y}.pbf"
    )
    assert "Zone" in keys
    assert "zone" not in keys
    assert "north" in strings
