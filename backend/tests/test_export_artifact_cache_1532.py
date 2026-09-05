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
import json
from datetime import UTC, datetime
import os
import shutil
import subprocess
import tempfile
import time
import uuid
import zipfile
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
        pmtiles_maxzoom=None,
        column_info=None,
        deadline=None,
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
    their pre-publish re-check and before publishing, and the test asserts both
    arrived; a sequence of two ``store`` calls proves nothing about concurrency.

    fix(#1532 review r29) made the barrier's placement matter: a builder whose
    re-check finds a fresh incumbent is handed that incumbent instead of
    publishing, so a barrier at the hash let the second builder's re-check land
    after the first's put and the two came back with ONE key — the lost-race
    path, which has its own test, not the two-publisher case this one pins.
    Holding both at the re-check makes both miss and both publish.
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
    real_lookup = cache.lookup

    async def _barriered(*args, **kwargs):
        nonlocal waiting
        result = await real_lookup(*args, **kwargs)
        if waiting < 2:
            waiting += 1
            if waiting == 2:
                arrived.set()
            await asyncio.wait_for(arrived.wait(), timeout=5)
        return result

    monkeypatch.setattr(cache, "lookup", _barriered)

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

    monkeypatch.setattr(cache, "digest_and_size", _cancelled)

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

    fix(#1532 review r18): the fallback DOES send an ETag now — the digest of
    the bytes it streams, the same validator the artifact path sends for the
    same bytes — so it is asserted equal to that digest rather than absent.
    Last-Modified stays absent: nothing on either path sends one.
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
    assert resp.headers.get("etag") == (
        f'"{hashlib.sha256(conversions.body).hexdigest()}"'
    ), (
        f"the fallback published etag={resp.headers.get('etag')!r}; the only "
        f"validator this path may send is the digest of the bytes it streams, "
        f"which is what the artifact path sends for the same bytes"
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
        k.split(f"/{dataset.id}/", 1)[1].rsplit("/", 1)[0]
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
    finished re-checks on the way out and adds no second artifact.

    fix(#1532 review r29): and it is handed the INCUMBENT to serve, not None. It
    used to serve its own bytes, which put its client on a representation no
    later Range would resolve; see
    `test_a_builder_that_loses_the_race_serves_the_incumbent`.
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

    assert stored is not None and stored.key == incumbent, (
        "a late builder must be handed the fresh sibling to serve, not None (r29) "
        "and not its own publication"
    )
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
    real_digest = cache.digest_and_size

    async def _barriered(file_path):
        nonlocal waiting
        result = await real_digest(file_path)
        if waiting < 2:
            waiting += 1
            if waiting == 2:
                arrived.set()
            await asyncio.wait_for(arrived.wait(), timeout=5)
        return result

    monkeypatch.setattr(cache, "digest_and_size", _barriered)

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
        k.split(f"/{dataset.id}/", 1)[1].rsplit("/", 1)[0]
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


@pytest.mark.parametrize("accept_encoding", ["gzip", "x-gzip", "br, gzip;q=0.9"])
async def test_the_export_route_is_never_gzipped_and_others_still_are(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    conversions,
    accept_encoding,
):
    """A compressed 200 and a raw 206 must not share one ETag — on THIS route only.

    Parametrized over the spellings that trip ``GZipMiddleware`` (fix(#1532
    review r17)): it engages on a SUBSTRING test, ``"gzip" in Accept-Encoding``,
    so ``x-gzip`` — which RFC 9110 section 8.4.1.3 makes equivalent to gzip —
    compresses too. The opt-out used to drop members that STARTED with gzip and
    let that one through; it now applies the same predicate the middleware does.

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
        headers={**admin_auth_header, "Accept-Encoding": accept_encoding},
    )
    assert export.status_code == 200, export.text
    assert export.headers.get("content-encoding") != "gzip", (
        f"the export was gzipped for Accept-Encoding: {accept_encoding}; its "
        f"ETag names the raw bytes every range is a slice of, so one validator "
        f"would name two byte streams"
    )

    features = await client.get(
        f"/datasets/{dataset.id}/features?limit=1",
        headers={**admin_auth_header, "Accept-Encoding": accept_encoding},
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

    fix(#1532 review r23/r24): the upload is five minutes, not five hours. The
    sweep ages through `_published_at` now, which caps publication at the stamp
    plus `_MAX_PUBLISH_SECONDS` — the longest an upload can take with a client
    still waiting — so a "push" that outlived that ceiling is not a publication
    anyone can be streaming, and IS reclaimed once the stamp plus the ceiling
    passes the horizon (`test_the_sweep_does_not_let_a_future_mtime_pin_an_artifact`
    pins that side). Inside the ceiling, the r10 property holds unchanged.
    """
    from app.platform.storage import get_storage
    from app.platform.storage.provider import StoredObject
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Slow Upload Sweep")
    storage = get_storage()
    stale_stamp = time.time() - 3600 - 300  # past the horizon; upload took 5 min
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


# ---------------------------------------------------------------------------
# Review r12
# ---------------------------------------------------------------------------


def test_two_gpkg_conversions_of_unchanged_data_are_byte_identical(tmp_path):
    """GeoPackage must hash the same twice, or ranges never work for it.

    ogr2ogr stamps `gpkg_contents.last_change` with the moment of conversion, so
    every rebuild of UNCHANGED data produced a different digest — and #1532
    builds its safety model on that digest. A per-build digest means every
    rebuild looks like a different representation, which is exactly what
    `contested` is designed to notice: under steady traffic each freshness
    rollover added a distinct sibling while the previous was retained for the
    reclamation horizon, so the selection was permanently contested and every
    range was answered with a whole 200. The DEFAULT export format could not be
    ranged at all.

    Run against the real driver, because the property being claimed is about
    what ogr2ogr writes. The unnormalized pair is asserted DIFFERENT first: with
    a fast enough machine both conversions could land in the same millisecond,
    and then the normalized comparison would prove nothing.
    """
    import shutil as _shutil
    import sqlite3
    import subprocess

    from app.processing.export.service import normalize_gpkg_timestamps

    if _shutil.which("ogr2ogr") is None:
        pytest.skip("ogr2ogr not available")

    source = tmp_path / "src.geojson"
    source.write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature",'
        '"properties":{"n":1},"geometry":{"type":"Point","coordinates":[1,2]}}]}'
    )

    def _convert(name: str) -> Path:
        out = tmp_path / name
        subprocess.run(
            ["ogr2ogr", "-f", "GPKG", str(out), str(source)],
            check=True,
            capture_output=True,
        )
        return out

    first = _convert("a.gpkg")
    time.sleep(0.05)  # `last_change` has millisecond precision
    second = _convert("b.gpkg")

    def _last_change(path: Path) -> str:
        conn = sqlite3.connect(path)
        try:
            return conn.execute("SELECT last_change FROM gpkg_contents").fetchone()[0]
        finally:
            conn.close()

    # Editing one of them to force a difference would ALSO bump SQLite's file
    # change counter, and the two would then differ forever however the
    # timestamps were normalized — the first version of this test did exactly
    # that and read its own artefact as a failure of the fix.
    if _last_change(first) == _last_change(second):
        pytest.skip("both conversions landed in the same millisecond")

    assert (
        hashlib.sha256(first.read_bytes()).digest()
        != hashlib.sha256(second.read_bytes()).digest()
    ), (
        "the two conversions were already identical, so this test would pass "
        "without the normalization it exists to check"
    )

    normalize_gpkg_timestamps(str(first))
    normalize_gpkg_timestamps(str(second))

    assert (
        hashlib.sha256(first.read_bytes()).hexdigest()
        == hashlib.sha256(second.read_bytes()).hexdigest()
    ), (
        "two GeoPackage exports of unchanged data still differ, so every rebuild "
        "registers as a new representation and the selection is permanently "
        "contested — no range is ever served for the default format"
    )


def test_normalize_survives_a_diverged_sqlite_change_counter(tmp_path):
    """fix(#1633): the counter that r12's test above cannot force by editing.

    #1633's evidence capture (#1637) caught a real merge-group flake and
    proved the two builds differed in EXACTLY two bytes, both in the SQLite
    header: offset 24-27 (the file change counter) and offset 92-95
    ("version-valid-for"), both incremented by transaction COUNT rather than
    by content. ogr2ogr's own write path committed one extra transaction on
    one build under CI load, so the counter pair diverged even though every
    row and every timestamp column already matched.

    r12's test above deliberately does NOT force a difference by editing a
    file, because a content edit ALSO bumps the counter and would make the
    pair "differ forever however the timestamps were normalized" (see its
    comment) — that was a false positive from the wrong tool, not evidence of
    the real bug. This test instead reproduces the ACTUAL mechanism directly
    against a copy of the first build: two reversible UPDATE transactions
    that leave every row exactly as they found it, but commit twice.

    fix(#1633 review, codex P2): the fix stamps a DERIVED value now, not a
    fixed constant (see `test_normalize_derives_distinct_counters_for_different_content`
    below for why), so this only checks the two header fields agree with
    each other and land on the same value for the same content — not that
    they equal any particular number.
    """
    import sqlite3
    import struct

    from app.processing.export.service import normalize_gpkg_timestamps

    _require_ogr2ogr()

    source = tmp_path / "src.geojson"
    source.write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature",'
        '"properties":{"n":1},"geometry":{"type":"Point","coordinates":[1,2]}}]}'
    )

    first = tmp_path / "a.gpkg"
    subprocess.run(
        ["ogr2ogr", "-f", "GPKG", str(first), str(source)],
        check=True,
        capture_output=True,
    )
    second = tmp_path / "b.gpkg"
    shutil.copy2(first, second)  # identical content, identical counter, to start

    def _header_pair(path: Path) -> tuple[int, int]:
        data = path.read_bytes()[:100]
        return (
            struct.unpack(">I", data[24:28])[0],
            struct.unpack(">I", data[92:96])[0],
        )

    # Two reversible transactions: set a column away from its original value
    # and commit, then set it straight back and commit. SQLite skips the
    # write entirely for an UPDATE that assigns a column's EXISTING value —
    # measured; a bare `BEGIN IMMEDIATE; COMMIT` with no write, and an UPDATE
    # to the same value, both leave the counter untouched. An actual value
    # change (even reverted immediately after) forces two real write
    # transactions, which is exactly the divergence the issue diagnosed:
    # final content identical, counter moved by transaction count alone.
    conn = sqlite3.connect(second)
    try:
        original = conn.execute("SELECT last_change FROM gpkg_contents").fetchone()[0]
        conn.execute("UPDATE gpkg_contents SET last_change = ?", ("__temp__",))
        conn.commit()
        conn.execute("UPDATE gpkg_contents SET last_change = ?", (original,))
        conn.commit()
    finally:
        conn.close()

    assert _header_pair(first) != _header_pair(second), (
        "the two reversible transactions did not move the change counter, so "
        "this test would pass without reproducing #1633's mechanism at all"
    )
    assert (
        hashlib.sha256(first.read_bytes()).hexdigest()
        != hashlib.sha256(second.read_bytes()).hexdigest()
    ), "the counter divergence above should already make the raw files differ"

    normalize_gpkg_timestamps(str(first))
    normalize_gpkg_timestamps(str(second))

    assert (
        hashlib.sha256(first.read_bytes()).hexdigest()
        == hashlib.sha256(second.read_bytes()).hexdigest()
    ), (
        "two GeoPackage builds that diverged ONLY by transaction count still "
        "differ after normalize_gpkg_timestamps — the row-level UPDATEs it runs "
        "cannot reach the SQLite header, so the change counter's own bump from "
        "those UPDATEs preserves whatever delta ogr2ogr's build left behind"
    )

    first_pair = _header_pair(first)
    second_pair = _header_pair(second)
    for path, pair in ((first, first_pair), (second, second_pair)):
        counter, valid_for = pair
        assert counter == valid_for, (
            f"{path.name}: header change-counter pair is {pair} — the change "
            f"counter and version-valid-for fields should always be stamped "
            f"together and agree, or the file misrepresents when its own "
            f"SQLITE_VERSION_NUMBER was last written"
        )
    assert first_pair == second_pair, (
        f"two builds of the SAME normalized content derived different header "
        f"counters ({first_pair} vs {second_pair}) — the derivation is meant "
        f"to be a pure function of content, so identical content must land on "
        f"the identical counter"
    )


def test_normalize_derives_distinct_counters_for_different_content(tmp_path):
    """fix(#1633 review, codex P2): the derived counter must vary with content.

    The first version of this fix stamped both header fields to a FIXED
    constant. That made #1633's determinism property hold, but it also meant
    every GeoPackage this route ever exports — for ANY dataset, at ANY time —
    shares one change-counter value. SQLite uses that pair for exactly one
    thing: letting a connection notice that a DIFFERENT connection wrote the
    file since it cached a page, so it knows to invalidate that cache. A
    client that keeps a `.gpkg` open and later has it overwritten in place
    with a materially different export would see the counter it already
    cached and skip invalidating — reading stale pages against new content.

    Deriving the counter from the normalized content instead keeps the
    determinism test above passing (same content -> same counter) while
    closing that hazard: different content must land on a different counter.
    """
    import struct

    from app.processing.export.service import normalize_gpkg_timestamps

    _require_ogr2ogr()

    def _build(tag: str, n: int) -> Path:
        source = tmp_path / f"src_{tag}.geojson"
        source.write_text(
            '{"type":"FeatureCollection","features":[{"type":"Feature",'
            f'"properties":{{"n":{n}}},'
            '"geometry":{"type":"Point","coordinates":[1,2]}}]}'
        )
        out = tmp_path / f"{tag}.gpkg"
        subprocess.run(
            ["ogr2ogr", "-f", "GPKG", str(out), str(source)],
            check=True,
            capture_output=True,
        )
        return out

    def _header_pair(path: Path) -> tuple[int, int]:
        data = path.read_bytes()[:100]
        return (
            struct.unpack(">I", data[24:28])[0],
            struct.unpack(">I", data[92:96])[0],
        )

    first = _build("a", 1)
    second = _build("b", 2)  # different attribute value -> different content

    normalize_gpkg_timestamps(str(first))
    normalize_gpkg_timestamps(str(second))

    assert (
        hashlib.sha256(first.read_bytes()).hexdigest()
        != hashlib.sha256(second.read_bytes()).hexdigest()
    ), (
        "the two builds carry different data, so this test would prove "
        "nothing if they already hashed the same after normalize"
    )

    first_pair = _header_pair(first)
    second_pair = _header_pair(second)
    assert first_pair != second_pair, (
        f"two exports of DIFFERENT content share the header change-counter "
        f"pair {first_pair} — a client watching this counter to know when "
        f"to invalidate a cached page could read stale data after the file "
        f"is overwritten in place with different content, since SQLite uses "
        f"this pair specifically to detect that a different connection wrote "
        f"the file"
    )


def test_the_streamed_header_derivation_matches_a_naive_whole_file_hash(tmp_path):
    """fix(#1633 review, codex P1): streaming must not change what gets stamped.

    `_stamp_gpkg_header_counters` reads and hashes the file in fixed-size
    chunks rather than loading it whole, because the naive version's
    `bytearray(handle.read())` followed by `hashlib.sha256(bytes(data))`
    holds up to THREE copies of a multi-GB GeoPackage in memory at once
    (`export_dataset` supports files that large), against a production API
    container with a 2 GiB cap.

    This proves the refactor is behaviour-preserving. The derived counter is
    defined as "the first 4 bytes of sha256(whole file, both counter fields
    zeroed)". Only the two 8-byte header ranges the patch writes differ
    between the pre-patch and post-patch file, so zeroing those same two
    ranges and hashing the (already patched) file the naive way must
    reproduce exactly the value that is currently stamped there — there is
    no need to reconstruct the pre-patch bytes to check this.
    """
    import struct

    from app.processing.export.service import normalize_gpkg_timestamps

    _require_ogr2ogr()

    source = tmp_path / "src.geojson"
    source.write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature",'
        '"properties":{"n":1},"geometry":{"type":"Point","coordinates":[1,2]}}]}'
    )
    out = tmp_path / "a.gpkg"
    subprocess.run(
        ["ogr2ogr", "-f", "GPKG", str(out), str(source)],
        check=True,
        capture_output=True,
    )

    normalize_gpkg_timestamps(str(out))

    stamped = struct.unpack(">I", out.read_bytes()[24:28])[0]

    naive = bytearray(out.read_bytes())
    naive[24:28] = b"\x00\x00\x00\x00"
    naive[92:96] = b"\x00\x00\x00\x00"
    naive_digest = hashlib.sha256(bytes(naive)).digest()
    naive_counter = struct.unpack(">I", naive_digest[:4])[0] or 1

    assert stamped == naive_counter, (
        f"the streamed derivation stamped {stamped}, but hashing the whole "
        f"file in one shot with both counter fields zeroed — the naive "
        f"approach this function replaced — derives {naive_counter}; the "
        f"streaming refactor must be byte-for-byte equivalent to the naive "
        f"one, only cheaper in memory"
    )


async def test_an_unchanged_rebuild_does_not_contest_the_selection(test_db_session):
    """The consequence of the above, at the level that matters.

    A rebuild of unchanged data must land on the SAME digest, so the selection
    holds one and ranges keep working across a freshness rollover. Changed data
    still contests, and still should: a slice of each spliced together is a
    corrupt file.
    """
    import tempfile

    from app.platform.storage import get_storage
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Deterministic Rebuild")
    payload = b"the same export bytes, twice"

    async def _publish() -> None:
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(payload)
            path = handle.name
        await cache.store(
            dataset.id,
            "steady",
            file_path=path,
            filename="x.gpkg",
            media_type="application/geopackage+sqlite3",
        )

    await _publish()
    # A rollover: the first artifact expires but is retained until the horizon.
    cache._ttl_seconds = lambda: 0
    try:
        await _publish()
    finally:
        cache._ttl_seconds = lambda: 600

    hit = await cache.lookup(
        dataset.id,
        "steady",
        filename="x.gpkg",
        media_type="application/geopackage+sqlite3",
    )

    keys = await get_storage().list(
        f"export-cache/{cache._tenant_segment()}/{dataset.id}/steady/"
    )
    assert len({cache.parse_artifact_key(k)[2] for k in keys}) == 1, (
        f"two rebuilds of identical bytes produced {len(keys)} distinct digests; "
        f"every rollover would add another and the selection never uncontests"
    )
    assert hit is not None and not hit.contested, (
        "an unchanged rebuild left the selection contested, so no range is "
        "served for as long as traffic continues"
    )


async def test_a_matching_if_range_resumes_even_on_a_contested_selection(
    client: AsyncClient, admin_auth_header: dict, test_db_session, conversions
):
    """A client that proved which bytes it holds gets its slice.

    `may_serve_range=False` is the fallback for a client that CANNOT say which
    representation its offsets belong to — a bare Range after a rebuild, or
    against a contested selection. A client sending this artifact's exact strong
    ETag has said precisely that, so refusing it denies a resume to the only
    clients that did the work to make one safe, over a doubt they have already
    resolved.

    The non-matching case is asserted alongside, because a rule that honoured
    every If-Range would pass the first half and reintroduce the splice.
    """
    from app.platform.storage import get_storage
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Proven Resume")
    url = _url(dataset.id)

    first = await client.get(url, headers=admin_auth_header)
    etag = first.headers["etag"]
    selection = [
        k.split(f"/{dataset.id}/", 1)[1].rsplit("/", 1)[0]
        for k in await get_storage().list(
            f"export-cache/{cache._tenant_segment()}/{dataset.id}/"
        )
    ][0]
    rival = b"a second builder's output, same window"
    # Stamped a second BEFORE the artifact the client names, deliberately: the
    # key stamp is whole seconds, and a rival minted in the same second ties
    # with it, so which one `lookup` calls newest was a tie-break. If the rival
    # won, the client's If-Range named a representation that was no longer the
    # current one and the (correct) answer was 200 — a flake that pinned the
    # wrong thing. Older by a second, the selection is contested and the named
    # artifact stays current, which is what this test is about.
    await get_storage().put(
        cache._artifact_key(
            dataset.id, selection, "c" * 64, len(rival), time.time() - 1
        ),
        rival,
    )

    proven = await client.get(
        url,
        headers={**admin_auth_header, "Range": "bytes=0-31", "If-Range": etag},
    )
    unproven = await client.get(
        url,
        headers={
            **admin_auth_header,
            "Range": "bytes=0-31",
            "If-Range": '"an-export-from-last-week"',
        },
    )

    assert proven.status_code == 206, (
        f"a client offering the exact ETag of the artifact it is reading got "
        f"{proven.status_code}; it has proved its offsets belong to these bytes"
    )
    assert unproven.status_code == 200, (
        f"a non-matching If-Range returned {unproven.status_code}; section "
        f"13.1.5 says ignore the Range, and on a contested selection that is the "
        f"only safe answer"
    )


# ---------------------------------------------------------------------------
# Review r13 — byte-determinism, enumerated per format
# ---------------------------------------------------------------------------
#
# r12 fixed GeoPackage in isolation. That was the wrong shape of fix: the
# property "two conversions of unchanged data produce identical bytes" is what
# #1532's whole safety model rests on, and it has to hold for EVERY format the
# route can emit, not for the one that happened to be reported. Shapefile was
# broken in exactly the same way and nobody had looked.
#
# So the parametrization is DERIVED from FORMAT_MAP rather than listed, and
# `test_no_export_format_escapes_the_determinism_check` fails when a format
# exists that this file does not build twice. A new format joins by existing.

_DETERMINISM_FORMATS = sorted(FORMAT_MAP) + ["parquet"]

# How far apart two builds have to be for a writer that stamps wall-clock time
# to be CAUGHT stamping it. Set by the coarsest field any of these formats
# carries: the ZIP directory's DOS timestamp, whose seconds are stored halved,
# so two builds 1.1s apart can land in the same value and hash identically with
# nothing pinned. Measured, not assumed — at 1.1s the shapefile red below
# reproduced only when the suite happened to straddle a bucket, which is a
# flake in the direction that hides the bug.
_DISTINGUISHABLE_BUILD_GAP_SECONDS = 2.2

_SAMPLE_GEOJSON = (
    '{"type":"FeatureCollection","features":['
    '{"type":"Feature","properties":{"n":1,"s":"alpha"},'
    '"geometry":{"type":"Point","coordinates":[1.5,2.5]}},'
    '{"type":"Feature","properties":{"n":2,"s":"beta"},'
    '"geometry":{"type":"Point","coordinates":[3.5,4.5]}}]}'
)


def _require_ogr2ogr():
    if shutil.which("ogr2ogr") is None:
        pytest.skip("ogr2ogr not available")


def _build_export(
    format_key: str, work_dir: Path, tag: str, evidence: dict | None = None
) -> Path:
    """Produce one export the way the route produces it, and return its path.

    Goes through the real writers — the driver named in ``FORMAT_MAP``, then
    that format's production post-step (`normalize_gpkg_timestamps` for GPKG,
    `_zip_export_files` for shapefile, none for the rest). A test that packaged
    the bytes its own way would be pinning its own mirror of the export path
    rather than the export path.

    fix(#1633): ``evidence``, when given a dict, is a side channel the
    determinism test uses to record the GPKG normalize step's before/after
    digest under ``f"{tag}_pre_normalize_sha256"`` /
    ``f"{tag}_post_normalize_sha256"``. Every other caller passes nothing and
    this behaves exactly as before.
    """
    from app.processing.export.service import _zip_export_files
    from app.processing.export.service import normalize_gpkg_timestamps

    stage = work_dir / tag
    stage.mkdir()

    if format_key == "parquet":
        # The route's parquet writer is not ogr2ogr; it is this function, which
        # is deliberately DB-free so it can be driven directly.
        from app.processing.export.parquet import _write_geoparquet

        out = stage / "export.parquet"
        _write_geoparquet(
            geom=[b"\x01\x01\x00\x00\x00", None],
            cols={"n": [1, 2], "s": ["alpha", "beta"]},
            attr_names=["n", "s"],
            geom_col="geometry",
            output_path=str(out),
        )
        return out

    source = work_dir / "source.geojson"
    if not source.exists():
        source.write_text(_SAMPLE_GEOJSON)

    fmt = FORMAT_MAP[format_key]
    ogr_output = stage / f"export{fmt['ext']}"
    subprocess.run(
        ["ogr2ogr", "-f", fmt["driver"], str(ogr_output), str(source)],
        check=True,
        capture_output=True,
    )

    if format_key == "gpkg":
        if evidence is not None:
            evidence[f"{tag}_pre_normalize_sha256"] = hashlib.sha256(
                ogr_output.read_bytes()
            ).hexdigest()
        normalize_gpkg_timestamps(str(ogr_output))
        if evidence is not None:
            evidence[f"{tag}_post_normalize_sha256"] = hashlib.sha256(
                ogr_output.read_bytes()
            ).hexdigest()
        return ogr_output
    if format_key == "shp":
        archive = stage / "export.zip"
        _zip_export_files(str(stage), str(archive))
        return archive
    return ogr_output


# ---------------------------------------------------------------------------
# fix(#1633): evidence capture for the next occurrence
# ---------------------------------------------------------------------------
#
# #1633 observed this gate fail ONCE in a merge-group run and pass 10/10 on a
# dev machine immediately after — a rare, environment- or time-dependent
# nondeterminism the issue explicitly asks to gather evidence on next time
# rather than guess at now. Everything below fires ONLY from inside the
# `if digests[0] != digests[1]` branch the test adds ahead of its (unchanged)
# assert: on the pass path this whole mechanism costs one list-equality check,
# so it does not change what the test measures or how it fails.

_DETERMINISM_EVIDENCE_DIR = (
    Path(__file__).resolve().parent.parent / "test-artifacts" / "determinism"
)


def _ogr2ogr_version() -> str:
    """Best-effort GDAL/ogr2ogr version string. Never raises."""
    try:
        result = subprocess.run(
            ["ogr2ogr", "--version"], capture_output=True, text=True, timeout=10
        )
        return (result.stdout or result.stderr).strip()
    except Exception as exc:  # noqa: BLE001 - evidence capture must never raise
        return f"<unavailable: {exc!r}>"


def _sqlite_structural_diff(
    path_a: Path, path_b: Path, max_diff_tables: int = 5
) -> dict | None:
    """Compare two SQLite files structurally, stdlib only.

    Returns None when either file is not a SQLite database this process can
    open read-only (e.g. a shapefile zip) — that is a normal "not applicable"
    outcome for a non-GPKG format, not an error worth surfacing.
    """
    import sqlite3

    try:
        conn_a = sqlite3.connect(f"file:{path_a}?mode=ro", uri=True)
        conn_b = sqlite3.connect(f"file:{path_b}?mode=ro", uri=True)
        # `connect` with mode=ro does not itself prove the file is a database;
        # a real query is needed to force that check.
        conn_a.execute("SELECT name FROM sqlite_master LIMIT 1")
        conn_b.execute("SELECT name FROM sqlite_master LIMIT 1")
    except sqlite3.Error:
        return None

    try:
        tables_a = {
            row[0]
            for row in conn_a.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        tables_b = {
            row[0]
            for row in conn_b.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        common = sorted(tables_a & tables_b)

        row_counts = {}
        differing_tables = []
        for table in common:
            # Table names come from sqlite_master, not user input.
            count_a = conn_a.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]  # noqa: S608
            count_b = conn_b.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]  # noqa: S608
            row_counts[table] = {"first": count_a, "second": count_b}
            if len(differing_tables) < max_diff_tables:
                rows_a = conn_a.execute(f'SELECT * FROM "{table}"').fetchall()  # noqa: S608
                rows_b = conn_b.execute(f'SELECT * FROM "{table}"').fetchall()  # noqa: S608
                if rows_a != rows_b:
                    differing_tables.append(
                        {
                            "table": table,
                            "first_row_count": len(rows_a),
                            "second_row_count": len(rows_b),
                            "first_sample": [list(r) for r in rows_a[:3]],
                            "second_sample": [list(r) for r in rows_b[:3]],
                        }
                    )

        pragmas = {}
        for pragma in ("page_count", "page_size", "freelist_count"):
            pragmas[pragma] = {
                "first": conn_a.execute(f"PRAGMA {pragma}").fetchone()[0],
                "second": conn_b.execute(f"PRAGMA {pragma}").fetchone()[0],
            }

        gpkg_rows = {}
        for special in ("gpkg_contents", "gpkg_metadata"):
            if special in common:
                gpkg_rows[special] = {
                    "first": [
                        list(r)
                        for r in conn_a.execute(
                            f'SELECT * FROM "{special}"'  # noqa: S608
                        ).fetchall()
                    ],
                    "second": [
                        list(r)
                        for r in conn_b.execute(
                            f'SELECT * FROM "{special}"'  # noqa: S608
                        ).fetchall()
                    ],
                }

        return {
            "tables_only_in_first": sorted(tables_a - tables_b),
            "tables_only_in_second": sorted(tables_b - tables_a),
            "row_counts": row_counts,
            "pragmas": pragmas,
            "gpkg_tables": gpkg_rows,
            "first_n_differing_tables": differing_tables,
        }
    finally:
        conn_a.close()
        conn_b.close()


def _capture_determinism_evidence(
    format_key: str,
    first: Path,
    second: Path,
    digests: list[str],
    evidence: dict,
) -> None:
    """Persist both artifacts plus a manifest when their digests diverge.

    fix(#1633): the gpkg byte-determinism gate flaked ONCE in a merge-group
    run and passed 10/10 locally right after — a rare nondeterminism the issue
    asks to gather evidence on, not guess at, on the next occurrence. This is
    called only from inside the caller's ``if digests[0] != digests[1]``
    branch, so it never runs on the pass path, and any failure inside here is
    swallowed so a capture bug can never turn a real determinism regression
    into an unrelated crash that masks the original assertion.
    """
    try:
        capture_dir = (
            _DETERMINISM_EVIDENCE_DIR
            / f"{format_key}_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        )
        capture_dir.mkdir(parents=True, exist_ok=True)

        first_copy = capture_dir / f"first_{first.name}"
        second_copy = capture_dir / f"second_{second.name}"
        shutil.copy2(first, first_copy)
        shutil.copy2(second, second_copy)

        manifest = {
            "format_key": format_key,
            "captured_at_utc": datetime.now(UTC).isoformat(),
            "gdal_version": _ogr2ogr_version(),
            "artifacts": {
                "first": {
                    "filename": first_copy.name,
                    "sha256": digests[0],
                    "size_bytes": first.stat().st_size,
                },
                "second": {
                    "filename": second_copy.name,
                    "sha256": digests[1],
                    "size_bytes": second.stat().st_size,
                },
            },
            "normalize_step": {
                "applicable": format_key == "gpkg",
                "first_pre_normalize_sha256": evidence.get(
                    "first_pre_normalize_sha256"
                ),
                "first_post_normalize_sha256": evidence.get(
                    "first_post_normalize_sha256"
                ),
                "second_pre_normalize_sha256": evidence.get(
                    "second_pre_normalize_sha256"
                ),
                "second_post_normalize_sha256": evidence.get(
                    "second_post_normalize_sha256"
                ),
            },
            "sqlite_structural_diff": _sqlite_structural_diff(first, second),
        }
        (capture_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, default=str)
        )
        print(f"determinism evidence captured: {capture_dir}")
    except Exception as exc:  # noqa: BLE001 - never let capture mask a real failure
        print(f"determinism evidence capture failed (non-fatal): {exc!r}")


@pytest.mark.parametrize("format_key", _DETERMINISM_FORMATS)
def test_every_export_format_is_byte_deterministic(format_key, tmp_path):
    """Two builds of unchanged data must hash the same, for every format.

    When they do not, the cache's `contested` rule — correctly — refuses every
    range for that selection, because a slice of each spliced together is a
    corrupt file. So a format that loses byte-determinism does not break
    visibly. It silently stops being rangeable, which for the formats GDAL
    opens over `/vsicurl/` is the entire point of #1532.

    Run against the real writers, not a stub: the claim is about what ogr2ogr
    and pyarrow put on disk, and no fake can be evidence for that.

    The gap between the two builds is set by the COARSEST clock any of these
    formats records, not by a round number — see the constant.

    fix(#1633): when the digests are about to differ, both artifacts and a
    manifest are captured to ``test-artifacts/determinism/`` before the
    assert below raises — see `_capture_determinism_evidence`. That capture
    is a no-op on the pass path and never changes this assertion.
    """
    _require_ogr2ogr()

    evidence: dict = {}
    first = _build_export(format_key, tmp_path, "first", evidence=evidence)
    time.sleep(_DISTINGUISHABLE_BUILD_GAP_SECONDS)
    second = _build_export(format_key, tmp_path, "second", evidence=evidence)

    digests = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (first, second)]
    if digests[0] != digests[1]:
        _capture_determinism_evidence(format_key, first, second, digests, evidence)
    assert digests[0] == digests[1], (
        f"two {format_key} exports of unchanged data differ ({digests[0][:12]} vs "
        f"{digests[1][:12]}); every rebuild registers as a new representation, "
        f"the selection is permanently contested, and no range is ever served "
        f"for this format"
    )


