"""Export ranges are slices of one stored artifact (#1532).

``GET /datasets/{id}/export`` ran a fresh conversion on every request, including
every range request, while advertising ``Accept-Ranges: bytes``. A single
``/vsicurl/`` open therefore cost roughly ten conversions, and whenever the data
moved under them, ten DIFFERENT artifacts served under one URL: #1532 measured
two probes reporting ``bytes 0-0/4045733`` and then ``bytes 0-0/2697263``.

Two failure classes, and the tests here are built around the second. Wasted work
is measurable and boring. The one that matters is a sequence of responses that are
each individually truthful and jointly describe no file that exists.

The constraint the issue is emphatic about: today's incoherence fails LOUDLY (a
spliced GeoJSON dies with ``ERROR 4: Failed to read GeoJSON data``), and a fix
that makes the failure quiet is worse than the bug. So the assertions below are
not "the second range succeeds" — they are that no two responses in a sequence are
ever parts of different artifacts presented as parts of one.

Requirements:
  - Docker database must be running (docker compose up db)
  - Run with: set -a && source ../.env.test && set +a
              uv run pytest tests/test_export_artifact_cache_1532.py -v
"""

import os
import shutil
import tempfile
import time
import uuid

import pytest
from httpx import AsyncClient

from app.platform.storage import get_storage
from app.processing.export import artifact_cache
from app.processing.export.ogr import FORMAT_MAP

from tests.factories import create_dataset, get_user_id

_COLUMNS = [
    {"name": "gid", "type": "integer"},
    {"name": "name", "type": "text"},
    {"name": "pop", "type": "integer"},
]


