"""The two clamps that decide which OGR driver may open an upload.

fix(#1846, GHSA-hrf5-v3cq-frx5). GDAL picks a driver by asking every
registered driver whether it recognises the bytes. Some of them answer yes to
a document that is really a set of instructions naming somewhere else to read
from, and a staged upload is bytes a caller chose. Two independent answers:

- ``local_input_driver_args`` (``processing/ingest/gdal_drivers.py``) turns the
  declared upload extension into repeated ``-if`` arguments, so only the
  drivers that extension could legitimately need are ever attempted.
- ``gdal_vector_safe_env`` (``processing/raster/vrt.py``) sets ``GDAL_SKIP`` so
  the pointer-following and network drivers are never registered at all.
- ``validate_content_directives`` (``processing/ingest/validation.py``)
  refuses a SQLite-family upload whose own schema names a source outside the
  file. Neither driver clamp can reach that one: GPKG is the primary supported
  upload format, so its driver cannot be dropped from the allowlist or added to
  the skip list, and the file really is a GeoPackage.

The structural half -- that every vector CLI argv in ``app/`` carries both --
is ``tests/test_rule2_structural.py``. This file is the behavioural half: what
the helpers say, that every entry point passes them, that real fixtures still
open under them, and that a document naming an outside address gets no request
out.
"""

import http.server
import json
import os
import functools
import shutil
import sqlite3
import socketserver
import subprocess
import threading
import zipfile
from pathlib import Path
from unittest import mock
from unittest.mock import patch

import pytest

from app.processing.ingest.gdal_drivers import (
    ARCHIVE_MEMBER_DRIVERS,
    allowed_input_drivers,
    local_input_driver_args,
)
from app.processing.ingest.validation import (
    ALLOWED_VIRTUAL_TABLE_MODULES,
    DRIVER_METADATA_EXTENSIONS,
    SQLITE_FAMILY_EXTENSIONS,
    UnsafeUploadError,
    validate_content_directives,
)
from app.processing.raster.vrt import gdal_service_safe_env, gdal_vector_safe_env

# A member whose bytes tell the OGR_VRT driver to go read a local path.
OGR_VRT_MEMBER = (
    "<OGRVRTDataSource><OGRVRTLayer name='probe'>"
    "<SrcDataSource relativeToVRT='0'>CSV:{target}</SrcDataSource>"
    "<SrcLayer>{stem}</SrcLayer></OGRVRTLayer></OGRVRTDataSource>"
)
# A member whose bytes tell the WFS driver to go fetch a URL. The WFS driver
# identifies on CONTENT, so the member name is irrelevant -- which is exactly
# why the extension refusal below cannot be the only layer.
WFS_MEMBER = "<OGRWFSDataSource><URL>{url}</URL></OGRWFSDataSource>"

needs_ogr = pytest.mark.skipif(
    shutil.which("ogrinfo") is None,
    reason="needs a GDAL command line to measure driver selection",
)


# ---------------------------------------------------------------------------
# What the helpers say
# ---------------------------------------------------------------------------


def _skipped(env):
    return set(env["GDAL_SKIP"].split())


def test_vector_env_refuses_the_pointer_and_network_drivers():
    skipped = _skipped(gdal_vector_safe_env())
    # The two measured on this finding, then the rest of the class.
    assert "OGR_VRT" in skipped
    assert "WFS" in skipped
    assert {"OAPIF", "OGCAPI", "HTTP", "CSW", "GMLAS", "NAS", "GPSBabel"} <= skipped


def test_service_env_keeps_only_the_two_drivers_the_importers_need():
    service = _skipped(gdal_service_safe_env())
    local = _skipped(gdal_vector_safe_env())
    assert local - service == {"WFS", "OAPIF"}
    assert "OGR_VRT" in service


def test_no_skipped_driver_name_contains_a_space():
    """GDAL_SKIP tokenises on spaces and commas.

    A short name with a space in it cannot be expressed here at all -- GDAL
    answers "Unable to find driver ESRI to unload" for ``ESRI Shapefile`` --
    so a spaced entry would read as a clamp and be one for neither half of the
    name. Drivers in that shape are excluded by the input allowlist instead.
    """
    for env in (gdal_vector_safe_env(), gdal_service_safe_env()):
        for name in env["GDAL_SKIP"].split():
            assert "," not in name
    assert all(" " not in name for name in _skipped(gdal_vector_safe_env()))


def test_vector_env_does_not_disturb_the_rest_of_the_environment():
    env = gdal_vector_safe_env()
    for key, value in os.environ.items():
        if key not in ("GDAL_SKIP", "GML_USE_SCHEMA_IMPORT", "GML_DOWNLOAD_SCHEMA"):
            assert env[key] == value


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/staging/x.geojson", ("GeoJSON",)),
        ("/staging/x.csv", ("CSV",)),
        ("/staging/x.fgb", ("FlatGeobuf",)),
        ("/staging/x.gpkg", ("GPKG",)),
        ("/staging/X.KML", ("LIBKML", "KML")),
        ("/staging/x.kmz", ("LIBKML", "KML")),
        ("/staging/x.zip", ARCHIVE_MEMBER_DRIVERS),
    ],
)
def test_extension_decides_the_attempted_drivers(path, expected):
    assert allowed_input_drivers(path) == expected


def test_unknown_extension_falls_back_to_local_file_drivers_only():
    """An operator may widen UPLOAD_ALLOWED_EXTENSIONS to a format this table
    has not met. That must not silently mean "no restriction"."""
    drivers = allowed_input_drivers("/staging/x.somethingnew")
    assert drivers == ARCHIVE_MEMBER_DRIVERS
    assert not {"WFS", "OAPIF", "HTTP", "OGR_VRT"} & set(drivers)


def test_no_allowlisted_driver_reaches_the_network_or_follows_a_pointer():
    banned = _skipped(gdal_vector_safe_env())
    for extension_drivers in (ARCHIVE_MEMBER_DRIVERS,):
        assert not banned & set(extension_drivers)


def test_driver_args_are_repeated_if_pairs():
    args = local_input_driver_args("/staging/x.kml")
    assert args == ["-if", "LIBKML", "-if", "KML"]


# ---------------------------------------------------------------------------
# Every vector entry point passes both clamps
# ---------------------------------------------------------------------------


class _FakeProc:
    returncode = 0

    def __init__(self, stdout=b"{}"):
        self._stdout = stdout

    async def communicate(self):
        return self._stdout, b""