def test_the_source_files_a_shapefile_zip_wraps_really_did_move(tmp_path):
    """Counterfactual for the shapefile row above.

    The zip is deterministic because its entries are pinned, not because the
    two builds happened to be identical events. If ogr2ogr's own output files
    came out with the same mtimes anyway, the parametrized test would pass with
    the pinning removed and would be proving nothing. This asserts the input
    the pinning is there to absorb.

    Compared at the DOS bucket the ZIP directory actually stores — seconds
    halved — rather than at whole seconds. Two mtimes one second apart occupy
    the same bucket half the time, so a whole-second comparison would certify a
    gap that the format cannot see, and the determinism test it guards would go
    quietly vacuous.
    """
    _require_ogr2ogr()

    (tmp_path / "source.geojson").write_text(_SAMPLE_GEOJSON)
    _build_export("shp", tmp_path, "first")
    time.sleep(_DISTINGUISHABLE_BUILD_GAP_SECONDS)
    _build_export("shp", tmp_path, "second")

    def _dos_buckets(tag):
        stage = tmp_path / tag
        return {
            p.name: int(p.stat().st_mtime) // 2
            for p in stage.iterdir()
            if p.suffix != ".zip"
        }

    before, after = _dos_buckets("first"), _dos_buckets("second")
    assert before.keys() == after.keys(), "the two builds wrote different members"
    assert any(before[n] != after[n] for n in before), (
        f"both shapefile builds landed in the same DOS timestamp bucket "
        f"({before}), so the zip would hash the same with the date_time pin "
        f"removed and the determinism test above is vacuous"
    )


