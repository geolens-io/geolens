"""fix(#1513): HEAD on /datasets/{id}/export must answer, not 405.

FastAPI's ``APIRoute`` does not add HEAD alongside GET the way starlette's
plain ``Route`` does, so a bare ``@router.get`` answers ``405 allow: GET``.
``_register_standards_head_routes`` (backend/app/api/main.py, fix #1470/#1478)
closes that gap for the standards surface only; ``/datasets/{id}/export`` is a
native download route and fell outside it.

Why it matters concretely, measured with GDAL 3.13.0 against a server that
streams the plain GET without a Content-Length (what the production edge does):

  * HEAD -> 405: ``HEAD not allowed. Retrying with GET``; the fallback GET
    learns no size either, so vsicurl decides the object is empty
    (``Request at offset 0, after end of file``), probes the parent path as a
    directory, and fails to open the layer at all.
  * HEAD -> 200 with no Content-Length: ``HEAD did not provide file size.
    Retrying with limited range GET``; the 206 carries Content-Range, vsicurl
    learns the size, and the layer opens — with ZERO full-body GETs.

The design decision these tests pin: HEAD answers with the headers a GET would
send and deliberately WITHOUT Content-Length, because the length of an export
is only known after a conversion that HEAD must not run (RFC 9110 section
9.3.2 permits omitting header fields whose value is determined only while
generating the content). ``content-length: 0`` would be worse than the 405 —
it is a wrong answer rather than no answer — so its absence is asserted.

Requirements:
  - Docker database must be running (docker compose up db)
  - Run with: set -a && source ../.env.test && set +a
              uv run pytest tests/test_export_head_1513.py -v
"""

import os
import shutil
import tempfile

import pytest
from httpx import AsyncClient

from app.processing.export.ogr import FORMAT_MAP

from tests.factories import create_dataset, get_user_id


@pytest.fixture
def mock_export_service(monkeypatch):
    """Stand in for ogr2ogr, and count how often the conversion actually runs.

    The counter is the point: a HEAD that runs a full export and throws the
    bytes away would pass a status-code assertion while handing anyone an
    unauthenticated way to spend a worker. ``calls`` makes that visible.
    """
    temp_dir = tempfile.mkdtemp(prefix="test_export_head_1513_")
    calls: list[str] = []

    async def _fake_export(
        table_name,
        dataset_name,
        format_key,
        *,
        schema,
        target_srs=None,
        bbox=None,
        where=None,
        column_info=None,
    ):
        calls.append(format_key)
        # Derive names through the same helper the route uses for HEAD, so a
        # header comparison between the two verbs tests the ROUTE's wiring
        # rather than this fixture's guess at a filename.
        from app.processing.export.service import export_descriptor

        filename, media = export_descriptor(dataset_name, format_key)
        file_path = os.path.join(temp_dir, filename)
        with open(file_path, "wb") as f:
            f.write(b"mock export data")
        return file_path, filename, media

    monkeypatch.setattr("app.processing.export.router.export_dataset", _fake_export)
    _fake_export.calls = calls  # type: ignore[attr-defined]

    yield _fake_export

    if os.path.isdir(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)


async def _public_dataset(test_db_session, name: str, **kwargs):
    admin_id = await get_user_id(test_db_session, "admin")
    return await create_dataset(
        test_db_session,
        created_by=admin_id,
        name=name,
        visibility=kwargs.pop("visibility", "public"),
        record_status=kwargs.pop("record_status", "published"),
        **kwargs,
    )


async def test_head_export_is_not_405(
    client: AsyncClient,
    test_db_session,
    mock_export_service,
):
    """The reported bug, reduced to one assertion."""
    ds = await _public_dataset(test_db_session, "HeadExportNot405")

    resp = await client.head(f"/datasets/{ds.id}/export?format=geojson")

    assert resp.status_code != 405, (
        f"HEAD on the export route answered 405 (allow: "
        f"{resp.headers.get('allow')!r}); GDAL /vsicurl/ and any client that "
        f"probes before downloading gets refused."
    )
    assert resp.status_code == 200, (
        f"Expected HEAD to agree with GET's 200, got {resp.status_code}"
    )


