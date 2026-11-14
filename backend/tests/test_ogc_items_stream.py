"""An OGC items page is streamed from a database cursor and always holds `limit` features."""

import json
from urllib.parse import parse_qs, urlparse

import anyio
import pytest
import structlog
from httpx import AsyncClient
from sqlalchemy import text

import app.standards.ogc.router as ogc_router
from app.modules.catalog.features import service as features_service
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


async def test_the_page_is_read_through_a_bounded_cursor(
    test_db_session, some_polygons, monkeypatch
) -> None:
    opened = []
    real_stream = test_db_session.stream

    async def spy(stmt, *args, **kwargs):
        opened.append(stmt.get_execution_options())
        return await real_stream(stmt, *args, **kwargs)

    monkeypatch.setattr(test_db_session, "stream", spy)
    gids = list(range(1, 1001))

    features = await features_service.open_feature_stream(
        test_db_session, some_polygons.table_name, gids
    )
    first = json.loads(await anext(features))
    await test_db_session.execute(text("SELECT pg_stat_clear_snapshot()"))
    portals = await test_db_session.execute(
        text("SELECT count(*) FROM pg_cursors WHERE statement LIKE :q"),
        {"q": _STREAM_QUERY},
    )
    rest = [json.loads(feature) async for feature in features]
    await test_db_session.rollback()

    assert [options["yield_per"] for options in opened] == [
        features_service.STREAM_FETCH_ROWS
    ]
    # The rows after the first are still on the server, behind an open portal.
    assert portals.scalar_one() == 1
    assert [first["id"], *(f["id"] for f in rest)] == gids
    assert first["geometry"]["type"] == "Polygon"
    assert first["properties"]["name"] == "polygon 1"


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


def _scope(path: str, query: str) -> dict:
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
        "headers": [(b"host", b"test")],
        "client": ("127.0.0.1", 50000),
        "server": ("test", 80),
    }


async def _run_asgi(path: str, query: str, *, on_body, send_delay: float = 0):
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

    async def send(message):
        sent.append(message)
        if message["type"] == "http.response.body" and message.get("body"):
            if await on_body(len([m for m in sent if m.get("body")])):
                disconnect.set()
            await anyio.sleep(send_delay)

    await app(_scope(path, query), receive, send)
    disconnect.set()
    return sent


def _body(sent: list[dict]) -> bytes:
    return b"".join(m.get("body", b"") for m in sent[1:])


async def test_a_client_disconnect_releases_the_connection(
    client: AsyncClient, test_db_session, some_polygons, monkeypatch
) -> None:
    during = []
    streams = []
    real_open = ogc_router.open_feature_stream

    async def recording_open(*args, **kwargs):
        streams.append(await real_open(*args, **kwargs))
        return streams[-1]

    monkeypatch.setattr(ogc_router, "open_feature_stream", recording_open)

    async def on_body(chunks: int) -> bool:
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


async def test_the_stream_ends_at_the_request_deadline(
    client: AsyncClient, test_db_session, some_polygons, monkeypatch
) -> None:
    monkeypatch.setattr(ogc_router, "current_deadline_ms", lambda: 300)

    async def on_body(chunks: int) -> bool:
        return False

    with structlog.testing.capture_logs() as logs:
        sent = await _run_asgi(
            f"/collections/{some_polygons.id}/items",
            "limit=1000",
            on_body=on_body,
            send_delay=0.05,
        )

    body = _body(sent)
    assert sent[0]["status"] == 200
    assert 0 < len(body) < 1_000_000
    with pytest.raises(json.JSONDecodeError):
        json.loads(body)
    assert [e["event"] for e in logs if e["log_level"] == "warning"] == [
        "ogc_items_stream_deadline"
    ]
    assert await _open_streams(test_db_session) == 0


async def test_a_failure_mid_stream_leaves_the_body_unparseable(
    client: AsyncClient, test_db_session, some_polygons, monkeypatch
) -> None:
    real_open = ogc_router.open_feature_stream

    async def failing_open(*args, **kwargs):
        features = await real_open(*args, **kwargs)

        async def fail_after_some():
            served = 0
            async for feature in features:
                if served == 300:
                    raise RuntimeError("connection lost")
                served += 1
                yield feature

        return fail_after_some()

    monkeypatch.setattr(ogc_router, "open_feature_stream", failing_open)

    with structlog.testing.capture_logs() as logs:
        resp = await client.get(
            f"/collections/{some_polygons.id}/items", params={"limit": 1000}
        )

    assert resp.status_code == 200
    assert len(resp.content) > 64 * 1024
    with pytest.raises(json.JSONDecodeError):
        json.loads(resp.content)
    errors = [e for e in logs if e["log_level"] in ("error", "critical")]
    assert [e["event"] for e in errors] == ["ogc_items_stream_failed"]
    assert await _open_streams(test_db_session) == 0


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