def test_the_shapefile_zip_pins_order_date_and_mode(tmp_path):
    """Name the three inputs, so a partial revert fails here and says which.

    A digest comparison alone reports "they differ" and leaves the next reader
    to rediscover why. These are the three the archive carries: member order
    (`os.listdir` returns the filesystem's, which is not stable across
    filesystems), each entry's `date_time` (the member's mtime, i.e. the moment
    of conversion), and the mode (the worker's umask).
    """
    _require_ogr2ogr()

    (tmp_path / "source.geojson").write_text(_SAMPLE_GEOJSON)
    archive = _build_export("shp", tmp_path, "only")

    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
        names = [i.filename for i in infos]
        assert names == sorted(names), (
            f"zip members are in filesystem order {names}; two servers on "
            f"different filesystems would produce different bytes for the same "
            f"export"
        )
        assert {i.date_time for i in infos} == {(1980, 1, 1, 0, 0, 0)}, (
            f"zip entries carry real timestamps "
            f"{sorted({i.date_time for i in infos})}, so every rebuild differs"
        )
        assert {i.external_attr for i in infos} == {0o100644 << 16}, (
            "zip entries carry the member's own mode, so the archive moves with "
            "the worker's umask"
        )


def test_the_dbf_date_is_normalized_inside_the_archive(tmp_path):
    """The member's own header, which pinning the archive metadata cannot reach.

    dBASE stores the date of last update in the file itself (bytes 1..3 of the
    header). ogr2ogr writes today, so a shapefile export rebuilt after midnight
    hashes differently from the one before it — the same failure as GeoPackage's
    `last_change`, at one-day granularity instead of one-millisecond, which
    means one contested window per day per selection rather than a permanent
    one. Bounded is not the same as absent.
    """
    _require_ogr2ogr()

    (tmp_path / "source.geojson").write_text(_SAMPLE_GEOJSON)
    archive = _build_export("shp", tmp_path, "only")

    with zipfile.ZipFile(archive) as zf:
        header = zf.read("export.dbf")[:4]

    assert header[1:4] == bytes((70, 1, 1)), (
        f"the dbf header carries the build date {1900 + header[1]}-{header[2]}-"
        f"{header[3]}, so this export will hash differently tomorrow"
    )


