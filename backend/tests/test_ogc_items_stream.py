"""An OGC items page is streamed in byte-bounded batches from one snapshot and holds `limit` features."""

import json
import tracemalloc
import zlib
from urllib.parse import parse_qs, urlparse

import anyio
import pytest
import structlog
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

import app.core.db as db_module
import app.standards.ogc.router as ogc_router
from app.modules.catalog.features.service import read_features_json as features_read
from tests.factories import get_user_id
from tests.test_ogc_features import _cleanup_table, _create_test_table_and_dataset

pytestmark = pytest.mark.anyio

# A 400-segment ring around each point, so a page of them is tens of megabytes.
_POLYGONS = (
    "INSERT INTO {table} (geom_4326, name) "
    "SELECT ST_Buffer(ST_SetSRID(ST_MakePoint(-74 + (i % 100) * 0.01, "
    "41 + (i / 100) * 0.01), 4326), 0.004, 100), 'polygon ' || i "
    "FROM generate_series(1, :count) i"
)
# About 1.2 MB of GeoJSON each: a 110,000-vertex ring.
_LARGE_POLYGONS = (
    "INSERT INTO {table} (geom_4326, name) "
    "SELECT ST_Buffer(ST_SetSRID(ST_MakePoint(-74 + i * 0.1, 41), 4326), "
    "0.04, 27500), 'large ' || i FROM generate_series(1, 24) i"
)
# The stream's own query, and no other statement the request runs.
_STREAM_QUERY = "%gid = ANY(%"


async def _polygon_dataset(session, count: int):
    admin_id = await get_user_id(session, "admin")
    dataset = await _create_test_table_and_dataset(
        session, created_by=admin_id, geometry_type="POLYGON"
    )
    await session.execute(
        text(_POLYGONS.format(table=f"data.{dataset.table_name}")),
        {"count": count},
    )
    dataset.feature_count = count
    await session.commit()
    return dataset


@pytest.fixture
async def detailed_polygons(test_db_session):
    dataset = await _polygon_dataset(test_db_session, 6000)
    table_name = dataset.table_name
    yield dataset
    await _cleanup_table(test_db_session, table_name)


@pytest.fixture
async def some_polygons(test_db_session):
    dataset = await _polygon_dataset(test_db_session, 1000)
    table_name = dataset.table_name
    yield dataset
    await _cleanup_table(test_db_session, table_name)


def _next(data: dict) -> str | None:
    for link in data["links"]:
        if link["rel"] == "next":
            return link["href"]
    return None


async def test_a_page_of_large_geometries_holds_limit_features(
    client: AsyncClient, detailed_polygons
) -> None:
    resp = await client.get(
        f"/collections/{detailed_polygons.id}/items",
        params={"limit": 5000},
        headers={"Accept-Encoding": "gzip"},
    )

    assert resp.status_code == 200
    assert resp.headers["content-encoding"] == "gzip"
    assert len(resp.content) > 32_000_000
    data = resp.json()
    ids = [feature["id"] for feature in data["features"]]
    assert len(ids) == 5000
    assert ids == sorted(ids)
    assert data["numberReturned"] == 5000
    assert data["numberMatched"] == 6000
    assert parse_qs(urlparse(_next(data)).query)["after_gid"] == [str(ids[-1])]
    assert resp.headers["content-type"] == "application/geo+json"
    assert f"after_gid={ids[-1]}" in resp.headers["link"]

    rest = await client.get(_next(data).replace("http://test/api", ""))
    remaining = rest.json()
    assert remaining["numberReturned"] == len(remaining["features"]) == 1000
    assert _next(remaining) is None


def _record_batches(monkeypatch) -> list[list[int]]:
    batches: list[list[int]] = []
    real_read = ogc_router.read_features_json

    async def recording_read(db, table_name, gids, **kwargs):
        batches.append(list(gids))
        return await real_read(db, table_name, gids, **kwargs)

    monkeypatch.setattr(ogc_router, "read_features_json", recording_read)
    return batches