@pytest.fixture
def spawned():
    """Capture the argv and env of every GDAL subprocess an entry point spawns."""
    calls: list[tuple[tuple[str, ...], dict]] = []

    async def _fake(*args, env=None, **kwargs):
        calls.append((args, env or {}))
        return _FakeProc()

    with patch("asyncio.create_subprocess_exec", side_effect=_fake):
        yield calls


@pytest.mark.anyio
async def test_run_ogrinfo_clamps_both_ways(spawned):
    from app.processing.ingest.ogr import run_ogrinfo

    await run_ogrinfo("/staging/upload.geojson")
    argv, env = spawned[0]
    assert "OGR_VRT" in env["GDAL_SKIP"]
    assert "-if" in argv and "GeoJSON" in argv


@pytest.mark.anyio
async def test_run_ogrinfo_preview_clamps_both_ways(spawned, tmp_path):
    from app.processing.ingest.ogr import run_ogrinfo_preview

    archive = _zip_with(tmp_path, {"layer.geojson": "{}"})
    await run_ogrinfo_preview(archive)
    argv, env = spawned[0]
    assert "OGR_VRT" in env["GDAL_SKIP"]
    assert "WFS" in env["GDAL_SKIP"]
    assert argv.count("-if") == len(ARCHIVE_MEMBER_DRIVERS)


@pytest.mark.anyio
async def test_run_ogr2ogr_clamps_both_ways(spawned):
    from app.processing.ingest.ogr import run_ogr2ogr

    await run_ogr2ogr(
        "/staging/upload.csv",
        "target_table",
        "PG:dbname=x",
        schema="data",
        geometry_type="POINT",
    )
    argv, env = spawned[0]
    assert "OGR_VRT" in env["GDAL_SKIP"]
    assert argv[argv.index("-if") + 1] == "CSV"


@pytest.mark.anyio
async def test_run_ogr2ogr_service_takes_the_service_variant(spawned):
    from app.processing.ingest.ogr import run_ogr2ogr_service

    await run_ogr2ogr_service(
        "WFS:https://example.test/wfs",
        "layer",
        "target_table",
        "PG:dbname=x",
        "wfs",
        schema="data",
    )
    _argv, env = spawned[0]
    assert "OGR_VRT" in env["GDAL_SKIP"]
    # The two drivers this call exists to use are still available.
    assert "WFS" not in env["GDAL_SKIP"].split()
    assert "OAPIF" not in env["GDAL_SKIP"].split()


@pytest.mark.anyio
async def test_service_preview_takes_the_service_variant(spawned):
    """The fifth clamped site, measured at the spawn rather than at the call.

    fix(#1857 item 3). The structural gate stops at the CALL, and this is the
    one clamped site that mutates the env after building it, so a change
    rebinding `env` before the spawn would keep full structural credit. The
    SERVICE variant, like `run_ogr2ogr_service`: WFS and OAPIF must survive.
    """
    from app.modules.catalog.sources.preview import run_service_preview

    await run_service_preview("WFS:https://example.test/wfs", "topp:parcels")

    _argv, env = spawned[0]
    skipped = env["GDAL_SKIP"].split()
    assert "OGR_VRT" in skipped
    assert "GPSBabel" in skipped
    # The two drivers this call exists to use are still available.
    assert "WFS" not in skipped
    assert "OAPIF" not in skipped


# ---------------------------------------------------------------------------
# The archive-member refusal
# ---------------------------------------------------------------------------


def _zip_with(tmp_path, members: dict[str, str], name="upload.zip") -> str:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        for member, body in members.items():
            archive.writestr(member, body)
    return str(path)


def test_driver_metadata_extensions_cover_the_vrt():
    assert ".vrt" in DRIVER_METADATA_EXTENSIONS


@pytest.mark.parametrize(
    "member", ["layer.vrt", "nested/dir/layer.VRT", "deep/deeper/x.Vrt"]
)
def test_archive_with_a_driver_metadata_member_is_refused(tmp_path, member):
    from app.processing.ingest.validation import validate_archive_safety

    path = _zip_with(tmp_path, {member: OGR_VRT_MEMBER.format(target="x", stem="x")})
    with pytest.raises(ValueError, match="VRT"):
        validate_archive_safety(path, "upload.zip")


def test_an_ordinary_archive_is_still_accepted(tmp_path):
    """Positive control for the refusal above."""
    from app.processing.ingest.validation import validate_archive_safety

    body = json.dumps({"type": "FeatureCollection", "features": []})
    path = _zip_with(tmp_path, {"layer.geojson": body, "notes.txt": "hello"})
    validate_archive_safety(path, "upload.zip")


# ---------------------------------------------------------------------------
# Against a real GDAL
# ---------------------------------------------------------------------------


# Every real-GDAL call here sticks to flags that have existed for the whole
# 3.x line, and reads TEXT rather than `-json`.
#
# fix(#1846 review round 5): CI installs Ubuntu's `gdal-bin` (GDAL 3.4) while
# the worker image is 3.10.3, and `-limit` does not exist on 3.4 -- `ogrinfo`
# exits 1 with "Unknown option name '-limit'" and an empty stdout, so a
# positive control asserting the smuggled row appeared failed before GDAL had
# read anything. `-json` is the same class of risk (the module's own code calls
# it "GDAL 3.7+" and carries a text fallback for exactly this reason), and it
# was worse than a failure: parsing a driver name out of absent JSON left
# `driver == ""`, which the caller below read as "this build has no
# virtual-table extension" and SKIPPED on. A wrong reason that hides a real
# gap is the one outcome these tests must not produce.
#
# So: `-ro`, `-al`, `-if` only. The first two are ancient; `-if` is probed
# below rather than assumed, because it is the one flag here whose absence
# would silently widen what the test allows GDAL to open.
_DRIVER_LINE = "using driver `"


