"""FlatGeobuf export with null/empty geometries.

GDAL's FlatGeobuf writer refuses null (and empty) geometries while it builds
the packed spatial index, so the export must drop the index for such tables
and keep it otherwise. These tests run the real ogr2ogr against a real table.
"""

import struct
import subprocess

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from tests.factories import get_user_id
from tests.test_features_crud import _create_test_table_and_dataset

pytestmark = pytest.mark.requires_ogr2ogr


async def _fgb_dataset(session, rows: list[str]):
    admin_id = await get_user_id(session, "admin")
    ds = await _create_test_table_and_dataset(
        session, created_by=admin_id, geometry_type="MultiPoint"
    )
    for geom in rows:
        await session.execute(
            text(f"INSERT INTO data.{ds.table_name} (geom, name) VALUES ({geom}, 'x')")
        )
    await session.commit()
    return ds


async def _export(client, headers, ds, tmp_path):
    resp = await client.get(
        f"/datasets/{ds.id}/export", params={"format": "fgb"}, headers=headers
    )
    path = tmp_path / "out.fgb"
    path.write_bytes(resp.content)
    return resp, path


def _feature_count(path) -> int:
    out = subprocess.run(
        ["ogrinfo", "-so", "-al", str(path)], capture_output=True, text=True
    ).stdout
    return int(
        next(ln for ln in out.splitlines() if "Feature Count" in ln).split(":")[1]
    )


def _index_node_size(path) -> int:
    """Read ``index_node_size`` from the FlatGeobuf header flatbuffer.

    Layout: 8-byte magic, uint32 header size, then the Header table; field 9
    is ``index_node_size`` (default 16, 0 means no packed index).
    """
    data = path.read_bytes()
    root = 12
    table = root + struct.unpack_from("<I", data, root)[0]
    vtable = table - struct.unpack_from("<i", data, table)[0]
    slot = struct.unpack_from("<H", data, vtable + 4 + 2 * 9)[0]
    return struct.unpack_from("<H", data, table + slot)[0] if slot else 16


@pytest.mark.anyio
async def test_empty_and_null_geometries_export_all_rows_without_index(
    client: AsyncClient, admin_auth_header: dict, test_db_session, tmp_path
):
    ds = await _fgb_dataset(
        test_db_session,
        [
            "ST_GeomFromText('MULTIPOINT(1 1)', 4326)",
            "'SRID=4326;MULTIPOINT EMPTY'",
            "NULL",
        ],
    )
    resp, path = await _export(client, admin_auth_header, ds, tmp_path)
    assert resp.status_code == 200, resp.text
    assert _feature_count(path) == 3
    assert _index_node_size(path) == 0


@pytest.mark.anyio
async def test_table_without_null_geometries_keeps_spatial_index(
    client: AsyncClient, admin_auth_header: dict, test_db_session, tmp_path
):
    ds = await _fgb_dataset(
        test_db_session, ["ST_GeomFromText('MULTIPOINT(1 1)', 4326)"]
    )
    resp, path = await _export(client, admin_auth_header, ds, tmp_path)
    assert resp.status_code == 200, resp.text
    assert _feature_count(path) == 1
    assert _index_node_size(path) == 16