def test_a_normalized_shapefile_still_opens(tmp_path):
    """Determinism must not be bought by producing a file nothing can read.

    Every constant here is written into bytes a GDAL reader parses. Asserting
    only that two builds match would be satisfied just as well by two identical
    corrupt archives, so the round trip is the assertion that matters: extract
    what the route would have served, and open it with the driver that wrote it.
    """
    _require_ogr2ogr()

    (tmp_path / "source.geojson").write_text(_SAMPLE_GEOJSON)
    archive = _build_export("shp", tmp_path, "only")

    with zipfile.ZipFile(archive) as zf:
        assert zf.testzip() is None, "a member failed its CRC"
        extracted = tmp_path / "extracted"
        extracted.mkdir()
        zf.extractall(extracted)

    probe = subprocess.run(
        ["ogrinfo", "-al", "-so", str(extracted / "export.shp")],
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, (
        f"ogrinfo refused the normalized shapefile: {probe.stderr.strip()}"
    )
    assert "Feature Count: 2" in probe.stdout, (
        f"the normalized shapefile lost features: {probe.stdout}"
    )


def test_no_export_format_escapes_the_determinism_check():
    """A new format must not be able to join the route silently.

    Written as "every format in FORMAT_MAP is covered here" rather than as a
    list of the ones known to be broken. A predicate that enumerates the known
    failures is a blocklist: it answers "no problem" for everything it has not
    heard of, which is precisely how shapefile survived r12.
    """
    from app.processing.export.ogr import PARQUET_MEDIA_TYPE

    covered = set(_DETERMINISM_FORMATS)
    assert set(FORMAT_MAP) <= covered, (
        f"{sorted(set(FORMAT_MAP) - covered)} can be exported but is never built "
        f"twice here; if it stamps the moment of conversion, ranges are dead for "
        f"it and nothing says so"
    )
    assert PARQUET_MEDIA_TYPE and "parquet" in covered, (
        "the route emits parquet outside FORMAT_MAP, so it has to be named"
    )


# ---------------------------------------------------------------------------
# Review r14
# ---------------------------------------------------------------------------


def test_the_scratch_sweep_walks_once_per_horizon_not_once_per_cycle(tmp_path):
    """The reclaimer must not re-walk everything stored every five minutes.

    It rides the credential sweeper's 300 s loop, but what it looks for cannot
    be reclaimed until it is four hours old, and the tree it walks is the whole
    staging root: originals, COGs, quicklooks, VRTs, map assets. So the cost is
    O(everything stored), it grows with the catalog, it is paid on every replica,
    and on all but roughly one pass in fifty it finds nothing eligible.

    Asserted through the consequence rather than by counting calls. A file that
    IS eligible is planted after the first pass: if the second pass walked, it
    would take it. Surviving is the only observable difference between a skipped
    walk and a walk that found nothing, and a call-counting assertion would pass
    just as well against a version that walked and returned early.

    The counterfactual runs last, because "the file survived" is also what a
    sweeper broken in some unrelated way produces. Releasing the guard and
    sweeping again must take it, or this test is pinning a bug.
    """
    from app.core.runtime import staging

    def _plant(name: str) -> Path:
        scratch = tmp_path / "rasters" / name
        scratch.parent.mkdir(parents=True, exist_ok=True)
        scratch.write_bytes(b"half a COG")
        old = time.time() - 10 * 3600
        os.utime(scratch, (old, old))
        return scratch

    staging._last_scratch_sweep_at = 0.0
    try:
        first = _plant("a.cog.tif.0123456789abcdef0123456789abcdef.tmp")
        assert (
            staging.sweep_orphaned_write_scratch_occasionally(
                tmp_path, age_threshold_seconds=4 * 3600
            )
            == 1
        ), "the first pass of a fresh process must walk"
        assert not first.exists()

        second = _plant("b.cog.tif.fedcba9876543210fedcba9876543210.tmp")
        assert (
            staging.sweep_orphaned_write_scratch_occasionally(
                tmp_path, age_threshold_seconds=4 * 3600
            )
            == 0
        ), "a second pass inside the horizon reported work, so it walked the tree"
        assert second.exists(), (
            "the second pass reclaimed a file, so it walked the whole staging "
            "root again five minutes after the last walk"
        )

        # Counterfactual: that file really was eligible, and the guard is the
        # only reason it survived.
        staging._last_scratch_sweep_at = 0.0
        assert (
            staging.sweep_orphaned_write_scratch_occasionally(
                tmp_path, age_threshold_seconds=4 * 3600
            )
            == 1
        ), "the surviving file was never eligible, so the assertion above was vacuous"
        assert not second.exists()
    finally:
        staging._last_scratch_sweep_at = 0.0


def test_the_scratch_sweep_interval_follows_the_horizon_it_is_given(tmp_path):
    """The cadence is the horizon argument, not a constant of its own.

    Two numbers that have to agree are two numbers that can drift, and the pair
    here has a failure mode in each direction: an interval longer than the
    horizon leaves residue for longer than intended, and one shorter than it
    reintroduces exactly the repeated walk this guard exists to stop. Deriving
    the cadence from the argument removes the second number.
    """
    from app.core.runtime import staging

    staging._last_scratch_sweep_at = 0.0
    try:
        assert (
            staging.sweep_orphaned_write_scratch_occasionally(
                tmp_path, age_threshold_seconds=0
            )
            == 0
        )
        first_walk_at = staging._last_scratch_sweep_at
        assert first_walk_at > 0, "the first pass did not record a walk"

        time.sleep(0.01)
        staging.sweep_orphaned_write_scratch_occasionally(
            tmp_path, age_threshold_seconds=0
        )
        assert staging._last_scratch_sweep_at > first_walk_at, (
            "a zero horizon means nothing is ever too recent to reclaim, so "
            "every pass must walk; this one was skipped, which means the "
            "interval is pinned to something other than the horizon"
        )
    finally:
        staging._last_scratch_sweep_at = 0.0


# ---------------------------------------------------------------------------
# Review r16
# ---------------------------------------------------------------------------


async def test_an_oversize_artifact_is_refused_on_an_empty_cache(monkeypatch):
    """The budget check has to hold when there is nothing to compare against.

    The running total accumulates page by page and returns False at the first
    overrun, which is the right shape for the ordinary case and vacuous at the
    boundary: a provider yields NO page for an empty prefix, so the loop body
    never ran and the function returned True for an artifact of any size. A cold
    cache is exactly when the first export arrives, so the case is the default
    one rather than an edge, and publishing there puts a second copy of the
    largest conversion on the shared staging volume.

    Parametrised over an empty listing and a populated one, because the fix has
    to refuse the oversize artifact in both and a check written only for the
    empty case would leave the populated one depending on what else is stored.
    """
    from app.processing.export import artifact_cache as cache

    class _Listing:
        def __init__(self, pages):
            self._pages = pages

        def iter_object_pages(self, prefix, **kwargs):
            async def _pages():
                for page in self._pages:
                    yield page

            return _pages()

    oversize = cache._BUDGET_BYTES + 1

    for label, pages in (("empty", []), ("one empty page", [[]])):
        monkeypatch.setattr(cache, "get_storage", lambda p=pages: _Listing(p))
        assert not await cache._fits_in_budget(oversize), (
            f"an artifact one byte over the entire budget was accepted against "
            f"a {label} listing; the ceiling is only enforced when something "
            f"else is already stored"
        )
        assert await cache._fits_in_budget(1), (
            f"a one-byte artifact was refused against a {label} listing, so the "
            f"guard is refusing everything rather than what is oversize"
        )


async def test_an_oversize_artifact_is_refused_when_the_listing_fails(monkeypatch):
    """Failing open covers what cannot be measured, not what needs no measuring.

    An unreadable listing means the running total is unknown, and refusing to
    cache over that would trade a bounded disk cost for an unbounded conversion
    one. Whether ONE artifact exceeds the whole budget is not a fact about the
    listing, so it is decided before the fail-open and stays decided.
    """
    from app.processing.export import artifact_cache as cache

    class _Broken:
        def iter_object_pages(self, prefix, **kwargs):
            async def _pages():
                raise RuntimeError("listing unavailable")
                yield []  # pragma: no cover - generator marker

            return _pages()

    monkeypatch.setattr(cache, "get_storage", lambda: _Broken())

    assert not await cache._fits_in_budget(cache._BUDGET_BYTES + 1), (
        "an oversize artifact was accepted because the listing failed; the "
        "fail-open swallowed a question the listing was never needed to answer"
    )
    assert await cache._fits_in_budget(1), (
        "an ordinary artifact was refused on an unreadable listing, which turns "
        "a measurement failure into a caching outage"
    )


@pytest.mark.parametrize("header,expected", [("If-None-Match", 304), ("If-Match", 412)])
async def test_a_rebuild_that_transfers_nothing_is_not_audited(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    conversions,
    header,
    expected,
):
    """A 304 or a 412 records no export, whichever path produced it.

    The audit ran before the store, so a conditional request that happened to
    land on a REBUILD wrote a `dataset.export` and then answered 412 or 304,
    while the identical request landing on a cache hit wrote nothing. Whether a
    download appears in the trail then depended on the cache's internal state at
    the moment of the request, which the operator reading the report cannot see
    and did not ask to have encoded there.

    Driven through a real expiry rather than by seeding, so the request really is
    a miss that converts: without `conversions.count == 2` the assertion below
    would also pass on the hit path, which never audited these responses anyway.
    """
    from app.modules.audit.models import AuditLog
    from app.processing.export import artifact_cache as cache
    from sqlalchemy import func, select

    dataset = await _dataset(test_db_session, "Unaudited Rebuild")
    url = _url(dataset.id)

    first = await client.get(url, headers=admin_auth_header)
    etag = first.headers["etag"]
    assert conversions.count == 1

    async def _export_rows() -> int:
        return (
            await test_db_session.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "dataset.export")
                .where(AuditLog.resource_id == str(dataset.id))
            )
        ).scalar_one()

    before = await _export_rows()

    value = '"an-export-from-last-week"' if header == "If-Match" else etag
    cache._ttl_seconds = lambda: 0  # force the next request to rebuild
    try:
        resp = await client.get(url, headers={**admin_auth_header, header: value})
    finally:
        cache._ttl_seconds = lambda: 600

    assert conversions.count == 2, "precondition: the second request rebuilt"
    assert resp.status_code == expected
    assert await _export_rows() == before, (
        f"a rebuild answering {expected} wrote a dataset.export row. Nothing was "
        f"transferred, and the same request against a cache hit writes nothing, "
        f"so the trail now depends on cache state the operator cannot see"
    )