async def test_large_geometries_are_read_a_bounded_batch_at_a_time(
    client: AsyncClient, test_db_session, monkeypatch
) -> None:
    dataset = await _polygon_dataset(test_db_session, 0)
    table_name = dataset.table_name
    await test_db_session.execute(
        text(_LARGE_POLYGONS.format(table=f"data.{table_name}"))
    )
    dataset.feature_count = 24
    await test_db_session.commit()
    monkeypatch.setattr(ogc_router, "STREAM_BATCH_BYTES", 3_000_000)
    batches = _record_batches(monkeypatch)
    received = features = 0

    async def on_body(chunks: int, body: bytes) -> bool:
        nonlocal received, features
        received += len(body)
        features += body.count(b'"type":"Feature"')
        return False

    try:
        tracemalloc.start()
        await _run_asgi(
            f"/collections/{dataset.id}/items", "limit=100", on_body=on_body, keep=False
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        await _cleanup_table(test_db_session, table_name)

    assert features == 24
    assert received > 24_000_000
    assert batches == [[gid] for gid in range(1, 25)]
    # Memory follows the largest batch, not the page; one batch would hold the
    # page several times over.
    assert peak < received / 2


@pytest.mark.parametrize(
    "variant", ["spatial", "without geometry", "nonspatial"], ids=lambda v: v
)
async def test_large_attributes_count_toward_a_batch(
    client: AsyncClient, test_db_session, monkeypatch, variant
) -> None:
    dataset = await _polygon_dataset(test_db_session, 40)
    table_name = dataset.table_name
    # 200 KB a row, which compresses in storage.
    await test_db_session.execute(
        text(f"UPDATE data.{table_name} SET status = repeat(md5(gid::text), 6250)")
    )
    if variant == "nonspatial":
        dataset.geometry_type = None
    await test_db_session.commit()
    monkeypatch.setattr(ogc_router, "STREAM_BATCH_BYTES", 1_000_000)
    batches = _record_batches(monkeypatch)
    params = {"limit": 100}
    if variant == "without geometry":
        params["include_geometry"] = "false"

    try:
        resp = await client.get(f"/collections/{dataset.id}/items", params=params)
        data = resp.json()
    finally:
        await _cleanup_table(test_db_session, table_name)

    assert data["numberReturned"] == 40
    assert len(data["features"][0]["properties"]["status"]) == 200_000
    assert len(batches) >= 20
    assert max(len(batch) for batch in batches) <= 2


@pytest.mark.parametrize(
    ("column_type", "value"),
    [
        ("numeric", "'1e-16000'::numeric"),
        ("numeric[]", "ARRAY['1e-16000'::numeric]"),
        ("jsonb", "jsonb_build_object('v', '1e-16000'::numeric)"),
    ],
    ids=["numeric", "numeric array", "jsonb"],
)
async def test_numbers_are_sized_by_their_text(
    client: AsyncClient, test_db_session, monkeypatch, column_type, value
) -> None:
    dataset = await _polygon_dataset(test_db_session, 40)
    table_name = dataset.table_name
    # Stored in a few bytes, written as 16,000 digits.
    await test_db_session.execute(
        text(f"ALTER TABLE data.{table_name} ADD COLUMN amount {column_type}")
    )
    await test_db_session.execute(
        text(f"UPDATE data.{table_name} SET amount = {value}")
    )
    dataset.geometry_type = None
    await test_db_session.commit()
    monkeypatch.setattr(ogc_router, "STREAM_BATCH_BYTES", 100_000)
    batches = _record_batches(monkeypatch)

    try:
        resp = await client.get(
            f"/collections/{dataset.id}/items", params={"limit": 100}
        )
        body = resp.content
    finally:
        await _cleanup_table(test_db_session, table_name)

    assert body.count(b"0" * 15_000) == 40
    assert len(batches) >= 10
    assert max(len(batch) for batch in batches) <= 3


async def _open_streams(session) -> int:
    """Backends still inside a transaction on the stream's query."""
    await session.execute(text("SELECT pg_stat_clear_snapshot()"))
    result = await session.execute(
        text(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
            "AND pid <> pg_backend_pid() AND state <> 'idle' AND query LIKE :q"
        ),
        {"q": _STREAM_QUERY},
    )
    return result.scalar_one()


def _scope(path: str, query: str, headers: list | None = None) -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": query.encode(),
        "headers": [(b"host", b"test"), *(headers or [])],
        "client": ("127.0.0.1", 50000),
        "server": ("test", 80),
    }