class Conversions:
    """A stand-in for ogr2ogr that counts, and whose output the test controls.

    Counting is the point of half this module: the defect is that the route
    converts per REQUEST rather than per artifact, and the only way to see that
    is to count conversions across a request sequence rather than to inspect one
    response.

    ``body`` is writable so a test can land a mutation between two range
    requests. The real conversion reads a table that changed; this one reads an
    attribute that changed, and the route cannot tell the difference — it hands
    the same arguments to the same callable and gets different bytes back, which
    is exactly the situation #1532 describes.

    Each call gets its own directory, like ``export_dataset`` does. The route
    removes ``os.path.dirname(file_path)`` once the bytes are safely stored, so a
    shared directory would have the first request delete the second's output.
    """

    def __init__(self, root: str, body: bytes) -> None:
        self.root = root
        self.body = body
        self.count = 0

    async def __call__(
        self,
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
        self.count += 1
        fmt = FORMAT_MAP[format_key]
        filename = f"{dataset_name}{'.zip' if format_key == 'shp' else fmt['ext']}"
        directory = os.path.join(self.root, uuid.uuid4().hex)
        os.makedirs(directory)
        path = os.path.join(directory, filename)
        with open(path, "wb") as handle:
            handle.write(self.body)
        return path, filename, fmt["media"]


@pytest.fixture
def conversions(monkeypatch):
    """Patch the route's conversion and hand the test the counter."""
    root = tempfile.mkdtemp(prefix="test_export_1532_")
    # Distinctive and long enough that a range is a genuine slice, and every byte
    # value present so a splice is detectable wherever it lands.
    counter = Conversions(root, bytes(range(256)) * 40)
    monkeypatch.setattr("app.processing.export.router.export_dataset", counter)
    yield counter
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(autouse=True)
def _long_ttl(monkeypatch):
    """Pin the freshness window so a slow test cannot expire its own artifact.

    The TTL is the correctness mechanism, so it gets its own test rather than
    being left to influence every other one implicitly.
    """
    monkeypatch.setattr(artifact_cache, "_ttl_seconds", lambda: 600)


async def _dataset(session, name: str, **kwargs):
    user_id = await get_user_id(session, "admin")
    return await create_dataset(
        session,
        created_by=user_id,
        name=name,
        theme_category=[],
        visibility="public",
        column_info=_COLUMNS,
        record_type="vector_dataset",
        **kwargs,
    )


def _url(dataset_id) -> str:
    return f"/datasets/{dataset_id}/export?format=geojson"


# ---------------------------------------------------------------------------
# Wasted work
# ---------------------------------------------------------------------------


async def test_a_probe_and_its_ranges_cost_one_conversion(
    client: AsyncClient, admin_auth_header: dict, test_db_session, conversions
):
    """The measured cost of one ``/vsicurl/`` open, as a number.

    A HEAD followed by five range GETs is the shape GDAL produces: it probes,
    learns it has no length, and reads the header in slices. Before this fix
    every one of those GETs re-entered the endpoint and re-ran the conversion.

    The assertion is the count, not the elapsed time, because the count is what
    the defect is: the route converted per request rather than per artifact.
    """
    dataset = await _dataset(test_db_session, "Cache Conversions")
    url = _url(dataset.id)

    await client.head(url, headers=admin_auth_header)
    for start in range(0, 500, 100):
        resp = await client.get(
            url,
            headers={**admin_auth_header, "Range": f"bytes={start}-{start + 99}"},
        )
        assert resp.status_code in (200, 206), resp.text

    assert conversions.count == 1, (
        f"one HEAD and five ranges cost {conversions.count} conversions. Each is "
        f"a full ogr2ogr run against the dataset's table, and each produces its "
        f"own artifact."
    )


async def test_every_range_is_a_slice_of_the_same_artifact(
    client: AsyncClient, admin_auth_header: dict, test_db_session, conversions
):
    """The coherence half: the slices reassemble into the object they came from.

    Wasted work would be tolerable. Ten artifacts under one URL is not, and this
    is the assertion that distinguishes them — reassembly, plus one ETag and one
    total size across every response.
    """
    dataset = await _dataset(test_db_session, "Cache Coherence")
    url = _url(dataset.id)

    whole = await client.get(url, headers=admin_auth_header)
    assert whole.status_code == 200, whole.text
    body = whole.content

    assembled = b""
    etags = set()
    totals = set()
    for start in range(0, len(body), 64):
        resp = await client.get(
            url,
            headers={**admin_auth_header, "Range": f"bytes={start}-{start + 63}"},
        )
        assert resp.status_code == 206, (
            f"range at {start} returned {resp.status_code}; a stored artifact "
            f"has to be sliceable or nothing above holds"
        )
        assembled += resp.content
        etags.add(resp.headers.get("etag"))
        totals.add(resp.headers["content-range"].split("/")[-1])

    assert assembled == body, (
        "the slices do not reassemble into the whole representation, which is "
        "the corrupt download this fix exists to prevent"
    )
    assert len(totals) == 1, (
        f"the range responses reported {sorted(totals)} as the total size. #1532 "
        f"measured exactly this: two probes, two sizes, one URL."
    )
    assert len(etags) == 1 and None not in etags, (
        f"the range responses carried {etags}; one artifact has one validator"
    )


# ---------------------------------------------------------------------------
# Coherence across a mutation
# ---------------------------------------------------------------------------


async def test_a_mutation_between_two_ranges_is_answered_with_the_whole_new_file(
    client: AsyncClient, admin_auth_header: dict, test_db_session, conversions
):
    """The sharp case, and the one the fix must not make quiet.

    A client reads bytes 0-99, the data changes, and it comes back for bytes
    100-199. Answering that with a 206 of the NEW artifact at the OLD offsets is
    a corrupt file assembled without a single error — and a bare ``Range``
    carries nothing the server could compare, because GDAL never sends
    ``If-Range``.

    So the second read is answered with the complete new representation and 200.
    The client discards its prefix and starts over, which is slower and correct,
    and it is the same call RFC 9110 section 13.1.5 makes for a stale
    ``If-Range``. What it must never be is a 206.
    """
    dataset = await _dataset(test_db_session, "Cache Mutation")
    url = _url(dataset.id)
    before = conversions.body

    first = await client.get(url, headers={**admin_auth_header, "Range": "bytes=0-99"})
    assert first.status_code in (200, 206), first.text

    # The mutation. A shorter body, like the DELETE #1532 measured, so a spliced
    # response is detectable by length as well as by content.
    after = bytes(range(200, 256)) * 30
    assert after != before[: len(after)]
    conversions.body = after
    dataset.bump_tile_cache_version()
    test_db_session.add(dataset)
    await test_db_session.commit()

    second = await client.get(
        url, headers={**admin_auth_header, "Range": "bytes=100-199"}
    )

    assert second.status_code == 200, (
        f"the resumed range returned {second.status_code}. A 206 here is bytes "
        f"100-199 of a different artifact, on its way to being appended to bytes "
        f"0-99 of the one the client started with."
    )
    assert second.content == after, (
        "the response after the mutation must be the complete new "
        "representation, not a slice of it"
    )
    assert "content-range" not in second.headers, (
        f"the response carried content-range="
        f"{second.headers.get('content-range')!r}, which tells the client to "
        f"treat it as a partial answer to its old offsets"
    )


async def test_a_mutation_moves_the_artifact_rather_than_editing_it(
    client: AsyncClient, admin_auth_header: dict, test_db_session, conversions
):
    """Invalidation is a key change, so the old artifact is never rewritten.

    This is what makes the mutation path safe for a reader that is mid-download:
    the new bytes land under a new key, and a client still streaming the previous
    artifact keeps reading an object that still exists. A cache that overwrote one
    mutable key would replace bytes underneath that reader — the same incoherence
    as the bug, arriving as a truncated file instead of a splice.
    """
    dataset = await _dataset(test_db_session, "Cache Key Move")
    url = _url(dataset.id)

    first = await client.get(url, headers=admin_auth_header)
    assert first.status_code == 200
    first_etag = first.headers.get("etag")

    conversions.body = b"a completely different export payload"
    dataset.bump_tile_cache_version()
    test_db_session.add(dataset)
    await test_db_session.commit()

    second = await client.get(url, headers=admin_auth_header)

    assert second.headers.get("etag") not in (None, first_etag), (
        f"the mutated export kept etag={second.headers.get('etag')!r}. A "
        f"validator that survives a content change is what makes a conditional "
        f"client accept stale bytes."
    )
    assert second.content == b"a completely different export payload"


async def test_the_artifact_expires_even_when_nothing_signalled_a_change(
    client: AsyncClient, admin_auth_header: dict, test_db_session, conversions
):
    """The TTL is the correctness mechanism, so it is tested on its own.

    ``tile_cache_version`` is folded into the cache key and invalidates
    instantly, but it is bumped from fourteen hand-maintained call sites and
    #1532 is explicit that a fix resting on such a list is worse than the bug.
    Here NOTHING signals the change — no bump, no touched row — and the artifact
    still stops answering, because the window it is usable for is a property of
    time rather than of anyone's diligence.

    A missed bump therefore costs one TTL of staleness. It cannot cost a wrong
    download that looks right.
    """
    dataset = await _dataset(test_db_session, "Cache Expiry")
    url = _url(dataset.id)

    assert (await client.get(url, headers=admin_auth_header)).status_code == 200
    assert conversions.count == 1

    conversions.body = b"the export after an unsignalled change"
    second = await client.get(url, headers=admin_auth_header)
    assert conversions.count == 1, (
        "precondition: inside the window the artifact answers without "
        "reconverting, so the expiry below is what this test measures"
    )
    assert second.content != conversions.body

    artifact_cache._ttl_seconds = lambda: 0  # type: ignore[assignment]
    try:
        third = await client.get(url, headers=admin_auth_header)
    finally:
        artifact_cache._ttl_seconds = lambda: 600  # type: ignore[assignment]

    assert conversions.count == 2, (
        "an expired artifact must be rebuilt; nothing else bounds how stale a "
        "download can be"
    )
    assert third.content == b"the export after an unsignalled change"


# ---------------------------------------------------------------------------
# HEAD
# ---------------------------------------------------------------------------


async def test_head_answers_a_real_length_once_an_artifact_exists(
    client: AsyncClient, admin_auth_header: dict, test_db_session, conversions
):
    """The length is what GDAL is probing for, and now it can have it.

    Not by converting: a HEAD that ran ogr2ogr to learn a length would hand any
    anonymous caller a worker per request, which is why fix(#1513) omits the
    header entirely under RFC 9110 section 9.3.2 and why the first probe below
    still does. Once an artifact exists the answer is free, and it is exact.

    Both halves are asserted together because the first is the DoS property and
    the second is the feature; a change that traded one for the other would pass
    a test that only checked the other.
    """
    dataset = await _dataset(test_db_session, "Cache Head")
    url = _url(dataset.id)

    cold = await client.head(url, headers=admin_auth_header)
    assert cold.status_code == 200
    assert conversions.count == 0, (
        f"the cold HEAD ran {conversions.count} conversion(s); probing must stay "
        f"free or it becomes a denial-of-service lever on a public dataset"
    )
    assert "content-length" not in cold.headers

    body = (await client.get(url, headers=admin_auth_header)).content

    warm = await client.head(url, headers=admin_auth_header)
    assert warm.headers.get("content-length") == str(len(body)), (
        f"HEAD reported content-length={warm.headers.get('content-length')!r} "
        f"for a {len(body)}-byte artifact"
    )
    assert warm.headers.get("etag") is not None
    assert warm.headers.get("accept-ranges") == "bytes"
    assert conversions.count == 1, (
        f"the warm HEAD ran a conversion ({conversions.count} total); it has an "
        f"artifact to read the length from"
    )


# ---------------------------------------------------------------------------
# Keying
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "changed",
    [
        {"format_key": "gpkg"},
        {"target_crs": "EPSG:3857"},
        {"bbox": "0,0,1,1"},
        {"where": "pop > 1000"},
        {"dataset_title": "Renamed"},
        {"table_name": "other_table"},
        {"tile_cache_version": 9},
    ],
)
def test_every_input_that_changes_the_bytes_changes_the_key(changed):
    """Rule 8, at the level the cache actually keys on.

    Each of these changes what the conversion emits, so each must land on a
    different artifact. ``table_name`` because a replace swaps the physical table
    underneath a stable dataset id; ``dataset_title`` because it becomes the
    output filename and ogr2ogr names a GPKG layer after the file it writes, so a
    retitle changes bytes rather than only a header.

    Parametrized one input at a time rather than asserting a set of keys is
    distinct: a single combined test passes while one dimension is silently
    ignored, as long as the others differ.
    """
    base = {
        "dataset_id": uuid.UUID("00000000-0000-0000-0000-000000000001"),
        "table_name": "some_table",
        "dataset_title": "Some Dataset",
        "tile_cache_version": 1,
        "format_key": "geojson",
        "target_crs": None,
        "bbox": None,
        "where": None,
    }

    assert artifact_cache.selection_key(**base) != artifact_cache.selection_key(
        **{**base, **changed}
    ), f"{sorted(changed)} does not change the cache key, so it is a staleness hole"


