"""fix(#1528): HEAD and byte ranges on /datasets/{id}/download/cog.

Two defects, and the second is the one that matters for the format.

**HEAD answered 405.** Same FastAPI/starlette gap #1513 documented: ``APIRoute``
does not add HEAD alongside GET the way starlette's plain ``Route`` does, so a
bare ``@router.get`` answers ``405 allow: GET``.

**The local-storage branch advertised no ``Accept-Ranges`` and served no 206.**
A Cloud-Optimized GeoTIFF exists so a client can read the header and then fetch
only the tiles it needs by byte range. A COG endpoint that cannot serve ranges
forces the whole file down the wire, which is the thing the format was invented
to avoid.

Why this route's HEAD is BETTER than the export route's, not a copy of it:
``/datasets/{id}/export`` runs a live ogr2ogr/pyarrow conversion, so its length
is unknowable before generating the content and its HEAD omits Content-Length
under RFC 9110 section 9.3.2. This route serves STORED bytes. ``storage.size()``
is one stat, so HEAD carries a real Content-Length and a truthful
``Accept-Ranges: bytes``, and the GET it describes actually honours a Range.

The failure class these tests are built around is not "405" — #1513 established
a 405 alone does not hang GDAL, because vsicurl falls back to a plain GET. The
class is a response that is CONFIDENTLY WRONG: a Content-Length of 0 on a HEAD
(what starlette supplies for an empty body if the explicit header is dropped),
or a 206 whose Content-Range does not describe the bytes in the body. Both are
worse than the 405 they replace, because the 405 did not lie. Every length and
every range here is checked against the real stored bytes.

Requirements:
  - Docker database must be running (docker compose up db)
  - Run with: set -a && source ../.env.test && set +a
              uv run pytest tests/test_cog_head_ranges_1528.py -v
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.storage import get_storage
from app.processing.raster.models import RasterAsset

from tests.factories import get_user_id

# Big enough that a range is a genuine slice rather than the whole object, and
# that a multi-chunk range crosses the streaming chunk boundary at least once
# is checked separately by monkeypatching the chunk size (see
# test_range_spanning_multiple_chunks_is_byte_exact).
_COG_BYTES = bytes(range(256)) * 800  # 204_800 bytes, every byte value present


async def _raster_dataset(
    session,
    *,
    storage_backend: str = "local",
    asset_uri: str | None = None,
    visibility: str = "public",
) -> tuple[Dataset, RasterAsset]:
    """Create a Record + Dataset + RasterAsset for the COG download route."""
    admin_id = await get_user_id(session, "admin")
    record = Record(
        title=f"COG Head Ranges {uuid.uuid4().hex[:6]}",
        summary="Dataset for the #1528 HEAD/Range tests",
        theme_category=["test"],
        visibility=visibility,
        record_status="published",
        record_type="raster_dataset",
        created_by=admin_id,
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=f"cog_head_1528_{uuid.uuid4().hex[:8]}",
        source_format="geotiff",
        source_filename="test.tif",
    )
    session.add(dataset)
    await session.flush()

    raster_asset = RasterAsset(
        dataset_id=dataset.id,
        asset_uri=asset_uri
        or f"rasters/{dataset.id}/{uuid.uuid4().hex[:8]}/src.cog.tif",
        storage_backend=storage_backend,
    )
    session.add(raster_asset)
    await session.flush()
    await session.commit()
    await session.refresh(dataset)
    await session.refresh(raster_asset)
    return dataset, raster_asset


@pytest.fixture
async def local_cog(test_db_session):
    """A public raster dataset whose COG bytes really exist in local storage.

    The conftest points the storage singleton at a ``LocalStorageProvider``
    rooted in the per-test staging dir, so these are real bytes on a real disk
    read back through the real provider — a range assertion here compares
    against the stored object, not against a mock's idea of it.
    """
    dataset, raster_asset = await _raster_dataset(test_db_session)
    # Single-tenant: resolve_storage_key returns the logical uri unchanged.
    await get_storage().put(raster_asset.asset_uri, _COG_BYTES)
    return dataset, raster_asset


# ---------------------------------------------------------------------------
# Defect 1: HEAD
# ---------------------------------------------------------------------------


async def test_head_cog_is_not_405(
    client: AsyncClient, admin_auth_header: dict, local_cog
):
    """The reported bug, reduced to one assertion."""
    dataset, _ = local_cog

    resp = await client.head(
        f"/datasets/{dataset.id}/download/cog", headers=admin_auth_header
    )

    assert resp.status_code != 405, (
        f"HEAD on the COG download answered 405 (allow: "
        f"{resp.headers.get('allow')!r}); every client that probes before "
        f"downloading — GDAL/QGIS /vsicurl/, resumable downloaders, link "
        f"checkers — is refused."
    )
    assert resp.status_code == 200, (
        f"Expected HEAD to agree with GET's 200, got {resp.status_code}"
    )


async def test_head_cog_carries_the_real_content_length(
    client: AsyncClient, admin_auth_header: dict, local_cog
):
    """The decision that differs from the export route's HEAD.

    The export route omits Content-Length because a conversion's length is
    unknowable before running it. Here the bytes are already stored, so HEAD
    can and must state the real size — checked against the body a GET actually
    delivers, so a plausible-but-wrong length fails.
    """
    dataset, _ = local_cog

    head = await client.head(
        f"/datasets/{dataset.id}/download/cog", headers=admin_auth_header
    )
    get = await client.get(
        f"/datasets/{dataset.id}/download/cog", headers=admin_auth_header
    )

    assert head.status_code == get.status_code == 200
    assert head.content == b"", "A HEAD response must carry no body"
    assert len(get.content) == len(_COG_BYTES), "precondition: GET returns the object"

    assert "content-length" in head.headers, (
        "HEAD sent no Content-Length. The object is stored, so its size is one "
        "stat away; omitting it costs vsicurl an extra range GET for nothing."
    )
    assert head.headers["content-length"] == str(len(_COG_BYTES)), (
        f"HEAD advertised content-length={head.headers['content-length']!r} for "
        f"a {len(_COG_BYTES)}-byte object. A WRONG length is worse than the 405 "
        f"it replaces: starlette's default for an empty body is 0, which makes "
        f"a client read the COG as an empty file."
    )
    assert head.headers.get("content-type") == get.headers.get("content-type")
    assert head.headers.get("content-disposition") == get.headers.get(
        "content-disposition"
    ), "HEAD must advertise the filename the GET actually delivers"


async def test_head_cog_does_not_read_the_object(
    client: AsyncClient, admin_auth_header: dict, local_cog, monkeypatch
):
    """A HEAD must answer from metadata, never by streaming bytes it discards.

    Mirrors ``test_head_export_does_not_run_the_conversion``: a HEAD that reads
    a 5 GB COG to produce a length would hand any authorized caller a way to
    spend the full download cost per probe.
    """
    dataset, _ = local_cog
    storage = get_storage()
    reads: list[str] = []

    original_stream = storage.get_stream

    def _counting_stream(key):
        reads.append(key)
        return original_stream(key)

    monkeypatch.setattr(storage, "get_stream", _counting_stream)

    head = await client.head(
        f"/datasets/{dataset.id}/download/cog", headers=admin_auth_header
    )

    assert head.status_code == 200
    assert reads == [], (
        f"HEAD opened the object stream {len(reads)} time(s); it must answer "
        f"from storage.size() alone."
    )


async def test_head_cog_does_not_write_a_download_audit_row(
    client: AsyncClient, admin_auth_header: dict, local_cog, test_db_session
):
    """A probe is not a download.

    Same call #1513 made: recording ``dataset.download_cog`` for a HEAD would
    misreport who downloaded what, and every vsicurl open would inflate the
    count.
    """
    from app.modules.audit.models import AuditLog

    dataset, _ = local_cog

    async def _download_rows() -> int:
        result = await test_db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "dataset.download_cog",
                AuditLog.resource_id == dataset.id,
            )
        )
        return len(result.scalars().all())

    assert await _download_rows() == 0, "precondition: no audit rows yet"

    head = await client.head(
        f"/datasets/{dataset.id}/download/cog", headers=admin_auth_header
    )
    assert head.status_code == 200
    assert await _download_rows() == 0, (
        "HEAD wrote a dataset.download_cog audit row. Nothing was downloaded."
    )

    get = await client.get(
        f"/datasets/{dataset.id}/download/cog", headers=admin_auth_header
    )
    assert get.status_code == 200
    assert await _download_rows() == 1, "GET must still record exactly one download"


# ---------------------------------------------------------------------------
# Defect 1, failure-class parity: HEAD and GET must agree on EVERY status
# ---------------------------------------------------------------------------


async def test_head_cog_denial_matches_get(client: AsyncClient, test_db_session):
    """HEAD must not become an existence oracle GET is not."""
    dataset, _ = await _raster_dataset(test_db_session, visibility="private")

    head = await client.head(f"/datasets/{dataset.id}/download/cog")
    get = await client.get(f"/datasets/{dataset.id}/download/cog")

    assert head.status_code == get.status_code, (
        f"HEAD/GET disagree on a denial: {head.status_code} vs {get.status_code}. "
        f"A HEAD that skips the authorization the GET runs tells an anonymous "
        f"caller whether a private dataset exists."
    )
    assert head.status_code in {401, 403, 404}


async def test_head_cog_matches_get_on_missing_object(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """404 parity when the catalog row outlives the stored bytes.

    The dataset and RasterAsset exist; nothing was ever written to storage.
    """
    dataset, _ = await _raster_dataset(test_db_session)

    head = await client.head(
        f"/datasets/{dataset.id}/download/cog", headers=admin_auth_header
    )
    get = await client.get(
        f"/datasets/{dataset.id}/download/cog", headers=admin_auth_header
    )

    assert get.status_code == 404, (
        f"precondition: GET should 404, got {get.status_code}"
    )
    assert head.status_code == get.status_code, (
        f"HEAD/GET disagree on a missing object: {head.status_code} vs "
        f"{get.status_code}. A HEAD claiming 200 makes the client fail its "
        f"range GET instead."
    )


async def test_head_cog_matches_get_on_storage_failure(
    client: AsyncClient, admin_auth_header: dict, local_cog, monkeypatch
):
    """503 parity: a storage backend that throws must throw for both verbs.

    Distinct from the missing-object case above — that one is a clean 404, this
    one is the backend erroring — and it is the class HEAD is most likely to
    miss, because HEAD reaches storage by a different call (``size``) than the
    GET's (``get_stream``).
    """
    dataset, _ = local_cog
    storage = get_storage()

    async def _boom(*args, **kwargs):
        raise RuntimeError("backend exploded")

    monkeypatch.setattr(storage, "exists", _boom)

    head = await client.head(
        f"/datasets/{dataset.id}/download/cog", headers=admin_auth_header
    )
    get = await client.get(
        f"/datasets/{dataset.id}/download/cog", headers=admin_auth_header
    )

    assert get.status_code == 503, (
        f"precondition: GET should 503, got {get.status_code}"
    )
    assert head.status_code == get.status_code, (
        f"HEAD/GET disagree on a storage failure: {head.status_code} vs "
        f"{get.status_code}"
    )


async def test_head_cog_matches_get_on_non_raster(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """400 parity on the record-type gate."""
    from tests.factories import create_dataset

    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(
        test_db_session,
        created_by=admin_id,
        name="CogHeadNonRaster",
        visibility="public",
        record_status="published",
    )

    head = await client.head(
        f"/datasets/{ds.id}/download/cog", headers=admin_auth_header
    )
    get = await client.get(f"/datasets/{ds.id}/download/cog", headers=admin_auth_header)

    assert head.status_code == get.status_code == 400, (
        f"HEAD {head.status_code} vs GET {get.status_code}, expected both 400"
    )


@pytest.mark.parametrize("backend", ["s3", "remote"])
async def test_head_cog_redirect_matches_get(
    backend, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    """302 parity on both redirecting backends.

    These branches hand the client off to storage that serves its own HEAD and
    its own ranges, so the honest HEAD here is the same redirect the GET sends —
    not a fabricated 200 carrying a length this service never measured. A HEAD
    that answered 200 here would be inventing metadata for bytes it does not
    hold.

    The presign is stubbed because the test storage singleton is a
    ``LocalStorageProvider``, which raises NotImplementedError for it; the
    branch under test is the router's, not the provider's.
    """
    presigned = "https://s3.example.test/presigned-cog?sig=abc"
    monkeypatch.setattr(
        get_storage(),
        "generate_presigned_get_url",
        lambda key, expiration=3600: presigned,
    )

    dataset, _ = await _raster_dataset(
        test_db_session,
        storage_backend=backend,
        asset_uri=(
            "https://example.com/data.tif"
            if backend == "remote"
            else f"rasters/{uuid.uuid4().hex[:8]}/src.cog.tif"
        ),
    )

    with patch(
        "app.platform.security.validate_url_for_ssrf", new=AsyncMock(return_value=None)
    ):
        head = await client.head(
            f"/datasets/{dataset.id}/download/cog",
            headers=admin_auth_header,
            follow_redirects=False,
        )
        get = await client.get(
            f"/datasets/{dataset.id}/download/cog",
            headers=admin_auth_header,
            follow_redirects=False,
        )

    assert get.status_code == 302, (
        f"precondition: GET should 302, got {get.status_code}"
    )
    assert head.status_code == get.status_code, (
        f"HEAD/GET disagree on the {backend} redirect: {head.status_code} vs "
        f"{get.status_code}"
    )
    assert head.headers.get("location") == get.headers.get("location"), (
        "HEAD must redirect where the GET redirects"
    )
    assert (
        "content-length" not in head.headers or head.headers["content-length"] == "0"
    ), (
        "A redirect describes no representation; HEAD must not attach a size "
        "to one it never measured."
    )


async def test_head_cog_remote_ssrf_denial_matches_get(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """403 parity: HEAD must not skip the download-time SSRF re-validation.

    SEC-06 re-runs ``validate_url_for_ssrf`` on the remote branch to defeat
    DNS-rebinding TOCTOU. A HEAD that returned the redirect without it would
    hand a client the location the GET refuses to give.
    """
    from app.platform.security import SSRFError

    dataset, _ = await _raster_dataset(
        test_db_session, storage_backend="remote", asset_uri="https://example.com/d.tif"
    )

    with patch(
        "app.platform.security.validate_url_for_ssrf",
        new=AsyncMock(side_effect=SSRFError("resolves to a private address")),
    ):
        head = await client.head(
            f"/datasets/{dataset.id}/download/cog",
            headers=admin_auth_header,
            follow_redirects=False,
        )
        get = await client.get(
            f"/datasets/{dataset.id}/download/cog",
            headers=admin_auth_header,
            follow_redirects=False,
        )

    assert get.status_code == 403, (
        f"precondition: GET should 403, got {get.status_code}"
    )
    assert head.status_code == get.status_code, (
        f"HEAD/GET disagree on the SSRF denial: {head.status_code} vs {get.status_code}"
    )


# ---------------------------------------------------------------------------
# Defect 2: byte ranges. The point of the format.
# ---------------------------------------------------------------------------


async def test_get_cog_advertises_ranges_and_length(
    client: AsyncClient, admin_auth_header: dict, local_cog
):
    """The full GET must state the size and admit it serves ranges.

    The missing Content-Length is the second ingredient in the GDAL hang #1513
    documented: a fallback GET that carries no length leaves vsicurl deciding
    the object is empty.

    ``Accept-Encoding: identity`` is not incidental — see
    ``test_gzip_middleware_strips_content_length_from_the_full_cog_get`` for
    what the global GZipMiddleware does to this same response when the client
    offers gzip, which is the reason this assertion has to name an encoding at
    all.
    """
    dataset, _ = local_cog

    get = await client.get(
        f"/datasets/{dataset.id}/download/cog",
        headers={**admin_auth_header, "Accept-Encoding": "identity"},
    )

    assert get.status_code == 200
    assert get.headers.get("accept-ranges") == "bytes", (
        "The COG GET does not advertise range support, so a client must "
        "download the whole file to read one tile."
    )
    assert get.headers.get("content-length") == str(len(_COG_BYTES)), (
        f"GET advertised content-length="
        f"{get.headers.get('content-length')!r} for {len(_COG_BYTES)} bytes"
    )
    assert get.content == _COG_BYTES, "the full GET must still deliver the object"


async def test_gzip_middleware_strips_content_length_from_the_full_cog_get(
    client: AsyncClient, admin_auth_header: dict, local_cog
):
    """MEASURED LIMIT, pinned so it is a decision rather than a surprise.

    ``app/api/main.py`` installs ``GZipMiddleware(minimum_size=256)`` globally.
    Starlette 1.6.0's responder compresses any streaming 200 whose client
    offered gzip and DELETES the Content-Length while doing it
    (``middleware/gzip.py``, the ``more_body`` branch). So the length this route
    sets survives to the wire only for a client that does not ask for gzip.

    The COG path is unaffected, which is why this is recorded rather than
    worked around here:

      * HEAD keeps its length — an empty body is under ``minimum_size``, so the
        responder passes it through, and HEAD is where /vsicurl/ learns the
        size.
      * 206 keeps its length AND its Content-Range — the responder skips
        partial responses outright (``self.partial_response = status == 206``).

    What remains is a plain full-file download that is chunked instead of
    length-delimited, and a COG — already-compressed pixel data — being run
    through DEFLATE for no gain. Fixing that means excluding image types at the
    middleware, which is ``app/api/main.py``, outside this change.

    If someone later excludes ``image/tiff`` there, THIS test fails and the one
    above stops needing its ``identity`` header. That is the intended signal.
    """
    dataset, _ = local_cog

    get = await client.get(
        f"/datasets/{dataset.id}/download/cog",
        headers={**admin_auth_header, "Accept-Encoding": "gzip"},
    )

    assert get.status_code == 200
    assert get.content == _COG_BYTES, "the bytes are still correct once decoded"
    assert get.headers.get("accept-ranges") == "bytes", (
        "the range advertisement must survive compression — it is what tells "
        "the client it can skip the full download next time"
    )
    assert get.headers.get("content-encoding") == "gzip", (
        "Expected the global GZipMiddleware to compress this response. If it "
        "no longer does, image types were excluded at the middleware and this "
        "test should be deleted along with the Accept-Encoding: identity "
        "header in test_get_cog_advertises_ranges_and_length."
    )
    assert "content-length" not in get.headers, (
        "GZipMiddleware kept a Content-Length on a compressed streaming "
        "response; if starlette changed that, the identity workaround above is "
        "no longer needed."
    )


async def test_head_cog_advertises_ranges(
    client: AsyncClient, admin_auth_header: dict, local_cog
):
    """``Accept-Ranges`` on HEAD must be TRUE of the GET it describes.

    Asserted together with a real 206 below, so the advertisement cannot pass
    while the range support behind it is absent.
    """
    dataset, _ = local_cog

    head = await client.head(
        f"/datasets/{dataset.id}/download/cog", headers=admin_auth_header
    )

    assert head.headers.get("accept-ranges") == "bytes"


@pytest.mark.parametrize(
    ("header", "expected_start", "expected_end"),
    [
        # The COG access pattern: a small header read, then a tile read from
        # the middle of the file.
        ("bytes=0-511", 0, 511),
        ("bytes=100000-100999", 100_000, 100_999),
        # Open-ended: everything from an offset to EOF.
        (f"bytes={len(_COG_BYTES) - 10}-", len(_COG_BYTES) - 10, len(_COG_BYTES) - 1),
        # Suffix: the last N bytes, which is how a client finds a trailing
        # index without knowing the size.
        ("bytes=-1024", len(_COG_BYTES) - 1024, len(_COG_BYTES) - 1),
        # Last byte past EOF must be CLAMPED, not rejected (RFC 9110 14.1.1).
        (f"bytes=0-{len(_COG_BYTES) + 5000}", 0, len(_COG_BYTES) - 1),
        # Suffix longer than the object is the whole object.
        (f"bytes=-{len(_COG_BYTES) + 5000}", 0, len(_COG_BYTES) - 1),
    ],
)
async def test_range_request_returns_the_exact_slice(
    header,
    expected_start,
    expected_end,
    client: AsyncClient,
    admin_auth_header: dict,
    local_cog,
):
    """206, a correct Content-Range, and bytes that MATCH that slice.

    The status and the header are the cheap half. The assertion that carries
    the weight is the last one: a 206 whose body is not the slice its
    Content-Range names is succeed-with-garbage — the client writes a corrupt
    COG and never learns why.
    """
    dataset, _ = local_cog
    expected_body = _COG_BYTES[expected_start : expected_end + 1]

    resp = await client.get(
        f"/datasets/{dataset.id}/download/cog",
        headers={**admin_auth_header, "Range": header},
    )

    assert resp.status_code == 206, (
        f"Range {header!r} got {resp.status_code}, expected 206 Partial Content"
    )
    assert resp.headers.get("content-range") == (
        f"bytes {expected_start}-{expected_end}/{len(_COG_BYTES)}"
    ), f"Range {header!r} produced content-range={resp.headers.get('content-range')!r}"
    assert resp.headers.get("content-length") == str(len(expected_body))
    assert resp.headers.get("accept-ranges") == "bytes"
    assert resp.content == expected_body, (
        f"Range {header!r} returned {len(resp.content)} bytes that are NOT the "
        f"slice its Content-Range claims. This is the corrupt-download class: "
        f"the client cannot detect it."
    )


async def test_range_spanning_multiple_chunks_is_byte_exact(
    client: AsyncClient, admin_auth_header: dict, local_cog, monkeypatch
):
    """A range longer than one read chunk must reassemble in order.

    A range is streamed rather than buffered so a multi-GB range cannot pin
    memory, which means the chunk loop is real code with a real off-by-one
    surface. The chunk size is shrunk here so an ordinary-sized range crosses
    many boundaries; at the production 1 MiB every range in this file would fit
    in a single read and the loop would never be exercised.
    """
    from app.modules.catalog.datasets.api import router_export

    monkeypatch.setattr(router_export, "_COG_RANGE_CHUNK_BYTES", 997)

    dataset, _ = local_cog
    start, end = 1234, 40_000
    resp = await client.get(
        f"/datasets/{dataset.id}/download/cog",
        headers={**admin_auth_header, "Range": f"bytes={start}-{end}"},
    )

    assert resp.status_code == 206
    assert resp.content == _COG_BYTES[start : end + 1], (
        "A multi-chunk range did not reassemble to the stored slice"
    )
    assert len(resp.content) == end - start + 1


async def test_unsatisfiable_range_returns_416_with_the_size(
    client: AsyncClient, admin_auth_header: dict, local_cog
):
    """Reject, do not silently serve something else.

    A first-byte-pos past the end cannot be satisfied. RFC 9110 section 15.5.17
    requires 416 with a ``Content-Range: bytes * /size`` so the client learns the
    real size and can retry — answering 200 with the whole object here would
    hand a client that asked for 1 KB a whole COG it will splice into the wrong
    offset.
    """
    dataset, _ = local_cog
    past_eof = len(_COG_BYTES) + 10

    resp = await client.get(
        f"/datasets/{dataset.id}/download/cog",
        headers={**admin_auth_header, "Range": f"bytes={past_eof}-{past_eof + 100}"},
    )

    assert resp.status_code == 416, (
        f"A range starting past EOF got {resp.status_code}; expected 416"
    )
    assert resp.headers.get("content-range") == f"bytes */{len(_COG_BYTES)}", (
        f"416 must report the real size, got {resp.headers.get('content-range')!r}"
    )
    assert resp.headers.get("accept-ranges") == "bytes", (
        "the client that most needs to know it may retry with a corrected "
        "range is the one that just sent a bad one"
    )
    assert "content-disposition" not in resp.headers, (
        "This response's body is the JSON error, not the raster. Labelling it "
        "'attachment; filename=\"....cog.tif\"' makes a browser save an error "
        "document under the COG's name."
    )


async def test_zero_byte_object_answers_416_for_any_range(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """An empty stored object has no byte to hand out, so every range is 416.

    A truncated-to-zero COG is a real state (an interrupted ingest), and it is
    the one size at which the range arithmetic has no valid answer: ``bytes=0-``
    names byte 0 of a file with no byte 0. RFC 9110 section 15.5.17 says 416,
    and the Content-Range must still report the size — 0 — so the client can
    tell "empty" from "you asked wrongly".
    """
    dataset, raster_asset = await _raster_dataset(test_db_session)
    await get_storage().put(raster_asset.asset_uri, b"")

    head = await client.head(
        f"/datasets/{dataset.id}/download/cog", headers=admin_auth_header
    )
    assert head.status_code == 200
    assert head.headers.get("content-length") == "0"

    for header in ("bytes=0-", "bytes=0-99", "bytes=-10"):
        resp = await client.get(
            f"/datasets/{dataset.id}/download/cog",
            headers={**admin_auth_header, "Range": header},
        )
        assert resp.status_code == 416, (
            f"Range {header!r} on a zero-byte object got {resp.status_code}"
        )
        assert resp.headers.get("content-range") == "bytes */0"


@pytest.mark.parametrize(
    "header",
    [
        "bytes=abc-def",  # not numbers
        "bytes=500-100",  # last < first
        "items=0-100",  # unsupported unit
        "bytes=",  # empty spec
        "bytes=-",  # neither first nor suffix
        "0-100",  # no unit at all
        "bytes=0-100, 200-300",  # multipart/byteranges: not implemented here
    ],
)
async def test_unusable_range_is_ignored_and_serves_the_whole_object(
    header, client: AsyncClient, admin_auth_header: dict, local_cog
):
    """The abort class: a Range this route cannot honour must not 500 or 206.

    RFC 9110 section 14.2 says an unsatisfiable-because-invalid Range is to be
    IGNORED, and section 14.2 permits serving a single range or none at all for
    a multi-range request. Both land on the same safe answer: 200 with the
    complete representation. What must never happen is a 206 whose body is not
    what Content-Range claims — a client that asked for two ranges and got one
    labelled as both writes a corrupt file.
    """
    dataset, _ = local_cog

    resp = await client.get(
        f"/datasets/{dataset.id}/download/cog",
        headers={**admin_auth_header, "Range": header},
    )

    assert resp.status_code == 200, (
        f"Range {header!r} produced {resp.status_code}; an unusable Range must "
        f"be ignored, not answered with a partial or an error."
    )
    assert "content-range" not in resp.headers, (
        f"Range {header!r} produced a 200 carrying content-range="
        f"{resp.headers.get('content-range')!r}, which describes a partial "
        f"response this is not."
    )
    assert resp.content == _COG_BYTES


async def test_head_with_a_range_header_still_describes_the_whole_object(
    client: AsyncClient, admin_auth_header: dict, local_cog
):
    """A HEAD is a probe for the representation, not for a slice.

    vsicurl sends a plain HEAD, but link checkers and proxies do send Range on
    HEAD. Answering 206 with a partial Content-Length would tell the client the
    object is 512 bytes long.
    """
    dataset, _ = local_cog

    head = await client.head(
        f"/datasets/{dataset.id}/download/cog",
        headers={**admin_auth_header, "Range": "bytes=0-511"},
    )

    assert head.status_code == 200
    assert head.headers.get("content-length") == str(len(_COG_BYTES)), (
        "HEAD reported a partial length as the object size"
    )


async def test_range_request_is_denied_like_a_plain_get(
    client: AsyncClient, test_db_session
):
    """The range path must not skip authorization.

    Ranges are served from a branch reached after the access checks; this pins
    that, so a future refactor that hoists range handling above them fails here
    rather than shipping an anonymous read of a private COG.
    """
    dataset, raster_asset = await _raster_dataset(test_db_session, visibility="private")
    await get_storage().put(raster_asset.asset_uri, _COG_BYTES)

    resp = await client.get(
        f"/datasets/{dataset.id}/download/cog", headers={"Range": "bytes=0-511"}
    )

    assert resp.status_code in {401, 403, 404}, (
        f"An anonymous range request on a private COG got {resp.status_code}"
    )
    assert resp.content != _COG_BYTES[:512]


async def test_range_request_does_not_read_the_whole_object(
    client: AsyncClient, admin_auth_header: dict, local_cog, monkeypatch
):
    """The efficiency claim, made falsifiable.

    ``Accept-Ranges`` is only worth advertising if a range actually avoids
    reading the rest of the file. A 206 built by streaming the whole object and
    slicing it would pass every assertion above while delivering none of the
    benefit the format exists for.
    """
    dataset, _ = local_cog
    storage = get_storage()
    full_reads: list[str] = []
    original_stream = storage.get_stream

    def _counting_stream(key):
        full_reads.append(key)
        return original_stream(key)

    monkeypatch.setattr(storage, "get_stream", _counting_stream)

    resp = await client.get(
        f"/datasets/{dataset.id}/download/cog",
        headers={**admin_auth_header, "Range": "bytes=0-511"},
    )

    assert resp.status_code == 206
    assert full_reads == [], (
        "A range request opened the full-object stream; the range must be read "
        "through storage.get_range()."
    )


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------


async def test_cog_head_stays_out_of_the_openapi_schema(client: AsyncClient):
    """The HEAD route is derived, not new API surface.

    Same call ``_clone_api_route`` and fix(#1513) make: a derived route
    documents nothing the canonical one does not, and publishing it would add a
    ``headDownloadCog`` to both SDKs and the CLI for no gain.
    """
    spec = (await client.get("/openapi.json")).json()
    methods = spec["paths"]["/datasets/{dataset_id}/download/cog"]

    assert set(methods) == {"get"}, (
        f"The COG download path publishes {sorted(methods)}; the HEAD route "
        f"must be registered with include_in_schema=False."
    )
