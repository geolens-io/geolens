"""The GDAL side of a database connection: freetds.conf, the child env, the
subprocess, the listing SQL and the redaction of what GDAL prints."""

import asyncio
import json
import os
import secrets
import stat

import pytest
import structlog
import structlog.testing

from app.core.config import settings
from app.core.config_database_sources import DatabaseConnection
from app.core.failure_reason import redact_failure_reason
from app.core.logging_config import _redact_sensitive_fields
from app.core.url_redaction import redact_odbc_credentials
from app.platform import database_sources
from app.platform.database_sources import (
    DatabaseConnectError,
    DatabaseTableError,
    UnknownDatabaseConnectionError,
    database_gdal_source,
    freetds_workdir,
    list_spatial_tables,
    quote_identifier,
    render_freetds_conf,
    run_database_sql,
    srid_probe_sql,
)
from app.platform.gdal_env import (
    _NETWORK_AND_POINTER_DRIVERS,
    gdal_database_safe_env,
    gdal_vector_safe_env,
)

PASSWORD = "pw " + secrets.token_hex(12) + " end"
HOST = "gis-sql.corp.example"
USERNAME = "geolens_reader"


def _connection(**overrides) -> DatabaseConnection:
    return DatabaseConnection.model_validate(
        {
            "engine": "sqlserver",
            "host": HOST,
            "database": "GIS",
            "username": USERNAME,
            "password": PASSWORD,
            **overrides,
        }
    )


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "database_sources", {"gis": _connection()})


# ---------------------------------------------------------------------------
# freetds.conf
# ---------------------------------------------------------------------------


def _conf_lines(connection) -> list[str]:
    return render_freetds_conf(connection).splitlines()


def test_conf_holds_one_section_with_the_server():
    lines = _conf_lines(_connection(port=14330))
    assert lines[0] == "[geolens]"
    assert [line for line in lines if line.startswith("[")] == ["[geolens]"]
    assert f"host = {HOST}" in lines
    assert "port = 14330" in lines
    assert "tds version = 7.4" in lines


def test_conf_verifies_against_the_ca_file():
    lines = _conf_lines(_connection(ca_file="/certs/ca.pem"))
    assert "encryption = require" in lines
    assert "ca file = /certs/ca.pem" in lines


def test_conf_verifies_against_the_system_store_without_a_ca_file():
    # FreeTDS skips verification when `ca file` is absent.
    lines = _conf_lines(_connection())
    assert "ca file = system" in lines


def test_conf_trust_opt_out_drops_only_the_ca_line():
    lines = _conf_lines(_connection(trust_server_certificate=True))
    assert not [line for line in lines if line.startswith("ca file")]
    assert "encryption = require" in lines


def test_conf_encrypt_false_still_verifies_when_tls_is_used():
    lines = _conf_lines(_connection(encrypt=False))
    assert "encryption = request" in lines
    assert "ca file = system" in lines


def test_conf_never_holds_the_login():
    conf = render_freetds_conf(_connection())
    assert PASSWORD not in conf
    assert USERNAME not in conf


def test_workdir_is_private_and_removed():
    with freetds_workdir(_connection()) as workdir:
        conf = os.path.join(workdir, "freetds.conf")
        assert stat.S_IMODE(os.stat(workdir).st_mode) == 0o700
        assert stat.S_IMODE(os.stat(conf).st_mode) == 0o600
    assert not os.path.exists(workdir)


def test_source_names_the_section_never_the_host():
    source = database_gdal_source(_connection())
    assert source == "MSSQL:Driver=FreeTDS;Servername=geolens;Database=GIS"
    assert HOST not in source


# ---------------------------------------------------------------------------
# The child env
# ---------------------------------------------------------------------------


def test_database_env_keeps_only_mssqlspatial(monkeypatch):
    skipped = set(
        gdal_database_safe_env("/x/freetds.conf", USERNAME, PASSWORD)[
            "GDAL_SKIP"
        ].split()
    )
    assert set(_NETWORK_AND_POINTER_DRIVERS) - skipped == {"MSSQLSpatial"}
    assert {"ODBC", "PGeo", "OGR_VRT", "WFS"} <= skipped


def test_upload_and_service_envs_skip_the_database_drivers():
    skipped = set(gdal_vector_safe_env()["GDAL_SKIP"].split())
    assert {"MSSQLSpatial", "ODBC", "PGeo"} <= skipped