def test_an_absent_filter_is_not_an_empty_one():
    """``where=""`` and ``where`` absent select different rows, so they key apart.

    The JSON encoding is what keeps them apart; a delimiter join would collapse
    them, which is the same trap ``embedding_config_fingerprint`` documents in
    #1546. The counterfactual matters here: the two values are both falsy, so
    every "if not where" shortcut in the neighbourhood treats them as one.
    """
    base = {
        "dataset_id": uuid.UUID("00000000-0000-0000-0000-000000000001"),
        "table_name": "t",
        "dataset_title": "T",
        "tile_cache_version": 1,
        "format_key": "geojson",
        "target_crs": None,
        "bbox": None,
    }
    assert artifact_cache.selection_key(**base, where=None) != (
        artifact_cache.selection_key(**base, where="")
    )


async def test_two_selections_do_not_share_an_artifact(
    client: AsyncClient, admin_auth_header: dict, test_db_session, conversions
):
    """The keying, driven through the endpoint rather than the helper.

    A helper test proves the strings differ. This proves the route asks with the
    inputs it should: two filters, two conversions, and the second answer is not
    the first one's bytes.
    """
    dataset = await _dataset(test_db_session, "Cache Selections")
    base = f"/datasets/{dataset.id}/export?format=geojson"

    first = await client.get(base, headers=admin_auth_header)
    conversions.body = b"a narrower selection"
    second = await client.get(f"{base}&where=pop+%3E+1000", headers=admin_auth_header)

    assert conversions.count == 2, (
        f"two different selections cost {conversions.count} conversion(s); the "
        f"filter is part of what the artifact IS"
    )
    assert first.content != second.content
    assert second.content == b"a narrower selection"