def _ogrinfo(target, *, env_extra=None, args=(), all_features=False):
    """Run the real ogrinfo. Returns (exit code, driver name, stdout)."""
    env = {**os.environ}
    env.pop("GDAL_SKIP", None)
    if env_extra:
        env.update(env_extra)
    argv = ["ogrinfo", "-ro"]
    if all_features:
        argv.append("-al")
    proc = subprocess.run(
        [*argv, *args, target],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    driver = ""
    if _DRIVER_LINE in proc.stdout:
        driver = proc.stdout.split(_DRIVER_LINE, 1)[1].split("'", 1)[0]
    return proc.returncode, driver, proc.stdout


@functools.cache
def _ogrinfo_rejects_if_flag() -> str:
    """The stderr this GDAL gives for `-if`, or "" when it accepts the flag.

    Probed rather than assumed: `-if` restricts which drivers may be attempted,
    so on a build that does not have it the flag is not merely inert, it is an
    error -- and a test that ignored that would be asserting about a driver set
    it never actually constrained.
    """
    if shutil.which("ogrinfo") is None:
        return "ogrinfo not installed"
    probe = subprocess.run(
        ["ogrinfo", "-ro", "-if", "GeoJSON", "/nonexistent-probe.geojson"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    stderr = (probe.stderr or "").strip()
    return stderr if "Unknown option" in stderr else ""


def _require_if_flag() -> None:
    rejected = _ogrinfo_rejects_if_flag()
    if rejected:
        pytest.skip(f"this ogrinfo does not accept -if: {rejected}")


@needs_ogr
def test_every_declared_driver_name_is_a_real_driver():
    """An unrecognised name is a WARNING to GDAL, not an error.

    A typo in either table would therefore be silent: an unknown ``-if`` name
    is ignored, and an unknown GDAL_SKIP name unloads nothing. Measured against
    whatever GDAL is on this machine rather than pinned to a version, so a base
    image that drops a driver fails here instead of in production.
    """
    formats = subprocess.run(
        ["ogrinfo", "--formats"], capture_output=True, text=True, timeout=120
    ).stdout
    known = {line.strip().split(" -", 1)[0] for line in formats.splitlines()[1:]}
    declared = (
        set(ARCHIVE_MEMBER_DRIVERS)
        | _skipped(gdal_vector_safe_env())
        | _skipped(gdal_service_safe_env())
    )
    assert declared <= known, sorted(declared - known)


@needs_ogr
@pytest.mark.parametrize(
    "fixture",
    [
        "backend/tests/fixtures/ingest/basic_attrs.geojson",
        "backend/tests/fixtures/ingest/mixed_types.csv",
        "backend/tests/fixtures/ingest/tier1_points.fgb",
        "backend/tests/fixtures/ingest/tier1_points.kml",
        "backend/tests/fixtures/ingest/tier1_points.kmz",
        "backend/tests/fixtures/ingest/dbf_collision.zip",
        "backend/tests/fixtures/ingest/tier1_points_gdb.zip",
        "e2e/fixtures/multi-layer-gpkg.gpkg",
        "e2e/fixtures/sample.geojson",
        "e2e/fixtures/sample-nonspatial.csv",
    ],
)
def test_real_fixtures_open_identically_under_the_clamp(fixture):
    """The positive control: the clamp must cost no supported format.

    Same driver, same exit code, with and without both clamps -- including the
    two archive shapes, where GDAL is choosing between a shapefile bundle and a
    File Geodatabase inside ``/vsizip``.
    """
    repo = Path(__file__).parents[2]
    path = str(repo / fixture)
    target = f"/vsizip/{path}" if fixture.endswith(".zip") else path
    _require_if_flag()
    plain_code, plain_driver, _ = _ogrinfo(target)
    clamped_code, clamped_driver, _ = _ogrinfo(
        target,
        env_extra={"GDAL_SKIP": gdal_vector_safe_env()["GDAL_SKIP"]},
        args=local_input_driver_args(fixture),
    )
    assert plain_driver, f"fixture did not open at all: {fixture}"
    assert (clamped_code, clamped_driver) == (plain_code, plain_driver)


class _Listener:
    """A local HTTP server that records every request it is asked for."""

    def __init__(self):
        self.hits: list[str] = []
        listener = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                listener.hits.append(self.path)
                body = b"<?xml version='1.0'?><root/>"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        socketserver.TCPServer.allow_reuse_address = True
        self._server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self):
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def listener():
    server = _Listener()
    try:
        yield server
    finally:
        server.close()


@needs_ogr
def test_an_archived_vrt_reads_nothing_under_the_clamp(tmp_path):
    """The negative control for the local-path half."""
    secret = tmp_path / "target.csv"
    secret.write_text("col_a,col_b\nmarker-a,marker-b\n")
    body = OGR_VRT_MEMBER.format(target=secret, stem=secret.stem)
    archive = _zip_with(tmp_path, {"bundle.dbf": body})

    _require_if_flag()
    unclamped_code, unclamped_driver, _ = _ogrinfo(f"/vsizip/{archive}")
    assert (unclamped_code, unclamped_driver) == (0, "OGR_VRT"), (
        "the primitive this test guards against did not reproduce, so a pass "
        "here would prove nothing"
    )

    code, driver, listing = _ogrinfo(
        f"/vsizip/{archive}",
        env_extra={"GDAL_SKIP": gdal_vector_safe_env()["GDAL_SKIP"]},
        args=local_input_driver_args("upload.zip"),
    )
    assert code != 0 and driver == ""


@needs_ogr
@pytest.mark.parametrize("member", ["bundle.dbf", "layer.geojson", "nested/x.txt"])
def test_an_archived_service_document_sends_no_request_under_the_clamp(
    tmp_path, listener, member
):
    """The negative control for the network half, and for the member NAME.

    The WFS driver identifies on content, so the same document works under any
    member name -- the reason the extension refusal cannot be the only layer.
    The listener is the measurement: zero requests, not merely a non-zero exit.
    """
    url = f"http://127.0.0.1:{listener.port}/probe"
    archive = _zip_with(tmp_path, {member: WFS_MEMBER.format(url=url)}, name="s.zip")

    _ogrinfo(f"/vsizip/{archive}")
    assert listener.hits, (
        "the primitive this test guards against did not reproduce, so a pass "
        "here would prove nothing"
    )
    listener.hits.clear()

    code, driver, listing = _ogrinfo(
        f"/vsizip/{archive}",
        env_extra={"GDAL_SKIP": gdal_vector_safe_env()["GDAL_SKIP"]},
        args=local_input_driver_args("upload.zip"),
    )
    assert listener.hits == []
    assert code != 0 and driver == ""


@needs_ogr
def test_the_input_allowlist_alone_stops_it(tmp_path, listener):
    """Each layer is load-bearing on its own; this is the allowlist half."""
    url = f"http://127.0.0.1:{listener.port}/probe"
    archive = _zip_with(tmp_path, {"bundle.dbf": WFS_MEMBER.format(url=url)})
    _require_if_flag()
    code, _driver, _ = _ogrinfo(
        f"/vsizip/{archive}", args=local_input_driver_args("upload.zip")
    )
    assert listener.hits == []
    assert code != 0


@needs_ogr
def test_the_env_clamp_alone_stops_it(tmp_path, listener):
    """And this is the GDAL_SKIP half, with no -if arguments at all."""
    url = f"http://127.0.0.1:{listener.port}/probe"
    archive = _zip_with(tmp_path, {"bundle.dbf": WFS_MEMBER.format(url=url)})
    code, _driver, _ = _ogrinfo(
        f"/vsizip/{archive}",
        env_extra={"GDAL_SKIP": gdal_vector_safe_env()["GDAL_SKIP"]},
    )
    assert listener.hits == []
    assert code != 0


# ---------------------------------------------------------------------------
# The SQLite schema check
# ---------------------------------------------------------------------------

# A schema row that tells the engine its rows come from a named outside file.
# Written straight into sqlite_master under `PRAGMA writable_schema`, which is
# how it survives without the module having to be loadable at write time.
_EXTERNAL_SOURCE_TABLE = (
    "CREATE VIRTUAL TABLE {name} USING VirtualText"
    "('{target}','UTF-8',1,POINT,DOUBLEQUOTE,COMMA)"
)


def _database_with_external_source(
    tmp_path, target, *, name="upload.gpkg", declaration=None, geopackage=False
):
    """A SQLite database whose schema reads from ``target``."""
    import sqlite3

    path = tmp_path / name
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE plain (id INTEGER)")
    if geopackage:
        # Enough of the GeoPackage tables that the GPKG driver claims the file
        # and lists the smuggled table as a layer.
        con.execute("PRAGMA application_id = 1196444487")
        con.execute(
            "CREATE TABLE gpkg_spatial_ref_sys (srs_name TEXT, srs_id INTEGER "
            "PRIMARY KEY, organization TEXT, organization_coordsys_id INTEGER, "
            "definition TEXT, description TEXT)"
        )
        con.execute(
            "CREATE TABLE gpkg_contents (table_name TEXT PRIMARY KEY, "
            "data_type TEXT, identifier TEXT, description TEXT, "
            "last_change TEXT, min_x REAL, min_y REAL, max_x REAL, max_y REAL, "
            "srs_id INTEGER)"
        )
        con.execute(
            "INSERT INTO gpkg_contents (table_name, data_type, identifier) "
            "VALUES ('smuggled','attributes','smuggled')"
        )
    con.execute("PRAGMA writable_schema=ON")
    con.execute(
        "INSERT INTO sqlite_master (type,name,tbl_name,rootpage,sql) "
        "VALUES ('table','smuggled','smuggled',0,?)",
        (declaration or _EXTERNAL_SOURCE_TABLE.format(name="smuggled", target=target),),
    )
    con.commit()
    con.close()
    return path


@pytest.fixture
def outside_file(tmp_path):
    target = tmp_path / "outside.csv"
    target.write_text("col_a,col_b\nmarker-one,marker-two\n")
    return target


def test_the_module_allowlist_holds_only_self_contained_index_modules():
    """Every allowed module reads the database's own tables and nothing else.

    Measured by writing both formats with the shipped GDAL: a GeoPackage
    carries `rtree` alone, and `-dsco SPATIALITE=YES` adds VirtualSpatialIndex,
    VirtualElementary and VirtualKNN2. Nothing in the list names a file.
    """
    assert "rtree" in ALLOWED_VIRTUAL_TABLE_MODULES
    assert "virtualspatialindex" in ALLOWED_VIRTUAL_TABLE_MODULES
    assert ALLOWED_VIRTUAL_TABLE_MODULES == {
        m.lower() for m in ALLOWED_VIRTUAL_TABLE_MODULES
    }
    # The whole point: nothing that names an outside source is allowed.
    for refused in (
        "virtualtext",
        "virtualdbf",
        "virtualshape",
        "virtualxl",
        "virtualgpx",
        "virtualgeojson",
        "virtualxpath",
        "virtualbbox",
        "virtualpostgis",
        "virtualodbc",
        "virtualfdo",
        "virtualnetwork",
        "virtualogr",
        "csv",
        "zipfile",
        "fileio",
        "fsdir",
    ):
        assert refused not in ALLOWED_VIRTUAL_TABLE_MODULES


@pytest.mark.parametrize("extension", sorted(SQLITE_FAMILY_EXTENSIONS))
def test_a_database_reading_from_outside_is_refused(tmp_path, outside_file, extension):
    path = _database_with_external_source(
        tmp_path, outside_file, name=f"upload{extension}"
    )
    with pytest.raises(UnsafeUploadError, match="smuggled"):
        validate_content_directives(str(path))


def test_a_geopackage_reading_from_outside_is_refused(tmp_path, outside_file):
    path = _database_with_external_source(tmp_path, outside_file, geopackage=True)
    with pytest.raises(UnsafeUploadError):
        validate_content_directives(str(path))


# Member names GDAL does not look at. The first is the honest one; the rest are
# the shapes the first version of this check walked straight past, because it
# selected members by extension and GDAL selects them by content.
ARCHIVE_MEMBER_NAMES = [
    "inner.gpkg",
    "nested/dir/inner.gpkg",
    "evil.bak",
    "evil",
    "data/evil.dat",
    "LAYER.DB.TXT",
]


@pytest.mark.parametrize("member", ARCHIVE_MEMBER_NAMES)
def test_a_database_inside_an_archive_is_refused_under_any_name(
    tmp_path, outside_file, member
):
    """The name decides nothing, so the check must not read it.

    Each case first proves GDAL WOULD open the member -- with the exact
    argv and env the fixed code builds for a `.zip` -- so a passing refusal
    below cannot be a refusal of something that was never a threat.
    """
    path = _database_with_external_source(tmp_path, outside_file, name="src.gpkg")
    archive = tmp_path / "upload.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.write(path, member)

    if shutil.which("ogrinfo") is not None:
        _require_if_flag()
        code, driver, listing = _ogrinfo(
            f"/vsizip/{archive}",
            env_extra={"GDAL_SKIP": gdal_vector_safe_env()["GDAL_SKIP"]},
            args=local_input_driver_args("upload.zip"),
        )
        assert (code, driver) == (0, "SQLite"), (
            f"GDAL did not open member {member!r} as SQLite, so this case "
            "proves nothing; re-derive it before trusting the refusal"
        )

    with pytest.raises(UnsafeUploadError):
        validate_content_directives(str(archive), "upload.zip")


@pytest.mark.parametrize("member", ["notes.txt", "readme", "deep/dir/x.dat"])
def test_a_vrt_inside_an_archive_is_refused_under_any_name(tmp_path, member):
    """Same rule for the other content-identified driver.

    The OGR VRT driver searches the leading bytes for its root element, so a
    byte-order mark, an XML declaration and leading junk all leave it
    identified -- asserted here rather than assumed.
    """
    body = (
        "\ufeff<?xml version='1.0'?>\n<!-- notes -->\nleading junk\n"
        + OGR_VRT_MEMBER.format(target="/x", stem="x")
    )
    archive = tmp_path / "upload.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(member, body)

    if shutil.which("ogrinfo") is not None:
        code, driver, listing = _ogrinfo(f"/vsizip/{archive}")
        assert (code, driver) == (0, "OGR_VRT"), (
            f"GDAL did not identify member {member!r} as a VRT, so this case "
            "proves nothing"
        )

    with pytest.raises(UnsafeUploadError, match="VRT"):
        validate_content_directives(str(archive), "upload.zip")


def test_the_archive_scan_bounds_its_total_decompression(tmp_path, monkeypatch):
    """Per-member bounds are not a bound.

    Ten thousand members each just under the per-member limit is ten thousand
    times the limit, and on the preview path this scan runs before the ingest
    task's own bomb check. The budget is shrunk here rather than the shared
    limit, because `validate_zip_safety` reads that same limit and would
    refuse first -- which would test the wrong thing.
    """
    import os as _os

    from app.processing.ingest import validation

    archive = tmp_path / "upload.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for index in range(8):
            # Incompressible, so the per-entry ratio check has nothing to say
            # and the budget is what the archive meets.
            z.writestr(f"member_{index}.bin", _os.urandom(200_000))

    real_budget = validation._ScanBudget
    monkeypatch.setattr(validation, "_ScanBudget", lambda _limit: real_budget(1024))
    with pytest.raises(UnsafeUploadError, match="decompressed limit"):
        validation.validate_content_directives(str(archive), "upload.zip")


def test_the_archive_scan_runs_the_bomb_checks_first(tmp_path):
    """The docstring's inheritance claim, asserted.

    The preview path calls this before the ingest task's own
    `validate_archive_safety`, so entry count, ratio and total have to be
    bounded here or they are not bounded at all on that path.
    """
    from app.processing.ingest import validation

    archive = tmp_path / "upload.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("bomb.bin", b"\0" * 5_000_000)

    with pytest.raises(UnsafeUploadError, match="compression ratio"):
        validation.validate_content_directives(str(archive), "upload.zip")
    # And the same archive is refused by the ingest task's own door, which is
    # what this is standing in for on the paths that reach it first.
    with pytest.raises(ValueError, match="compression ratio"):
        validation.validate_archive_safety(str(archive), "upload.zip")


def test_the_refusal_never_names_the_staging_path(tmp_path, outside_file):
    """A staging basename carries the job id and the temp prefix.

    `ingest/ogr.py` keeps those out of user-facing text everywhere else
    (`_friendly_open_failure_message`), and the preview calls this check with
    no user-visible filename to give, so the message has to manage without one.
    """
    staged = _database_with_external_source(
        tmp_path, outside_file, name="ab12cd34_upload.gpkg"
    )
    with pytest.raises(UnsafeUploadError) as refused:
        validate_content_directives(str(staged))
    assert "ab12cd34" not in str(refused.value)
    assert str(tmp_path) not in str(refused.value)


@pytest.mark.parametrize(
    "declaration",
    [
        # Every spelling here is one SQLite's own schema parser accepts, so
        # every one is a file GDAL would read. Measured, not assumed: case,
        # IF NOT EXISTS, all three quoting styles, an interrupting comment and
        # a statement split across lines.
        "create virtual table if not exists smuggled using VIRTUALTEXT('/x')",
        'CREATE VIRTUAL TABLE "smuggled" USING "VirtualText"(\'/x\')',
        "CREATE VIRTUAL TABLE [smuggled] USING [VirtualDbf]('/x')",
        "CREATE VIRTUAL TABLE smuggled /* comment */ USING VirtualShape('/x')",
        "CREATE\nVIRTUAL\nTABLE\nsmuggled\nUSING\nVirtualXL('/x')",
    ],
)
def test_spellings_sqlite_accepts_are_all_refused(tmp_path, declaration):
    path = _database_with_external_source(tmp_path, "/x", declaration=declaration)
    # The premise, asserted rather than assumed: SQLite reads this schema, so
    # GDAL reading through the same SQLite would list the table.
    connection = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    connection.execute("SELECT name FROM sqlite_master").fetchall()
    connection.close()
    with pytest.raises(UnsafeUploadError):
        validate_content_directives(str(path), "upload.gpkg")


@pytest.mark.parametrize(
    "declaration",
    [
        'CREATE VIRTUAL TABLE main."smuggled" USING "VirtualText"(\'/x\')',
        "CREATE VIRTUAL TABLE smuggled",
    ],
)
def test_a_schema_sqlite_will_not_parse_is_left_to_the_driver(tmp_path, declaration):
    """Standing aside on a corrupt schema has to be safe, so measure it.

    These two spellings make SQLite reject the whole schema (SQLITE_CORRUPT,
    "malformed database schema"). GDAL reads the file through the same SQLite,
    so it cannot list the table either -- asserted below against a real
    ogrinfo. Standing aside is therefore not a gap, and speaking here would
    take the open-failure message away from the code that words it carefully.
    """
    path = _database_with_external_source(tmp_path, "/x", declaration=declaration)
    with pytest.raises(sqlite3.DatabaseError):
        connection = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
        connection.execute("SELECT name FROM sqlite_master").fetchall()

    validate_content_directives(str(path), "upload.gpkg")

    if shutil.which("ogrinfo") is not None:
        _require_if_flag()
        _, _, listing = _ogrinfo(
            str(path),
            env_extra={"GDAL_SKIP": gdal_vector_safe_env()["GDAL_SKIP"]},
            args=["-if", "SQLite"],
        )
        assert "smuggled" not in listing


def test_a_virtual_table_whose_module_cannot_be_read_is_refused(tmp_path):
    """Fail closed: a spelling SQLite reads and this cannot is still a no.

    The module name here is quoted and contains a space, which SQLite accepts
    and the module pattern deliberately will not read, so the refusal comes
    from the unreadable branch rather than from the allowlist.
    """
    path = _database_with_external_source(
        tmp_path,
        "/x",
        declaration="CREATE VIRTUAL TABLE smuggled USING \"Virtual Text\"('/x')",
    )
    connection = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    connection.execute("SELECT name FROM sqlite_master").fetchall()
    connection.close()
    with pytest.raises(UnsafeUploadError):
        validate_content_directives(str(path), "upload.gpkg")


def test_a_schema_too_large_to_scan_is_refused(tmp_path, monkeypatch):
    """Truncating the scan would leave the rows past the cap unexamined.

    That is the one outcome a bound must not produce quietly, so the cap
    refuses rather than stopping early. Exercised with a small cap rather than
    by writing a hundred thousand tables.
    """
    from app.processing.ingest import validation

    monkeypatch.setattr(validation, "MAX_SQLITE_SCHEMA_ROWS", 2)
    path = tmp_path / "upload.gpkg"
    con = sqlite3.connect(path)
    for index in range(5):
        con.execute(f"CREATE TABLE plain_{index} (id INTEGER)")
    con.commit()
    con.close()
    with pytest.raises(UnsafeUploadError, match="schema objects"):
        validation.validate_content_directives(str(path), "upload.gpkg")


@needs_ogr
def test_a_geopackage_whose_layer_name_has_a_space_passes(tmp_path):
    """The spatial index is named after the layer, so the name can be quoted.

    A layer called "my layer" yields `CREATE VIRTUAL TABLE "rtree_my layer_geom"
    USING rtree(...)`. Reading the module out of that is what a name pattern
    has to get right, or the check refuses a perfectly ordinary GeoPackage.
    """
    repo = Path(__file__).parents[2]
    out = tmp_path / "spaced.gpkg"
    result = subprocess.run(
        [
            "ogr2ogr",
            "-f",
            "GPKG",
            "-nln",
            "my layer",
            str(out),
            str(repo / "backend/tests/fixtures/ingest/basic_attrs.geojson"),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0 and out.exists(), result.stderr
    import sqlite3 as _sqlite3

    schema = (
        _sqlite3.connect(out)
        .execute("SELECT sql FROM sqlite_master WHERE sql LIKE '%VIRTUAL%'")
        .fetchall()
    )
    assert any(" " in row[0] for row in schema), (
        "this GDAL did not produce a quoted index name, so the case this test "
        "exists for was not exercised"
    )
    validate_content_directives(str(out), "spaced.gpkg")


def test_an_ordinary_column_named_virtual_is_not_refused(tmp_path):
    """The pre-filter is loose on purpose; it must still not be absurd."""
    path = tmp_path / "upload.gpkg"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE plain (virtual_id INTEGER, is_virtual TEXT)")
    con.commit()
    con.close()
    validate_content_directives(str(path), "upload.gpkg")


def test_a_file_that_is_not_a_database_is_left_to_the_driver(tmp_path):
    """Bytes that are not a database have no schema to name an outside source.

    `validate_file_content` already refuses a `.gpkg` whose magic bytes are
    wrong, and `ingest/ogr.py` has a carefully worded message for the open
    failure that follows. Speaking here would only replace that with a worse
    message, and `tests/test_ingest_open_failure_message.py` pins the wording
    this must not trample.
    """
    path = tmp_path / "upload.gpkg"
    path.write_bytes(b"not a database at all")
    validate_content_directives(str(path), "upload.gpkg")


def test_a_missing_staged_file_is_left_to_the_driver(tmp_path):
    validate_content_directives(str(tmp_path / "gone.gpkg"), "gone.gpkg")


def test_a_database_it_cannot_open_for_any_other_reason_is_refused(tmp_path):
    """Standing aside is scoped to the two "not a database" codes, not to
    every failure: a file this cannot vouch for is still a no."""
    from app.processing.ingest import validation

    path = tmp_path / "upload.gpkg"
    sqlite3.connect(path).close()

    def _refuse(*args, **kwargs):
        error = sqlite3.OperationalError("unable to open database file")
        error.sqlite_errorcode = sqlite3.SQLITE_CANTOPEN
        raise error

    with mock.patch.object(validation.sqlite3, "connect", _refuse):
        with pytest.raises(UnsafeUploadError):
            validation.validate_content_directives(str(path), "upload.gpkg")


@pytest.mark.parametrize(
    "path",
    ["e2e/fixtures/multi-layer-gpkg.gpkg"],
)
def test_shipped_geopackage_fixtures_pass(path):
    """Positive control: the spatial index every GeoPackage carries is allowed."""
    repo = Path(__file__).parents[2]
    validate_content_directives(str(repo / path))


def test_a_spatialite_database_written_by_gdal_passes(tmp_path):
    """Positive control for the other writer, if a GDAL is available."""
    if shutil.which("ogr2ogr") is None:
        pytest.skip("needs a GDAL command line to write a SpatiaLite database")
    repo = Path(__file__).parents[2]
    out = tmp_path / "spatialite.sqlite"
    result = subprocess.run(
        [
            "ogr2ogr",
            "-f",
            "SQLite",
            "-dsco",
            "SPATIALITE=YES",
            str(out),
            str(repo / "backend/tests/fixtures/ingest/basic_attrs.geojson"),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0 or not out.exists():
        pytest.skip("this GDAL build cannot write SpatiaLite")
    validate_content_directives(str(out))


def test_an_ordinary_upload_extension_is_not_opened_as_a_database(tmp_path):
    """The check is an extension test on everything it does not apply to."""
    path = tmp_path / "upload.geojson"
    path.write_text("not a database")
    validate_content_directives(str(path))


@needs_ogr
def test_the_driver_would_have_read_it_without_the_check(tmp_path, outside_file):
    """The audit's positive control, so a pass above cannot be vacuous.

    Runs the exact argv and env the fixed code builds for a `.gpkg` upload and
    asserts the smuggled layer IS listed and read. If this stops reproducing,
    the refusal tests are guarding nothing and should be re-derived rather than
    trusted.
    """
    path = _database_with_external_source(tmp_path, outside_file, name="upload.sqlite")
    _require_if_flag()
    code, driver, listing = _ogrinfo(
        str(path),
        env_extra={"GDAL_SKIP": gdal_vector_safe_env()["GDAL_SKIP"]},
        args=local_input_driver_args("upload.sqlite"),
    )
    if driver != "SQLite":
        # A build without the virtual-table extension cannot show the
        # primitive, and that is the ONLY reason this may be skipped. The
        # driver line and the exit code go in the reason so a skip can never
        # stand in for "the flags were wrong" -- which is what it silently did
        # when this parsed `-json` that GDAL 3.4 does not emit.
        pytest.skip(
            f"ogrinfo did not open the database as SQLite (exit {code}, "
            f"driver {driver or 'none'}); no virtual-table extension here"
        )
    _, _, features = _ogrinfo(
        str(path),
        env_extra={"GDAL_SKIP": gdal_vector_safe_env()["GDAL_SKIP"]},
        args=local_input_driver_args("upload.sqlite"),
        all_features=True,
    )
    assert code == 0
    assert "smuggled" in listing, (
        "the primitive this check guards against did not reproduce on this "
        "GDAL, so the refusal tests prove nothing here"
    )
    # And the outside file's contents really do come back as feature data.
    assert "marker-one" in features, features[:400]
    # And the check refuses the very file the driver just read.
    with pytest.raises(UnsafeUploadError):
        validate_content_directives(str(path))


# ---------------------------------------------------------------------------
# A damaged archive is a refusal, not a crash
# ---------------------------------------------------------------------------


def _archive_with_a_damaged_member(tmp_path, name="upload.zip") -> Path:
    """A ZIP whose central directory is intact and whose member data is not.

    ``validate_zip_safety`` reads the central directory and never touches
    member data, so an archive like this walks past it. The damage only
    surfaces when a member is read to its end, which is when zipfile verifies
    the CRC -- and that is exactly what the content scan does.
    """
    path = tmp_path / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "layer.geojson", '{"type":"FeatureCollection","features":[]}' * 40
        )
        info = archive.infolist()[0]

    raw = bytearray(path.read_bytes())
    # Local file header: 30 fixed bytes, then the name and the extra field.
    start = info.header_offset
    name_len = int.from_bytes(raw[start + 26 : start + 28], "little")
    extra_len = int.from_bytes(raw[start + 28 : start + 30], "little")
    payload = start + 30 + name_len + extra_len
    raw[payload + 4] ^= 0xFF
    path.write_bytes(bytes(raw))
    return path


def test_a_damaged_member_is_refused_as_a_value_error(tmp_path):
    """The shape every door maps, not the one the archive library raises.

    `_validate_upload_file_safety` promises ValueError and `tasks_vector`
    catches exactly that, so a `zipfile.BadZipFile` escaping here would fail an
    ordinary truncated upload's job with an uncaught exception instead of the
    refusal the caller is meant to see.
    """
    from app.processing.ingest import validation

    archive = _archive_with_a_damaged_member(tmp_path)

    # Positive control, both halves: the archive really is damaged, and the
    # check that runs first really does let it through.
    with zipfile.ZipFile(archive) as opened:
        with pytest.raises(zipfile.BadZipFile):
            opened.read("layer.geojson")
    validation.validate_zip_safety(str(archive))

    with pytest.raises(UnsafeUploadError) as refused:
        validation.validate_content_directives(str(archive), "upload.zip")
    assert isinstance(refused.value, ValueError)
    assert "could not be read" in str(refused.value)


@pytest.mark.anyio
async def test_preview_maps_a_damaged_archive_to_422(
    client, admin_auth_header, test_db_session, tmp_path
):
    """End to end: the refusal reaches the caller as a 422 that says what to do."""
    import uuid as _uuid

    from app.platform.jobs.models import IngestJob
    from tests.factories import get_user_id

    archive = _archive_with_a_damaged_member(tmp_path, name=f"{_uuid.uuid4()}.zip")
    job = IngestJob(
        source_filename="upload.zip",
        file_path=str(archive),
        created_by=await get_user_id(test_db_session, "admin"),
        status="pending",
        user_metadata={"file_type": "vector"},
    )
    test_db_session.add(job)
    await test_db_session.commit()

    response = await client.post(f"/ingest/preview/{job.id}", headers=admin_auth_header)

    assert response.status_code == 422, response.text
    assert "could not be read" in response.json()["detail"]


# ---------------------------------------------------------------------------
# The schema walk is linear, and bounded even so
# ---------------------------------------------------------------------------


def _pathological_schema(kilobytes: int) -> str:
    """Block-comment openers with no terminator, inside a valid schema.

    This is what makes a lazy `/\\*.*?\\*/` quadratic: each opener restarts a
    scan that runs to the end of the string. A column DEFAULT is enough to
    carry it, so the text is uploader-chosen through a schema SQLite accepts.
    """
    return "CREATE TABLE t(a TEXT DEFAULT '" + ("/* " * (kilobytes * 1024 // 3)) + "')"


def _strip_steps(text: str) -> int:
    """Line events executed inside `_strip_sql_comments` for this input.

    A step count, not a stopwatch: a slow machine cannot fail this and a fast
    one cannot hide a quadratic scan from it.
    """
    import sys

    from app.processing.ingest import validation

    code = validation._strip_sql_comments.__code__
    steps = 0

    def tracer(frame, event, arg):
        nonlocal steps
        if event == "line" and frame.f_code is code:
            steps += 1
        return tracer

    sys.settrace(tracer)
    try:
        validation._strip_sql_comments(text)
    finally:
        sys.settrace(None)
    return steps


def test_the_comment_strip_is_linear_in_the_size_of_the_schema():
    """The lazy regex this replaced was quadratic on uploader-chosen text.

    `re.compile(r"/\*.*?\*/", re.DOTALL)` restarts a scan to end-of-string at
    every unterminated opener: 64 KB took 3.6 s, and the scan used to run
    inline on the request that uploaded the file. Worth recording that the
    "standard linear block comment" pattern does not fix it either -- measured
    slower still on this input -- which is why the strip is a walk.

    Doubling the input must not more than double the work.
    """
    steps = {kb: _strip_steps(_pathological_schema(kb)) for kb in (64, 128, 256)}
    assert steps[128] <= steps[64] * 3, steps
    assert steps[256] <= steps[64] * 6, steps
    # The absolute figure stays tiny because the walk skips a quoted literal in
    # one step rather than character by character.
    assert steps[256] < 10_000, steps

    # And a ceiling, because the step count alone is not enough to guard this.
    # Line tracing sees the WALK's iterations; if someone swapped the walk back
    # for a regex the cost would move inside the C engine where tracing cannot
    # follow it, and the count would read as ~3 steps however slow it got. The
    # margin makes this a fact rather than a race: the walk does 1 MB in about
    # half a millisecond, and the lazy regex this replaced needs roughly a
    # quarter of an hour, so anything between them is still four orders of
    # magnitude clear of the bound.
    import time

    from app.processing.ingest.validation import _strip_sql_comments

    started = time.perf_counter()
    _strip_sql_comments(_pathological_schema(1024))
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0, f"1 MB of schema took {elapsed:.1f}s; the strip is not linear"


def test_the_comment_strip_is_linear_outside_a_quoted_string_too():
    """The same input unquoted, where the walk cannot skip it wholesale."""
    payload = "CREATE VIRTUAL TABLE x {} USING rtree(a)"
    steps = {
        kb: _strip_steps(payload.format("/* " * (kb * 1024 // 3)))
        for kb in (64, 128, 256)
    }
    assert steps[128] <= steps[64] * 3, steps
    assert steps[256] <= steps[64] * 6, steps


def test_an_oversized_schema_is_refused_before_it_is_walked(tmp_path, monkeypatch):
    """The byte cap, so even the linear pass has a ceiling.

    Asked of the database as `SUM(LENGTH(sql))` before any schema text is
    materialised, so an oversized schema is refused rather than read.
    """
    from app.processing.ingest import validation

    path = tmp_path / "upload.gpkg"
    con = sqlite3.connect(path)
    con.execute(f"CREATE TABLE big (a TEXT DEFAULT '{'x' * 200_000}')")
    con.commit()
    con.close()

    monkeypatch.setattr(validation, "MAX_SQLITE_SCHEMA_BYTES", 1024)
    with pytest.raises(UnsafeUploadError, match="schema"):
        validation.validate_content_directives(str(path), "upload.gpkg")


def test_comment_stripping_leaves_quoted_text_alone():
    """No comment regex can do this, and the module match downstream needs it."""
    from app.processing.ingest.validation import _strip_sql_comments

    assert "-- not a comment" in _strip_sql_comments(
        "CREATE TABLE t(a TEXT DEFAULT '-- not a comment')"
    )
    assert "/* not a comment */" in _strip_sql_comments(
        "CREATE TABLE t(a TEXT DEFAULT '/* not a comment */')"
    )
    stripped = _strip_sql_comments(
        "CREATE VIRTUAL TABLE x /* real comment */ USING VirtualText('/x')"
    )
    assert "real comment" not in stripped
    assert "USING VirtualText" in stripped


def _archive_with_unsupported_compression(tmp_path, name="upload.zip") -> Path:
    """A ZIP whose member declares a compression method zipfile cannot inflate.

    Built by rewriting the method field in both the local header and the
    central directory, because `zipfile` will not write one it cannot read.
    """
    path = tmp_path / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("layer.geojson", '{"type":"FeatureCollection"}' * 20)

    raw = bytearray(path.read_bytes())
    unsupported = (99).to_bytes(2, "little")  # 99 = AE-x encryption marker
    # Local file header: method at offset 8. Central directory: method at 10.
    for signature, offset in ((b"PK\x03\x04", 8), (b"PK\x01\x02", 10)):
        at = raw.find(signature)
        assert at >= 0, signature
        raw[at + offset : at + offset + 2] = unsupported
    path.write_bytes(bytes(raw))
    return path


def _archive_with_encrypted_member(tmp_path, name="upload.zip") -> Path:
    """A ZIP whose member sets the encryption bit in its general-purpose flags.

    `zipfile` raises RuntimeError for these when no password is supplied, which
    is an ordinary thing to receive from a user and not a bug on our side.
    """
    path = tmp_path / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("layer.geojson", '{"type":"FeatureCollection"}' * 20)

    raw = bytearray(path.read_bytes())
    # General-purpose bit flag: local header offset 6, central directory 8.
    for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        at = raw.find(signature)
        assert at >= 0, signature
        flags = int.from_bytes(raw[at + offset : at + offset + 2], "little")
        raw[at + offset : at + offset + 2] = (flags | 0x1).to_bytes(2, "little")
    path.write_bytes(bytes(raw))
    return path


@pytest.mark.parametrize(
    ("build", "raises"),
    [
        (_archive_with_encrypted_member, RuntimeError),
        (_archive_with_unsupported_compression, NotImplementedError),
    ],
)
def test_a_member_zipfile_will_not_decode_is_refused_not_raised(
    tmp_path, build, raises
):
    """Neither of these is a ValueError, and both are ordinary uploads.

    `validate_zip_safety` passes both -- it reads the central directory and
    never touches member data -- so without the conversion each reaches the
    caller as an uncaught exception rather than the mapped refusal.
    """
    from app.processing.ingest import validation

    archive = build(tmp_path)

    # Positive control, both halves: zipfile really raises this, and the check
    # that runs first really does let the archive through.
    with zipfile.ZipFile(archive) as opened:
        with pytest.raises(raises):
            opened.read("layer.geojson")
    validation.validate_zip_safety(str(archive))

    with pytest.raises(UnsafeUploadError) as refused:
        validation.validate_content_directives(str(archive), "upload.zip")
    assert isinstance(refused.value, ValueError)


@pytest.mark.anyio
async def test_reupload_preview_maps_a_content_refusal_to_422(
    client, admin_auth_header, test_db_session, tmp_path
):
    """The sibling endpoint's mapping, which it did not have.

    `router_reupload` wrapped its preview in try/finally with no `except`, so a
    refusal that `preview_file` returns as a 422 with a message naming the fix
    came back from this route as a generic 500.
    """
    from tests.factories import get_user_id
    from tests.test_reupload import _create_dataset

    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_dataset(test_db_session, created_by=admin_id)

    archive = _archive_with_a_damaged_member(tmp_path)
    uploaded = await client.post(
        f"/datasets/{dataset.id}/reupload",
        files={"file": ("update.zip", archive.read_bytes(), "application/zip")},
        headers=admin_auth_header,
    )
    assert uploaded.status_code == 201, uploaded.text

    response = await client.post(
        f"/datasets/{dataset.id}/reupload/{uploaded.json()['job_id']}/preview",
        headers=admin_auth_header,
    )
    assert response.status_code == 422, response.text
    assert "could not be read" in response.json()["detail"]