@pytest.mark.parametrize("fmt", ["gpkg", "geojson", "csv", "shp"])
async def test_head_export_agrees_with_get(
    fmt,
    client: AsyncClient,
    test_db_session,
    mock_export_service,
):
    """HEAD and GET must agree on status and content-type, for every format.

    Includes ``shp``, whose download is a zip built after the conversion — the
    format where a HEAD is most tempted to guess wrong about the media type.
    """
    ds = await _public_dataset(test_db_session, f"HeadExportAgrees_{fmt}")

    head = await client.head(f"/datasets/{ds.id}/export?format={fmt}")
    get = await client.get(f"/datasets/{ds.id}/export?format={fmt}")

    assert head.status_code == get.status_code, (
        f"HEAD/GET status disagree for {fmt!r}: {head.status_code} vs {get.status_code}"
    )
    assert head.headers.get("content-type") == get.headers.get("content-type"), (
        f"HEAD/GET content-type disagree for {fmt!r}: "
        f"{head.headers.get('content-type')!r} vs {get.headers.get('content-type')!r}"
    )
    # startswith, not equality: starlette appends "; charset=utf-8" to any
    # text/* media type, on both verbs (csv is the one format that hits it).
    assert head.headers.get("content-type", "").startswith(FORMAT_MAP[fmt]["media"]), (
        f"HEAD advertised {head.headers.get('content-type')!r} for {fmt!r}, "
        f"expected the format's {FORMAT_MAP[fmt]['media']!r}"
    )
    assert head.content == b"", "A HEAD response must carry no body"


@pytest.mark.parametrize(
    "name",
    [
        "HeadExportDisposition",
        # Non-ASCII title: starlette's FileResponse switches to the RFC 5987
        # filename* form here, so this catches a HEAD that only handles the
        # easy branch.
        "Zürich Höhenmodell",
    ],
)
async def test_head_export_content_disposition_matches_get(
    name,
    client: AsyncClient,
    test_db_session,
    mock_export_service,
):
    """Byte-for-byte parity on content-disposition.

    GET's value is derived by starlette's ``FileResponse``; HEAD's is derived
    by the route. This is the anti-drift guard for that duplication — if
    starlette changes its rule, this fails rather than shipping a HEAD that
    advertises a different filename than the GET delivers.
    """
    ds = await _public_dataset(test_db_session, name)

    head = await client.head(f"/datasets/{ds.id}/export?format=geojson")
    get = await client.get(f"/datasets/{ds.id}/export?format=geojson")

    assert head.headers.get("content-disposition") == get.headers.get(
        "content-disposition"
    ), (
        f"HEAD/GET content-disposition disagree for {name!r}: "
        f"{head.headers.get('content-disposition')!r} vs "
        f"{get.headers.get('content-disposition')!r}"
    )


async def test_head_export_omits_content_length_and_advertises_ranges(
    client: AsyncClient,
    test_db_session,
    mock_export_service,
):
    """The two headers that decide whether /vsicurl/ can open the file.

    ``accept-ranges: bytes`` must be truthful — the route's GET is a
    ``FileResponse``, which serves 206 byte ranges — and ``content-length``
    must be ABSENT rather than 0.
    """
    ds = await _public_dataset(test_db_session, "HeadExportHeaders")

    head = await client.head(f"/datasets/{ds.id}/export?format=geojson")
    get = await client.get(f"/datasets/{ds.id}/export?format=geojson")

    assert head.status_code == 200
    assert head.headers.get("accept-ranges") == "bytes", (
        "HEAD must advertise range support; vsicurl falls back to a limited "
        "range GET to learn the size when Content-Length is missing."
    )
    assert get.headers.get("accept-ranges") == "bytes", (
        "The advertisement must be true of the GET it describes."
    )
    assert "content-length" not in head.headers, (
        f"HEAD sent content-length={head.headers.get('content-length')!r}. The "
        f"size is unknown before conversion, and a wrong length (0) makes a "
        f"client treat the export as an empty file."
    )