# ---------------------------------------------------------------------------
# Degradation
# ---------------------------------------------------------------------------


async def test_a_storage_failure_still_serves_the_download(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    conversions,
    monkeypatch,
):
    """A cache that cannot store must not be able to fail a request.

    The conversion succeeded and the file is in hand, so a broken object store
    costs the caching, not the export. ``lookup`` and ``store`` both swallow and
    return rather than raise for exactly this, and the route falls back to the
    ``FileResponse`` it sent before #1532.

    The outage is injected at ``get_storage`` rather than at either function, so
    every path through this module meets it: the lookup at the top of the
    request, the digest-and-put, the pointer write and the eviction. Patching
    ``store`` alone would leave the lookup untested and pass against a route that
    500s before it ever reaches the conversion.
    """

    dataset = await _dataset(test_db_session, "Cache Storage Down")

    def _down():
        raise OSError("object store is down")

    monkeypatch.setattr("app.processing.export.artifact_cache.get_storage", _down)

    resp = await client.get(_url(dataset.id), headers=admin_auth_header)

    assert resp.status_code == 200, (
        f"a storage outage answered {resp.status_code}; the export itself never "
        f"needed the object store before this fix and must not start now"
    )
    assert resp.content == conversions.body
    assert conversions.count == 1, (
        "the download came from a conversion, which is the fallback this test is about"
    )


# ---------------------------------------------------------------------------
# Review r1: a client that names what it is resuming
# ---------------------------------------------------------------------------


