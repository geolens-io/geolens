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

import hashlib
from datetime import UTC, datetime
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.platform.storage import get_storage
from app.processing.export import artifact_cache
from app.processing.export.ogr import FORMAT_MAP

from tests.factories import create_dataset, get_user_id

# Past `_MAX_EXPORT_FEATURES`, which is the only shape that reaches the ogr
# path's bounded COUNT at all: under the ceiling the route skips it entirely.
_OVER_THE_CEILING = 5_000_001

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


async def _seed_aged_artifact(storage, dataset_id, selection, digest, payload, age):
    """Put an artifact and make it genuinely that old, mtime included.

    fix(#1532 review r10): reclamation ages from `max(key stamp, last_modified)`,
    so backdating only the key stamp seeds a state production cannot reach — an
    object whose bytes landed seconds ago but whose name claims otherwise. The
    file's modified time has to move too, or the test is describing a fiction and
    asserting the sweep respects it.
    """
    key = artifact_cache._artifact_key(
        dataset_id, selection, digest, len(payload), time.time() - age
    )
    await storage.put(key, payload)
    path = Path(storage.base_dir) / key
    when = time.time() - age
    os.utime(path, (when, when))
    return key


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

    aged = await _seed_aged_artifact(
        storage, dataset.id, "old", "a" * 64, b"abcdef", 7200
    )
    young = cache._artifact_key(dataset.id, "new", "b" * 64, 6, time.time())
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

    aged = await _seed_aged_artifact(
        storage, dataset.id, selection, "a" * 64, b"abcdef", 7200
    )
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


# ---------------------------------------------------------------------------
# Review r4
# ---------------------------------------------------------------------------


async def test_a_full_store_reclaims_and_then_succeeds(test_db_session, monkeypatch):
    """fix(#1532 review r4): a full store must not deadlock the cache.

    ``_sweep_occasionally`` ran AFTER the upload, and it is the only production
    call to it. A ``put`` that raised on a full volume therefore exited ``store``
    before any reclamation, and with nothing else sweeping ``export-cache/`` the
    aged artifacts that filled the volume could never be removed by a later
    request: caching stayed dead, and on the local backend the shared staging
    volume stayed too full to generate larger exports at all, until an operator
    deleted files by hand.

    Sweeping first makes a full store self-healing. The quota here is a stand-in
    for ENOSPC — what matters is that the write fails while aged artifacts are
    sitting there reclaimable, and that the next attempt gets them back.
    """
    import tempfile

    from app.platform.storage import get_storage
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Full Store")
    storage = get_storage()
    for n in range(3):
        await _seed_aged_artifact(
            storage, dataset.id, f"old-{n}", f"{n:064d}", b"abcdef", 5 * 3600
        )

    root = f"export-cache/{cache._tenant_segment()}/{dataset.id}/"
    quota = 3

    class _QuotaStorage:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        async def put(self, key, data):
            if len(await self._inner.list(root)) >= quota:
                raise OSError("No space left on device")
            return await self._inner.put(key, data)

    monkeypatch.setattr(
        "app.processing.export.artifact_cache.get_storage",
        lambda: _QuotaStorage(storage),
    )

    with tempfile.NamedTemporaryFile(delete=False) as handle:
        handle.write(b"a new export")
        path = handle.name

    stored = await cache.store(
        dataset.id,
        "fresh",
        file_path=path,
        filename="x.geojson",
        media_type="application/geo+json",
    )

    assert stored is not None, (
        "the store failed on a volume whose aged artifacts were reclaimable. "
        "Nothing else sweeps this prefix, so it stays full and caching stays "
        "dead for every later request."
    )
    assert await storage.exists(stored.key)


def test_the_sweep_horizon_matches_the_temp_export_sweeper():
    """fix(#1532 review r4): one horizon, imported rather than restated.

    ``staging.py`` already worked this hazard out for the temp-export sweeper:
    at one hour, "an in-flight export survives a restart" becomes "any export
    whose generation plus client download time exceeds an hour is deleted out
    from under it on the very next cycle". The same applies to a cached artifact
    still being streamed, and worse on Azure, where ``downloader.chunks()``
    fetches later chunks as the response goes — so an already-started 200 dies
    truncated rather than failing to start.

    Asserted by identity, not by value: a test comparing against 14400 would
    keep passing if `staging.py` revised its reasoning and this module did not.
    """
    from app.core.runtime.staging import EXPORTS_PERIODIC_SWEEP_AGE_SECONDS
    from app.processing.export import artifact_cache as cache

    assert cache._SWEEP_AGE_SECONDS == EXPORTS_PERIODIC_SWEEP_AGE_SECONDS
    assert cache._SWEEP_AGE_SECONDS > 3600, (
        "an hour is the horizon staging.py explicitly rejected for a periodic "
        "pass, because it deletes long downloads out from under themselves"
    )