async def test_a_rebuild_that_does_transfer_is_still_audited(
    client: AsyncClient, admin_auth_header: dict, test_db_session, conversions
):
    """The counterfactual: moving the audit must not have silenced the trail.

    A guard that stopped auditing rebuilds altogether would pass every assertion
    above. This is the case that has to keep working.
    """
    from app.modules.audit.models import AuditLog
    from app.processing.export import artifact_cache as cache
    from sqlalchemy import func, select

    dataset = await _dataset(test_db_session, "Audited Rebuild")
    url = _url(dataset.id)

    await client.get(url, headers=admin_auth_header)
    assert conversions.count == 1

    async def _export_rows() -> int:
        return (
            await test_db_session.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "dataset.export")
                .where(AuditLog.resource_id == str(dataset.id))
            )
        ).scalar_one()

    before = await _export_rows()

    cache._ttl_seconds = lambda: 0
    try:
        resp = await client.get(url, headers=admin_auth_header)
    finally:
        cache._ttl_seconds = lambda: 600

    assert conversions.count == 2, "precondition: the second request rebuilt"
    assert resp.status_code == 200
    assert await _export_rows() == before + 1, (
        "a rebuild that delivered the whole export recorded nothing; the audit "
        "moved below the precondition exits and fell off the transfer path too"
    )


# ---------------------------------------------------------------------------
# Review r17
# ---------------------------------------------------------------------------


async def test_a_rebuild_answering_416_releases_its_directory_and_is_not_audited(
    client: AsyncClient, admin_auth_header: dict, test_db_session, conversions
):
    """A 416 on the REBUILD path leaves no conversion directory and no audit row.

    A matching ``If-Range`` outranks ``may_serve_range`` (review r12), and the
    export is byte-deterministic, so a client resuming with the ETag it holds
    is proven against what a rebuild just produced. If its Range then names no
    byte — ``bytes=<size>-`` is what a resumer sends for a file it already has
    whole — ``read_response`` raises the 416 as an ``HTTPException``.

    Two things went wrong on that exit before r17. The conversion directory was
    owned by a ``BackgroundTask`` that was never attached to a response, so it
    outlived the request until the orphan sweep. And the audit row had already
    been written above the call, so a request that transferred nothing was
    recorded as a download — the exact inconsistency r16 closed for 412 and
    304, still open one branch further down.

    Driven through a real expiry, and ``conversions.count == 2`` pins that the
    second request rebuilt: on the hit path there is no directory to strand and
    the audit already sits below the 416, so a version of this test that landed
    on a hit would have passed against the defect.
    """
    from app.modules.audit.models import AuditLog
    from app.processing.export import artifact_cache as cache
    from sqlalchemy import func, select

    dataset = await _dataset(test_db_session, "Rebuild 416")
    url = _url(dataset.id)

    first = await client.get(url, headers=admin_auth_header)
    assert first.status_code == 200, first.text
    etag = first.headers["etag"]
    size = int(first.headers["content-length"])
    assert conversions.count == 1

    async def _export_rows() -> int:
        return (
            await test_db_session.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "dataset.export")
                .where(AuditLog.resource_id == str(dataset.id))
            )
        ).scalar_one()

    before = await _export_rows()

    cache._ttl_seconds = lambda: 0  # force the next request to rebuild
    try:
        resp = await client.get(
            url,
            headers={
                **admin_auth_header,
                "Range": f"bytes={size}-",
                "If-Range": etag,
            },
        )
    finally:
        cache._ttl_seconds = lambda: 600

    assert conversions.count == 2, "precondition: the second request rebuilt"
    assert resp.status_code == 416, resp.text
    assert resp.headers["content-range"] == f"bytes */{size}"

    leftovers = [
        name
        for name in os.listdir(conversions.root)
        if os.path.isdir(os.path.join(conversions.root, name))
    ]
    assert leftovers == [], (
        f"the conversion directory {leftovers} outlived a 416. The response that "
        f"would have owned it was never constructed, so nothing else releases it "
        f"before the orphan sweep."
    )
    assert await _export_rows() == before, (
        "a rebuild answering 416 wrote a dataset.export row. Nothing was "
        "transferred, and the same request against a cache hit writes nothing."
    )


# ---------------------------------------------------------------------------
# Review r18
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "header,value,expected",
    [
        ("If-None-Match", "current", 304),
        ("If-Match", "stale", 412),
        (None, None, 200),
    ],
)
async def test_the_fallback_path_carries_and_evaluates_the_validator(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    conversions,
    monkeypatch,
    header,
    value,
    expected,
):
    """When publication does not happen, preconditions are still answered.

    fix(#1532 review r18): `store()` returns None on a full store, a lost race
    or an outage, and the route then streams the conversion it has in hand.
    r10 put `If-Match`/`If-None-Match` on the STORED branch only, so on this one
    an expired-but-byte-identical export with a matching `If-None-Match` was
    retransmitted whole, and a stale `If-Match` was ignored rather than
    refused. The validator is now the digest of the built file, computed once
    and handed to `store`, so it exists whether or not the artifact is kept —
    and the fallback 200 sends it, so the next conditional request has
    something to name.

    Forced onto the fallback by exhausting the budget AFTER the first build,
    and `conversions.count == 2` pins that the second request really rebuilt:
    on a hit the artifact's own ETag would answer and this test would pass
    against the defect.
    """
    from app.modules.audit.models import AuditLog
    from app.processing.export import artifact_cache as cache
    from sqlalchemy import func, select

    dataset = await _dataset(test_db_session, f"Fallback {expected}")
    url = _url(dataset.id)

    first = await client.get(url, headers=admin_auth_header)
    assert first.status_code == 200, first.text
    etag = first.headers["etag"]
    assert conversions.count == 1

    async def _export_rows() -> int:
        return (
            await test_db_session.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "dataset.export")
                .where(AuditLog.resource_id == str(dataset.id))
            )
        ).scalar_one()

    before = await _export_rows()

    headers = dict(admin_auth_header)
    if header is not None:
        headers[header] = etag if value == "current" else '"an-export-from-last-week"'

    monkeypatch.setattr(cache, "_BUDGET_BYTES", 0)  # nothing fits: store() -> None
    cache._ttl_seconds = lambda: 0  # force the next request to rebuild
    try:
        resp = await client.get(url, headers=headers)
    finally:
        cache._ttl_seconds = lambda: 600

    assert conversions.count == 2, "precondition: the second request rebuilt"
    assert resp.status_code == expected, resp.text
    if expected == 200:
        assert resp.headers.get("etag") == etag, (
            "the fallback 200 sent no validator (or a different one), so a client "
            "on this path can never revalidate or resume against the bytes it got"
        )
        assert resp.headers.get("content-encoding") != "gzip"
        assert await _export_rows() == before + 1
    else:
        assert resp.headers.get("etag") == etag
        assert await _export_rows() == before, (
            f"a fallback answering {expected} wrote a dataset.export row"
        )

    leftovers = [
        name
        for name in os.listdir(conversions.root)
        if os.path.isdir(os.path.join(conversions.root, name))
    ]
    assert leftovers == [], f"the conversion directory {leftovers} was stranded"


# ---------------------------------------------------------------------------
# Review r19
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "range_value,if_range,expected",
    [
        ("bytes=100-199", "current", 206),
        ("bytes=100-199", "other", 200),
        ("bytes=100-199", None, 200),
        ("bytes=END-", "current", 416),
    ],
)
async def test_the_fallback_honours_a_proven_if_range_with_a_local_slice(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    conversions,
    monkeypatch,
    range_value,
    if_range,
    expected,
):
    """On the fallback, a Range behind THIS file's ETag is a local 206 or a 416.

    fix(#1532 review r19): r18 gave the fallback the same validator the artifact
    path sends, and then still answered every Range with the whole file. A
    client whose `If-Range` names that ETag has proved its offsets belong to
    these bytes — the export is byte-deterministic — and got a multi-gigabyte
    200 on every resume attempt for as long as publication stayed unavailable.
    r12's rule for the stored branch applies here too: proven, slice; a bare
    Range or a mismatched `If-Range` still gets the whole thing, and a proven
    Range naming nothing is a 416 that strands no directory and audits nothing.

    Forced onto the fallback by exhausting the budget after the first build.
    """
    from app.modules.audit.models import AuditLog
    from app.processing.export import artifact_cache as cache
    from sqlalchemy import func, select

    dataset = await _dataset(test_db_session, f"Fallback Slice {expected} {if_range}")
    url = _url(dataset.id)

    first = await client.get(url, headers=admin_auth_header)
    assert first.status_code == 200, first.text
    etag = first.headers["etag"]
    size = int(first.headers["content-length"])
    assert conversions.count == 1

    async def _export_rows() -> int:
        return (
            await test_db_session.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "dataset.export")
                .where(AuditLog.resource_id == str(dataset.id))
            )
        ).scalar_one()

    before = await _export_rows()

    headers = {**admin_auth_header, "Range": range_value.replace("END", str(size))}
    if if_range == "current":
        headers["If-Range"] = etag
    elif if_range == "other":
        headers["If-Range"] = '"an-export-from-last-week"'

    monkeypatch.setattr(cache, "_BUDGET_BYTES", 0)  # nothing fits: store() -> None
    cache._ttl_seconds = lambda: 0  # force the next request to rebuild
    try:
        resp = await client.get(url, headers=headers)
    finally:
        cache._ttl_seconds = lambda: 600

    assert conversions.count == 2, "precondition: the second request rebuilt"
    assert resp.status_code == expected, resp.text
    assert resp.headers.get("etag") == etag
    if expected == 206:
        assert resp.content == conversions.body[100:200]
        assert resp.headers["content-range"] == f"bytes 100-199/{size}"
        assert resp.headers["content-length"] == "100"
        assert await _export_rows() == before + 1
    elif expected == 200:
        assert resp.content == conversions.body
        assert "content-range" not in resp.headers
        assert await _export_rows() == before + 1
    else:
        assert resp.headers["content-range"] == f"bytes */{size}"
        assert await _export_rows() == before, "a fallback 416 wrote an audit row"

    leftovers = [
        name
        for name in os.listdir(conversions.root)
        if os.path.isdir(os.path.join(conversions.root, name))
    ]
    assert leftovers == [], f"the conversion directory {leftovers} was stranded"