async def test_a_resume_naming_the_previous_artifact_is_not_sliced(
    client: AsyncClient, admin_auth_header: dict, test_db_session, conversions
):
    """fix(#1532 review r1): `If-Range` is evaluated before the artifact is sliced.

    The artifact publishes a strong validator now, so a careful client CAN name
    the representation it is resuming — curl -C does, browsers do, and GDAL may
    one day. Without evaluating it, such a client got a 206 of the CURRENT
    artifact at the offsets it measured against the previous one: the same splice
    `may_serve_range` closes for the rebuild case, arriving through the very
    header the client sent to prevent it.

    RFC 9110 section 13.1.5 gives one answer for a validator that does not match:
    ignore the Range and serve the complete representation. Not a 206, and not a
    412 — `If-Range` is an optimization the server may decline.
    """
    dataset = await _dataset(test_db_session, "IfRange Stale")
    url = _url(dataset.id)

    first = await client.get(url, headers=admin_auth_header)
    stale_etag = first.headers["etag"]

    conversions.body = b"the export after the data moved on" * 8
    dataset.bump_tile_cache_version()
    test_db_session.add(dataset)
    await test_db_session.commit()
    await client.get(url, headers=admin_auth_header)  # publishes the new artifact

    resumed = await client.get(
        url,
        headers={**admin_auth_header, "Range": "bytes=10-19", "If-Range": stale_etag},
    )

    assert resumed.status_code == 200, (
        f"a resume naming the previous artifact returned {resumed.status_code}. "
        f"A 206 here is ten bytes of the new export at offsets measured against "
        f"the old one, which is the splice this PR exists to prevent."
    )
    assert resumed.content == conversions.body
    assert "content-range" not in resumed.headers


async def test_a_matching_if_range_still_resumes(
    client: AsyncClient, admin_auth_header: dict, test_db_session, conversions
):
    """The vacuity guard: `If-Range` must admit the requests it should.

    An implementation that ignored every Range whenever `If-Range` was present
    would pass the test above and break resumable downloads for exactly the
    clients careful enough to use the header.
    """
    dataset = await _dataset(test_db_session, "IfRange Match")
    url = _url(dataset.id)

    first = await client.get(url, headers=admin_auth_header)
    etag = first.headers["etag"]

    resumed = await client.get(
        url, headers={**admin_auth_header, "Range": "bytes=10-19", "If-Range": etag}
    )

    assert resumed.status_code == 206, (
        f"a matching If-Range returned {resumed.status_code}; resumable "
        f"downloads through this header are broken"
    )
    assert resumed.content == first.content[10:20]


async def test_a_weak_if_range_never_authorizes_a_resume(
    client: AsyncClient, admin_auth_header: dict, test_db_session, conversions
):
    """`W/` is not a match, even wrapping the right digest.

    Section 13.1.5 specifies the STRONG comparison function for `If-Range`,
    unlike `If-None-Match`, and the difference is not an oversight: a resumed
    range needs the two representations byte-identical at the offsets it skipped,
    where a cache revalidation only needs them equivalent.
    """
    dataset = await _dataset(test_db_session, "IfRange Weak")
    url = _url(dataset.id)

    first = await client.get(url, headers=admin_auth_header)

    resumed = await client.get(
        url,
        headers={
            **admin_auth_header,
            "Range": "bytes=10-19",
            "If-Range": f"W/{first.headers['etag']}",
        },
    )

    assert resumed.status_code == 200, (
        f"a weak If-Range returned {resumed.status_code}; strong comparison "
        f"means W/ can never authorize a resume, however familiar the digest "
        f"inside it looks"
    )


# ---------------------------------------------------------------------------
# Review r1: the read path on every provider
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["get_stream", "get_range_stream", "size", "exists"])
def test_no_provider_stubs_out_a_method_the_read_path_calls(method):
    """fix(#1532 review r1): every provider must really implement the read path.

    ``AzureBlobStorageProvider.get_stream`` raised ``NotImplementedError`` behind
    a docstring asserting "the router returns a SAS-signed redirect for the azure
    storage backend, so this method is unreachable". It was reachable, and the
    claim was already stale before this PR — fix(#1540) established that no
    ingest path writes ``storage_backend="azure"`` at all, so managed assets take
    the LOCAL branch, whose whole-object GET calls exactly that method. The
    cached export made a second caller.

    The failure mode is what makes this worth a structural test rather than an
    integration one. The raise happens while ``StreamingResponse`` is consuming
    the iterator — after the response has begun — so the client gets a truncated
    body rather than a clean 500, and no status-code assertion anywhere would
    have seen it.

    Source inspection rather than a call, deliberately: this has to run in the
    default suite, and S3 and Azure both need a backend to call. A docstring
    explaining why a method is unreachable is exactly what this catches, because
    that is the form the bug took.
    """
    import inspect

    from app.platform.storage.azure import AzureBlobStorageProvider
    from app.platform.storage.local import LocalStorageProvider
    from app.platform.storage.s3 import S3StorageProvider

    for provider in (LocalStorageProvider, S3StorageProvider, AzureBlobStorageProvider):
        source = inspect.getsource(getattr(provider, method))
        assert "raise NotImplementedError" not in source, (
            f"{provider.__name__}.{method} is a NotImplementedError stub, and the "
            f"export and COG read paths both call it. On that backend the "
            f"download fails mid-stream, which reads to the client as a truncated "
            f"file rather than an error."
        )