async def test_a_cached_parquet_probe_does_not_replan_per_range(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    """fix(#1532 review r4): the expensive plan is behind the cache, not in front.

    ``plan_parquet_export`` introspects the live table and runs a bounded count
    up to a million rows, and it sat ABOVE the artifact lookup — so every HEAD
    and every range slice of an artifact that already existed repeated that
    scan, preserving most of the load the cache exists to remove.

    Counted rather than timed, and across a request SEQUENCE, for the same
    reason the conversion-count test is: the defect is per-request work that
    should be per-artifact, and one response cannot show it.

    The planner is stubbed rather than run. What is being asserted is that the
    ROUTE stops calling it once an artifact exists; running the real one would
    need a materialized feature table and would measure pyarrow rather than the
    ordering under test.
    """
    import tempfile

    import app.processing.export.parquet as parquet_module

    plans = {"count": 0}
    root = tempfile.mkdtemp(prefix="test_parquet_1532_")

    async def _counted_plan(*args, **kwargs):
        plans["count"] += 1
        return SimpleNamespace(columns=["gid"], where=None, bbox=None)

    async def _fake_export(*args, **kwargs):
        directory = os.path.join(root, uuid.uuid4().hex)
        os.makedirs(directory)
        path = os.path.join(directory, "Parquet Probe.parquet")
        with open(path, "wb") as handle:
            handle.write(b"PAR1" + bytes(range(256)) * 4)
        return path, "Parquet Probe.parquet", parquet_module.PARQUET_MEDIA_TYPE

    monkeypatch.setattr(parquet_module, "plan_parquet_export", _counted_plan)
    monkeypatch.setattr(parquet_module, "export_parquet", _fake_export)

    dataset = await _dataset(test_db_session, "Parquet Probe")
    url = f"/datasets/{dataset.id}/export?format=parquet"

    first = await client.get(url, headers=admin_auth_header)
    assert first.status_code == 200, first.text
    assert plans["count"] == 1, (
        f"precondition: the cold request plans once, saw {plans['count']}"
    )

    await client.head(url, headers=admin_auth_header)
    for start in range(0, 400, 100):
        resp = await client.get(
            url, headers={**admin_auth_header, "Range": f"bytes={start}-{start + 99}"}
        )
        assert resp.status_code in (200, 206), resp.text

    assert plans["count"] == 1, (
        f"a HEAD and four ranges against a cached parquet export ran "
        f"{plans['count']} planner invocations. Each introspects the table and "
        f"counts up to a million rows for an artifact that already exists."
    )

    shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------
# Review r5
# ---------------------------------------------------------------------------


async def test_an_enospc_mid_write_leaves_no_partial_object(
    test_db_session, monkeypatch
):
    """fix(#1532 review r5): a failed write must not hold the volume it filled.

    ``LocalStorageProvider.put`` opened the FINAL path with ``wb`` and streamed
    into it, so an ENOSPC mid-copy left a truncated file under the name every
    reader resolves — carrying a FRESH timestamp, which is what made it
    unreclaimable. The forced sweep skips it because it is young by every rule
    this module has, the retry then fails for the reason the first attempt did on
    a volume the first attempt made worse, and the space is held for the whole
    four-hour horizon while later exports 503.

    This is the size-in-key detection revealing its own residue: lookup notices
    the truncation and rebuilds, which is correct and which leaves another
    partial behind every time. Detection without cleanup accumulates.

    The write is broken partway rather than refused outright, because a ``put``
    that never writes anything proves nothing about a partial.
    """
    import tempfile

    import app.platform.storage.local as local_module
    from app.platform.storage import get_storage
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "ENOSPC")
    storage = get_storage()
    real_copy = local_module.shutil.copyfileobj

    def _fails_partway(src, dst, length=None):
        dst.write(src.read(64))
        dst.flush()
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(local_module.shutil, "copyfileobj", _fails_partway)

    with tempfile.NamedTemporaryFile(delete=False) as handle:
        handle.write(bytes(range(256)) * 8)
        path = handle.name

    stored = await cache.store(
        dataset.id,
        "torn",
        file_path=path,
        filename="x.geojson",
        media_type="application/geo+json",
    )

    monkeypatch.setattr(local_module.shutil, "copyfileobj", real_copy)

    assert stored is None, "precondition: the write failed"
    residue = await storage.list(
        f"export-cache/{cache._tenant_segment()}/{dataset.id}/"
    )
    assert residue == [], (
        f"a failed write left {residue}. Each carries a fresh timestamp, so the "
        f"sweep cannot reclaim it for four hours, and every rebuild in that "
        f"window adds another."
    )


async def test_a_non_atomic_provider_has_its_partial_deleted(
    test_db_session, monkeypatch
):
    """The belt-and-braces half, on the backend shape that needs it.

    `LocalStorageProvider.put` is atomic now, so on the shipped backends a
    failed write leaves nothing to delete and `_discard` is a no-op. That is
    exactly why it needs its own test: a cleanup that only runs where nothing is
    broken is a cleanup nobody notices has stopped working, and a future provider
    that writes in place would opt out of it silently.

    The double writes the object and THEN fails, which is what a non-atomic
    provider does.
    """
    import tempfile

    from app.platform.storage import get_storage
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Non Atomic")
    storage = get_storage()
    written: list[str] = []

    class _WritesThenFails:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        async def put(self, key, data):
            await self._inner.put(key, b"a partial object")
            written.append(key)
            raise OSError(28, "No space left on device")

    monkeypatch.setattr(
        "app.processing.export.artifact_cache.get_storage",
        lambda: _WritesThenFails(storage),
    )

    with tempfile.NamedTemporaryFile(delete=False) as handle:
        handle.write(b"the export that never landed")
        path = handle.name

    stored = await cache.store(
        dataset.id,
        "partial",
        file_path=path,
        filename="x.geojson",
        media_type="application/geo+json",
    )

    assert stored is None, "precondition: the write failed"
    assert len(written) == 2, (
        f"precondition: the write is attempted twice, once before the forced "
        f"sweep and once after, saw {len(written)}"
    )
    for key in written:
        assert not await storage.exists(key), (
            f"{key} survived a failed write. Both attempts leave a partial, and "
            f"neither is old enough for the sweep to reclaim."
        )


# ---------------------------------------------------------------------------
# Internal review: the degraded path is the one that fires under load
# ---------------------------------------------------------------------------


async def test_the_fallback_never_answers_a_range_with_a_slice(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    conversions,
    monkeypatch,
):
    """When publication does not happen, a Range must still get 200-whole.

    The fallback used to be a `FileResponse`, and starlette parses `Range`
    inside it — single and multipart, no `If-Range` required. So a resuming
    client was answered with a 206 of a FRESH conversion at offsets it had
    measured against a previous one: #1532's entire defect, alive on the path
    that fires precisely when things are going wrong. A full store, a contested
    selection and an exhausted budget all land here.

    The mtime validators are asserted absent too. `FileResponse` sent an ETag
    and a Last-Modified derived from the temp file, which the artifact path
    never sends, so one URL disagreed with itself about which validators the
    resource has — and #1532 measured that ETag changing between two conversions
    of unchanged data, so a client that trusted it would resume across a
    rebuild.
    """

    def _down():
        raise OSError("object store is down")

    dataset = await _dataset(test_db_session, "Fallback Range")
    monkeypatch.setattr("app.processing.export.artifact_cache.get_storage", _down)

    resp = await client.get(
        _url(dataset.id), headers={**admin_auth_header, "Range": "bytes=100-199"}
    )

    assert resp.status_code == 200, (
        f"the fallback answered {resp.status_code} to a bare Range. A 206 here "
        f"is a slice of a conversion this client has never seen, at offsets it "
        f"measured against one it has."
    )
    assert resp.content == conversions.body
    assert "content-range" not in resp.headers
    assert "etag" not in resp.headers, (
        f"the fallback published etag={resp.headers.get('etag')!r}, which the "
        f"artifact path never sends and which #1532 measured changing between "
        f"two conversions of identical data"
    )
    assert "last-modified" not in resp.headers