# ---------------------------------------------------------------------------
# Review r20
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("header,expected", [("If-None-Match", 304), ("If-Match", 200)])
async def test_a_hash_that_fails_here_and_succeeds_in_store_still_yields_the_validator(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    conversions,
    monkeypatch,
    header,
    expected,
):
    """The precondition validator is the published artifact's when there is one.

    fix(#1532 review r20): the route hashes the file itself and hands the result
    to `store`, which recomputes it if handed None. A hash that failed on the
    route and succeeded inside `store` therefore left the route's `etag` None
    while the response advertised `stored.etag`: a matching `If-Match` was
    refused with 412, and a matching `If-None-Match` transferred the export it
    named. The validator now comes from `stored` whenever publication happened.

    The first `digest_and_size` call raises and the second delegates, so this
    is exactly "failed here, recovered there"; `conversions.count == 2` pins
    that the second request rebuilt.
    """
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, f"Recovered Hash {expected}")
    url = _url(dataset.id)

    first = await client.get(url, headers=admin_auth_header)
    assert first.status_code == 200, first.text
    etag = first.headers["etag"]
    assert conversions.count == 1

    real = cache.digest_and_size
    calls = {"n": 0}

    async def _flaky(file_path):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("transient read failure")
        return await real(file_path)

    monkeypatch.setattr(cache, "digest_and_size", _flaky)
    cache._ttl_seconds = lambda: 0  # force the next request to rebuild
    try:
        resp = await client.get(url, headers={**admin_auth_header, header: etag})
    finally:
        cache._ttl_seconds = lambda: 600

    assert conversions.count == 2, "precondition: the second request rebuilt"
    assert calls["n"] == 2, (
        "precondition: the hash failed on the route and ran in store"
    )
    assert resp.status_code == expected, (
        f"{header}: {etag} against a rebuild whose published ETag is {etag} "
        f"answered {resp.status_code}; the route evaluated it against no validator"
    )
    assert resp.headers.get("etag") == etag


# ---------------------------------------------------------------------------
# Review r21
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "header,value,expected",
    [
        ("If-None-Match", "*", 304),
        ("If-None-Match", '"some-tag"', 200),
        ("If-Match", "*", 200),
        ("If-Match", '"some-tag"', 412),
    ],
)
async def test_a_cold_head_evaluates_preconditions_without_building(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    conversions,
    header,
    value,
    expected,
):
    """A cold HEAD answers conditionals the same way a warm one does — minus the tag.

    fix(#1532 review r21): the cold HEAD returned above the precondition checks
    that run on a hit and after a rebuild, so `HEAD If-None-Match: *` was 200
    when the cache was cold and 304 when it was warm, and a specific `If-Match`
    was accepted cold and refused warm. Conditional behaviour depended on cache
    state the client cannot see.

    Cold means no validator: `*` sees the representation the resource has (a
    GET would produce it), and a specific tag is unverifiable, so it is refused
    rather than guessed — the same call the shared helpers make for a COG row
    with no stored digest. And still no conversion: `conversions.count == 0`
    pins that answering the precondition did not build the export.
    """
    dataset = await _dataset(test_db_session, f"Cold HEAD {expected} {header}")

    resp = await client.head(
        _url(dataset.id), headers={**admin_auth_header, header: value}
    )

    assert conversions.count == 0, (
        "a cold HEAD ran the conversion to answer a precondition"
    )
    assert resp.status_code == expected, resp.text
    assert "etag" not in resp.headers, (
        "a cold HEAD holds no validator and must not mint one"
    )
    if expected == 200:
        assert "content-length" not in resp.headers


async def test_a_cold_get_with_if_none_match_star_answers_304_without_building(
    client: AsyncClient, admin_auth_header: dict, test_db_session, conversions
):
    """`GET If-None-Match: *` on a cold cache is a 304 that converts nothing.

    fix(#1532 review r21): the wildcard asks "does the resource have a
    representation at all", which is answerable without producing one. Before
    this the cold GET converted the whole export and then answered 304 from the
    freshly built validator — the correct status, reached by doing all the work
    the status says was unnecessary. A specific tag still proceeds to the build,
    which is the only place it can be evaluated exactly.
    """
    dataset = await _dataset(test_db_session, "Cold GET Star")

    resp = await client.get(
        _url(dataset.id), headers={**admin_auth_header, "If-None-Match": "*"}
    )

    assert resp.status_code == 304, resp.text
    assert conversions.count == 0, "the wildcard revalidation ran the conversion"
    assert "etag" not in resp.headers

    specific = await client.get(
        _url(dataset.id), headers={**admin_auth_header, "If-None-Match": '"held"'}
    )
    assert specific.status_code == 200
    assert conversions.count == 1, "a specific tag must reach the build to be evaluated"


# ---------------------------------------------------------------------------
# Review r22
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method,expected_conversions", [("HEAD", 0), ("GET", 1)])
async def test_a_stale_if_match_beats_a_wildcard_if_none_match_on_a_cold_cache(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    conversions,
    method,
    expected_conversions,
):
    """`If-Match: "stale"` + `If-None-Match: *` is a 412 cold, as it is warm.

    fix(#1532 review r22): RFC 9110 section 13.2.2 evaluates If-Match before
    If-None-Match, so a failed If-Match is authoritative. The cold wildcard
    shortcut (r21) returned 304 first, which made the answer depend on cache
    state: the hit and rebuild paths already gave 412. HEAD refuses the
    unverifiable tag without building; GET builds — the only place a specific
    tag can be evaluated exactly — and then refuses it, in order.
    """
    dataset = await _dataset(test_db_session, f"Cold Order {method}")
    headers = {
        **admin_auth_header,
        "If-Match": '"an-export-from-last-week"',
        "If-None-Match": "*",
    }
    resp = await client.request(method, _url(dataset.id), headers=headers)

    assert resp.status_code == 412, resp.text
    assert conversions.count == expected_conversions

    # The counterfactual: with If-Match satisfiable, the wildcard is a 304 for
    # both verbs, and neither converts to say so.
    fine = await client.request(
        method,
        _url(dataset.id),
        headers={**admin_auth_header, "If-Match": "*", "If-None-Match": "*"},
    )
    assert fine.status_code == 304, fine.text
    assert conversions.count == expected_conversions


@pytest.mark.parametrize(
    "stamp_age,mtime_offset,expected",
    [
        # store clock BEHIND by most of the publish allowance: the object looks
        # published long ago, but this worker minted the stamp just now — floor
        # at the stamp.
        (0, -500, "hit"),
        # store clock BEHIND by more than the allowance plus the TTL: the stamp
        # is clamped to the mtime plus the allowance (r28) and that is expired.
        # A store this far behind the fleet is a cache that does not serve.
        (0, -1300, "miss"),
        # store clock AHEAD, on an artifact that really is stale: a future
        # modified time is capped at the stamp plus the publish ceiling, and
        # that is past the TTL.
        (1500, +600, "miss"),
        # store clock AHEAD, on a fresh artifact: falls back to the stamp,
        # which is fresh.
        (0, +600, "hit"),
        # controls: honest clocks, stale; and r9's slow upload — stamp old,
        # published recently — still fresh.
        (1200, -1200, "miss"),
        (700, -10, "hit"),
    ],
)
async def test_freshness_is_bounded_by_the_workers_own_clock(
    test_db_session, stamp_age, mtime_offset, expected
):
    """`last_modified` is the store's clock; the cutoff and the stamp are ours.

    fix(#1532 review r22): freshness compared the two directly. A store clock
    behind by more than the TTL made every artifact expired the moment it
    appeared — every probe reconverted and uploaded, and the cache was silently
    dead. A store clock ahead reported a publication this worker had not
    reached and lengthened the window by the skew. Publication is now floored
    at the worker's own key stamp (it cannot precede the upload it names), and
    a modified time beyond `now` plus the jitter allowance is not trusted at
    all — the stamp answers instead.

    fix(#1532 review r23): the bound is a pure function of the object — the
    stamp as the floor, the stamp plus the publish ceiling as the cap — and
    reads no clock of its own, so the verdict cannot go expired → fresh later.

    Seeded with the key stamp and the file's mtime set INDEPENDENTLY, because
    the skew IS the difference between them; `_seed_aged_artifact` deliberately
    keeps them equal and is the wrong helper here.
    """
    from app.platform.storage import get_storage
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, f"Clock Skew {stamp_age} {mtime_offset}")
    storage = get_storage()
    selection = "skew"
    payload = b"skewed"
    digest = hashlib.sha256(payload).hexdigest()

    now = time.time()
    key = cache._artifact_key(
        dataset.id, selection, digest, len(payload), now - stamp_age
    )
    await storage.put(key, payload)
    when = now + mtime_offset
    os.utime(Path(storage.base_dir) / key, (when, when))

    resolved = await cache.lookup(
        dataset.id, selection, filename="x.geojson", media_type="application/geo+json"
    )
    if expected == "hit":
        assert resolved is not None and resolved.key == key, (
            f"stamp {stamp_age}s old, modified {mtime_offset:+}s: the artifact was "
            f"not served. A store clock behind this worker's must not expire what "
            f"this worker just published."
        )
    else:
        assert resolved is None, (
            f"stamp {stamp_age}s old, modified {mtime_offset:+}s: a stale artifact "
            f"was served on the strength of a modified time from the future"
        )