async def _run_asgi(
    path: str,
    query: str,
    *,
    on_body,
    send_delay: float = 0,
    headers: list | None = None,
    keep: bool = True,
):
    """Call the app directly, as a server would; returns the messages it sent."""
    from app.api.main import app

    sent: list[dict] = []
    disconnect = anyio.Event()
    requested = False

    async def receive():
        nonlocal requested
        if not requested:
            requested = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    chunks = 0

    async def send(message):
        nonlocal chunks
        body = message.get("body", b"")
        if keep or message["type"] != "http.response.body":
            sent.append(message)
        if message["type"] == "http.response.body" and body:
            chunks += 1
            if await on_body(chunks, body):
                disconnect.set()
            await anyio.sleep(send_delay)

    await app(_scope(path, query, headers), receive, send)
    disconnect.set()
    return sent


def _body(sent: list[dict]) -> bytes:
    return b"".join(m.get("body", b"") for m in sent[1:])


def _assert_uncacheable(sent: list[dict]) -> None:
    headers = dict(sent[0]["headers"])
    assert b"etag" not in headers
    assert headers[b"cache-control"] == b"no-store"


_GZIP = [(b"accept-encoding", b"gzip")]


def _unterminated_gzip(body: bytes) -> bool:
    inflate = zlib.decompressobj(wbits=31)
    return len(inflate.decompress(body)) > 0 and not inflate.eof


async def test_a_client_disconnect_releases_the_connection(
    client: AsyncClient, test_db_session, some_polygons, monkeypatch
) -> None:
    during = []
    streams = []
    real_body = ogc_router.feature_collection_body

    def recording_body(*args, **kwargs):
        streams.append(real_body(*args, **kwargs))
        return streams[-1]

    monkeypatch.setattr(ogc_router, "feature_collection_body", recording_body)

    async def on_body(chunks: int, body: bytes) -> bool:
        if chunks == 2:
            during.append(await _open_streams(test_db_session))
            return True
        return False

    sent = await _run_asgi(
        f"/collections/{some_polygons.id}/items", "limit=1000", on_body=on_body
    )

    assert sent[0]["status"] == 200
    assert during == [1]
    assert len(_body(sent)) < 1_000_000
    # Closed by the response itself, not left for the garbage collector.
    assert [stream.ag_frame for stream in streams] == [None]
    assert await _open_streams(test_db_session) == 0
    again = await client.get(
        f"/collections/{some_polygons.id}/items", params={"limit": 2}
    )
    assert again.json()["numberReturned"] == 2


@pytest.mark.parametrize("gzip", [False, True], ids=["identity", "gzip"])
async def test_the_stream_ends_at_the_request_deadline(
    client: AsyncClient, test_db_session, some_polygons, monkeypatch, gzip
) -> None:
    monkeypatch.setattr(ogc_router, "current_deadline_ms", lambda: 300)

    async def on_body(chunks: int, body: bytes) -> bool:
        return False

    with structlog.testing.capture_logs() as logs:
        sent = await _run_asgi(
            f"/collections/{some_polygons.id}/items",
            "limit=1000",
            on_body=on_body,
            send_delay=0.05,
            headers=_GZIP if gzip else None,
        )

    body = _body(sent)
    assert sent[0]["status"] == 200
    _assert_uncacheable(sent)
    assert 0 < len(body) < 1_000_000
    if gzip:
        assert _unterminated_gzip(body)
    else:
        with pytest.raises(json.JSONDecodeError):
            json.loads(body)
    assert [e["event"] for e in logs if e["log_level"] == "warning"] == [
        "ogc_items_stream_deadline"
    ]
    assert await _open_streams(test_db_session) == 0