class _NoPresignProvider:
    """A provider shaped like Azure: real reads, no presigned URLs.

    Azure signs with SAS tokens and raises ``NotImplementedError`` from both
    presign methods. This double keeps that shape over a real local provider so
    the route's cold and cache-hit paths can be driven end to end without an
    emulator, and so any attempt to reach for a presigned URL on this path fails
    loudly instead of quietly working on the two backends that have one.
    """

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        if name.startswith("generate_presigned"):
            raise NotImplementedError(
                "Azure uses SAS tokens; this provider has no presigned URLs"
            )
        return getattr(self._inner, name)


async def test_a_provider_without_presigning_serves_cold_and_hit(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    conversions,
    monkeypatch,
):
    """Both paths, on the provider shape that has no redirect to fall back to.

    Cold (the request that builds and stores) and hit (a later request with no
    usable Range) both end in ``get_stream``. Asserting them together is the
    point: the cold path was reachable before this PR too, and a change that
    fixed one while leaving the other would pass a test that checked one.
    """
    from app.platform.storage import get_storage

    dataset = await _dataset(test_db_session, "Azure Shaped")
    wrapped = _NoPresignProvider(get_storage())
    monkeypatch.setattr(
        "app.processing.export.artifact_cache.get_storage", lambda: wrapped
    )
    monkeypatch.setattr("app.processing.export.router.get_storage", lambda: wrapped)

    cold = await client.get(_url(dataset.id), headers=admin_auth_header)
    hit = await client.get(_url(dataset.id), headers=admin_auth_header)

    assert conversions.count == 1, "precondition: the second request is a cache hit"
    assert cold.status_code == 200 and cold.content == conversions.body, (
        "the cold path streamed nothing usable on a provider with no presigned "
        "URL to redirect to"
    )
    assert hit.status_code == 200 and hit.content == conversions.body, (
        "the cache-hit path streamed nothing usable"
    )


# ---------------------------------------------------------------------------
# Review r1: two publishers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Review r3: nothing is rewritten, so nothing races
# ---------------------------------------------------------------------------


async def test_two_concurrent_publishers_both_survive(test_db_session, monkeypatch):
    """Two builders racing a selection publish side by side and readers take the newer.

    This started as fix(#1532 review r1)'s bug: an eviction-on-build step deleted
    "everything but mine and the one I superseded", so interleaved builders each
    removed the other's object and the surviving pointer could name a key that
    was already gone. r2 found the same shape in the sweep. r3 removed the last
    piece of mutable state, and the property now holds because publishing is one
    ``put`` to a key nothing else can be using — there is no flip to race and
    nothing deletes on the publish path at all.

    The overlap is FORCED, not hoped for. A barrier holds both builders after
    hashing and before publishing, and the test asserts both arrived; a sequence
    of two ``store`` calls proves nothing about concurrency.
    """
    import asyncio
    import tempfile

    from app.platform.storage import get_storage
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Two Publishers")
    selection = "race"
    storage = get_storage()

    arrived = asyncio.Event()
    waiting = 0
    real_digest = cache._digest_and_size

    async def _barriered(file_path):
        nonlocal waiting
        result = await real_digest(file_path)
        if waiting < 2:
            waiting += 1
            if waiting == 2:
                arrived.set()
            await asyncio.wait_for(arrived.wait(), timeout=5)
        return result

    monkeypatch.setattr(cache, "_digest_and_size", _barriered)

    async def _publish(payload: bytes):
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(payload)
            path = handle.name
        return await cache.store(
            dataset.id,
            selection,
            file_path=path,
            filename="x.geojson",
            media_type="application/geo+json",
        )

    first, second = await asyncio.gather(
        _publish(b"builder one output"), _publish(b"builder two output")
    )

    assert waiting == 2, (
        "the two builders did not overlap, so this test would have proved "
        "nothing about the race it is named for"
    )
    assert first is not None and second is not None
    assert first.key != second.key, (
        "precondition: two builders must land on different keys, which is what "
        "makes neither able to overwrite the other"
    )
    for artifact in (first, second):
        assert await storage.exists(artifact.key), (
            f"{artifact.key} is gone; a publish deleted another writer's object, "
            f"and a reader mid-stream on it would be truncated"
        )

    resolved = await cache.lookup(
        dataset.id,
        selection,
        filename="x.geojson",
        media_type="application/geo+json",
    )
    assert resolved is not None and resolved.key == max(first.key, second.key), (
        "a reader must resolve to the newer of the two, deterministically"
    )