@pytest.mark.parametrize(
    "modified_offset",
    [-100_000, -1, 0, 1, 599, 600, 601, 3600, 100_000],
)
def test_publication_is_a_pure_function_of_the_object(modified_offset):
    """`_published_at` reads no clock, so an artifact can only go fresh → expired.

    fix(#1532 review r23): the r22 rule distrusted a modified time beyond
    `now` plus the jitter allowance and fell back to the stamp — correct at
    first, and then wrong: as `now` moved on, the same immutable object crossed
    back to fresh the moment its future mtime came within reach, and stale
    bytes were served well past the TTL on a schedule set by the store's skew.

    Pinned two ways: the result sits inside `[built_at, built_at + ceiling]`
    for any modified time, and the function's signature takes no `now` — a
    reintroduced clock read would need a parameter this test does not pass.
    """
    import inspect

    from app.processing.export import artifact_cache as cache

    built_at = 1_700_000_000.0
    published = cache._published_at(built_at + modified_offset, built_at)

    modified = built_at + modified_offset
    stamp = min(built_at, modified + cache._MAX_PUBLISH_SECONDS)
    assert stamp <= published <= stamp + cache._MAX_PUBLISH_SECONDS
    assert modified <= published <= modified + cache._MAX_PUBLISH_SECONDS or (
        # a store clock ahead: publication is capped at the stamp's allowance
        modified_offset > cache._MAX_PUBLISH_SECONDS
        and published == built_at + cache._MAX_PUBLISH_SECONDS
    )
    assert published == min(max(modified, stamp), stamp + 600)
    assert "now" not in inspect.signature(cache._published_at).parameters, (
        "the publication bound must not depend on the lookup's clock; that is "
        "what let a future mtime resurrect an expired artifact"
    )


# ---------------------------------------------------------------------------
# Review r24
# ---------------------------------------------------------------------------


async def test_the_sweep_does_not_let_a_future_mtime_pin_an_artifact(test_db_session):
    """Reclamation ages through the same bound freshness uses.

    fix(#1532 review r24): the sweep took `max(stamp, last_modified)` with no
    ceiling, so a store clock running ahead placed the age origin in the
    future and the object lived a full horizon past a time that had not
    happened yet — the byte inventory pinned at its ceiling and every later
    export forced onto the uncached path. `_published_at` caps publication at
    the stamp plus the publish ceiling; the sweep now reads it too, so the
    worst an ahead store can do to reclamation is the same allowance, once.

    Seeded past the horizon by the stamp, with an mtime an hour in the future:
    reclaimed. The counterfactual keeps the r10 property — a stamp past the
    horizon whose honest mtime is recent (a slow upload) is NOT reclaimed.
    """
    from app.platform.storage import get_storage
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Sweep Future Mtime")
    storage = get_storage()
    now = time.time()
    horizon = cache._SWEEP_AGE_SECONDS

    async def _seed(selection: str, stamp_age: float, mtime_offset: float) -> str:
        payload = selection.encode()
        key = cache._artifact_key(
            dataset.id,
            selection,
            hashlib.sha256(payload).hexdigest(),
            len(payload),
            now - stamp_age,
        )
        await storage.put(key, payload)
        when = now + mtime_offset
        os.utime(Path(storage.base_dir) / key, (when, when))
        return key

    pinned = await _seed("future-mtime", stamp_age=horizon + 3600, mtime_offset=+3600)
    slow = await _seed("slow-upload", stamp_age=horizon + 60, mtime_offset=-30)

    await cache.sweep()

    assert not await storage.exists(pinned), (
        "an artifact past the horizon by its stamp survived the sweep because "
        "its mtime lay an hour in the future; a store clock ahead of the worker "
        "must not be able to pin objects past the horizon"
    )
    assert await storage.exists(slow), (
        "the r10 property regressed: a slow upload whose bytes landed recently "
        "was reclaimed on the strength of a stamp taken before the push"
    )


# ---------------------------------------------------------------------------
# Review r25
# ---------------------------------------------------------------------------


async def test_the_artifact_is_stamped_with_the_snapshot_not_the_upload(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    conversions,
    monkeypatch,
):
    """The key's stamp is taken BEFORE the conversion reads the data.

    fix(#1532 review r25): it was minted just before the upload, after the
    conversion had finished. A mutation that misses `tile_cache_version` and
    lands during a long conversion makes an artifact stale at birth, and a
    stamp taken after the build let it age from after the staleness began —
    served for the rest of the build plus the upload plus the TTL. Stamped from
    the snapshot, `_published_at`'s ceiling bounds build plus upload, and the
    data behind a served artifact is never older than TTL plus that ceiling.

    The conversion is made to take two seconds so a stamp taken after it would
    be trivially distinguishable from one taken before.

    fix(#1859): compares `built_at` against a timestamp the double itself
    records when the conversion STARTS, not against `before + 1.0`. That fixed
    margin assumed request overhead ahead of the conversion (auth, the dataset
    fetch, the precondition checks) stays under a second, which is exactly a
    wall-clock threshold racing a loaded CI runner — the margin, not the
    property being tested, is what could fail. Watching the double's own start
    time proves the same thing (the stamp precedes the conversion) without
    guessing how long unrelated request overhead takes anywhere it runs.
    """
    import asyncio

    from app.processing.export import artifact_cache as cache
    from app.processing.export import router as export_router

    dataset = await _dataset(test_db_session, "Snapshot Stamp")
    real_conversion = export_router.export_dataset
    conversion_started_at: float | None = None

    async def _slow(*args, **kwargs):
        nonlocal conversion_started_at
        conversion_started_at = time.time()
        await asyncio.sleep(2.0)
        return await real_conversion(*args, **kwargs)

    monkeypatch.setattr(export_router, "export_dataset", _slow)

    resp = await client.get(_url(dataset.id), headers=admin_auth_header)
    assert resp.status_code == 200, resp.text
    assert conversions.count == 1
    assert conversion_started_at is not None

    selection = cache.selection_key(
        dataset_id=dataset.id,
        table_name=dataset.table_name,
        dataset_title=dataset.record.title,
        tile_cache_version=dataset.tile_cache_version,
        format_key="geojson",
        target_crs=None,
        bbox=None,
        where=None,
    )
    artifact = await cache.lookup(
        dataset.id, selection, filename="x.geojson", media_type="application/geo+json"
    )
    assert artifact is not None
    assert artifact.built_at <= conversion_started_at, (
        f"the artifact is stamped {artifact.built_at - conversion_started_at:.2f}s "
        f"after the 2s conversion began; the stamp must precede the read so the "
        f"ceiling bounds the data's age, not just the upload's"
    )


@pytest.mark.parametrize("snapshot_age,expected", [(30, "hit"), (700, "miss")])
async def test_an_artifact_whose_snapshot_is_older_than_the_ceiling_is_not_served(
    test_db_session, monkeypatch, snapshot_age, expected
):
    """Build plus upload past the ceiling yields an artifact no request uses.

    fix(#1532 review r25): with the stamp on the snapshot, `_published_at`
    places publication no later than the stamp plus `_MAX_PUBLISH_SECONDS`, so
    an artifact whose data is older than TTL plus that ceiling at publication is
    expired the moment it exists. That is the promise, stated in the module
    docstring; a conversion that outlives the edge's request budget has lost
    its client anyway.
    """
    import tempfile

    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, f"Old Snapshot {snapshot_age}")
    monkeypatch.setattr(cache, "_ttl_seconds", lambda: 60)

    with tempfile.NamedTemporaryFile(delete=False) as handle:
        handle.write(b"snapshot-aged export")
        path = handle.name

    stored = await cache.store(
        dataset.id,
        "aged",
        file_path=path,
        filename="x.geojson",
        media_type="application/geo+json",
        snapshot_at=time.time() - snapshot_age,
    )
    assert stored is not None, "publication itself is unconditional"

    resolved = await cache.lookup(
        dataset.id, "aged", filename="x.geojson", media_type="application/geo+json"
    )
    if expected == "hit":
        assert resolved is not None and resolved.key == stored.key
    else:
        assert resolved is None, (
            "an artifact whose snapshot is older than the ceiling plus the TTL was "
            "served; the data behind it can be arbitrarily stale"
        )


# ---------------------------------------------------------------------------
# Review r28
# ---------------------------------------------------------------------------


async def test_a_far_future_stamp_cannot_pin_an_artifact_past_reclamation(
    test_db_session,
):
    """A writer clock a month ahead does not keep its object for a month.

    fix(#1532 review r28): `lookup` refused a future-stamped key, but the sweep
    floored publication at that future stamp, so the object could not be
    reclaimed until then plus the horizon — its size counting against the
    budget and its digest keeping the selection contested the whole time.
    `_published_at` now clamps the stamp to the store's modified time plus the
    publish allowance, symmetrically with the ceiling it already applied the
    other way, so a stamp far ahead of the bytes ages from when the bytes
    actually appeared plus that allowance.

    The counterfactual keeps the r22 store-behind property: a stamp inside the
    allowance ahead of a recent mtime is not reclaimed.
    """
    from app.platform.storage import get_storage
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Future Stamp Sweep")
    storage = get_storage()
    now = time.time()
    horizon = cache._SWEEP_AGE_SECONDS

    async def _seed(selection: str, stamp_offset: float, mtime_offset: float) -> str:
        payload = selection.encode()
        key = cache._artifact_key(
            dataset.id,
            selection,
            hashlib.sha256(payload).hexdigest(),
            len(payload),
            now + stamp_offset,
        )
        await storage.put(key, payload)
        when = now + mtime_offset
        os.utime(Path(storage.base_dir) / key, (when, when))
        return key

    # Stamped a month in the future; the bytes appeared past the horizon by
    # more than the publish allowance, which is where the clamped stamp lands.
    pinned = await _seed(
        "future-stamp", stamp_offset=+30 * 86400, mtime_offset=-(horizon + 700)
    )
    # Stamped inside the allowance ahead of bytes that appeared just now: kept.
    recent = await _seed("store-behind", stamp_offset=+120, mtime_offset=-30)

    await cache.sweep()

    assert not await storage.exists(pinned), (
        "an object stamped a month ahead survived the sweep although its bytes "
        "appeared past the horizon; a writer clock must not be able to pin an "
        "artifact, its budget share and its selection's contested state"
    )
    assert await storage.exists(recent), (
        "the store-behind property regressed: a stamp within the allowance of a "
        "recent mtime was reclaimed"
    )


# ---------------------------------------------------------------------------
# Review r29
# ---------------------------------------------------------------------------