async def test_a_contested_selection_answers_ranges_with_the_whole_thing(
    client: AsyncClient, admin_auth_header: dict, test_db_session, conversions
):
    """Two distinct fresh artifacts under one key must not be sliced.

    Nothing stops two artifacts inside one TTL: every client arriving during a
    slow build misses and builds its own, and the herd repeats at each window
    boundary. Their bytes differ whenever the format is GPKG — the default, and
    it stamps `gpkg_contents.last_change` per build — or whenever a write landed
    without moving `tile_cache_version`. So a client reading in slices could be
    handed one artifact and then the other.

    `lookup` already has the listing, so noticing costs nothing, and the answer
    is the same one a rebuild gets: the complete representation. HEAD and the
    ETag are unaffected — each artifact is internally consistent, and a
    whole-object read of either is correct.
    """
    from app.platform.storage import get_storage
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Contested")
    url = _url(dataset.id)

    first = await client.get(url, headers=admin_auth_header)
    assert first.status_code == 200

    # A second builder's output, landing inside the same window with different
    # bytes — what an overlapping GPKG build produces.
    selection = [
        k.rsplit("/", 2)[1]
        for k in await get_storage().list(
            f"export-cache/{cache._tenant_segment()}/{dataset.id}/"
        )
    ][0]
    rival = b"a second builder's output, same window"
    await get_storage().put(
        cache._artifact_key(dataset.id, selection, "c" * 64, len(rival), time.time()),
        rival,
    )

    sliced = await client.get(url, headers={**admin_auth_header, "Range": "bytes=0-31"})

    assert sliced.status_code == 200, (
        f"a range against a contested selection returned {sliced.status_code}. "
        f"Two distinct sets of bytes are fresh here, so a slice of either can be "
        f"appended to a slice of the other."
    )
    assert "content-range" not in sliced.headers


async def test_a_second_publisher_does_not_add_to_a_fresh_selection(
    test_db_session, monkeypatch
):
    """A build that finishes late does not publish over a fresh sibling.

    The other half of the contested fix, and the one that keeps the condition
    rare rather than merely handled: a builder that started before a sibling
    finished re-checks on the way out and serves its own bytes instead of adding
    a second artifact nobody asked for.
    """
    import tempfile

    from app.platform.storage import get_storage
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Late Publisher")
    storage = get_storage()
    incumbent = cache._artifact_key(dataset.id, "busy", "a" * 64, 6, time.time())
    await storage.put(incumbent, b"abcdef")

    with tempfile.NamedTemporaryFile(delete=False) as handle:
        handle.write(b"the late builder's output")
        path = handle.name

    stored = await cache.store(
        dataset.id,
        "busy",
        file_path=path,
        filename="x.geojson",
        media_type="application/geo+json",
    )

    assert stored is None, "a late builder must not publish over a fresh sibling"
    keys = await storage.list(f"export-cache/{cache._tenant_segment()}/{dataset.id}/")
    assert keys == [incumbent], f"the selection grew to {keys}"


async def test_a_future_stamped_artifact_is_not_served(test_db_session):
    """A clock-ahead worker's key must not outrank every honest one.

    Candidates are ordered by the stamp in the key, so a future one beats every
    honest sibling for as long as the skew lasts.

    fix(#1532 review r9) narrowed this without removing it. Freshness now comes
    from the object's own modified time, which the BACKEND stamps, so a bad
    worker clock can no longer keep an artifact alive past its TTL. What it can
    still do is win the sort — and reclamation, which must stay portable, still
    reads the key — so a future-stamped candidate is skipped outright. Ignoring
    it costs a rebuild.
    """
    from app.platform.storage import get_storage
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Clock Ahead")
    storage = get_storage()
    honest = cache._artifact_key(dataset.id, "skew", "a" * 64, 6, time.time() - 1)
    await storage.put(honest, b"abcdef")
    await storage.put(
        cache._artifact_key(dataset.id, "skew", "b" * 64, 6, time.time() + 3600),
        b"abcdef",
    )

    resolved = await cache.lookup(
        dataset.id, "skew", filename="x.geojson", media_type="application/geo+json"
    )

    assert resolved is not None and resolved.key == honest, (
        f"lookup resolved to {resolved.key if resolved else None}; a key stamped "
        f"an hour in the future would answer for the TTL plus that hour"
    )


async def test_publication_stops_at_the_byte_budget(test_db_session, monkeypatch):
    """Fresh artifacts must not be able to fill the shared staging volume.

    On the local backend this cache lives inside `settings.upload_staging_dir` —
    the volume `export_dataset` converts on and every ingest stages uploads on.
    Before #1532 those export bytes were transient; retaining a copy of every
    distinct selection for a horizon means a handful of large ones blocks every
    conversion and upload on the instance. The reclaim-and-retry added in review
    r4 only frees AGED artifacts, so a volume full of FRESH ones has nothing to
    give back.
    """
    import tempfile

    from app.platform.storage import get_storage
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Budget")
    storage = get_storage()
    monkeypatch.setattr(cache, "_BUDGET_BYTES", 32)
    await storage.put(
        cache._artifact_key(dataset.id, "held", "a" * 64, 30, time.time()), b"a" * 30
    )

    with tempfile.NamedTemporaryFile(delete=False) as handle:
        handle.write(b"more than the budget has room for")
        path = handle.name

    stored = await cache.store(
        dataset.id,
        "over",
        file_path=path,
        filename="x.geojson",
        media_type="application/geo+json",
    )

    assert stored is None, (
        "publication past the byte budget would let a few large selections hold "
        "the volume every conversion and upload needs"
    )


async def test_a_failed_write_cannot_delete_a_siblings_object(test_db_session):
    """Writer-owned keys: `_discard` must only ever remove this writer's attempt.

    Keys were `{stamp}-{size}-{digest}` with a whole-second stamp, so two
    builders of a DETERMINISTIC format finishing in the same second computed the
    same key. If one write then failed — an S3 SlowDown, a lost
    CompleteMultipartUpload ack — its cleanup deleted the object the other had
    just published, and readers already past their response headers got a
    FileNotFoundError mid-stream.

    Identical payloads, deliberately: `test_two_concurrent_publishers_both_survive`
    uses different ones, so the same-key case it is named for was the one case it
    could not reach.
    """
    from app.processing.export import artifact_cache as cache

    payload = b"byte-identical output"
    digest = hashlib.sha256(payload).hexdigest()
    at = time.time()
    dataset = await _dataset(test_db_session, "Same Second")

    first = cache._artifact_key(dataset.id, "sel", digest, len(payload), at)
    second = cache._artifact_key(dataset.id, "sel", digest, len(payload), at)

    assert first != second, (
        "two builders of identical bytes in the same second share a key, so one "
        "writer's cleanup deletes the other's published object"
    )
    assert (
        cache.parse_artifact_key(first)
        == cache.parse_artifact_key(second)
        == (
            float(int(at)),
            len(payload),
            digest,
        )
    ), "the nonce must not disturb what the key means"