def test_database_env_pins_debug_off_and_drops_freetds_overrides(monkeypatch):
    monkeypatch.setenv("CPL_DEBUG", "ON")
    monkeypatch.setenv("TDSDUMP", "/tmp/tds.log")
    monkeypatch.setenv("TDSPORT", "1")
    monkeypatch.setenv("MSSQLSPATIAL_LIST_ALL_TABLES", "YES")
    monkeypatch.setenv("GDAL_CONFIG_FILE", "/home/x/.gdal/gdalrc")
    env = gdal_database_safe_env("/x/freetds.conf", USERNAME, PASSWORD)
    assert env["CPL_DEBUG"] == "OFF"
    assert env["GDAL_CONFIG_FILE"] == os.devnull
    assert "TDSDUMP" not in env
    assert "TDSPORT" not in env
    assert "MSSQLSPATIAL_LIST_ALL_TABLES" not in env
    assert env["MSSQLSPATIAL_USE_GEOMETRY_COLUMNS"] == "NO"
    assert env["FREETDSCONF"] == "/x/freetds.conf"
    assert env["MSSQLSPATIAL_UID"] == USERNAME
    assert env["MSSQLSPATIAL_PWD"] == PASSWORD


# ---------------------------------------------------------------------------
# The subprocess
# ---------------------------------------------------------------------------


class _Proc:
    def __init__(self, stdout=b"", stderr=b"", returncode=0, hang=False):
        self._out = (stdout, stderr)
        self._rc = returncode
        self._hang = hang
        self.returncode = None
        self.killed = False

    async def communicate(self):
        if self._hang:
            await asyncio.sleep(3600)
        self.returncode = self._rc
        return self._out

    def kill(self):
        self.killed = True
        self.returncode = -9

    async def wait(self):
        return self.returncode


def _features(rows) -> bytes:
    return json.dumps(
        {"layers": [{"features": [{"properties": row} for row in rows]}]}
    ).encode()


@pytest.fixture
def spawn(monkeypatch):
    """Record each spawn (argv, env, the SQL file and conf as they were) and
    answer with the queued processes."""
    calls: list[dict] = []
    replies: list[_Proc] = []

    async def _fake(*argv, env=None, **_kwargs):
        sql_arg = argv[argv.index("-sql") + 1]
        conf = env["FREETDSCONF"]
        with open(sql_arg[1:], encoding="utf-8") as handle:
            sql = handle.read()
        with open(conf, encoding="utf-8") as handle:
            conf_text = handle.read()
        calls.append({"argv": argv, "env": env, "sql": sql, "conf": conf_text})
        return replies.pop(0) if replies else _Proc(stdout=_features([]))

    monkeypatch.setattr(database_sources.asyncio, "create_subprocess_exec", _fake)
    return calls, replies


@pytest.mark.anyio
async def test_login_reaches_the_child_only_through_its_env(configured, spawn):
    calls, replies = spawn
    replies.append(_Proc(stdout=_features([{"a": 1}])))

    rows = await run_database_sql("gis", "SELECT 1 AS a")

    assert rows == [{"a": 1}]
    argv, env = calls[0]["argv"], calls[0]["env"]
    assert argv[:4] == ("ogrinfo", "-ro", "-if", "MSSQLSpatial")
    assert argv[-1] == "MSSQL:Driver=FreeTDS;Servername=geolens;Database=GIS"
    assert "--debug" not in argv
    assert all(PASSWORD not in arg and USERNAME not in arg for arg in argv)
    assert env["MSSQLSPATIAL_PWD"] == PASSWORD
    assert calls[0]["sql"] == "SELECT 1 AS a"
    assert f"host = {HOST}" in calls[0]["conf"]
    # The temp directory, conf and SQL file are gone afterwards.
    assert not os.path.exists(env["FREETDSCONF"])


@pytest.mark.anyio
async def test_an_unknown_connection_spawns_nothing(configured, spawn):
    calls, _ = spawn
    with pytest.raises(UnknownDatabaseConnectionError):
        await run_database_sql("other", "SELECT 1")
    assert calls == []