async def test_a_truncated_artifact_is_skipped_rather_than_served(test_db_session):
    """A half-written object must not become "the newest" and be served.

    ``LocalStorageProvider.put`` streams straight to the destination, so a process
    killed mid-copy leaves a truncated file at the final key. The pointer design
    avoided that by never naming such a file; taking the newest key instead has
    to DETECT it, which is what the size in the key is for.

    Free, too: the response needs the length anyway, so verifying it costs the
    call that was already being made. Without the check a truncated export is
    served to every reader until the horizon — a persistent version of exactly
    the corrupt download this PR exists to prevent.
    """
    from app.platform.storage import get_storage
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Truncated")
    selection = "torn"
    storage = get_storage()
    now = time.time()

    good = cache._artifact_key(dataset.id, selection, "a" * 64, 11, now - 5)
    await storage.put(good, b"good bytes\n")
    torn = cache._artifact_key(dataset.id, selection, "b" * 64, 4096, now)
    await storage.put(torn, b"half a f")  # 8 bytes where the key claims 4096

    resolved = await cache.lookup(
        dataset.id, selection, filename="x.geojson", media_type="application/geo+json"
    )

    assert resolved is not None, "the intact older artifact should still answer"
    assert resolved.key == good, (
        f"lookup resolved to {resolved.key}, whose stored length does not match "
        f"the size in its own name. Serving it hands every reader a truncated "
        f"export until the horizon."
    )


# ---------------------------------------------------------------------------
# Review r3: reclamation
# ---------------------------------------------------------------------------


async def test_the_sweep_reclaims_aged_artifacts_and_keeps_young_ones(test_db_session):
    """One rule, both directions, asserted together.

    A sweep that deleted nothing would pass a "young survives" test; one that
    deleted everything would pass an "aged goes" test. The pair is what pins the
    rule, and the rule is the whole safety argument: an object goes when the
    timestamp in its own name is past the horizon, and a publish mints its key
    from ``time.time()``, so an aged key can never become fresh and a fresh key
    can never look aged.
    """
    from app.platform.storage import get_storage
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Sweep Rule")
    storage = get_storage()

    aged = cache._artifact_key(dataset.id, "old", "a" * 64, 6, time.time() - 7200)
    young = cache._artifact_key(dataset.id, "new", "b" * 64, 6, time.time())
    await storage.put(aged, b"abcdef")
    await storage.put(young, b"abcdef")

    removed = await cache.sweep(age_threshold_seconds=3600)

    assert not await storage.exists(aged), (
        f"the sweep removed {removed} key(s) and left an artifact two hours past "
        f"the horizon; nothing else reclaims it"
    )
    assert await storage.exists(young), (
        "the sweep deleted an artifact published moments ago, which is a "
        "download in progress"
    )


async def test_a_publish_racing_the_sweep_survives(test_db_session, monkeypatch):
    """The sweep must not delete on the strength of a snapshot (review r2, r3).

    An earlier revision read a selection's pointer, found it past the horizon,
    declared the whole PREFIX stale and removed every key under it — including
    the young artifact another worker had just uploaded. The next revision judged
    per key but still read the pointer to decide the pointer's own fate, which
    merely narrowed the window.

    Now no read is involved at all: the age is in the name, so a publish landing
    anywhere inside the sweep is invisible to its decisions. The race is still
    constructed, because a property that holds by construction is exactly the
    kind that stops being tested.
    """
    from app.platform.storage import get_storage
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Sweep Race")
    selection = "contested"
    storage = get_storage()

    aged = cache._artifact_key(dataset.id, selection, "a" * 64, 6, time.time() - 7200)
    await storage.put(aged, b"abcdef")
    fresh = cache._artifact_key(dataset.id, selection, "b" * 64, 6, time.time())
    published: dict = {}

    class _RacingStorage:
        """A publish landing inside the sweep, between its paging and its deletes."""

        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def iter_object_pages(self, prefix, **kwargs):
            inner_pages = self._inner.iter_object_pages(prefix, **kwargs)

            async def _paged():
                async for page in inner_pages:
                    if "at" not in published:
                        published["at"] = time.time()
                        await self._inner.put(fresh, b"abcdef")
                    yield page

            return _paged()

    monkeypatch.setattr(
        "app.processing.export.artifact_cache.get_storage",
        lambda: _RacingStorage(storage),
    )

    await cache.sweep(age_threshold_seconds=3600)

    assert published, (
        "the publish never landed inside the sweep, so this test says nothing "
        "about the window it is named for"
    )
    assert await storage.exists(fresh), (
        "the sweep deleted an artifact published while it was running. The "
        "request that published it is now streaming a key that does not exist."
    )
    assert not await storage.exists(aged), (
        "the genuinely aged artifact survived, so the sweep reclaims nothing"
    )