def _fail_on_read(monkeypatch, failing_call: int) -> None:
    real_read = ogc_router.read_features_json
    calls = 0

    async def failing_read(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == failing_call:
            raise OperationalError("SELECT", {}, Exception("connection lost"))
        return await real_read(*args, **kwargs)

    monkeypatch.setattr(ogc_router, "read_features_json", failing_read)


async def test_a_failure_before_the_status_line_is_a_503(
    client: AsyncClient, some_polygons, monkeypatch
) -> None:
    _fail_on_read(monkeypatch, 1)

    resp = await client.get(
        f"/collections/{some_polygons.id}/items", params={"limit": 1000}
    )

    assert resp.status_code == 503


async def _fail_mid_stream(some_polygons, monkeypatch, headers=None):
    monkeypatch.setattr(ogc_router, "STREAM_BATCH_BYTES", 500_000)
    _fail_on_read(monkeypatch, 3)

    async def on_body(chunks: int, body: bytes) -> bool:
        return False

    with structlog.testing.capture_logs() as logs:
        sent = await _run_asgi(
            f"/collections/{some_polygons.id}/items",
            "limit=1000",
            on_body=on_body,
            headers=headers,
        )
    errors = [e["event"] for e in logs if e["log_level"] in ("error", "critical")]
    return sent, errors


async def test_a_failure_mid_stream_leaves_the_body_unparseable(
    client: AsyncClient, test_db_session, some_polygons, monkeypatch
) -> None:
    sent, errors = await _fail_mid_stream(some_polygons, monkeypatch)

    body = _body(sent)
    assert sent[0]["status"] == 200
    _assert_uncacheable(sent)
    assert len(body) > 64 * 1024
    with pytest.raises(json.JSONDecodeError):
        json.loads(body)
    assert errors == ["ogc_items_stream_failed"]
    assert await _open_streams(test_db_session) == 0


async def test_a_failure_mid_stream_leaves_gzip_unterminated(
    client: AsyncClient, some_polygons, monkeypatch
) -> None:
    sent, errors = await _fail_mid_stream(some_polygons, monkeypatch, headers=_GZIP)

    assert dict(sent[0]["headers"])[b"content-encoding"] == b"gzip"
    _assert_uncacheable(sent)
    assert _unterminated_gzip(_body(sent))
    assert errors == ["ogc_items_stream_failed"]


async def test_a_truncated_page_leaves_nothing_to_revalidate(
    client: AsyncClient, some_polygons, monkeypatch
) -> None:
    url = f"/collections/{some_polygons.id}/items"
    sent, _ = await _fail_mid_stream(some_polygons, monkeypatch)
    _assert_uncacheable(sent)
    monkeypatch.setattr(ogc_router, "read_features_json", features_read)

    retry = await client.get(url, params={"limit": 1000})
    small = await client.get(url, params={"limit": 2})
    again = await client.get(
        url, params={"limit": 2}, headers={"If-None-Match": small.headers["etag"]}
    )

    assert "etag" not in retry.headers
    assert retry.headers["cache-control"] == "no-store"
    assert retry.json()["numberReturned"] == 1000
    # A page read in one batch is sent whole and keeps its validator.
    assert "content-length" in small.headers
    assert again.status_code == 304


async def _write_between_reads(monkeypatch, statement: str) -> None:
    """Commit *statement* on another connection just before the first batch read."""
    real_read = ogc_router.read_features_json
    done = False

    async def read_after_write(*args, **kwargs):
        nonlocal done
        if not done:
            done = True
            async with db_module.engine.begin() as conn:
                await conn.execute(text(statement))
        return await real_read(*args, **kwargs)

    monkeypatch.setattr(ogc_router, "read_features_json", read_after_write)


async def test_a_row_deleted_after_the_page_is_chosen_is_still_served(
    client: AsyncClient, some_polygons, monkeypatch
) -> None:
    table = f"data.{some_polygons.table_name}"
    await _write_between_reads(monkeypatch, f"DELETE FROM {table} WHERE gid = 3")

    resp = await client.get(
        f"/collections/{some_polygons.id}/items", params={"limit": 5}
    )

    data = resp.json()
    assert [f["id"] for f in data["features"]] == [1, 2, 3, 4, 5]
    assert data["numberReturned"] == 5


async def test_a_row_updated_after_the_page_is_chosen_still_matches_the_filter(
    client: AsyncClient, some_polygons, monkeypatch
) -> None:
    table = f"data.{some_polygons.table_name}"
    await _write_between_reads(
        monkeypatch, f"UPDATE {table} SET name = 'renamed' WHERE gid = 3"
    )

    resp = await client.get(
        f"/collections/{some_polygons.id}/items", params={"name": "polygon 3"}
    )

    features = resp.json()["features"]
    assert [f["properties"]["name"] for f in features] == ["polygon 3"]


async def test_a_page_keeps_its_members(client: AsyncClient, some_polygons) -> None:
    resp = await client.get(
        f"/collections/{some_polygons.id}/items",
        params={"limit": 3, "offset": 3, "include_geometry": "false"},
    )

    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert data["timeStamp"].endswith("Z")
    assert data["numberMatched"] == 1000
    assert data["numberReturned"] == 3
    assert [f["id"] for f in data["features"]] == [4, 5, 6]
    assert data["features"][0] == {
        "type": "Feature",
        "id": 4,
        "geometry": None,
        "properties": {"name": "polygon 4", "status": None},
    }
    assert {link["rel"] for link in data["links"]} == {
        "self",
        "collection",
        "next",
        "prev",
    }