async def test_a_cached_probe_does_not_recount_the_selection(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    conversions,
    monkeypatch,
):
    """The ogr path's bounded COUNT is behind the cache too.

    Sibling of the parquet planner case, and it needed its own move:
    `_count_selected_features` scans to 5,000,001 rows with the caller's WHERE on
    an unindexed column, and it ran above the lookup — so every range slice and
    every HEAD of an artifact that already existed paid for it.

    The dataset is over the unfiltered ceiling and the request carries a filter,
    which is the only shape that reaches the COUNT at all.
    """
    import app.processing.export.router as router_module

    counts = {"n": 0}

    async def _counted(*args, **kwargs):
        # Stubbed rather than delegated: the real one needs a materialized
        # feature table, and what is under test is whether the ROUTE calls it.
        counts["n"] += 1
        return 1

    monkeypatch.setattr(router_module, "_count_selected_features", _counted)

    dataset = await _dataset(
        test_db_session, "Counted Probe", feature_count=_OVER_THE_CEILING
    )
    url = f"/datasets/{dataset.id}/export?format=geojson&where=pop+%3E+1"

    first = await client.get(url, headers=admin_auth_header)
    assert first.status_code == 200, first.text
    assert counts["n"] == 1, f"precondition: the cold request counts once, saw {counts}"

    await client.head(url, headers=admin_auth_header)
    for start in range(0, 300, 100):
        resp = await client.get(
            url, headers={**admin_auth_header, "Range": f"bytes={start}-{start + 99}"}
        )
        assert resp.status_code in (200, 206), resp.text

    assert counts["n"] == 1, (
        f"a HEAD and three ranges against a cached export ran {counts['n']} "
        f"bounded counts. Each is a scan to five million rows for an artifact "
        f"that already exists."
    )


async def test_a_cancel_during_the_first_write_discards_its_attempt(
    test_db_session, monkeypatch
):
    """A cancelled FIRST write must clean up after itself too.

    `_put_with_reclaim` caught `Exception` around the first attempt, and a
    `CancelledError` is not one — a client disconnect or a worker shutdown
    therefore skipped the retry (right: a cancelled request wants no retry) AND
    the discard (wrong: the attempt it made may have landed). Only the retry's
    own arm cleaned up, so the failure mode was the FIRST write's partial
    surviving.

    The local provider is atomic now, so its final key is safe either way; a
    non-atomic backend is not, and that is what the double here stands in for.
    Nothing about the shape of `except Exception` announces which of the two
    arms a cancel reaches, which is why this needs a test rather than a reading.
    """
    import asyncio
    import tempfile

    from app.platform.storage import get_storage
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Cancelled First Write")
    storage = get_storage()
    written: list[str] = []

    class _WritesThenCancels:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        async def put(self, key, data):
            await self._inner.put(key, b"a partial object")
            written.append(key)
            raise asyncio.CancelledError()

    monkeypatch.setattr(
        "app.processing.export.artifact_cache.get_storage",
        lambda: _WritesThenCancels(storage),
    )

    with tempfile.NamedTemporaryFile(delete=False) as handle:
        handle.write(b"the export whose client hung up")
        path = handle.name

    with pytest.raises(asyncio.CancelledError):
        await cache.store(
            dataset.id,
            "cancelled",
            file_path=path,
            filename="x.geojson",
            media_type="application/geo+json",
        )

    assert len(written) == 1, (
        f"a cancel must not be retried; the write was attempted {len(written)} time(s)"
    )
    assert not await storage.exists(written[0]), (
        f"{written[0]} survived a cancelled write. Nothing else removes it: it "
        f"carries a fresh timestamp, so the sweep leaves it alone for a horizon."
    )


async def test_an_exhausted_budget_reclaims_and_then_publishes(
    test_db_session, monkeypatch
):
    """fix(#1532 review r6): the budget check must not sit above the sweep.

    It was an early return placed before the only thing that reclaims, so once
    claimed sizes reached the ceiling every later publication left without
    sweeping — and once those artifacts passed the horizon nothing was ever
    going to reclaim them. Misses then rebuilt and served whole forever, until an
    operator cleaned storage by hand.

    The same deadlock r4 fixed for ENOSPC, re-created by a new early exit above
    the same sweep. The artifacts here are past the horizon, so a sweep frees the
    room; the point is whether one runs at all.
    """
    import tempfile

    from app.platform.storage import get_storage
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Budget Reclaim")
    storage = get_storage()
    monkeypatch.setattr(cache, "_BUDGET_BYTES", 64)
    for n in range(3):
        await _seed_aged_artifact(
            storage, dataset.id, f"old-{n}", f"{n:064d}", b"a" * 30, 5 * 3600
        )

    with tempfile.NamedTemporaryFile(delete=False) as handle:
        handle.write(b"a new export")
        path = handle.name

    stored = await cache.store(
        dataset.id,
        "fresh",
        file_path=path,
        filename="x.geojson",
        media_type="application/geo+json",
    )

    assert stored is not None, (
        "the budget refused a publication whose room was sitting there past the "
        "horizon. Nothing else sweeps this prefix, so it never comes back."
    )
    assert await storage.exists(stored.key)


