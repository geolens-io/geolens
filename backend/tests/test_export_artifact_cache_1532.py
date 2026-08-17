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
import uuid

import pytest
from httpx import AsyncClient

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
