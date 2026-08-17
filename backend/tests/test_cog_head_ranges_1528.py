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

The review findings on the PR belong to that same class, which is why they live
here rather than in a module of their own. The last section is the sharpest case
of it: two 206 responses that are each individually truthful, taken from either
side of a raster replacement, assembling into a file that is neither COG.

Requirements:
  - Docker database must be running (docker compose up db)
  - Run with: set -a && source ../.env.test && set +a
              uv run pytest tests/test_cog_head_ranges_1528.py -v
"""

import hashlib
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
    sha256: str | None = None,
) -> tuple[Dataset, RasterAsset]:
    """Create a Record + Dataset + RasterAsset for the COG download route.

    ``sha256`` is the digest of the COG bytes, which real ingest always stamps
    (``tasks_raster_common.py`` on create, ``tasks_raster_swap.py`` on replace)
    and which fix(#1540 review P2) turns into the response ETag. It stays
    optional because rows predating the column exist and must still download.
    """
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
        sha256=sha256,
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

    The row carries the digest of those exact bytes, because a real one does:
    ingest stamps ``sha256`` from ``sha256_file`` over the converted COG. The
    ETag assertions below would prove nothing against a row whose digest was
    invented here.
    """
    dataset, raster_asset = await _raster_dataset(
        test_db_session, sha256=hashlib.sha256(_COG_BYTES).hexdigest()
    )
    # Single-tenant: resolve_storage_key returns the logical uri unchanged.
    await get_storage().put(raster_asset.asset_uri, _COG_BYTES)
    return dataset, raster_asset


# A second COG for the replacement cases. Same length as `_COG_BYTES` so a
# splice is about CONTENT rather than about the file getting shorter, and
# byte-for-byte different at every offset (i vs 255-i never coincide), so a
# response that silently continued across the replacement is detectable
# wherever the client resumed.
_REPLACEMENT_BYTES = bytes(range(255, -1, -1)) * 800


async def _complete_a_replacement(session, raster_asset, new_bytes: bytes) -> str:
    """Land a raster replacement, the way a finished replace job leaves it.

    ``_write_swapped_fields`` (``app/processing/ingest/tasks_raster_swap.py``)
    points the SAME asset row at a NEW storage key and restamps ``sha256`` and
    ``size_bytes``; the dataset id, and therefore the download URL, do not move.
    That is what makes the URL stable and its bytes not: two range requests to
    one URL, either side of this, read two different objects.

    Only the three fields the download route reads are set here. Running the
    real job would need GDAL, a source upload and the queue — this module is
    about what the download route does once the swap has happened.
    """
    new_key = f"rasters/{uuid.uuid4().hex[:8]}/replacement.cog.tif"
    await get_storage().put(new_key, new_bytes)
    raster_asset.asset_uri = new_key
    raster_asset.sha256 = hashlib.sha256(new_bytes).hexdigest()
    raster_asset.size_bytes = len(new_bytes)
    session.add(raster_asset)
    await session.commit()
    return new_key


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

    ``size`` is the call to break, and since fix(#1540 review P2) it is the ONLY
    one the stat makes: breaking ``exists`` used to fail both verbs here and now
    fails neither, because nothing calls it. A ``RuntimeError`` rather than a
    ``FileNotFoundError`` on purpose — the latter is the 404 the sibling test
    covers, and this one is about the 503 the broad handler is for.
    """
    dataset, _ = local_cog
    storage = get_storage()

    async def _boom(*args, **kwargs):
        raise RuntimeError("backend exploded")

    monkeypatch.setattr(storage, "size", _boom)

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


async def test_a_delete_racing_the_stat_is_a_404_not_a_503(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    """fix(#1540 review P2): an object that vanished is gone, not broken.

    The stat used to be ``exists()`` and then ``size()``, and a delete landing
    between them produced exactly the pair asserted here: ``exists()`` answering
    yes about an object that was there when it looked, and ``size()`` raising
    ``FileNotFoundError`` about the same key a moment later. The broad handler
    caught that raise and called it 503 — telling the client the backend was
    unwell and to come back later, about a COG that is never coming back.

    ``exists`` is monkeypatched to the stale answer rather than the test trying
    to win a real race; the ``FileNotFoundError`` is real, raised by ``stat()``
    on a file that genuinely is not there. Since the fix, ``exists`` is not
    consulted at all — which is why the lie changes nothing and the missing
    bytes answer 404 on both verbs.
    """
    dataset, _ = await _raster_dataset(test_db_session)  # local backend, no bytes
    storage = get_storage()

    async def _stale_yes(key):
        return True

    monkeypatch.setattr(storage, "exists", _stale_yes)

    head = await client.head(
        f"/datasets/{dataset.id}/download/cog", headers=admin_auth_header
    )
    get = await client.get(
        f"/datasets/{dataset.id}/download/cog", headers=admin_auth_header
    )

    assert (head.status_code, get.status_code) == (404, 404), (
        f"HEAD {head.status_code} / GET {get.status_code} for bytes that are "
        f"gone. 503 here means the existence check is back and the object "
        f"disappeared inside the window between it and the size call."
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


@pytest.mark.parametrize("backend", ["remote"])
async def test_head_cog_redirect_matches_get(
    backend, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    """302 parity on the ``remote`` backend.

    This branch hands the client off to a third-party origin that serves its
    own HEAD and its own ranges, at a URL this service never signed. The honest
    HEAD is therefore the same redirect the GET sends — not a fabricated 200
    carrying a length this service never measured, which would be inventing
    metadata for bytes it does not hold.

    ``s3`` used to be parametrized here too and no longer is: fix(#1540) review
    P1. That URL IS signed by this service, for ``get_object``, and the HTTP
    method is part of an S3/MinIO SigV4 signature — so the redirect a HEAD
    followed landed on a 403. See
    ``test_head_cog_on_s3_is_answered_from_object_metadata`` for the fix, and
    ``test_s3_head_and_get_are_deliberately_asymmetric`` for the invariant that
    replaces this one on that backend.

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


@pytest.fixture
def s3_storage(monkeypatch):
    """Point the storage singleton at a real ``S3StorageProvider`` on moto.

    A stub would let this suite assert whatever it liked about the object's
    size. moto runs the actual boto3 ``head_object`` against a bucket holding
    the actual bytes, so the Content-Length the route reports below is measured
    the same way a MinIO deployment would measure it.

    What moto CANNOT show is the failure itself: it does not verify SigV4
    signatures, so a presigned URL it mints is accepted for any method. The 403
    was measured against a real MinIO instead — see the module docstring of
    ``test_cog_s3_head_wire_1540.py``, which replays the whole route over a
    socket against one.
    """
    import boto3
    from moto import mock_aws

    import app.platform.storage.provider as storage_provider_module
    from app.platform.storage.s3 import S3StorageProvider

    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(var, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="cog-1540")
        provider = S3StorageProvider(
            bucket="cog-1540",
            region="us-east-1",
            access_key_id="testing",
            secret_access_key="testing",
        )
        monkeypatch.setattr(storage_provider_module, "_storage", provider)
        yield provider


async def test_head_cog_on_s3_is_answered_from_object_metadata(
    client: AsyncClient, admin_auth_header: dict, test_db_session, s3_storage
):
    """fix(#1540) review P1: the S3 HEAD must not be a redirect.

    ``generate_presigned_get_url`` signs ``get_object``, and the HTTP method is
    part of an S3/MinIO SigV4 canonical request. A 302 does not rewrite the
    method (RFC 9110 section 15.4 reserves that for 303), so a redirect-
    following client re-issued its HEAD against a URL signed for GET and was
    refused — MEASURED at 403 against MinIO RELEASE.2025-09-07. Every
    ``/vsicurl/`` open starts with that probe, so the feature this PR exists to
    deliver was broken on exactly the deployments that store COGs in a bucket.

    The assertion is the feature, not the plumbing: a real client, following
    redirects the way curl and GDAL do, gets 200 with ``Accept-Ranges`` and the
    object's true length. ``head.history == []`` is the sharp half — it fails if
    this ever regresses to answering with a redirect, whether or not whatever
    sits behind that redirect happens to reply 200.
    """
    dataset, raster_asset = await _raster_dataset(
        test_db_session,
        storage_backend="s3",
        asset_uri=f"rasters/{uuid.uuid4().hex[:8]}/src.cog.tif",
        sha256=hashlib.sha256(_COG_BYTES).hexdigest(),
    )
    await s3_storage.put(raster_asset.asset_uri, _COG_BYTES)

    head = await client.head(
        f"/datasets/{dataset.id}/download/cog",
        headers=admin_auth_header,
        follow_redirects=True,
    )

    assert head.status_code == 200, (
        f"HEAD on the s3 backend returned {head.status_code} after "
        f"{len(head.history)} redirect(s); a presigned GET URL refuses HEAD, so "
        f"this route has to answer the probe itself."
    )
    # fix(#1540 review P2): this HEAD is the only answer an s3 deployment gets
    # from this process — the GET redirects, and the bucket then applies its own
    # validator to any range. A client that wants to resume safely picks the
    # version up here or nowhere.
    assert head.headers.get("etag") == f'"{raster_asset.sha256}"', (
        f"the s3 HEAD carried etag={head.headers.get('etag')!r}; a probe that "
        f"advertises Accept-Ranges without naming a version tells a resumable "
        f"client nothing it can check its next request against."
    )
    assert head.history == [], (
        f"HEAD was answered with a redirect to "
        f"{[r.headers.get('location') for r in head.history]}. That URL is "
        f"signed for get_object and rejects HEAD with 403."
    )
    assert head.headers.get("content-length") == str(len(_COG_BYTES)), (
        f"HEAD reported content-length="
        f"{head.headers.get('content-length')!r} for a "
        f"{len(_COG_BYTES)}-byte object"
    )
    assert head.headers.get("accept-ranges") == "bytes"


async def test_s3_head_and_get_are_deliberately_asymmetric(
    client: AsyncClient, admin_auth_header: dict, test_db_session, s3_storage
):
    """HEAD 200 / GET 302 on s3, on purpose. This replaces a parity assertion.

    ``test_head_cog_redirect_matches_get`` used to run for ``s3`` as well and
    asserted that HEAD and GET agree on status. fix(#1540) review P1 retires
    that invariant for this backend rather than dropping it silently, because
    the asymmetry IS the fix: HEAD no longer travels the redirect, since the
    presigned URL at the end of it is signed for GET and answers a HEAD with
    403. Parity with a broken GET-shaped answer was the bug.

    The GET is deliberately untouched. The bytes must keep coming from the
    bucket rather than through this process — a presigned GET honours a Range
    once the client gets there, and proxying multi-GB COGs through the API to
    avoid one redirect would trade a signature bug for a bandwidth bill.
    """
    dataset, raster_asset = await _raster_dataset(
        test_db_session,
        storage_backend="s3",
        asset_uri=f"rasters/{uuid.uuid4().hex[:8]}/src.cog.tif",
    )
    await s3_storage.put(raster_asset.asset_uri, _COG_BYTES)

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

    assert (head.status_code, get.status_code) == (200, 302), (
        f"expected the deliberate HEAD 200 / GET 302 split on s3, got "
        f"HEAD {head.status_code} / GET {get.status_code}. Equal statuses here "
        f"mean HEAD is back on the redirect."
    )
    assert "location" not in head.headers
    location = get.headers["location"]
    assert raster_asset.asset_uri in location, (
        f"the GET redirected to {location!r}, which does not name the object"
    )
    # Signature parameter, not a specific one: boto3 picks SigV2 or SigV4 from
    # the endpoint it is talking to, and this assertion is about the redirect
    # still being presigned, not about which scheme signed it.
    assert "Signature=" in location, (
        f"the GET redirected to an UNSIGNED url ({location!r}); a public URL "
        f"to a private bucket object is either broken or a leak."
    )


async def test_head_cog_on_a_missing_s3_object_is_404(
    client: AsyncClient, admin_auth_header: dict, test_db_session, s3_storage
):
    """A HEAD for bytes the bucket does not hold answers 404, like local does.

    Routing both branches through ``_cog_object_size`` is what stops the S3
    HEAD drifting into its own error vocabulary — the local counterpart is
    ``test_head_cog_matches_get_on_missing_object``. Before fix(#1540) the S3
    branch stat'd nothing at all: it answered 302 to a presigned URL for a key
    with no object behind it, so the 404 arrived from the bucket one hop later
    and only for a client that followed.
    """
    dataset, _ = await _raster_dataset(
        test_db_session,
        storage_backend="s3",
        asset_uri=f"rasters/{uuid.uuid4().hex[:8]}/absent.cog.tif",
    )

    head = await client.head(
        f"/datasets/{dataset.id}/download/cog",
        headers=admin_auth_header,
        follow_redirects=True,
    )

    # The 404 alone is NOT the assertion. Before the fix this test passed for
    # the wrong reason: the route answered 302 to an s3.amazonaws.com URL,
    # ASGITransport handed that back to the same app, no route matched, and the
    # 404 came from the router rather than from the object store. `history`
    # is what separates "this endpoint stat'd the bucket and found nothing"
    # from "a redirect fell off the end of the world".
    assert head.history == [], (
        f"HEAD was redirected to "
        f"{[r.headers.get('location') for r in head.history]} instead of "
        f"stat'ing the object; any 404 after that is the redirect's, not this "
        f"route's."
    )
    assert head.status_code == 404, (
        f"HEAD on a missing s3 object returned {head.status_code}, not 404"
    )


async def test_head_cog_issues_exactly_one_s3_metadata_call(
    client: AsyncClient, admin_auth_header: dict, test_db_session, s3_storage
):
    """fix(#1540 review P2): one ``HeadObject`` per probe, not two.

    The reason this PR answers HEAD here instead of signing a second URL for
    ``head_object`` is that it is ONE round trip. ``exists()`` then ``size()``
    quietly made it two — both are ``head_object`` on the S3 provider — so every
    ``/vsicurl/`` open paid two object-store round trips and two request charges
    for one probe, and the argument the design was chosen on stopped being true.

    Counted at the botocore layer rather than by patching the provider, so it is
    requests that are counted and not method calls. The recorded sequence is
    asserted whole: a ``GetObject`` appearing here would mean the HEAD had
    started reading the object to learn its length, which is the amplification
    ``_cog_head_response`` exists to avoid.
    """
    dataset, raster_asset = await _raster_dataset(
        test_db_session,
        storage_backend="s3",
        asset_uri=f"rasters/{uuid.uuid4().hex[:8]}/src.cog.tif",
    )
    await s3_storage.put(raster_asset.asset_uri, _COG_BYTES)

    calls: list[str] = []
    s3_storage.client.meta.events.register(
        "before-call.s3", lambda model, **kwargs: calls.append(model.name)
    )

    head = await client.head(
        f"/datasets/{dataset.id}/download/cog",
        headers=admin_auth_header,
        follow_redirects=True,
    )

    assert head.status_code == 200, f"precondition: HEAD should 200, got {head}"
    assert calls == ["HeadObject"], (
        f"the HEAD made {len(calls)} S3 request(s) {calls}, not one HeadObject. "
        f"exists() and size() are both head_object, so splitting the stat in two "
        f"doubles the round trips and the request charges on every probe."
    )


async def test_a_stale_resume_on_s3_is_not_redirected(
    client: AsyncClient, admin_auth_header: dict, test_db_session, s3_storage
):
    """fix(#1540 review P2, round 4): the version binding reaches the s3 branch.

    It landed in ``_local_cog_response`` first, which left the splice open on
    the backend this PR was extended to support. The bucket cannot be asked to
    close it: MEASURED against MinIO RELEASE.2025-09-07, a presigned GET
    carrying `Range` plus a non-matching `If-Range` answers **206 anyway** (see
    ``test_a_presigned_get_ignores_conditional_headers`` in
    ``test_cog_s3_head_wire_1540.py``). Nor can a 302 strip the client's Range
    on the way past. So the route answers this one case itself.

    ``history == []`` is the assertion that separates the fix from the bug: a
    redirect here, however the object store answers it afterwards, is a client
    appending bytes 100-199 of the replacement to bytes 0-99 of the COG it
    started with.
    """
    dataset, raster_asset = await _raster_dataset(
        test_db_session,
        storage_backend="s3",
        asset_uri=f"rasters/{uuid.uuid4().hex[:8]}/src.cog.tif",
        sha256=hashlib.sha256(_COG_BYTES).hexdigest(),
    )
    await s3_storage.put(raster_asset.asset_uri, _COG_BYTES)
    stale = f'"{raster_asset.sha256}"'

    new_key = f"rasters/{uuid.uuid4().hex[:8]}/replacement.cog.tif"
    await s3_storage.put(new_key, _REPLACEMENT_BYTES)
    raster_asset.asset_uri = new_key
    raster_asset.sha256 = hashlib.sha256(_REPLACEMENT_BYTES).hexdigest()
    test_db_session.add(raster_asset)
    await test_db_session.commit()

    resumed = await client.get(
        f"/datasets/{dataset.id}/download/cog",
        headers={**admin_auth_header, "Range": "bytes=100-199", "If-Range": stale},
        follow_redirects=True,
    )

    assert _COG_BYTES[100:200] != _REPLACEMENT_BYTES[100:200]
    assert resumed.history == [], (
        f"the stale resume was redirected to "
        f"{[r.headers.get('location') for r in resumed.history]}. The bucket "
        f"does not evaluate If-Range, so that redirect ends in a 206 of the "
        f"replacement at the offsets of the COG the client started with."
    )
    assert resumed.status_code == 200, (
        f"the stale resume returned {resumed.status_code}, not the whole "
        f"current representation RFC 9110 section 13.1.5 calls for."
    )
    assert resumed.content == _REPLACEMENT_BYTES
    assert "content-range" not in resumed.headers


async def test_if_none_match_answers_304_on_s3_too(
    client: AsyncClient, admin_auth_header: dict, test_db_session, s3_storage
):
    """Revalidation is answered before the storage branching, so s3 gets it.

    The 304 saves more here than anywhere else: the alternative is a redirect
    the client follows to the bucket, and then the whole object it already
    holds, billed as egress.
    """
    dataset, raster_asset = await _raster_dataset(
        test_db_session,
        storage_backend="s3",
        asset_uri=f"rasters/{uuid.uuid4().hex[:8]}/src.cog.tif",
        sha256=hashlib.sha256(_COG_BYTES).hexdigest(),
    )
    await s3_storage.put(raster_asset.asset_uri, _COG_BYTES)

    conditional = {**admin_auth_header, "If-None-Match": f'"{raster_asset.sha256}"'}
    url = f"/datasets/{dataset.id}/download/cog"

    revalidated = await client.get(url, headers=conditional, follow_redirects=False)
    probed = await client.head(url, headers=conditional, follow_redirects=False)

    assert revalidated.status_code == 304, (
        f"a revalidating GET on s3 returned {revalidated.status_code}; a 302 "
        f"here sends the client to the bucket for bytes it already has."
    )
    assert probed.status_code == 304, (
        f"a revalidating HEAD on s3 returned {probed.status_code}"
    )
    assert revalidated.headers.get("etag") == f'"{raster_asset.sha256}"'


async def test_a_bucket_issued_validator_is_not_recognized_and_fails_safe(
    client: AsyncClient, admin_auth_header: dict, test_db_session, s3_storage
):
    """The s3 asymmetry this design accepts, pinned so it is a decision.

    A client can pick up two different validators for one resource here. A HEAD
    is answered by this route and carries the COG's SHA-256; a ranged GET is
    redirected, so the 206 the client reads is the bucket's and carries the
    bucket's own ETag, which is an MD5 (or a multipart digest) and never equal
    to ours.

    A resume carrying the bucket's tag is therefore unrecognized, and
    unrecognized means refused: the whole current object, not a 206. That is the
    safe direction and it is not free — the client re-downloads through this
    process rather than resuming from the bucket. Closing that gap would mean
    either serving every s3 range from here or publishing the bucket's ETag
    instead of a content digest, and both are larger changes than the splice
    this round is fixing.
    """
    dataset, raster_asset = await _raster_dataset(
        test_db_session,
        storage_backend="s3",
        asset_uri=f"rasters/{uuid.uuid4().hex[:8]}/src.cog.tif",
        sha256=hashlib.sha256(_COG_BYTES).hexdigest(),
    )
    await s3_storage.put(raster_asset.asset_uri, _COG_BYTES)

    resumed = await client.get(
        f"/datasets/{dataset.id}/download/cog",
        headers={
            **admin_auth_header,
            "Range": "bytes=100-199",
            # What a bucket reports: an MD5 of the object, not our digest.
            "If-Range": '"d41d8cd98f00b204e9800998ecf8427e"',
        },
        follow_redirects=False,
    )

    assert resumed.status_code == 200, (
        f"a resume carrying a validator this route did not issue returned "
        f"{resumed.status_code}; it cannot be matched, so it cannot authorize "
        f"a range."
    )
    assert resumed.content == _COG_BYTES


async def test_a_full_download_works_when_the_provider_is_s3(
    client: AsyncClient, admin_auth_header: dict, test_db_session, s3_storage
):
    """The shape a real S3 deployment has, which is NOT the ``s3`` row.

    ``storage_backend`` is a property of the ASSET, and no ingest path writes
    ``"s3"`` to it: ``tasks_raster_common.py`` and ``tasks_vrt.py`` both create
    rows as ``"local"``, the replace swap resets them to ``"local"``, and STAC
    imports write ``"remote"``. ``"local"`` means "GeoLens owns these bytes";
    which object store holds them is ``get_storage()``'s business. So on a
    deployment configured for S3 the COG download takes this branch, with an
    ``S3StorageProvider`` underneath — and its whole-object GET calls
    ``get_stream``, which raised ``NotImplementedError`` on the strength of a
    docstring saying the router always redirects for s3.

    That is fixed as a consequence of fix(#1540 review P1), which needed a real
    ``get_stream`` for the stale-resume fallback. This test is here because the
    two facts are independent: the fallback could be implemented some other way
    and this path would silently go back to raising.
    """
    dataset, raster_asset = await _raster_dataset(
        test_db_session,
        storage_backend="local",  # what ingest actually writes, S3 or not
        asset_uri=f"rasters/{uuid.uuid4().hex[:8]}/managed.cog.tif",
        sha256=hashlib.sha256(_COG_BYTES).hexdigest(),
    )
    await s3_storage.put(raster_asset.asset_uri, _COG_BYTES)

    whole = await client.get(
        f"/datasets/{dataset.id}/download/cog", headers=admin_auth_header
    )

    assert whole.status_code == 200, (
        f"a full COG download on an S3-backed deployment returned "
        f"{whole.status_code}; this is the path every managed raster takes."
    )
    assert whole.content == _COG_BYTES
    assert whole.headers.get("etag") == f'"{raster_asset.sha256}"'


async def test_an_ordinary_range_makes_one_object_store_request(
    client: AsyncClient, admin_auth_header: dict, test_db_session, s3_storage
):
    """fix(#1540 review P1): the everyday tile read, not just the odd branch.

    The stale-resume fallback was fixed a round earlier and this path was left
    looping ``get_range`` at 1 MiB a call — and it is the path that matters
    most, because on an S3 or Azure deployment ordinary ingested assets carry
    ``storage_backend="local"`` and every range request lands here. No stale
    validator needed: ``Range: bytes=0-`` on a 5 GiB COG issued 5,120 serial
    object-store requests while the rate limiter counted one API call.

    A 3 MiB object and a range spanning all of it, because at 204,800 bytes the
    loop and the stream are indistinguishable — one chunk either way.
    """
    big = bytes(range(256)) * (3 * 1024 * 4)  # 3 MiB exactly
    dataset, raster_asset = await _raster_dataset(
        test_db_session,
        storage_backend="local",  # what ingest writes on an S3 deployment too
        asset_uri=f"rasters/{uuid.uuid4().hex[:8]}/big.cog.tif",
        sha256=hashlib.sha256(big).hexdigest(),
    )
    await s3_storage.put(raster_asset.asset_uri, big)

    calls: list[str] = []
    s3_storage.client.meta.events.register(
        "before-call.s3", lambda model, **kwargs: calls.append(model.name)
    )

    ranged = await client.get(
        f"/datasets/{dataset.id}/download/cog",
        headers={**admin_auth_header, "Range": "bytes=0-"},
    )

    assert ranged.status_code == 206, (
        f"precondition: an open-ended range should be a 206, got {ranged.status_code}"
    )
    assert ranged.content == big
    assert calls == ["HeadObject", "GetObject"], (
        f"a single range request issued {len(calls)} object-store requests "
        f"{calls}. One stat for the length and one ranged read: at a request "
        f"per MiB this is 5,120 of them for a 5 GiB COG, and the rate limiter "
        f"sees one."
    )


async def test_the_stale_resume_fallback_makes_one_object_store_request(
    client: AsyncClient, admin_auth_header: dict, test_db_session, s3_storage
):
    """fix(#1540 review P1): the fallback must not re-request the object per MiB.

    Answering a stale resume with the whole representation is the RFC 9110
    section 13.1.5 contract and is not in question. How the body is produced
    was: streaming it through ``_iter_storage_range`` issued a ranged
    ``get_object`` per 1 MiB, so a 5 GiB COG cost 5,120 object-store requests
    and the per-request rate limiter counted the lot as one.

    It is selectable, too. Any caller who can reach this route — including an
    anonymous holder of a download token for a public dataset — sends one stale
    validator and picks the expensive branch on purpose.

    3 MiB rather than the module's usual payload because the amplification is
    invisible below the chunk size: at 204,800 bytes the old loop and the new
    stream both make exactly one request.
    """
    big = bytes(range(256)) * (3 * 1024 * 4)  # 3 MiB exactly
    dataset, raster_asset = await _raster_dataset(
        test_db_session,
        storage_backend="s3",
        asset_uri=f"rasters/{uuid.uuid4().hex[:8]}/big.cog.tif",
        sha256=hashlib.sha256(big).hexdigest(),
    )
    await s3_storage.put(raster_asset.asset_uri, big)

    calls: list[str] = []
    s3_storage.client.meta.events.register(
        "before-call.s3", lambda model, **kwargs: calls.append(model.name)
    )

    resumed = await client.get(
        f"/datasets/{dataset.id}/download/cog",
        headers={
            **admin_auth_header,
            "Range": "bytes=1048576-2097151",
            "If-Range": '"' + "0" * 64 + '"',
        },
        follow_redirects=False,
    )

    assert resumed.status_code == 200, (
        f"precondition: the stale resume should serve the whole object, got "
        f"{resumed.status_code}"
    )
    assert resumed.content == big
    assert calls == ["HeadObject", "GetObject"], (
        f"serving a 3 MiB object took {len(calls)} object-store requests "
        f"{calls}. One stat for the length and one body: a request per chunk "
        f"is an amplification a caller can select with a header."
    )


async def test_s3_keeps_redirecting_everything_that_is_not_a_stale_resume(
    client: AsyncClient, admin_auth_header: dict, test_db_session, s3_storage
):
    """The vacuity guard for the branch above: s3 is not now a proxy.

    Whole-object GETs and valid resumes carry the multi-GB payloads, and they
    must keep coming from the bucket. A fix that answered every s3 GET from
    this process would pass the splice test and put every COG download through
    the API's bandwidth, which is the cost the redirect design exists to avoid.
    """
    dataset, raster_asset = await _raster_dataset(
        test_db_session,
        storage_backend="s3",
        asset_uri=f"rasters/{uuid.uuid4().hex[:8]}/src.cog.tif",
        sha256=hashlib.sha256(_COG_BYTES).hexdigest(),
    )
    await s3_storage.put(raster_asset.asset_uri, _COG_BYTES)
    url = f"/datasets/{dataset.id}/download/cog"

    whole = await client.get(url, headers=admin_auth_header, follow_redirects=False)
    unconditional = await client.get(
        url,
        headers={**admin_auth_header, "Range": "bytes=0-99"},
        follow_redirects=False,
    )
    valid_resume = await client.get(
        url,
        headers={
            **admin_auth_header,
            "Range": "bytes=100-199",
            "If-Range": f'"{raster_asset.sha256}"',
        },
        follow_redirects=False,
    )

    for name, resp in (
        ("whole-object GET", whole),
        ("unconditional range", unconditional),
        ("resume with a matching validator", valid_resume),
    ):
        assert resp.status_code == 302, (
            f"the {name} on s3 returned {resp.status_code} instead of a "
            f"redirect; those bytes must come from the bucket, not through "
            f"this process."
        )
        assert "location" in resp.headers


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

    No ``Accept-Encoding`` workaround any more. This assertion used to need
    ``identity`` because the global GZipMiddleware compressed the response and
    deleted its length; fix(#1540 review P2) excluded ``image/tiff`` there, and
    ``test_one_etag_names_one_byte_stream_whatever_the_client_accepts`` is what
    now holds that ground — including for a client that does ask for gzip.
    """
    dataset, _ = local_cog

    get = await client.get(
        f"/datasets/{dataset.id}/download/cog",
        headers=admin_auth_header,
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


async def test_one_etag_names_one_byte_stream_whatever_the_client_accepts(
    client: AsyncClient, admin_auth_header: dict, local_cog
):
    """fix(#1540 review P2): a strong validator identifies ONE representation.

    ``GZipMiddleware`` compresses a 200 and skips a 206 by design
    (``self.partial_response = status == 206``). While ``image/tiff`` was
    missing from its exclusion list, that asymmetry made one strong ETag name
    two different byte streams: gzip bytes on the full download, raw bytes on
    every range. RFC 9110 section 8.8.3 requires a strong validator to change
    when the representation does, and a content coding is part of the
    representation — so a client that resumed the encoded one could have its
    validator accepted and splice raw bytes at encoded offsets. Everything it
    did was correct, and the file it assembled was not.

    ``image/tiff`` is excluded at the middleware now, which is also free CPU: a
    COG is internally compressed, so DEFLATE over one buys nearly nothing.

    The assertion is the invariant, not the mechanism: the same request that
    used to come back gzipped returns the raw object with its real length, and
    a range of it is a slice of exactly those bytes.
    """
    dataset, raster_asset = local_cog
    url = f"/datasets/{dataset.id}/download/cog"

    whole = await client.get(
        url, headers={**admin_auth_header, "Accept-Encoding": "gzip"}
    )
    sliced = await client.get(
        url,
        headers={
            **admin_auth_header,
            "Accept-Encoding": "gzip",
            "Range": "bytes=1000-1099",
        },
    )

    assert whole.status_code == 200
    assert "content-encoding" not in whole.headers, (
        f"the full COG came back {whole.headers.get('content-encoding')!r}-"
        f"encoded while a 206 of the same resource does not, so the ETag both "
        f"carry describes two different byte streams."
    )
    assert whole.headers.get("content-length") == str(len(_COG_BYTES)), (
        f"content-length={whole.headers.get('content-length')!r} for "
        f"{len(_COG_BYTES)} raw bytes; compression is what used to delete it."
    )
    assert whole.content == _COG_BYTES

    assert sliced.status_code == 206
    assert whole.headers["etag"] == sliced.headers["etag"] == f'"{raster_asset.sha256}"'
    assert sliced.content == whole.content[1000:1100], (
        "the 206 must be a slice of the bytes the 200 delivers — that is the "
        "whole promise the shared ETag makes to a resuming client."
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

    The knob moved in fix(#1540 review P1). The route used to do its own
    chunking, one ``get_range`` call per chunk, which is what made an ordinary
    range cost a request per MiB; the provider now streams the window from one
    read and owns the chunk size. Same assertion, one layer down.
    """
    from app.platform.storage import local as local_storage

    monkeypatch.setattr(local_storage, "_STREAM_CHUNK_BYTES", 997)

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


@pytest.mark.parametrize("unit", ["bytes", "Bytes", "BYTES", "bYtEs"])
async def test_the_range_unit_is_matched_case_insensitively(
    unit, client: AsyncClient, admin_auth_header: dict, local_cog
):
    """fix(#1540 review P2): ``Bytes=0-99`` is a conforming request.

    A range unit is a token (RFC 9110 section 14.1) and tokens compare
    case-insensitively. Matching only lowercase did not reject the odd-looking
    request — "unusable Range" means ignore it and serve the whole
    representation, so a 16 KiB tile read came back as the entire COG with a
    200. The client cannot even tell: it asked for a window, got a valid
    response, and reads gigabytes.

    Every case pattern, not just the capitalized one the review named: a
    ``.lower()`` on the header, a case-folded prefix check and an
    ``re.IGNORECASE`` all pass the first two and only one of them passes
    ``bYtEs``.
    """
    dataset, _ = local_cog

    resp = await client.get(
        f"/datasets/{dataset.id}/download/cog",
        headers={**admin_auth_header, "Range": f"{unit}=0-99"},
    )

    assert resp.status_code == 206, (
        f"Range unit {unit!r} answered {resp.status_code} with "
        f"{len(resp.content)} bytes; a conforming range request must not be "
        f"upgraded into a whole-object transfer."
    )
    assert resp.content == _COG_BYTES[:100]
    assert resp.headers["content-range"] == f"bytes 0-99/{len(_COG_BYTES)}"


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
    dataset, raster_asset = local_cog
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
    assert resp.headers.get("etag") == f'"{raster_asset.sha256}"', (
        "the 416 reports a size, so it has to say which version that size "
        "belongs to; a client retrying against it can otherwise not tell the "
        "object changed again in between"
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


# A digit string one longer than CPython's default int-from-string limit
# (sys.get_int_max_str_digits() == 4300). ~4.2 KB of header, comfortably inside
# the 8 KiB per-header budget nginx's `large_client_header_buffers 4 8k` and
# uvicorn's h11 limit both allow, so it reaches the app on a real deployment.
_OVERLONG_DIGITS = "9" * 4301


@pytest.mark.parametrize(
    ("header", "expected_status", "expected_content_range"),
    [
        # first-byte-pos beyond any object: RFC 9110 section 15.5.17 wants a 416
        # carrying the real size so the client can retry.
        (f"bytes={_OVERLONG_DIGITS}-", 416, f"bytes */{len(_COG_BYTES)}"),
        # last-byte-pos beyond the end: clamped, section 14.1.1. Clients that do
        # not know the size ask for more than exists on purpose.
        (
            f"bytes=0-{_OVERLONG_DIGITS}",
            206,
            f"bytes 0-{len(_COG_BYTES) - 1}/{len(_COG_BYTES)}",
        ),
        # suffix longer than the object: also clamped, to the whole object.
        (
            f"bytes=-{_OVERLONG_DIGITS}",
            206,
            f"bytes 0-{len(_COG_BYTES) - 1}/{len(_COG_BYTES)}",
        ),
    ],
    ids=["first-byte-pos", "last-byte-pos", "suffix-length"],
)
async def test_an_overlong_range_number_does_not_500(
    header,
    expected_status,
    expected_content_range,
    client: AsyncClient,
    admin_auth_header: dict,
    local_cog,
):
    """fix(#1540) review P2: a huge Range digit string must not reach ``int()``.

    CPython refuses to convert an integer literal longer than
    ``sys.get_int_max_str_digits()`` (4300 by default) and raises ValueError.
    Each of these headers is syntactically valid under RFC 9110 section 14.1.1
    (``first-pos = 1*DIGIT``), so it matched the route's pattern and went
    straight into ``int()`` — turning a header the RFC lets a server handle in
    stride into a 500.

    One case per numeric field, because the three do not share a code path:
    ``first`` decides 416-vs-206, ``last`` is clamped against the size, and the
    suffix is subtracted from it. A guard on only the one a reviewer happened to
    anchor to would leave the other two live.

    The status is asserted exactly rather than as "not 500". Saturating instead
    of ignoring matters: ignoring an unusable Range and replying 200 is the
    right answer for a MALFORMED header, but these are well-formed and merely
    enormous, and handing a client that asked for one tile the entire COG is the
    corrupt-splice failure the 416 branch exists to prevent.
    """
    dataset, _ = local_cog

    resp = await client.get(
        f"/datasets/{dataset.id}/download/cog",
        headers={**admin_auth_header, "Range": header},
    )

    assert resp.status_code != 500, (
        f"Range with a {len(_OVERLONG_DIGITS)}-digit number produced a 500; "
        f"int() raised on the header instead of it being bounded first."
    )
    assert resp.status_code == expected_status, (
        f"Range {header[:24]}...{header[-4:]!r} produced {resp.status_code}, "
        f"expected {expected_status}"
    )
    assert resp.headers.get("content-range") == expected_content_range


@pytest.mark.parametrize(
    "form",
    ["bytes={n}-", "bytes=0-{n}", "bytes=-{n}"],
    ids=["first-byte-pos", "last-byte-pos", "suffix-length"],
)
async def test_an_overlong_range_agrees_with_a_merely_large_one(
    form, client: AsyncClient, admin_auth_header: dict, local_cog
):
    """The bound must not invent a THIRD behaviour for each range form.

    This is the trap in fixing P2 by rejecting instead of saturating. "Too many
    digits" is not a synonym for "unsatisfiable": only the first form earns a
    416, and a single length check that bails out before branching per form
    would turn the other two valid 206s into 416s. A suffix longer than the
    representation IS the representation — ``bytes=-<huge>`` means "give me all
    of it", not "I asked for something impossible".

    So the assertion is agreement rather than three hardcoded answers: whatever
    the route already does for a merely-too-big number, it must do for an
    astronomical one. That cannot drift out of sync with the non-overlong tests
    the way a duplicated expectation can, and it fails for whichever form a
    future "simplification" of the guard breaks.
    """
    dataset, _ = local_cog
    big = len(_COG_BYTES) + 5000

    async def fetch(n: str):
        return await client.get(
            f"/datasets/{dataset.id}/download/cog",
            headers={**admin_auth_header, "Range": form.format(n=n)},
        )

    overlong = await fetch(_OVERLONG_DIGITS)
    merely_large = await fetch(str(big))

    assert overlong.status_code == merely_large.status_code, (
        f"{form.format(n='<4301 digits>')} answered {overlong.status_code} but "
        f"{form.format(n=big)} answered {merely_large.status_code}. The digit "
        f"bound changed this form's semantics instead of only its arithmetic."
    )
    assert overlong.headers.get("content-range") == merely_large.headers.get(
        "content-range"
    )
    assert len(overlong.content) == len(merely_large.content)


async def test_a_zero_padded_suffix_is_still_a_zero_length_suffix(
    client: AsyncClient, admin_auth_header: dict, local_cog
):
    """The bound is on the VALUE, not on how many characters express it.

    ``bytes=-0000...0`` is 4301 characters and names zero bytes. A length check
    that ran before stripping the padding would read it as astronomically large
    and clamp it to the whole object — a 206 where the RFC wants a 416, which is
    the one direction ``_RANGE_UNSATISFIABLE`` was added to rule out.
    """
    dataset, _ = local_cog

    resp = await client.get(
        f"/datasets/{dataset.id}/download/cog",
        headers={**admin_auth_header, "Range": f"bytes=-{'0' * 4301}"},
    )

    assert resp.status_code == 416, (
        f"a zero-length suffix written with 4301 zeros produced "
        f"{resp.status_code}, not the 416 a zero-length suffix earns"
    )
    assert resp.headers.get("content-range") == f"bytes */{len(_COG_BYTES)}"


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
# fix(#1540) review P2: a range must name the version it is a slice of
# ---------------------------------------------------------------------------


async def test_every_stored_bytes_response_carries_a_strong_etag(
    client: AsyncClient, admin_auth_header: dict, local_cog
):
    """HEAD, the whole-object GET and the 206 all name the same version.

    A response that advertises ``Accept-Ranges`` and no validator is what makes
    the splice below possible: the client is invited to resume and given nothing
    to resume against. All three shapes carry it because a resumable client
    reads the ETag from whichever one it happened to start with.

    Strong, not weak. ``W/`` tags are excluded from the ``If-Range`` comparison
    by RFC 9110 section 13.1.5, so a weak tag here would be a validator that can
    never authorize a range — worse than none, because it looks like one.
    """
    dataset, raster_asset = local_cog
    expected = f'"{raster_asset.sha256}"'
    url = f"/datasets/{dataset.id}/download/cog"

    head = await client.head(url, headers=admin_auth_header)
    whole = await client.get(url, headers=admin_auth_header)
    sliced = await client.get(url, headers={**admin_auth_header, "Range": "bytes=0-99"})

    assert sliced.status_code == 206, (
        f"precondition: the range request should 206, got {sliced.status_code}"
    )
    for name, resp in (("HEAD", head), ("GET", whole), ("206", sliced)):
        assert resp.headers.get("etag") == expected, (
            f"the {name} response carried etag={resp.headers.get('etag')!r}, "
            f"expected the COG's own digest {expected!r}"
        )
        assert not resp.headers["etag"].startswith("W/"), (
            f"the {name} ETag is weak; If-Range never matches a weak validator, "
            f"so a resumable client could not use it."
        )


async def test_the_etag_changes_when_the_cog_is_replaced(
    client: AsyncClient, admin_auth_header: dict, test_db_session, local_cog
):
    """A validator that survived a replacement would authorize the splice.

    The dataset id does not move across a replace, so the download URL does not
    either. The bytes behind it do. If the ETag tracked the URL rather than the
    object, a stale ``If-Range`` would match and the range would be served from
    the new COG at the old offsets — precisely the failure, wearing a validator.
    """
    dataset, raster_asset = local_cog
    url = f"/datasets/{dataset.id}/download/cog"

    before = await client.head(url, headers=admin_auth_header)
    await _complete_a_replacement(test_db_session, raster_asset, _REPLACEMENT_BYTES)
    after = await client.head(url, headers=admin_auth_header)

    assert _COG_BYTES != _REPLACEMENT_BYTES, "precondition: the two COGs differ"
    assert before.headers.get("etag") and after.headers.get("etag"), (
        f"both responses need a validator: {before.headers.get('etag')!r} then "
        f"{after.headers.get('etag')!r}"
    )
    assert before.headers["etag"] != after.headers["etag"], (
        f"the ETag survived a replacement ({before.headers['etag']}), so it "
        f"identifies the URL and not the bytes."
    )
    assert (
        after.headers["etag"] == f'"{hashlib.sha256(_REPLACEMENT_BYTES).hexdigest()}"'
    )


async def test_a_resumed_range_across_a_replacement_does_not_splice_two_cogs(
    client: AsyncClient, admin_auth_header: dict, test_db_session, local_cog
):
    """The failure itself: two COGs, one file, no error anywhere.

    A resumable downloader reads a prefix, loses its connection, and comes back
    for the rest. A replacement lands in between. Without a validator both
    requests succeed with 206 and the client writes out a file that is the head
    of the old COG and the tail of the new one — no status code ever says
    otherwise, and the result is a raster the user treats as authoritative.

    With one, the second request cannot match and RFC 9110 section 13.1.5 says
    ignore the Range: the client gets the whole current object with 200, throws
    away its prefix, and starts again. Slower and correct.
    """
    dataset, raster_asset = local_cog
    url = f"/datasets/{dataset.id}/download/cog"

    first = await client.get(url, headers={**admin_auth_header, "Range": "bytes=0-99"})
    assert first.status_code == 206, (
        f"precondition: the first leg should 206, got {first.status_code}"
    )
    assert first.content == _COG_BYTES[:100], "precondition: the prefix is the old COG"
    validator = first.headers["etag"]

    await _complete_a_replacement(test_db_session, raster_asset, _REPLACEMENT_BYTES)

    resumed = await client.get(
        url,
        headers={**admin_auth_header, "Range": "bytes=100-199", "If-Range": validator},
    )

    # Non-vacuous: the two COGs differ at these exact offsets, so a 206 here
    # would be a genuinely corrupt assembly rather than a harmless one.
    assert _COG_BYTES[100:200] != _REPLACEMENT_BYTES[100:200]
    assert resumed.status_code == 200, (
        f"the resumed range returned {resumed.status_code}. A 206 here hands the "
        f"client bytes 100-199 of the REPLACEMENT to append to bytes 0-99 of the "
        f"COG it started with, and nothing in the exchange reports a problem."
    )
    assert "content-range" not in resumed.headers, (
        f"a 200 that still carries {resumed.headers.get('content-range')!r} "
        f"describes a partial representation with a whole-object status."
    )
    assert resumed.content == _REPLACEMENT_BYTES, (
        f"the client got {len(resumed.content)} bytes; ignoring the Range means "
        f"serving the complete current representation."
    )


async def test_a_resumed_range_within_one_version_still_serves_206(
    client: AsyncClient, admin_auth_header: dict, local_cog
):
    """The vacuity guard: If-Range must still ADMIT the ranges it should.

    A fix that answered 200 to every conditional range would pass the splice
    test above and destroy resumable downloads — the feature this PR exists to
    add. Nothing has been replaced here, so the validator still matches and the
    client resumes exactly as intended.
    """
    dataset, raster_asset = local_cog
    url = f"/datasets/{dataset.id}/download/cog"

    resumed = await client.get(
        url,
        headers={
            **admin_auth_header,
            "Range": "bytes=100-199",
            "If-Range": f'"{raster_asset.sha256}"',
        },
    )

    assert resumed.status_code == 206, (
        f"a conditional range whose validator still matches returned "
        f"{resumed.status_code}; resumable downloads are broken."
    )
    assert resumed.content == _COG_BYTES[100:200]
    assert resumed.headers["content-range"] == f"bytes 100-199/{len(_COG_BYTES)}"


async def test_a_weak_validator_never_authorizes_a_resumed_range(
    client: AsyncClient, admin_auth_header: dict, local_cog
):
    """``W/"..."`` is not a match, even wrapping the right digest.

    RFC 9110 section 13.1.5 evaluates If-Range with the STRONG comparison
    function. A weak validator only promises semantic equivalence, which is not
    enough to promise that byte 100 of one representation is byte 100 of the
    other — the only property a resumed range depends on.
    """
    dataset, raster_asset = local_cog

    resumed = await client.get(
        f"/datasets/{dataset.id}/download/cog",
        headers={
            **admin_auth_header,
            "Range": "bytes=100-199",
            "If-Range": f'W/"{raster_asset.sha256}"',
        },
    )

    assert resumed.status_code == 200, (
        f"a weak If-Range returned {resumed.status_code}; strong comparison "
        f"means W/ never matches, however familiar the digest inside it looks."
    )
    assert resumed.content == _COG_BYTES


async def test_a_stale_conditional_range_past_the_new_end_is_not_a_416(
    client: AsyncClient, admin_auth_header: dict, test_db_session, local_cog
):
    """Ignoring the Range means ignoring it, including its bounds.

    The replacement here is SHORTER than what the client was reading, so the
    offsets it wants no longer exist. Both answers are defensible in isolation;
    416 is the wrong one, because the range it reports as unsatisfiable was
    never evaluated — the validator already said this client is asking about a
    version that is gone. Answering 416 would send it back to negotiate offsets
    against an object it has not been told it is now reading.
    """
    dataset, raster_asset = local_cog
    short = b"\x2a" * 512
    url = f"/datasets/{dataset.id}/download/cog"

    stale = (await client.head(url, headers=admin_auth_header)).headers["etag"]
    await _complete_a_replacement(test_db_session, raster_asset, short)

    resumed = await client.get(
        url,
        headers={
            **admin_auth_header,
            "Range": f"bytes=1024-{len(_COG_BYTES) - 1}",
            "If-Range": stale,
        },
    )

    assert resumed.status_code == 200, (
        f"expected the whole 512-byte replacement, got {resumed.status_code} "
        f"(416 answers a range question that the stale validator retired)."
    )
    assert resumed.content == short


async def test_a_row_with_no_digest_refuses_a_conditional_range(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """Rows predating the sha256 column still download; they just cannot resume.

    No digest means no validator to publish and nothing for an ``If-Range`` to
    be compared against. The safe direction is the whole object: a server that
    treated "I cannot check" as "it matches" would serve exactly the spliced
    range this finding is about, on precisely the rows least likely to be
    noticed.

    An UNCONDITIONAL range still works. Legacy rows keep byte-range downloads;
    what they lose is the guarantee across a replacement, which they never had.
    """
    dataset, raster_asset = await _raster_dataset(test_db_session, sha256=None)
    await get_storage().put(raster_asset.asset_uri, _COG_BYTES)
    url = f"/datasets/{dataset.id}/download/cog"

    head = await client.head(url, headers=admin_auth_header)
    plain = await client.get(url, headers={**admin_auth_header, "Range": "bytes=0-99"})
    conditional = await client.get(
        url,
        headers={
            **admin_auth_header,
            "Range": "bytes=0-99",
            "If-Range": '"whatever-the-client-remembers"',
        },
    )

    assert "etag" not in head.headers, (
        f"a row with no digest published etag={head.headers.get('etag')!r}; an "
        f"invented validator is worse than none, it authorizes resumes it "
        f"cannot vouch for."
    )
    assert plain.status_code == 206, (
        f"an unconditional range on a legacy row returned {plain.status_code}; "
        f"the missing digest must not cost these rows byte ranges."
    )
    assert conditional.status_code == 200, (
        f"a conditional range with nothing to check against returned "
        f"{conditional.status_code}; unverifiable must not mean honoured."
    )
    assert conditional.content == _COG_BYTES


async def test_if_none_match_answers_304_for_every_request_shape(
    client: AsyncClient, admin_auth_header: dict, local_cog
):
    """A revalidating client must not be told to download the COG again.

    Publishing an ETag without evaluating ``If-None-Match`` is the expensive
    half of a cache contract: the client dutifully stores the validator, offers
    it back, and gets another 200 with a multi-GB body it already has on disk.

    All three shapes, including the ranged one. RFC 9110 section 13.2.2 puts
    If-None-Match ahead of Range and If-Range in the evaluation order, so a
    client holding this exact representation is told so whether or not it asked
    for a slice of it.
    """
    dataset, raster_asset = local_cog
    url = f"/datasets/{dataset.id}/download/cog"
    validator = f'"{raster_asset.sha256}"'
    conditional = {**admin_auth_header, "If-None-Match": validator}

    head = await client.head(url, headers=conditional)
    whole = await client.get(url, headers=conditional)
    sliced = await client.get(url, headers={**conditional, "Range": "bytes=0-99"})

    for name, resp in (("HEAD", head), ("GET", whole), ("ranged GET", sliced)):
        assert resp.status_code == 304, (
            f"a revalidating {name} got {resp.status_code}; the client already "
            f"holds this representation and is now re-downloading it."
        )
        assert resp.content == b"", f"the 304 for {name} carried a body"
        assert resp.headers.get("etag") == validator, (
            f"the 304 for {name} dropped the ETag; RFC 9110 section 15.4.5 "
            f"wants it back so the cache can restamp its entry."
        )
        assert "content-length" not in resp.headers, (
            f"the 304 for {name} carried content-length="
            f"{resp.headers.get('content-length')!r}"
        )


async def test_a_stale_if_match_refuses_the_range_instead_of_splicing(
    client: AsyncClient, admin_auth_header: dict, test_db_session, local_cog
):
    """fix(#1540 review P2): the same splice, through the other spelling.

    ``If-Match`` and ``If-Range`` are two ways for a resuming client to say the
    same thing: only give me bytes if this is still the representation I have.
    Evaluating one and ignoring the other meant a conforming client that chose
    ``If-Match`` had its precondition dropped, the absent ``If-Range`` read as
    permission, and a 206 of the replacement appended to a prefix of the COG it
    started with.

    A failed If-Match is 412, not a degradation. Unlike If-Range, RFC 9110 gives
    it no "ignore the condition and serve the whole thing" fallback — section
    13.1.1 says do not perform the method.
    """
    dataset, raster_asset = local_cog
    url = f"/datasets/{dataset.id}/download/cog"
    stale = f'"{raster_asset.sha256}"'

    await _complete_a_replacement(test_db_session, raster_asset, _REPLACEMENT_BYTES)

    resumed = await client.get(
        url, headers={**admin_auth_header, "Range": "bytes=100-199", "If-Match": stale}
    )

    assert _COG_BYTES[100:200] != _REPLACEMENT_BYTES[100:200]
    assert resumed.status_code == 412, (
        f"a stale If-Match answered {resumed.status_code}. A 206 here is bytes "
        f"100-199 of the replacement, on their way to being appended to bytes "
        f"0-99 of the COG this client already has."
    )
    assert resumed.headers.get("etag") == f'"{raster_asset.sha256}"', (
        "the 412 should name the version that IS current, so the client can "
        "restart against it without a second round trip"
    )


async def test_a_matching_if_match_still_serves_the_range(
    client: AsyncClient, admin_auth_header: dict, local_cog
):
    """The vacuity guard: If-Match must admit the requests it should.

    An implementation that answered 412 to every If-Match would pass the test
    above and break every conforming client that uses the header correctly,
    which is the population it exists for.
    """
    dataset, raster_asset = local_cog
    url = f"/datasets/{dataset.id}/download/cog"

    matching = await client.get(
        url,
        headers={
            **admin_auth_header,
            "Range": "bytes=100-199",
            "If-Match": f'"{raster_asset.sha256}"',
        },
    )
    star = await client.get(url, headers={**admin_auth_header, "If-Match": "*"})

    assert matching.status_code == 206, (
        f"a matching If-Match returned {matching.status_code}; resumable "
        f"downloads through this header are broken."
    )
    assert matching.content == _COG_BYTES[100:200]
    assert star.status_code == 200, (
        f"If-Match: * asks whether a current representation exists at all, and "
        f"one does; got {star.status_code}."
    )


async def test_if_match_is_evaluated_before_if_none_match(
    client: AsyncClient, admin_auth_header: dict, test_db_session, local_cog
):
    """RFC 9110 section 13.2.2 fixes the order, and the order is observable.

    A client holding an old copy can send both: ``If-Match`` naming the version
    it wants to act on, ``If-None-Match`` naming the copy it has cached — here
    the same stale tag. Evaluating If-None-Match first answers 304, telling the
    client its stale copy is current. Evaluating If-Match first answers 412,
    which is the truth: the representation moved.
    """
    dataset, raster_asset = local_cog
    stale = f'"{raster_asset.sha256}"'

    await _complete_a_replacement(test_db_session, raster_asset, _REPLACEMENT_BYTES)

    resp = await client.get(
        f"/datasets/{dataset.id}/download/cog",
        headers={**admin_auth_header, "If-Match": stale, "If-None-Match": stale},
    )

    assert resp.status_code == 412, (
        f"got {resp.status_code}. A 304 here tells a client whose copy is out "
        f"of date that it is current, which is the more expensive lie: it stops "
        f"asking."
    )


async def test_a_row_with_no_digest_refuses_a_specific_if_match_but_allows_star(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """Unverifiable is not a pass, but ``*`` is asking something else.

    A specific tag against a row with no ``sha256`` cannot be compared, and the
    safe answer is 412 — the same call ``_range_bound_to_this_version`` makes
    for a conditional range. ``*`` is a different question: does a current
    representation exist at all? It does, digest or no digest.
    """
    dataset, raster_asset = await _raster_dataset(test_db_session, sha256=None)
    await get_storage().put(raster_asset.asset_uri, _COG_BYTES)
    url = f"/datasets/{dataset.id}/download/cog"

    specific = await client.get(
        url, headers={**admin_auth_header, "If-Match": '"a-cog-from-last-week"'}
    )
    star = await client.get(url, headers={**admin_auth_header, "If-Match": "*"})

    assert specific.status_code == 412, (
        f"a tag this route cannot check returned {specific.status_code}; "
        f"unverifiable must not mean honoured."
    )
    assert star.status_code == 200, (
        f"If-Match: * returned {star.status_code} for an object that exists"
    )
    assert star.content == _COG_BYTES


async def test_a_remote_cog_leaves_if_match_to_the_origin(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """The blank row stays blank, in both directions.

    This service publishes no validator for a ``remote`` asset, so any
    ``If-Match`` a client sends was issued by the origin at the other end of
    the redirect — and it travels there with the request. Answering 412 on its
    behalf would refuse a precondition this service is in no position to
    evaluate, using a digest recorded at import time.
    """
    dataset, _ = await _raster_dataset(
        test_db_session,
        storage_backend="remote",
        asset_uri="https://example.com/remote.cog.tif",
        sha256=hashlib.sha256(_COG_BYTES).hexdigest(),
    )

    resp = await client.get(
        f"/datasets/{dataset.id}/download/cog",
        headers={**admin_auth_header, "If-Match": '"issued-by-the-origin"'},
        follow_redirects=False,
    )

    assert resp.status_code == 302, (
        f"a conditional GET on the remote branch returned {resp.status_code}; "
        f"the origin owns those bytes and their validators."
    )


async def test_the_two_conditionals_use_their_own_comparison_functions(
    client: AsyncClient, admin_auth_header: dict, local_cog
):
    """``W/`` revalidates a cache. It does not authorize a resume.

    One header, two rules, and the split is the specification's, not a
    shortcut: RFC 9110 evaluates ``If-None-Match`` with weak comparison
    (section 13.1.2) because a cache only needs equivalence, and ``If-Range``
    with strong comparison (section 13.1.5) because a resumed range needs the
    two representations to be byte-identical at the offsets it skipped.

    Asserting both in one test is the point. Implementing either comparison
    once and reusing it for the other passes half of this and fails the other.
    """
    dataset, raster_asset = local_cog
    url = f"/datasets/{dataset.id}/download/cog"
    weak = f'W/"{raster_asset.sha256}"'

    revalidated = await client.get(
        url, headers={**admin_auth_header, "If-None-Match": weak}
    )
    resumed = await client.get(
        url,
        headers={**admin_auth_header, "Range": "bytes=100-199", "If-Range": weak},
    )

    assert revalidated.status_code == 304, (
        f"a weak If-None-Match returned {revalidated.status_code}; weak "
        f"comparison is what caches are supposed to get."
    )
    assert resumed.status_code == 200, (
        f"a weak If-Range returned {resumed.status_code}; strong comparison "
        f"means a weak tag can never authorize a resume."
    )


async def test_a_star_if_none_match_revalidates_and_a_foreign_one_downloads(
    client: AsyncClient, admin_auth_header: dict, local_cog
):
    """``*`` matches any current representation; anything else must not.

    The second half is the vacuity guard for the whole 304 path. An
    implementation that answered 304 to every conditional request would pass
    the tests above and quietly break every client that holds a stale copy,
    which is the population the header exists for.
    """
    dataset, _ = local_cog
    url = f"/datasets/{dataset.id}/download/cog"

    star = await client.get(url, headers={**admin_auth_header, "If-None-Match": "*"})
    stale = await client.get(
        url, headers={**admin_auth_header, "If-None-Match": '"a-cog-from-last-week"'}
    )

    assert star.status_code == 304, f"If-None-Match: * returned {star.status_code}"
    assert stale.status_code == 200, (
        f"a client holding an OLD validator got {stale.status_code}; it needs "
        f"the current bytes, not a 304 telling it the stale copy is fine."
    )
    assert stale.content == _COG_BYTES


async def test_a_304_writes_no_download_audit_row(
    client: AsyncClient, admin_auth_header: dict, local_cog, test_db_session
):
    """Revalidation is not a download, for the same reason a probe is not.

    Sibling of ``test_head_cog_does_not_write_a_download_audit_row``. Nothing
    is transferred, so a ``dataset.download_cog`` row would misreport who
    downloaded what, and a browser that revalidates on every page view would
    inflate the count without moving a byte.
    """
    from app.modules.audit.models import AuditLog

    dataset, raster_asset = local_cog

    async def _download_rows() -> int:
        result = await test_db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "dataset.download_cog",
                AuditLog.resource_id == dataset.id,
            )
        )
        return len(result.scalars().all())

    assert await _download_rows() == 0, "precondition: no audit rows yet"

    revalidated = await client.get(
        f"/datasets/{dataset.id}/download/cog",
        headers={**admin_auth_header, "If-None-Match": f'"{raster_asset.sha256}"'},
    )

    assert revalidated.status_code == 304
    assert await _download_rows() == 0, (
        "a 304 wrote a dataset.download_cog audit row. Nothing was downloaded."
    )


async def test_a_remote_cog_publishes_no_validator(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """The `remote` backend answers for bytes this service does not hold.

    Its asset is a third-party URL that this route redirects to and never
    reads. A digest recorded at import time would claim an object is unchanged
    on the strength of a months-old measurement, so no ETag is published and no
    conditional is evaluated: the origin at the other end of the redirect
    answers with validators of its own.
    """
    dataset, _ = await _raster_dataset(
        test_db_session,
        storage_backend="remote",
        asset_uri="https://example.com/remote.cog.tif",
        sha256=hashlib.sha256(_COG_BYTES).hexdigest(),
    )
    url = f"/datasets/{dataset.id}/download/cog"

    head = await client.head(url, headers=admin_auth_header, follow_redirects=False)
    revalidated = await client.get(
        url,
        headers={**admin_auth_header, "If-None-Match": "*"},
        follow_redirects=False,
    )
    resumed = await client.get(
        url,
        headers={
            **admin_auth_header,
            "Range": "bytes=100-199",
            "If-Range": '"anything-at-all"',
        },
        follow_redirects=False,
    )

    assert (resumed.status_code, "etag" in resumed.headers) == (302, False), (
        f"a conditional range on the remote branch answered "
        f"{resumed.status_code}; range semantics there belong to the origin "
        f"that owns the bytes, and this service publishes no validator to "
        f"evaluate them against."
    )
    assert "etag" not in head.headers, (
        f"the remote branch published etag={head.headers.get('etag')!r} for "
        f"bytes it neither stores nor hashes."
    )
    assert revalidated.status_code == 302, (
        f"a conditional GET on the remote branch returned "
        f"{revalidated.status_code}; answering 304 there vouches for a "
        f"third-party object this service has not looked at."
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