async def test_two_publishers_may_overshoot_and_the_horizon_reclaims_it(
    test_db_session, monkeypatch
):
    """The budget's contract: a soft ceiling with bounded, expiring overshoot.

    `StorageProvider` offers no way to claim space, so two workers list the same
    total, both pass the pre-check and both write. The excess is bounded by
    concurrent publishers times one artifact each and lasts at most one
    reclamation horizon.

    A post-write re-check that dropped the writer's own artifact lived here for
    one round (fix(#1532 review r6)) and is withdrawn (r7): once `put` returns,
    `lookup` can hand that key to another request, which has already declared a
    Content-Length and is about to open its stream — so the delete truncates a
    download. An overshoot that expires is a better failure than a truncated
    file, and making the ceiling hard would need publication to become visible
    only after a check, which needs a rename primitive S3 and Azure do not have
    short of a server-side copy.

    So the assertions are the contract, not a count: both requests complete, and
    the horizon takes the excess.
    """
    import asyncio
    import tempfile

    from app.platform.storage import get_storage
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Budget Race")
    storage = get_storage()
    payload = b"z" * 40
    monkeypatch.setattr(cache, "_BUDGET_BYTES", 60)  # room for one, not two

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

    async def _publish(tag: bytes):
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(payload + tag)
            path = handle.name
        return await cache.store(
            dataset.id,
            "contended",
            file_path=path,
            filename="x.geojson",
            media_type="application/geo+json",
        )

    results = await asyncio.gather(_publish(b"a"), _publish(b"b"))

    assert waiting == 2, (
        "the two publishers did not overlap, so this says nothing about the "
        "case it is named for"
    )
    assert all(r is not None for r in results), (
        "both publications must complete; the ceiling is soft, and a writer that "
        "measured room for itself is not asked to give it back"
    )
    for artifact in results:
        assert await storage.exists(artifact.key), (
            f"{artifact.key} was deleted after publication. A key `lookup` can "
            f"already have handed out belongs to a response that has declared "
            f"its length."
        )

    await cache.sweep(age_threshold_seconds=-1)

    remaining = [
        k
        for k in await storage.list(
            f"export-cache/{cache._tenant_segment()}/{dataset.id}/"
        )
        if cache.parse_artifact_key(k)
    ]
    assert remaining == [], (
        f"the horizon left {remaining}. An overshoot the sweep does not reclaim "
        f"is not bounded, it is permanent."
    )


# ---------------------------------------------------------------------------
# Review r7: the scratch files this PR introduced, everywhere
# ---------------------------------------------------------------------------


def test_orphaned_write_scratch_is_reclaimed_outside_the_export_prefix(tmp_path):
    """`LocalStorageProvider.put`'s scratch files leak from EVERY caller, not one.

    The atomic write added for #1532 writes `<name>.<hex>.tmp` beside its
    destination and renames. An ordinary failure removes it; a SIGKILL, an OOM or
    a power loss does not — and the residue sits at full or partial size under
    whatever prefix was being written. COGs, uploaded originals, VRTs, map
    assets: all of them, because the write is shared.

    Only the export cache knew the pattern and it only scans its own prefix, so
    everything else leaked permanently and repeated crashes ate the shared
    staging volume. This PR introduced the files, so it owns the reclaimer.

    The fresh one is asserted to survive in the same test as the aged one: a
    sweeper that took both would delete a multi-gigabyte COG mid-write, which is
    a worse failure than the leak.
    """
    from app.core.runtime.staging import sweep_orphaned_write_scratch

    rasters = tmp_path / "rasters" / "abc"
    rasters.mkdir(parents=True)
    aged = rasters / "src.cog.tif.0123456789abcdef0123456789abcdef.tmp"
    aged.write_bytes(b"half a COG")
    os.utime(aged, (time.time() - 10 * 3600, time.time() - 10 * 3600))
    fresh = rasters / "other.cog.tif.fedcba9876543210fedcba9876543210.tmp"
    fresh.write_bytes(b"a write in progress")
    unrelated = rasters / "keep.tif"
    unrelated.write_bytes(b"a real object")

    removed = sweep_orphaned_write_scratch(tmp_path, age_threshold_seconds=4 * 3600)

    assert not aged.exists(), (
        f"the sweeper removed {removed} file(s) and left a ten-hour-old scratch "
        f"file outside export-cache/. Nothing else knows the pattern."
    )
    assert fresh.exists(), (
        "a scratch file younger than the horizon is a write in progress; "
        "deleting it truncates whatever is being uploaded"
    )
    assert unrelated.exists(), "the sweeper must only take the scratch pattern"


async def test_a_put_survives_losing_its_directory_to_a_prune(tmp_path, monkeypatch):
    """A concurrent prune must not fail an unrelated, valid write.

    Removing empty directories used to live in `LocalStorageProvider.delete`,
    which made every caller race it: a map or ingest write, neither of which
    retries, could lose its directory between the `mkdir` and opening its temp
    file, and get a `FileNotFoundError` for a write that was entirely correct.

    Both halves are fixed and this covers the second. The pruning moved into the
    export cache's own sweep, which owns its prefix — and `put` tolerates losing
    the directory anyway, because "nothing else prunes today" is a property of
    today.

    The race is driven into the window rather than hoped for: the directory is
    removed between the mkdir and the open.
    """
    from app.platform.storage.local import LocalStorageProvider

    provider = LocalStorageProvider(base_dir=str(tmp_path))
    key = "some/deep/prefix/object.bin"
    target_dir = tmp_path / "some" / "deep" / "prefix"
    real_copy = shutil.copyfileobj
    pruned = {"done": False}

    def _prune_then_copy(src, dst, length=None):
        return real_copy(src, dst, length)

    import app.platform.storage.local as local_module

    real_mkdir = Path.mkdir

    def _mkdir_then_prune(self, *args, **kwargs):
        result = real_mkdir(self, *args, **kwargs)
        if self == target_dir and not pruned["done"]:
            pruned["done"] = True
            # A sweeper deciding this directory is empty, right now.
            shutil.rmtree(tmp_path / "some")
        return result

    monkeypatch.setattr(local_module.shutil, "copyfileobj", _prune_then_copy)
    monkeypatch.setattr(Path, "mkdir", _mkdir_then_prune)

    await provider.put(key, b"a valid write")

    monkeypatch.undo()
    assert pruned["done"], "the prune never landed inside the window"
    assert await provider.get(key) == b"a valid write", (
        "a write that lost its directory to a concurrent prune failed, and the "
        "callers that hit this (map assets, ingest) have no retry of their own"
    )


async def test_the_sweep_prunes_its_own_empty_selection_dirs(test_db_session):
    """Directory pruning belongs to the prefix's owner, not to every delete.

    A filesystem keeps a directory after its last file goes; an object store has
    none to keep. The export cache creates one per caller-controlled selection,
    so they accumulate and every listing scandirs all of them — but doing the
    cleanup inside the generic `delete` made unrelated writers race it.

    Asked for by `getattr` rather than `isinstance`, so a provider with no
    directories simply does not offer it.
    """
    from app.platform.storage import get_storage
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Prune Dirs")
    storage = get_storage()
    for n in range(4):
        await _seed_aged_artifact(
            storage, dataset.id, f"one-off-{n}", f"{n:064d}", b"abcdef", 10 * 3600
        )

    root = Path(storage.base_dir) / "export-cache"
    assert sum(1 for p in root.rglob("*") if p.is_dir()) >= 4

    await cache.sweep(age_threshold_seconds=3600)

    leftover = [p for p in root.rglob("*") if p.is_dir()]
    assert leftover == [], (
        f"{len(leftover)} empty selection directories survived: "
        f"{[p.name for p in leftover[:3]]}. Filters are caller-controlled, so "
        f"they accumulate without limit and every later listing walks them."
    )