async def test_a_builder_that_loses_the_race_serves_the_incumbent(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    conversions,
    monkeypatch,
):
    """Two overlapping builders with DIFFERENT bytes: both clients get the same ones.

    fix(#1532 review r29, P1): when a builder found a fresh incumbent at
    publish time, `store` returned None and the route streamed the builder's
    OWN conversion whole. If the two conversions had taken different snapshots
    (a mutation that missed `tile_cache_version` landing between them), that
    client held bytes no later request would resolve — an interrupted download
    resumed with a bare Range against the sole, uncontested incumbent and was
    handed a 206 of the other conversion at its offsets. `store` now returns
    the incumbent and the route serves it.

    The lost race is FORCED, not hoped for: both requests are held after
    hashing until both have converted (so both really missed), and `store` is
    then serialized behind a lock, so exactly one publishes and the other finds
    it as the incumbent at its re-check. Without the lock the two re-checks can
    both miss and both publish — the two-publisher case, which is contested and
    already safe — and this test would prove nothing about the lost race. The
    double's body is changed between the two conversions, so the two builds
    really differ. Both responses must then carry the SAME bytes and the same
    ETag, and a bare Range afterwards must be a slice of those same bytes.
    """
    import asyncio

    from app.processing.export import artifact_cache as cache
    from app.processing.export import router as export_router

    dataset = await _dataset(test_db_session, "Lost Race")
    url = _url(dataset.id)

    first_body = conversions.body
    second_body = bytes(reversed(first_body))
    assert first_body != second_body

    real_conversion = export_router.export_dataset
    builds = {"n": 0}

    async def _mutating(*args, **kwargs):
        builds["n"] += 1
        if builds["n"] == 2:
            conversions.body = second_body  # the data moved between the two reads
        return await real_conversion(*args, **kwargs)

    monkeypatch.setattr(export_router, "export_dataset", _mutating)

    arrived = asyncio.Event()
    waiting = {"n": 0}
    real_digest = cache.digest_and_size

    async def _barriered(file_path):
        result = await real_digest(file_path)
        waiting["n"] += 1
        if waiting["n"] == 2:
            arrived.set()
        await asyncio.wait_for(arrived.wait(), timeout=5)
        return result

    monkeypatch.setattr(cache, "digest_and_size", _barriered)

    real_store = cache.store
    publish_lock = asyncio.Lock()

    async def _serialized_store(*args, **kwargs):
        async with publish_lock:
            return await real_store(*args, **kwargs)

    monkeypatch.setattr(cache, "store", _serialized_store)

    one, two = await asyncio.gather(
        client.get(url, headers=admin_auth_header),
        client.get(url, headers=admin_auth_header),
    )
    assert waiting["n"] == 2, "the two builders did not overlap"
    assert conversions.count == 2
    assert one.status_code == 200 and two.status_code == 200
    assert one.headers["etag"] == two.headers["etag"], (
        "the two overlapping builders answered with different validators; the "
        "loser served its own bytes and its client is now off the incumbent"
    )
    assert one.content == two.content, (
        "the two overlapping builders answered with different bytes; a client "
        "resuming the loser's download with a bare Range will splice"
    )
    served = one.content
    assert served in (first_body, second_body)

    # And the resume a real client would make: a bare Range against the
    # incumbent is a slice of exactly what both clients were given.
    monkeypatch.setattr(cache, "digest_and_size", real_digest)
    resumed = await client.get(
        url, headers={**admin_auth_header, "Range": "bytes=100-199"}
    )
    assert resumed.status_code == 206, resumed.text
    assert resumed.content == served[100:200]
    assert resumed.headers["etag"] == one.headers["etag"]


# ---------------------------------------------------------------------------
# Release smoke follow-up: the cold GDAL open
# ---------------------------------------------------------------------------


async def test_a_cold_open_gets_its_leading_slice_from_the_fresh_build(
    client: AsyncClient, admin_auth_header: dict, test_db_session, conversions
):
    """A bare Range from byte 0 on a cold cache is a 206, and the open proceeds.

    fix(#1532) follow-up, found by the release smoke: GDAL 3.10's ``/vsicurl/``
    open does not begin with a HEAD. Its first request is ``Range:
    bytes=0-16383``, and the fresh-build path answered it with 200 and the whole
    file — which GDAL reports as "Range downloading not supported by this
    server!" and aborts. A cold cache could not be opened; only the second
    attempt worked, because by then the artifact existed.

    A Range that starts at byte 0 is a probe or a restart, never a resume — a
    resumer holds a prefix and asks from its length — so nothing appended after
    it can come from a different representation: every later request finds the
    artifact this one published. The build still costs one conversion, and the
    follow-up ranges are slices of that same artifact under the same ETag.
    """
    dataset = await _dataset(test_db_session, "Cold GDAL Open")
    url = _url(dataset.id)

    first = await client.get(url, headers={**admin_auth_header, "Range": "bytes=0-99"})
    assert conversions.count == 1
    assert first.status_code == 206, (
        f"the leading range of a cold open answered {first.status_code}; GDAL "
        f"reads a 200 to a ranged GET as 'Range downloading not supported' and "
        f"aborts the open"
    )
    assert first.content == conversions.body[:100]
    assert first.headers["content-range"] == f"bytes 0-99/{len(conversions.body)}"
    etag = first.headers["etag"]

    later = await client.get(
        url, headers={**admin_auth_header, "Range": "bytes=100-199"}
    )
    assert later.status_code == 206
    assert later.headers["etag"] == etag
    assert later.content == conversions.body[100:200]
    assert conversions.count == 1, "the follow-up range converted again"


async def test_a_bare_range_not_from_zero_on_a_fresh_build_stays_whole(
    client: AsyncClient, admin_auth_header: dict, test_db_session, conversions
):
    """The counterfactual to the leading-slice exception: an offset a resumer
    would ask for, on a representation this request built, is still answered
    whole. This is what `test_a_mutation_between_two_ranges_is_answered_with_the_whole_new_file`
    rests on; stated here on its own so the exception cannot quietly widen.
    """
    dataset = await _dataset(test_db_session, "Cold Resume Offset")

    resp = await client.get(
        _url(dataset.id), headers={**admin_auth_header, "Range": "bytes=100-199"}
    )
    assert conversions.count == 1
    assert resp.status_code == 200, resp.text
    assert resp.content == conversions.body
    assert "content-range" not in resp.headers


async def test_a_leading_range_after_a_change_is_whole_when_old_bytes_are_still_live(
    client: AsyncClient, admin_auth_header: dict, test_db_session, conversions
):
    """The counter-case from #1585 review: re-reading byte 0 after a change.

    A random-access client reads a later block, the data changes (and moves
    `tile_cache_version`, so the artifact is cold under a NEW version segment of
    the same URL), and the client re-reads the header with `bytes=0-...` while
    still holding the old block. Byte 0 alone does not prove a fresh read, so
    the leading-slice exception must not fire: the earlier artifact of this URL
    is still live with different bytes, and the answer is the whole new file.

    And the case that must keep working: the same URL rebuilt to IDENTICAL bytes
    (a re-open after expiry) still gets its leading 206, because equal bytes
    cannot splice whatever the client holds.
    """
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Reread Zero")
    url = _url(dataset.id)

    later_block = await client.get(
        url, headers={**admin_auth_header, "Range": "bytes=100-199"}
    )
    assert later_block.status_code == 200  # cold, not from zero: whole (and built)
    assert conversions.count == 1

    # The data changes and the version moves: the next request is cold under a
    # new version segment, while the old artifact stays live under this URL.
    conversions.body = bytes(reversed(conversions.body))
    dataset.bump_tile_cache_version()
    test_db_session.add(dataset)
    await test_db_session.commit()

    reread = await client.get(url, headers={**admin_auth_header, "Range": "bytes=0-99"})
    assert conversions.count == 2
    assert reread.status_code == 200, (
        f"a leading Range after a change answered {reread.status_code}; the old "
        f"artifact of this URL is still live with different bytes, so a client "
        f"holding a block of it would splice"
    )
    assert reread.content == conversions.body
    assert "content-range" not in reread.headers

    # Identical rebuild after expiry: still a leading 206.
    same = await _dataset(test_db_session, "Reopen After Expiry")
    same_url = _url(same.id)
    first = await client.get(
        same_url, headers={**admin_auth_header, "Range": "bytes=0-99"}
    )
    assert first.status_code == 206
    cache._ttl_seconds = lambda: 0
    try:
        again = await client.get(
            same_url, headers={**admin_auth_header, "Range": "bytes=0-99"}
        )
    finally:
        cache._ttl_seconds = lambda: 600
    assert again.status_code == 206, (
        f"a re-open after expiry with unchanged bytes answered {again.status_code}; "
        f"GDAL re-opens more than a TTL apart are the common case"
    )
    assert again.headers["etag"] == first.headers["etag"]


async def test_a_hit_inside_the_first_ttl_after_a_change_answers_bare_ranges_whole(
    client: AsyncClient, admin_auth_header: dict, test_db_session, conversions
):
    """#1585 review r3: the hit path honours the URL's history too, for one TTL.

    Client A reads the leading block (a fresh build, 206). The data changes and
    the version moves. Client B fetches the export, building the new version's
    artifact. Client A comes back for its next block: that is a HIT on the new
    artifact, uncontested within the new version — and a 206 there would append
    new bytes to A's old leading block. Inside the first TTL after the change
    the answer is whole. Once the new bytes are settled — a same-digest sibling
    older than a TTL is live under the new version — ranges resume, and the
    history listing is not consulted at all.
    """
    from app.platform.storage import get_storage
    from app.processing.export import artifact_cache as cache

    dataset = await _dataset(test_db_session, "Hit After Change")
    url = _url(dataset.id)

    leading = await client.get(
        url, headers={**admin_auth_header, "Range": "bytes=0-99"}
    )
    assert leading.status_code == 206 and conversions.count == 1

    conversions.body = bytes(reversed(conversions.body))
    dataset.bump_tile_cache_version()
    test_db_session.add(dataset)
    await test_db_session.commit()

    other_client = await client.get(url, headers=admin_auth_header)  # builds v2
    assert other_client.status_code == 200 and conversions.count == 2
    v2_etag = other_client.headers["etag"]

    resumed = await client.get(
        url, headers={**admin_auth_header, "Range": "bytes=100-199"}
    )
    assert conversions.count == 2, (
        "the resume must be a hit, or the test proves nothing"
    )
    assert resumed.status_code == 200, (
        f"a bare Range hit inside the first TTL after a change answered "
        f"{resumed.status_code}; the client's leading block came from the "
        f"previous representation, which is still live under this URL"
    )
    assert resumed.headers["etag"] == v2_etag
    assert "content-range" not in resumed.headers

    # Let the change age out. The URL's last possible answer with the OLD
    # bytes is a v1 publication plus a TTL, and the client that took it gets a
    # TTL to come back — so a v1 publication 700 s old (TTL 600: served until
    # 100 s ago) still holds bare ranges whole, and one 1300 s old releases
    # them (#1585 review r5). Re-keyed each time, since the stamp in the name
    # floors publication.
    storage = get_storage()
    prefix = f"export-cache/{cache._tenant_segment()}/{dataset.id}/"
    v1_keys = [
        k
        for k in await storage.list(prefix)
        if cache.parse_artifact_key(k)
        and cache.parse_artifact_key(k)[2] != v2_etag.strip('"')
    ]
    assert v1_keys, "the previous representation must still be live for this test"

    async def _age_v1_to(seconds_ago: float) -> None:
        nonlocal v1_keys
        moved = []
        for k in v1_keys:
            parsed = cache.parse_artifact_key(k)
            selection_v1 = k.split(f"/{dataset.id}/", 1)[1].rsplit("/", 1)[0]
            payload = await storage.get(k)
            aged = cache._artifact_key(
                dataset.id,
                selection_v1,
                parsed[2],
                parsed[1],
                time.time() - seconds_ago,
            )
            await storage.put(aged, payload)
            when = time.time() - seconds_ago
            os.utime(Path(storage.base_dir) / aged, (when, when))
            await storage.delete(k)
            moved.append(aged)
        v1_keys = moved

    await _age_v1_to(700)
    still = await client.get(
        url, headers={**admin_auth_header, "Range": "bytes=100-199"}
    )
    assert still.status_code == 200, (
        f"the previous bytes were servable until 100 s ago and a client that took "
        f"them may not be back yet; a bare Range hit answered {still.status_code}"
    )

    await _age_v1_to(1300)
    settled = await client.get(
        url, headers={**admin_auth_header, "Range": "bytes=100-199"}
    )
    assert conversions.count == 2
    assert settled.status_code == 206, (
        f"two TTLs after the URL last published other bytes, a bare Range hit "
        f"answered {settled.status_code}; GDAL opens after a settled change must work"
    )
    assert settled.headers["etag"] == v2_etag