_DEBUG_ECHO = (
    "ODBC: SQLDriverConnect(Driver=FreeTDS;Servername=geolens;Database=GIS;"
    f"UID={USERNAME};PWD={PASSWORD})\n"
)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("stderr", "error"),
    [
        (
            "ERROR 1: Unable to initialize connection to the server for "
            "MSSQL:Driver=FreeTDS;Servername=geolens;Database=GIS,\n",
            DatabaseConnectError,
        ),
        (
            "ERROR 1: Couldn't fetch requested layer 'dbo.parcels'!\n",
            DatabaseTableError,
        ),
        (
            "ERROR 1: [37000][FreeTDS][SQL Server]Invalid object name\n",
            DatabaseTableError,
        ),
    ],
)
async def test_failures_map_to_a_message_naming_only_the_connection(
    configured, spawn, stderr, error
):
    _calls, replies = spawn
    replies.append(_Proc(stderr=(_DEBUG_ECHO + stderr).encode(), returncode=1))

    with pytest.raises(error) as caught:
        await run_database_sql("gis", "SELECT 1")

    message = str(caught.value)
    assert "'gis'" in message
    for leaked in (HOST, USERNAME, PASSWORD, "MSSQL:", "geolens;"):
        assert leaked not in message


@pytest.mark.anyio
async def test_logged_stderr_carries_no_login(configured, spawn):
    _calls, replies = spawn
    replies.append(
        _Proc(
            stderr=(
                _DEBUG_ECHO
                + "ERROR 1: Unable to initialize connection to the server for "
                "MSSQL:Driver=FreeTDS;Servername=geolens;Database=GIS,\n"
                + f"login failed, password was {PASSWORD}\n"
            ).encode(),
            returncode=1,
        )
    )
    with structlog.testing.capture_logs() as logs:
        with pytest.raises(DatabaseConnectError):
            await run_database_sql("gis", "SELECT 1")
    text = json.dumps(logs)
    assert "database read failed" in text
    assert "Unable to initialize connection" in text
    assert PASSWORD not in text
    assert PASSWORD.split()[1] not in text
    assert f"UID={USERNAME}" not in text
    assert "Servername=geolens" not in text


@pytest.mark.anyio
async def test_a_hung_child_is_killed_and_reads_as_a_connect_failure(
    configured, spawn, monkeypatch
):
    _calls, replies = spawn
    proc = _Proc(hang=True)
    replies.append(proc)
    monkeypatch.setattr(database_sources, "SUBPROCESS_TIMEOUT_SECONDS", 0.05)

    with pytest.raises(DatabaseConnectError):
        await run_database_sql("gis", "SELECT 1")
    assert proc.killed


def test_the_subprocess_deadline_outlasts_gdals_login_timeout():
    assert database_sources.SUBPROCESS_TIMEOUT_SECONDS > 30


# ---------------------------------------------------------------------------
# The listing
# ---------------------------------------------------------------------------


def _catalog_row(schema, name, column, type_name="geometry", object_type="U "):
    return {
        "schema_name": schema,
        "object_name": name,
        "object_type": object_type,
        "column_name": column,
        "type_name": type_name,
    }


def test_identifiers_are_bracket_quoted_with_the_bracket_doubled():
    assert quote_identifier("a]b") == "[a]]b]"
    assert quote_identifier("x];DROP TABLE t;--") == "[x]];DROP TABLE t;--]"
    sql = srid_probe_sql([("dbo", "a]b", "ge]om")])
    assert sql == (
        "SELECT 0 AS i, (SELECT TOP 1 [ge]]om].STSrid FROM [dbo].[a]]b] "
        "WHERE [ge]]om] IS NOT NULL) AS srid"
    )


@pytest.mark.anyio
async def test_listing_reads_the_catalog_then_probes_each_srid(configured, spawn):
    calls, replies = spawn
    replies.append(
        _Proc(
            stdout=_features(
                [
                    _catalog_row("dbo", "parcels", "shape"),
                    _catalog_row("dbo", "places", "geog", "geography"),
                    _catalog_row("dbo", "sketch", "geom"),
                    _catalog_row("dbo", "empty", "geom"),
                    _catalog_row("gis", "a]b", "geom", object_type="V "),
                ]
            )
        )
    )
    replies.append(
        _Proc(
            stdout=_features(
                [
                    {"i": 0, "srid": 2263},
                    {"i": 1, "srid": 4326},
                    {"i": 2, "srid": 0},
                    {"i": 3, "srid": None},
                    {"i": 4, "srid": 3857},
                ]
            )
        )
    )

    listing = await list_spatial_tables("gis")

    assert not listing.truncated
    assert [(t.table_name, t.column_type, t.srid) for t in listing.tables] == [
        ("parcels", "geometry", 2263),
        ("places", "geography", 4326),
        ("sketch", "geometry", None),
        ("empty", "geometry", None),
        ("a]b", "geometry", 3857),
    ]
    assert listing.tables[4].object_type == "view"
    catalog_sql, probe_sql = calls[0]["sql"], calls[1]["sql"]
    assert "HAS_PERMS_BY_NAME" in catalog_sql
    assert "TOP (501)" in catalog_sql
    assert "FROM [gis].[a]]b]" in probe_sql
    assert probe_sql.count(" UNION ALL ") == 4