# ---------------------------------------------------------------------------
# Review r8
# ---------------------------------------------------------------------------


async def test_a_staggered_sibling_still_refuses_ranges_after_it_expires(
    client: AsyncClient, admin_auth_header: dict, test_db_session, conversions
):
    """`contested` must see every sibling, not only the fresh ones.

    Two builders a second apart are both inside the window at first, so ranges
    are correctly refused. Then the older one crosses the TTL: the fresh set
    holds a single digest, `contested` flips false, and a bare-Range client that
    started on the OLDER artifact resumes into a 206 of the newer. The same
    silent splice, arriving late through the staggered window rather than the
    overlapping one.

    The older sibling is exactly the artifact a client can still be reading —
    it lives until the horizon by design, so a reader that resolved it keeps
    streaming it. Freshness answers "may this serve a NEW request"; this asks
    "could anyone be part-way through a different one", and those are not the
    same question.

    The older artifact here is aged past the TTL and well inside the horizon,
    which is the exact window the fresh-set computation could not see.
    """
    from app.platform.storage import get_storage
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Staggered")
    url = _url(dataset.id)

    first = await client.get(url, headers=admin_auth_header)
    assert first.status_code == 200
    selection = [
        k.rsplit("/", 2)[1]
        for k in await get_storage().list(
            f"export-cache/{cache._tenant_segment()}/{dataset.id}/"
        )
    ][0]

    # A second builder's output, published a moment later and then aged out of
    # the freshness window — still reclaimable only by the horizon.
    older = b"the artifact a client is part-way through"
    await get_storage().put(
        cache._artifact_key(
            dataset.id, selection, "d" * 64, len(older), time.time() - 600
        ),
        older,
    )

    sliced = await client.get(url, headers={**admin_auth_header, "Range": "bytes=0-31"})

    assert sliced.status_code == 200, (
        f"a range returned {sliced.status_code} for a selection whose older "
        f"sibling has expired but not been reclaimed. That sibling is what a "
        f"resuming client is holding offsets against."
    )
    assert "content-range" not in sliced.headers