async def test_head_export_does_not_run_the_conversion(
    client: AsyncClient,
    test_db_session,
    mock_export_service,
):
    """A HEAD must not spend an ogr2ogr run to produce bytes it discards."""
    ds = await _public_dataset(test_db_session, "HeadExportNoConversion")

    head = await client.head(f"/datasets/{ds.id}/export?format=geojson")

    assert head.status_code == 200
    assert mock_export_service.calls == [], (
        f"HEAD ran the export conversion {len(mock_export_service.calls)} "
        f"time(s). Every HEAD would then cost a full table conversion — an "
        f"unauthenticated amplification foot-gun on a public dataset."
    )

    get = await client.get(f"/datasets/{ds.id}/export?format=geojson")

    assert get.status_code == 200
    assert mock_export_service.calls == ["geojson"], (
        "GET must still run exactly one conversion"
    )


async def test_head_export_does_not_run_the_parquet_conversion(
    client: AsyncClient,
    test_db_session,
    monkeypatch,
):
    """Same guard for the second, non-ogr2ogr conversion path (pyarrow)."""
    calls: list[str] = []

    async def _fake_parquet(*args, **kwargs):
        calls.append("parquet")
        raise AssertionError("parquet writer must not run for a HEAD")

    monkeypatch.setattr("app.processing.export.parquet.export_parquet", _fake_parquet)
    ds = await _public_dataset(test_db_session, "HeadExportParquet")

    head = await client.head(f"/datasets/{ds.id}/export?format=parquet")

    assert head.status_code == 200
    assert calls == [], "HEAD ran the GeoParquet writer"
    assert "content-length" not in head.headers


async def test_head_export_denial_matches_get(
    client: AsyncClient,
    test_db_session,
):
    """HEAD must not become a side channel that GET is not.

    An anonymous caller gets 404 for a private dataset on GET; HEAD has to
    return the same, or HEAD becomes an existence oracle for hidden datasets.
    """
    ds = await _public_dataset(
        test_db_session, "HeadExportPrivateDenied", visibility="private"
    )

    head = await client.head(f"/datasets/{ds.id}/export?format=geojson")
    get = await client.get(f"/datasets/{ds.id}/export?format=geojson")

    assert head.status_code == get.status_code, (
        f"HEAD/GET disagree on a denial: {head.status_code} vs {get.status_code}"
    )
    assert head.status_code in {401, 403, 404}


async def test_head_export_rejects_raster_like_get(
    client: AsyncClient,
    test_db_session,
    mock_export_service,
):
    """Validation parity: a pre-conversion 400 must reach HEAD too."""
    ds = await _public_dataset(
        test_db_session,
        "HeadExportRaster",
        record_type="raster_dataset",
        geometry_type=None,
    )

    head = await client.head(f"/datasets/{ds.id}/export?format=geojson")
    get = await client.get(f"/datasets/{ds.id}/export?format=geojson")

    assert head.status_code == get.status_code == 400, (
        f"HEAD {head.status_code} vs GET {get.status_code}, expected both 400"
    )


async def test_head_export_stays_out_of_the_openapi_schema(client: AsyncClient):
    """The HEAD route is derived, not new API surface.

    ``_clone_api_route`` hides the standards HEAD routes for the same reason:
    "A derived route documents nothing the canonical one does not, and
    publishing it would churn every generated SDK." Publishing this one would
    add a ``headExportDataset`` to both SDKs and the CLI for no gain.
    """
    spec = (await client.get("/openapi.json")).json()
    methods = spec["paths"]["/datasets/{dataset_id}/export"]

    assert set(methods) == {"get"}, (
        f"Export path publishes {sorted(methods)}; the HEAD route must be "
        f"registered with include_in_schema=False."
    )
