"""GET /services/databases/{connection}/tables/ and the capabilities listing."""

import json
import secrets

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.config_database_sources import DatabaseConnection
from app.platform import database_sources

PASSWORD = secrets.token_hex(16)
HOST = "gis-sql.corp.example"
USERNAME = "geolens_reader"


@pytest.fixture
def configured(monkeypatch):
    connection = DatabaseConnection.model_validate(
        {
            "engine": "sqlserver",
            "host": HOST,
            "database": "GIS",
            "username": USERNAME,
            "password": PASSWORD,
        }
    )
    monkeypatch.setattr(settings, "database_sources", {"gis": connection})


class _Proc:
    def __init__(self, stdout=b"", stderr=b"", returncode=0):
        self._out = (stdout, stderr)
        self._rc = returncode
        self.returncode = None

    async def communicate(self):
        self.returncode = self._rc
        return self._out


def _features(rows) -> bytes:
    return json.dumps(
        {"layers": [{"features": [{"properties": row} for row in rows]}]}
    ).encode()


class _Spawns(list):
    """Queued subprocess answers, plus the argv of every spawn."""

    def __init__(self) -> None:
        super().__init__()
        self.spawned: list[tuple] = []


@pytest.fixture
def replies(monkeypatch) -> _Spawns:
    spawns = _Spawns()

    async def _fake(*argv, **_kwargs):
        spawns.spawned.append(argv)
        return spawns.pop(0)

    monkeypatch.setattr(database_sources.asyncio, "create_subprocess_exec", _fake)
    return spawns


URL = "/services/databases/gis/tables/"


@pytest.mark.anyio
async def test_lists_spatial_columns(
    client: AsyncClient, editor_auth_header: dict, configured, replies
):
    replies.append(
        _Proc(
            stdout=_features(
                [
                    {
                        "schema_name": "dbo",
                        "object_name": "a]b",
                        "object_type": "U ",
                        "column_name": "shape",
                        "type_name": "geometry",
                    },
                    {
                        "schema_name": "gis",
                        "object_name": "v_roads",
                        "object_type": "V ",
                        "column_name": "geog",
                        "type_name": "geography",
                    },
                ]
            )
        )
    )
    replies.append(
        _Proc(stdout=_features([{"i": 0, "srid": 2263}, {"i": 1, "srid": 0}]))
    )

    resp = await client.get(URL, headers=editor_auth_header)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "connection": "gis",
        "database": "GIS",
        "limit": database_sources.LISTING_LIMIT,
        "truncated": False,
        "tables": [
            {
                "schema_name": "dbo",
                "table_name": "a]b",
                "object_type": "table",
                "geometry_column": "shape",
                "column_type": "geometry",
                "srid": 2263,
            },
            {
                "schema_name": "gis",
                "table_name": "v_roads",
                "object_type": "view",
                "geometry_column": "geog",
                "column_type": "geography",
                "srid": None,
            },
        ],
    }
    assert HOST not in resp.text and USERNAME not in resp.text


@pytest.mark.anyio
async def test_no_trailing_slash_alias(
    client: AsyncClient, editor_auth_header: dict, configured, replies
):
    replies.append(_Proc(stdout=_features([])))
    resp = await client.get(URL.rstrip("/"), headers=editor_auth_header)
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_requires_create_layers(
    client: AsyncClient, viewer_auth_header: dict, configured, replies
):
    resp = await client.get(URL, headers=viewer_auth_header)
    assert resp.status_code == 403
    assert replies.spawned == []


@pytest.mark.anyio
async def test_requires_authentication(client: AsyncClient, configured, replies):
    resp = await client.get(URL)
    assert resp.status_code in (401, 403)
    assert replies.spawned == []


@pytest.mark.anyio
async def test_unknown_connection_is_404(
    client: AsyncClient, editor_auth_header: dict, configured, replies
):
    resp = await client.get(
        "/services/databases/other/tables/", headers=editor_auth_header
    )
    assert resp.status_code == 404
    assert replies.spawned == []


@pytest.mark.anyio
async def test_no_connections_configured_is_404(
    client: AsyncClient, editor_auth_header: dict, monkeypatch, replies
):
    monkeypatch.setattr(settings, "database_sources", {})
    resp = await client.get(URL, headers=editor_auth_header)
    assert resp.status_code == 404


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        (
            "ERROR 1: Unable to initialize connection to the server for "
            "MSSQL:Driver=FreeTDS;Servername=geolens;Database=GIS,\n",
            "Couldn't connect or sign in to the database connection 'gis'.",
        ),
        (
            "ERROR 1: [37000][FreeTDS][SQL Server]Invalid object name\n",
            "A table in the database connection 'gis' was not found or is not "
            "readable.",
        ),
    ],
)
async def test_gdal_failures_are_502_naming_only_the_connection(
    client: AsyncClient, editor_auth_header: dict, configured, replies, stderr, expected
):
    replies.append(
        _Proc(
            stderr=(
                f"ODBC: SQLDriverConnect(Server={HOST};UID={USERNAME};PWD={PASSWORD})\n"
                + stderr
            ).encode(),
            returncode=1,
        )
    )
    resp = await client.get(URL, headers=editor_auth_header)
    assert resp.status_code == 502
    assert resp.json()["detail"] == expected
    for leaked in (HOST, USERNAME, PASSWORD, "MSSQL:"):
        assert leaked not in resp.text


@pytest.mark.anyio
async def test_capabilities_lists_connections_to_dataset_creators(
    client: AsyncClient, editor_auth_header: dict, configured
):
    body = (await client.get("/capabilities/", headers=editor_auth_header)).json()
    assert body["me"]["database_connections"] == [{"name": "gis", "database": "GIS"}]
    text = json.dumps(body)
    assert HOST not in text and USERNAME not in text and PASSWORD not in text


@pytest.mark.anyio
async def test_capabilities_hides_connections_from_viewers(
    client: AsyncClient, viewer_auth_header: dict, configured
):
    body = (await client.get("/capabilities/", headers=viewer_auth_header)).json()
    assert body["me"]["database_connections"] == []


@pytest.mark.anyio
async def test_capabilities_is_empty_without_connections(
    client: AsyncClient, editor_auth_header: dict, monkeypatch
):
    monkeypatch.setattr(settings, "database_sources", {})
    body = (await client.get("/capabilities/", headers=editor_auth_header)).json()
    assert body["me"]["database_connections"] == []