async def test_a_remote_put_drains_its_thread_before_the_caller_cleans_up(
    test_db_session, monkeypatch
):
    """A cancelled remote upload must finish before its cleanup runs.

    S3 and Azure handed their uploads to a bare `asyncio.to_thread`, which
    RETURNS on a cancel while the SDK keeps running in the executor. The
    caller's cleanup then races a live upload: `_discard` deletes the key being
    written, the router closes the source file underneath it, and the upload can
    commit after the delete, read a closed handle, or leave multipart residue no
    lifecycle rule is configured to collect.

    Only the local provider drained. Both remote ones do now, through the same
    helper the digest step uses.

    The double's thread sleeps past the cancel, and the assertion is on ORDER
    rather than on a status: the discard must not be observed before the upload
    thread returns. A test that only checked the final state would pass against
    the racing version whenever the scheduler happened to be kind.

    What this does NOT prove is that S3 and Azure drain — the double drains, so
    it would pass against providers that do not. It pins the half that is this
    module's: given a draining put, the cleanup is ordered after it.
    ``test_both_remote_puts_drain_their_upload_thread`` pins the other half.
    """
    import asyncio
    import tempfile
    import threading

    from app.platform.storage import get_storage
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Drain On Cancel")
    events: list[str] = []
    upload_started = threading.Event()

    class _SlowRemote:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        async def put(self, key, data):
            from app.core.async_io import run_in_thread_draining

            def _upload():
                upload_started.set()
                time.sleep(0.3)  # the SDK still working after the cancel
                events.append("upload-returned")

            await run_in_thread_draining(_upload)
            return "ok"

        async def delete(self, key):
            events.append("discard")
            return await self._inner.delete(key)

    monkeypatch.setattr(
        "app.processing.export.artifact_cache.get_storage",
        lambda: _SlowRemote(get_storage()),
    )

    with tempfile.NamedTemporaryFile(delete=False) as handle:
        handle.write(b"an export whose client hangs up mid-upload")
        path = handle.name

    task = asyncio.ensure_future(
        cache.store(
            dataset.id,
            "cancelled-upload",
            file_path=path,
            filename="x.geojson",
            media_type="application/geo+json",
        )
    )
    await asyncio.to_thread(upload_started.wait, 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert events and events[0] == "upload-returned", (
        f"cleanup ran before the upload thread returned: {events}. The delete "
        f"then races a live upload that can commit after it."
    )


def test_both_remote_puts_drain_their_upload_thread():
    """S3 and Azure must hand their uploads to the draining helper.

    A bare ``asyncio.to_thread`` RETURNS on a cancel while the SDK upload keeps
    running in the executor, so the caller's cleanup races a live upload: it can
    delete the key mid-write, close the source handle underneath it, or leave
    multipart parts and staged blocks behind that no lifecycle rule is
    configured to collect. Only the local provider drained.

    Structural, and for the same reason the read-path stub test is: exercising
    the real ones needs a backend, and this has to run in the default suite. The
    unwanted call is asserted absent as well as the wanted one present —
    `run_in_thread_draining` appearing somewhere in the method proves nothing if
    the upload itself still goes through `to_thread`.

    Comments are stripped and the call form is matched, so an explanatory
    mention of ``asyncio.to_thread`` beside the fixed call does not read as one.
    """
    import inspect

    from app.platform.storage.azure import AzureBlobStorageProvider
    from app.platform.storage.s3 import S3StorageProvider

    for provider in (S3StorageProvider, AzureBlobStorageProvider):
        source = "\n".join(
            line
            for line in inspect.getsource(provider.put).splitlines()
            if not line.strip().startswith("#")
        )
        assert "run_in_thread_draining(" in source, (
            f"{provider.__name__}.put does not drain its upload thread; a "
            f"cancelled request returns while the SDK is still writing"
        )
        assert "asyncio.to_thread(" not in source, (
            f"{provider.__name__}.put still hands the upload to a bare "
            f"to_thread, which is the call that returns before the write does"
        )


# ---------------------------------------------------------------------------
# Review r9
# ---------------------------------------------------------------------------


async def test_the_export_route_is_never_gzipped_and_others_still_are(
    client: AsyncClient, admin_auth_header: dict, test_db_session, conversions
):
    """A compressed 200 and a raw 206 must not share one ETag — on THIS route only.

    `GZipMiddleware` compresses a full response and skips a 206 by design, and
    this route's validator names the RAW stored bytes, so a client that took it
    from a compressed 200 and offered it back on an `If-Range` would have it
    accepted and splice raw bytes at compressed offsets. fix(#1540) hit exactly
    this with `image/tiff`.

    Scoped by PATH, and the second half of this test is why. An earlier revision
    excluded the export MEDIA TYPES app-wide, which also stopped compressing
    feature GeoJSON and the admin and audit CSV streams — endpoints that serve
    one representation and never a range, so the safety bought nothing there and
    the bandwidth loss was a straight regression. Asserting only that exports are
    uncompressed would have passed against that revision too.
    """
    dataset = await _dataset(test_db_session, "Gzip Scope")

    export = await client.get(
        _url(dataset.id),
        headers={**admin_auth_header, "Accept-Encoding": "gzip"},
    )
    assert export.status_code == 200, export.text
    assert export.headers.get("content-encoding") != "gzip", (
        "the export was gzipped; its ETag names the raw bytes every range is a "
        "slice of, so one validator would name two byte streams"
    )

    features = await client.get(
        f"/datasets/{dataset.id}/features?limit=1",
        headers={**admin_auth_header, "Accept-Encoding": "gzip"},
    )
    if features.status_code == 200 and len(features.content) >= 256:
        assert features.headers.get("content-encoding") == "gzip", (
            "feature GeoJSON stopped being compressed. It serves one "
            "representation and never a range, so excluding it buys no safety "
            "and costs real bandwidth."
        )


def test_the_gzip_exclusion_is_scoped_to_the_export_path():
    """The TIFF exclusion stays a media type; the export one must not be.

    `image/tiff` is right as a media-type exclusion because the COG download is
    its only producer — there the type and the route are the same set. The export
    formats are not: `application/geo+json` and `text/csv` have other producers,
    so excluding the types reaches endpoints that never needed it.

    Structural because the regression is invisible from the export route's own
    responses: both shapes make an export uncompressed, and only one of them
    leaves the rest of the API alone.
    """
    from app.api.main import app

    gzip_layer = next(
        m for m in app.user_middleware if m.cls.__name__ == "GZipMiddleware"
    )
    excluded = set(gzip_layer.kwargs["exclude_content_types"])

    assert "image/tiff" in excluded, (
        "the COG exclusion fix(#1540) added must survive this change"
    )
    for media in ("application/geo+json", "text/csv"):
        assert media not in excluded, (
            f"{media} is excluded app-wide, which also silences compression on "
            f"the feature and CSV-stream endpoints that share the type"
        )
    assert any(
        m.cls.__name__ == "NoCompressionForExportMiddleware"
        for m in app.user_middleware
    ), "the export route has no path-scoped opt-out, so it would be compressed"


async def test_the_budget_scan_stops_as_soon_as_it_knows(test_db_session, monkeypatch):
    """The inventory is bounded by the budget, not by the object count.

    It materialised the whole `export-cache/` listing on every publication, and
    the prefix is caller-controlled — anonymous callers vary bbox and where — so
    the cost grew with the number of distinct selections in the window and every
    publication paid for all of them.

    Accumulating page by page and returning at the first overrun bounds the work:
    at most one page beyond whatever fits. Asserted by counting pages CONSUMED,
    because a version that summed everything and compared once would return the
    same answer while doing all the work.
    """
    from app.platform.storage import get_storage
    from app.platform.storage.provider import StoredObject
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Budget Paging")
    consumed = {"pages": 0}
    monkeypatch.setattr(cache, "_BUDGET_BYTES", 100)

    class _ManyPages:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def iter_object_pages(self, prefix, **kwargs):
            async def _pages():
                for n in range(20):
                    consumed["pages"] += 1
                    yield [
                        StoredObject(
                            key=cache._artifact_key(
                                dataset.id, f"sel-{n}", f"{n:064d}", 60, time.time()
                            ),
                            last_modified=datetime.now(UTC),
                        )
                    ]

            return _pages()

    monkeypatch.setattr(
        "app.processing.export.artifact_cache.get_storage",
        lambda: _ManyPages(get_storage()),
    )

    assert await cache._fits_in_budget(10) is False
    assert consumed["pages"] == 2, (
        f"the scan read {consumed['pages']} of 20 pages. The budget is exceeded "
        f"on the second, so every page after it is work whose answer is already "
        f"known — and the prefix is caller-controlled."
    )


async def test_a_slow_upload_does_not_expire_its_own_artifact(
    test_db_session, monkeypatch
):
    """The freshness clock starts at publication, not before the upload.

    `built_at` is stamped before `put`, so a multi-gigabyte push to an object
    store spent the whole TTL getting there and the artifact was expired the
    moment it existed — the next probe missed and reconverted, defeating the
    cache for exactly the exports big enough to need ranges.

    Freshness reads the object's own modified time now, which every backend
    reports as completion. The key keeps its stamp for reclamation, which is a
    different question (could anything still be reading) and has to stay
    portable.

    The double sleeps past the TTL inside `put`, which is what a slow upload
    looks like from here.
    """
    import asyncio
    import tempfile

    from app.platform.storage import get_storage
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Slow Upload")
    monkeypatch.setattr(cache, "_ttl_seconds", lambda: 1)

    class _SlowUpload:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        async def put(self, key, data):
            await asyncio.sleep(1.4)  # longer than the TTL
            return await self._inner.put(key, data)

    monkeypatch.setattr(
        "app.processing.export.artifact_cache.get_storage",
        lambda: _SlowUpload(get_storage()),
    )

    with tempfile.NamedTemporaryFile(delete=False) as handle:
        handle.write(b"an export that took a while to upload")
        path = handle.name

    stored = await cache.store(
        dataset.id,
        "slow",
        file_path=path,
        filename="x.geojson",
        media_type="application/geo+json",
    )
    assert stored is not None

    monkeypatch.undo()
    monkeypatch.setattr(cache, "_ttl_seconds", lambda: 1)

    hit = await cache.lookup(
        dataset.id, "slow", filename="x.geojson", media_type="application/geo+json"
    )

    assert hit is not None, (
        "the artifact was expired the moment it was published, because its clock "
        "started before the upload it was waiting on"
    )
    assert hit.key == stored.key


@pytest.mark.parametrize("method", ["GET", "HEAD"])
async def test_a_revalidating_client_gets_304_from_the_cache(
    client: AsyncClient, admin_auth_header: dict, test_db_session, conversions, method
):
    """The ETag this route advertises has to be answerable.

    Publishing a strong validator and then ignoring `If-None-Match` is the
    expensive half of a cache contract: the client stores it, offers it back and
    receives the whole export it already has. Both verbs, because a probing
    client revalidates too, and the cached HEAD returns even earlier than the
    GET.
    """
    dataset = await _dataset(test_db_session, "Revalidate")
    url = _url(dataset.id)

    first = await client.get(url, headers=admin_auth_header)
    etag = first.headers["etag"]

    resp = await client.request(
        method, url, headers={**admin_auth_header, "If-None-Match": etag}
    )

    assert resp.status_code == 304, (
        f"a revalidating {method} got {resp.status_code}; the client already "
        f"holds this representation and is being sent it again"
    )
    assert resp.content == b""


@pytest.mark.parametrize("method", ["GET", "HEAD"])
async def test_a_stale_if_match_is_refused_by_the_cache(
    client: AsyncClient, admin_auth_header: dict, test_db_session, conversions, method
):
    """A client naming a version that has moved gets 412, not the new bytes.

    `If-Match` is the other way a careful client says "only if this is still the
    representation I have". RFC 9110 section 13.1.1 gives it no ignore-and-serve
    fallback, unlike `If-Range` — so a stale one is refused, and the 412 carries
    the ETag that IS current so the client can restart in one round trip.
    """
    dataset = await _dataset(test_db_session, "Stale IfMatch")
    url = _url(dataset.id)

    await client.get(url, headers=admin_auth_header)

    resp = await client.request(
        method,
        url,
        headers={**admin_auth_header, "If-Match": '"an-export-from-last-week"'},
    )

    assert resp.status_code == 412, (
        f"a stale If-Match on a {method} returned {resp.status_code}; a client "
        f"asking to act only on the version it holds was handed a different one"
    )
    assert resp.headers.get("etag"), "the 412 must name the version that IS current"


@pytest.mark.parametrize("method", ["GET", "HEAD"])
async def test_a_matching_if_match_still_serves_the_export(
    client: AsyncClient, admin_auth_header: dict, test_db_session, conversions, method
):
    """The vacuity guard: preconditions must admit the requests they should.

    An implementation that answered 412 to every `If-Match` and 304 to every
    `If-None-Match` would pass both tests above and break every conforming
    client, which is the population these headers exist for.
    """
    dataset = await _dataset(test_db_session, "Matching IfMatch")
    url = _url(dataset.id)

    first = await client.get(url, headers=admin_auth_header)
    etag = first.headers["etag"]

    resp = await client.request(
        method, url, headers={**admin_auth_header, "If-Match": etag}
    )

    assert resp.status_code == 200, (
        f"a matching If-Match on a {method} returned {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# Review r10
# ---------------------------------------------------------------------------


async def test_a_slow_upload_is_not_reclaimed_the_moment_it_appears(
    test_db_session, monkeypatch
):
    """Reclamation ages from publication too, not from the pre-upload stamp.

    Once freshness moved onto `last_modified` (review r9) the two clocks
    diverged by however long the push took. The sweep still read the key's
    stamp, which is taken BEFORE the upload — so an S3 or Azure upload that
    consumed most of the four-hour horizon could be reclaimed shortly after
    becoming visible, with a client streaming it, and one that exceeded the
    horizon was eligible the moment it appeared.

    Reclamation asks "could anyone still be reading this", and a client can only
    have started reading once the object existed. The key stamp stays as the
    portable floor; `last_modified` raises it to publication.

    The double reports a key stamped past the horizon and a modified time of
    now, which is exactly the slow-upload shape.
    """
    from app.platform.storage import get_storage
    from app.platform.storage.provider import StoredObject
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Slow Upload Sweep")
    storage = get_storage()
    stale_stamp = time.time() - 5 * 3600
    key = cache._artifact_key(dataset.id, "slow", "a" * 64, 6, stale_stamp)
    await storage.put(key, b"abcdef")

    class _JustPublished:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def iter_object_pages(self, prefix, **kwargs):
            async def _pages():
                yield [
                    StoredObject(
                        key=key,
                        last_modified=datetime.now(UTC),
                    )
                ]

            return _pages()

    monkeypatch.setattr(
        "app.processing.export.artifact_cache.get_storage",
        lambda: _JustPublished(storage),
    )

    await cache.sweep(age_threshold_seconds=3600)

    assert await storage.exists(key), (
        "an artifact whose upload finished seconds ago was reclaimed because "
        "its key was stamped before the upload began. A client that resolved it "
        "is mid-stream."
    )


@pytest.mark.parametrize("header,expected", [("If-None-Match", 304), ("If-Match", 412)])
async def test_the_build_path_answers_validators_too(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    conversions,
    header,
    expected,
):
    """Preconditions were evaluated on the hit branch only.

    A rebuild is exactly when a client's version claim matters most, and it was
    the one path that ignored it. The export is byte-deterministic for unchanged
    data, so a client revalidating after its artifact expired sends a validator
    that MATCHES what the rebuild produces — and was handed the whole export it
    already had. A stale `If-Match` on a rebuild got the new representation
    rather than a refusal.

    Driven through an expiry rather than by seeding, so the request really is a
    miss that builds: the first GET publishes, the TTL is dropped to nothing, and
    the second request rebuilds and then has to answer the validator.
    """
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Build Path Validators")
    url = _url(dataset.id)

    first = await client.get(url, headers=admin_auth_header)
    etag = first.headers["etag"]
    assert conversions.count == 1

    monkeypatch_value = '"an-export-from-last-week"' if header == "If-Match" else etag
    cache._ttl_seconds = lambda: 0  # every later request is a miss that rebuilds
    try:
        resp = await client.get(
            url, headers={**admin_auth_header, header: monkeypatch_value}
        )
    finally:
        cache._ttl_seconds = lambda: 600

    assert conversions.count == 2, "precondition: the second request rebuilt"
    assert resp.status_code == expected, (
        f"a {header} on the build path returned {resp.status_code}, not "
        f"{expected}; the rebuild ignored a claim the client was right to make"
    )