async def test_one_off_selections_do_not_accumulate(
    client: AsyncClient, admin_auth_header: dict, test_db_session, conversions
):
    """Storage is bounded by build rate times horizon, not by all-time selections.

    fix(#1532 review r3): the previous design left a ``current.json`` per
    selection forever, and a selection is (dataset, format, filters) — anonymous
    callers can export a public dataset with arbitrary ``bbox`` and ``where``, so
    the set is caller-controlled and unbounded. Storage grew without limit after
    every artifact had expired, and each sweep's listing grew with it.

    Driven through the endpoint rather than by seeding keys, because what is
    being asserted is that the ROUTE leaves nothing behind — a helper-level test
    would describe whatever the helper happens to write, which is the thing that
    changed.

    A negative horizon puts every object past it, which is the same state the
    real threshold reaches an hour later without making the test wait.
    """
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Bounded")
    base = f"/datasets/{dataset.id}/export?format=geojson"
    for n in range(8):
        resp = await client.get(f"{base}&where=pop+%3E+{n}", headers=admin_auth_header)
        assert resp.status_code == 200, resp.text

    root = f"export-cache/{cache._tenant_segment()}/{dataset.id}/"
    before = await get_storage().list(root)
    assert len(before) >= 8, f"precondition: eight selections were stored, saw {before}"

    await cache.sweep(age_threshold_seconds=-1)

    after = await get_storage().list(root)
    assert after == [], (
        f"{len(after)} object(s) outlived the horizon: {after[:3]}. A caller who "
        f"varies bbox or where can otherwise grow this prefix without bound, and "
        f"every later sweep pays to list it."
    )


# ---------------------------------------------------------------------------
# Review r3: cancellation
# ---------------------------------------------------------------------------


async def test_a_cancel_during_publication_does_not_strand_the_conversion(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    conversions,
    monkeypatch,
):
    """A client disconnect mid-publish must not leave a multi-GB directory behind.

    ``store`` catches ``Exception``, and ``CancelledError`` is a
    ``BaseException`` — the same distinction fix(#1550) turned on. The await sat
    outside the ``except BaseException`` that owns the conversion directory and
    before any response had taken it, so a cancel during the hash, the upload or
    the sweep stranded the directory until the four-hour orphan sweep, and
    repeated cancels fill the staging volume.

    Cancelled at the hash because that is where a large export spends its time,
    and because it is the first await inside ``store`` — a fix that only guarded
    the upload would pass a test that cancelled the upload.
    """
    import asyncio

    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Cancelled Publish")

    async def _cancelled(file_path):
        raise asyncio.CancelledError()

    monkeypatch.setattr(cache, "_digest_and_size", _cancelled)

    # The ASGI stack turns the cancel into "No response returned" by the time it
    # reaches httpx, so the abort is asserted by NAME rather than by type — and
    # asserted at all, because a request that quietly succeeded would leave no
    # directory either (the response's background task would have taken it) and
    # this test would pass having exercised nothing.
    outcome = "completed"
    try:
        await client.get(_url(dataset.id), headers=admin_auth_header)
    except (asyncio.CancelledError, RuntimeError) as exc:
        outcome = type(exc).__name__

    assert outcome in ("CancelledError", "RuntimeError"), (
        f"the request {outcome}; this test needs it aborted mid-publication"
    )
    assert conversions.count == 1, "precondition: the conversion ran"
    leftovers = [
        name
        for name in os.listdir(conversions.root)
        if os.path.isdir(os.path.join(conversions.root, name))
    ]
    assert leftovers == [], (
        f"the conversion directory {leftovers} outlived a cancelled request. "
        f"Nothing owns it now: the response never existed, so no background task "
        f"will clean it up."
    )