@pytest.mark.anyio
async def test_listing_stops_at_the_limit_and_says_so(configured, spawn):
    _calls, replies = spawn
    replies.append(
        _Proc(stdout=_features([_catalog_row("dbo", f"t{i}", "g") for i in range(4)]))
    )
    listing = await list_spatial_tables("gis", limit=3)
    assert listing.truncated
    assert [t.table_name for t in listing.tables] == ["t0", "t1", "t2"]


@pytest.mark.anyio
async def test_a_failed_srid_probe_still_lists_the_tables(configured, spawn):
    _calls, replies = spawn
    replies.append(_Proc(stdout=_features([_catalog_row("dbo", "v_broken", "g")])))
    replies.append(_Proc(stderr=b"ERROR 1: Invalid object name\n", returncode=1))
    listing = await list_spatial_tables("gis")
    assert [(t.table_name, t.srid) for t in listing.tables] == [("v_broken", None)]


@pytest.mark.anyio
async def test_a_probe_that_times_out_still_lists_the_tables(
    configured, spawn, monkeypatch
):
    _calls, replies = spawn
    replies.append(_Proc(stdout=_features([_catalog_row("dbo", "t", "g")])))
    probe = _Proc(hang=True)
    replies.append(probe)
    monkeypatch.setattr(database_sources, "SUBPROCESS_TIMEOUT_SECONDS", 0.05)
    listing = await list_spatial_tables("gis")
    assert [(t.table_name, t.srid) for t in listing.tables] == [("t", None)]
    assert probe.killed


@pytest.mark.anyio
async def test_a_listing_without_srids_reads_only_the_catalog(configured, spawn):
    calls, replies = spawn
    replies.append(_Proc(stdout=_features([_catalog_row("dbo", "t", "g")])))
    listing = await list_spatial_tables("gis", probe_srids=False)
    assert [(t.table_name, t.srid) for t in listing.tables] == [("t", None)]
    assert len(calls) == 1


@pytest.mark.anyio
async def test_an_empty_catalog_runs_no_probe(configured, spawn):
    calls, _replies = spawn
    listing = await list_spatial_tables("gis")
    assert listing.tables == [] and len(calls) == 1


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


def test_odbc_redaction_masks_the_source_and_login_keys():
    text = redact_odbc_credentials(
        "for MSSQL:Driver=FreeTDS;Servername=geolens;Database=GIS, and "
        f"SQLDriverConnect(Driver=FreeTDS;Server={HOST};Port=1433;"
        f"UID={USERNAME};PWD={PASSWORD})"
    )
    for leaked in (PASSWORD, PASSWORD.split()[1], USERNAME, HOST, "Database=GIS"):
        assert leaked not in text
    assert "MSSQL:<redacted>" in text


def test_stored_failure_reasons_carry_no_odbc_detail():
    reason = redact_failure_reason(
        "Database import failed: Unable to initialize connection to the server for "
        f"MSSQL:Driver=FreeTDS;Server={HOST};UID={USERNAME};PWD={PASSWORD}"
    )
    for leaked in (PASSWORD, USERNAME, HOST):
        assert leaked not in reason
    assert reason.startswith("Database import failed")


def test_log_events_carry_no_odbc_detail():
    event = _redact_sensitive_fields(
        None,
        "warning",
        {"event": f"open failed for MSSQL:Driver=FreeTDS;Server={HOST};PWD={PASSWORD}"},
    )["event"]
    assert event.startswith("open failed for MSSQL:<redacted>")
    assert PASSWORD not in event and HOST not in event
