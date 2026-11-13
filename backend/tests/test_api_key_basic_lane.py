"""An API key sent as the password of an HTTP Basic login.

Desktop GIS clients such as ArcGIS Pro send a saved login only after a Basic
challenge, and then send it on every request to the host. The key rides in
the password and the username is ignored. A browser that saved the same login
replays it on cross-site requests, so the lane authenticates reads only, the
same transport rule as ``?api_key=``. Everything else about the key (its
scope, its binding to a dataset, revocation) applies exactly as it does on
the ``X-Api-Key`` header.
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest
import sqlalchemy
from httpx import AsyncClient
from sqlalchemy import text

from app.core.config import settings
from app.core.public_urls import desktop_entry_serves
from app.modules.auth.dependencies import _basic_password
from app.modules.catalog.datasets.domain.models import Dataset, Record
from tests.factories import create_raster_dataset, create_user

pytestmark = pytest.mark.anyio

ADMIN_USER = settings.geolens_admin_username
ADMIN_PASS = settings.geolens_admin_password.get_secret_value()

POINT = {"type": "Point", "coordinates": [-73.9857, 40.7484]}
CHALLENGE = 'Basic realm="GeoLens"'


def _in_days(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _basic(password: str, username: str = "arcgis") -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture(autouse=True)
def _remove_keys_minted_by_the_test(request):
    """Minting commits through the app's own sessions, so the test removes its keys.

    A scoped key left behind makes a later downgrade past its migration refuse.
    """
    if "client" not in request.fixturenames:
        yield
        return
    engine = sqlalchemy.create_engine(settings.test_database_url_sync)
    try:
        with engine.begin() as conn:
            before = [
                row[0] for row in conn.execute(text("SELECT id FROM catalog.api_keys"))
            ]
        yield
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM catalog.api_keys WHERE id <> ALL(:before)"),
                {"before": before},
            )
    finally:
        engine.dispose()


async def _feature_dataset(session, *, owner_id, visibility: str):
    table_name = f"test_basic_{uuid.uuid4().hex[:8]}"
    await session.execute(
        text(
            f"CREATE TABLE data.{table_name} (gid SERIAL PRIMARY KEY, "
            "geom geometry(Point, 4326), geom_4326 geometry(Geometry, 4326), "
            "name TEXT)"
        )
    )
    await session.execute(
        text(
            f"INSERT INTO data.{table_name} (geom, geom_4326, name) VALUES "
            "(ST_SetSRID(ST_MakePoint(-73.98, 40.74), 4326), "
            "ST_SetSRID(ST_MakePoint(-73.98, 40.74), 4326), 'seed')"
        )
    )
    await session.execute(text(f"GRANT SELECT ON data.{table_name} TO geolens_reader"))
    record = Record(
        title=f"Basic lane {table_name}",
        visibility=visibility,
        record_status="published",
        created_by=owner_id,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="POINT",
        feature_count=1,
        column_info=[{"name": "name", "type": "text"}],
        source_format="created",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


@pytest.fixture
async def owner(client: AsyncClient, admin_auth_header):
    """An editor who owns the datasets below; returns (session headers, user id)."""
    headers, user_id = await create_user(client, admin_auth_header, "editor")
    return headers, uuid.UUID(user_id)


@pytest.fixture
async def datasets(test_db_session, owner):
    """Two private point datasets and one public one, all owned by ``owner``."""
    _, owner_id = owner
    made = [
        await _feature_dataset(test_db_session, owner_id=owner_id, visibility=v)
        for v in ("private", "private", "public")
    ]
    ids = [(d.table_name, d.record_id) for d in made]
    yield made
    for table_name, record_id in ids:
        await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table_name}"))
        await test_db_session.execute(
            text("DELETE FROM catalog.records WHERE id = :id"), {"id": record_id}
        )
    await test_db_session.commit()


async def _mint(client: AsyncClient, headers: dict, **body) -> str:
    resp = await client.post(
        "/auth/api-keys/", json={"name": "Basic Lane", **body}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["key"]


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


async def test_a_basic_key_reads_a_private_dataset(
    client: AsyncClient, test_db_session, owner, datasets
):
    headers, owner_id = owner
    private = datasets[0]
    raster = await create_raster_dataset(
        test_db_session, created_by=owner_id, visibility="private"
    )
    key = await _mint(client, headers)

    for url in (f"/collections/{private.id}/items", f"/stac/items/{raster.id}"):
        anonymous = await client.get(url)
        assert anonymous.status_code == 404, url
        resp = await client.get(url, headers=_basic(key))
        assert resp.status_code == 200, (url, resp.text)

    items = await client.get(f"/collections/{private.id}/items", headers=_basic(key))
    assert [f["properties"]["name"] for f in items.json()["features"]] == ["seed"]

    head = await client.head(f"/collections/{private.id}/items", headers=_basic(key))
    assert head.status_code == 200


async def test_the_scheme_and_username_do_not_matter(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    private = datasets[0]
    key = await _mint(client, headers)
    token = base64.b64encode(f":{key}".encode()).decode()

    resp = await client.get(
        f"/collections/{private.id}/items", headers={"Authorization": f"bAsIc {token}"}
    )
    assert resp.status_code == 200, resp.text


async def test_a_basic_key_answers_what_the_header_key_answers(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    public = datasets[2]
    key = await _mint(client, headers)

    for url in ("/collections", f"/collections/{public.id}/items", "/stac/collections"):
        via_header = await client.get(url, headers={"X-Api-Key": key})
        via_basic = await client.get(url, headers=_basic(key))
        assert via_header.status_code == 200, (url, via_header.text)
        assert via_basic.status_code == 200, (url, via_basic.text)
        # A feature page stamps the time it was generated.
        assert {**via_basic.json(), "timeStamp": None} == {
            **via_header.json(),
            "timeStamp": None,
        }, url


# ---------------------------------------------------------------------------
# Writes are refused on the lane
# ---------------------------------------------------------------------------


async def test_a_full_key_cannot_write_over_basic(client: AsyncClient, owner, datasets):
    headers, _ = owner
    private = datasets[0]
    key = await _mint(client, headers)

    created = await client.post(
        f"/datasets/{private.id}/features/",
        json={"geometry": POINT, "properties": {"name": "from basic"}},
        headers=_basic(key),
    )
    assert created.status_code == 401, created.text

    patched = await client.patch(
        f"/datasets/{private.id}",
        json={"title": "Renamed Over Basic"},
        headers=_basic(key),
    )
    assert patched.status_code == 401, patched.text

    deleted = await client.delete(f"/datasets/{private.id}", headers=_basic(key))
    assert deleted.status_code == 401, deleted.text

    minted = await client.post(
        "/auth/api-keys/", json={"name": "Minted Over Basic"}, headers=_basic(key)
    )
    assert minted.status_code == 401, minted.text

    items = await client.get(f"/collections/{private.id}/items", headers=headers)
    assert [f["properties"]["name"] for f in items.json()["features"]] == ["seed"]
    detail = await client.get(f"/datasets/{private.id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["title"] != "Renamed Over Basic"
    keys = (await client.get("/auth/api-keys/", headers=headers)).json()["items"]
    assert "Minted Over Basic" not in {item["name"] for item in keys}


async def test_the_same_key_still_writes_over_the_header(
    client: AsyncClient, owner, datasets
):
    """The paired control: the refusal is the transport, not the key."""
    headers, _ = owner
    private = datasets[0]
    key = await _mint(client, headers)

    created = await client.post(
        f"/datasets/{private.id}/features/",
        json={"geometry": POINT, "properties": {"name": "from header"}},
        headers={"X-Api-Key": key},
    )
    assert created.status_code == 201, created.text


# ---------------------------------------------------------------------------
# What does not resolve stays 401
# ---------------------------------------------------------------------------


async def test_an_unresolvable_basic_login_is_refused(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    private, _, public = datasets
    key = await _mint(client, headers)
    malformed = {
        "bad base64": {"Authorization": "Basic not*base64"},
        "no colon": {
            "Authorization": f"Basic {base64.b64encode(key.encode()).decode()}"
        },
        "empty password": _basic(""),
        "not utf-8": {
            "Authorization": "Basic " + base64.b64encode(b"u:\xff\xfe").decode()
        },
    }
    refused = {
        "wrong key": _basic("glk_not-a-real-key"),
        "account password": _basic(ADMIN_PASS, username=ADMIN_USER),
        **malformed,
    }
    for name, auth in refused.items():
        for url in (
            f"/collections/{private.id}/items",
            f"/collections/{public.id}/items",
        ):
            resp = await client.get(url, headers=auth)
            assert resp.status_code == 401, (name, url, resp.text)
            assert resp.headers["www-authenticate"] == CHALLENGE, (name, url)


async def test_a_required_auth_route_challenges_a_dead_basic_login_for_basic(
    client: AsyncClient,
):
    resp = await client.get("/auth/me/", headers=_basic("glk_not-a-real-key"))
    assert resp.status_code == 401, resp.text
    assert resp.headers["www-authenticate"] == CHALLENGE

    resp = await client.get("/auth/me/", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 401, resp.text
    assert resp.headers["www-authenticate"] == "Bearer"


async def test_a_revoked_key_is_refused_over_basic(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    private = datasets[0]
    resp = await client.post(
        "/auth/api-keys/", json={"name": "Revoke Me"}, headers=headers
    )
    key, key_id = resp.json()["key"], resp.json()["id"]
    url = f"/collections/{private.id}/items"
    assert (await client.get(url, headers=_basic(key))).status_code == 200

    assert (
        await client.delete(f"/auth/api-keys/{key_id}", headers=headers)
    ).status_code == 204
    assert (await client.get(url, headers=_basic(key))).status_code == 401


def test_only_a_well_formed_basic_value_yields_a_password():
    def encoded(raw: bytes) -> str:
        return base64.b64encode(raw).decode()

    assert _basic_password(f"Basic {encoded(b'user:glk_abc')}") == "glk_abc"
    assert _basic_password(f"basic {encoded(b':glk_abc')}") == "glk_abc"
    assert _basic_password(f"Basic {encoded(b'user:pa:ss')}") == "pa:ss"
    for value in (
        "",
        "Bearer glk_abc",
        "Basic",
        "Basic not*base64",
        f"Basic {encoded(b'user:glk_abc')[:-1]}",
        f"Basic {encoded(b'no-colon')}",
        f"Basic {encoded(b'user:')}",
        "Basic " + encoded(b"u:\xff"),
        "Basic \u00e9",
    ):
        assert _basic_password(value) is None, value


# ---------------------------------------------------------------------------
# Key scopes apply unchanged
# ---------------------------------------------------------------------------


async def test_a_read_only_key_keeps_its_limits_over_basic(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    private = datasets[0]
    key = await _mint(client, headers, scope="read_only")

    items = await client.get(f"/collections/{private.id}/items", headers=_basic(key))
    assert items.status_code == 200, items.text

    # A GET that writes is refused on the lane before the scope is consulted.
    refresh = await client.get(
        f"/datasets/{private.id}/validate",
        params={"refresh": "true"},
        headers=_basic(key),
    )
    assert refresh.status_code == 401, refresh.text


async def test_a_publish_key_keeps_its_limits_over_basic(
    client: AsyncClient, admin_auth_header
):
    key = await _mint(client, admin_auth_header, scope="publish")

    assert (await client.get("/auth/me/", headers=_basic(key))).status_code == 200
    users = await client.get("/admin/users/", headers=_basic(key))
    assert users.status_code == 403, users.text
    assert users.json()["detail"]["code"] == "api_key_scope"


async def test_a_dataset_key_keeps_its_binding_over_basic(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    bound, other, _ = datasets
    resp = await client.post(
        f"/datasets/{bound.id}/api-keys",
        json={"name": "Bound", "expires_at": _in_days(30)},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    key = resp.json()["key"]

    own = await client.get(f"/collections/{bound.id}/items", headers=_basic(key))
    assert own.status_code == 200, own.text

    for url in (f"/collections/{other.id}/items", "/auth/me/", "/collections"):
        refused = await client.get(url, headers=_basic(key))
        assert refused.status_code == 401, (url, refused.text)

    # The key may write its dataset over the header, but not over Basic.
    created = await client.post(
        f"/datasets/{bound.id}/features/",
        json={"geometry": POINT, "properties": {"name": "from basic"}},
        headers=_basic(key),
    )
    assert created.status_code == 401, created.text


# ---------------------------------------------------------------------------
# The desktop entry: the OGC API under /desktop, for signed-in callers only
# ---------------------------------------------------------------------------


def _entry_paths(private, public) -> list[str]:
    paths = ["/desktop", "/desktop/", "/desktop/conformance", "/desktop/openapi.json"]
    paths += ["/desktop/collections/datasets", "/desktop/collections/datasets/items"]
    for dataset in (private, public):
        paths += [
            "/desktop/collections",
            "/desktop/collections/",
            f"/desktop/collections/{dataset.id}/items/",
            f"/desktop/collections/{dataset.id}",
            f"/desktop/collections/{dataset.id}/queryables",
            f"/desktop/collections/{dataset.id}/items",
        ]
    return paths


async def _api_base(client: AsyncClient) -> str:
    links = (await client.get("/")).json()["links"]
    return next(link["href"] for link in links if link["rel"] == "self").rstrip("/")


def _links(document) -> list[dict]:
    """Every object carrying an ``href`` anywhere in ``document``."""
    if isinstance(document, list):
        return [link for item in document for link in _links(item)]
    if not isinstance(document, dict):
        return []
    found = [document] if isinstance(document.get("href"), str) else []
    return found + [link for value in document.values() for link in _links(value)]


async def test_every_route_under_the_entry_challenges_a_caller_without_a_credential(
    client: AsyncClient, datasets
):
    private, _, public = datasets
    for path in _entry_paths(private, public):
        for method in ("GET", "HEAD"):
            resp = await client.request(method, path)
            assert resp.status_code == 401, (method, path, resp.text)
            assert resp.headers["www-authenticate"] == CHALLENGE, (method, path)
            assert resp.headers["cache-control"] == "no-store", (method, path)


async def test_a_credential_that_does_not_resolve_is_refused_under_the_entry(
    client: AsyncClient, datasets
):
    _, _, public = datasets
    for path in (
        "/desktop",
        "/desktop/conformance",
        f"/desktop/collections/{public.id}",
    ):
        for auth in (
            _basic("glk_not-a-real-key"),
            _basic(ADMIN_PASS, username=ADMIN_USER),
            {"Authorization": "Basic not*base64"},
        ):
            resp = await client.get(path, headers=auth)
            assert resp.status_code == 401, (path, resp.text)
            assert resp.headers["www-authenticate"] == CHALLENGE, path
        for auth in (
            {"Authorization": "Bearer not-a-token"},
            {"X-Api-Key": "glk_not-a-real-key"},
        ):
            resp = await client.get(path, headers=auth)
            assert resp.status_code == 401, (path, auth, resp.text)
            assert resp.headers["www-authenticate"] == "Bearer", (path, auth)


async def test_a_key_sent_as_the_basic_password_reads_every_route_under_the_entry(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    private, _, public = datasets
    key = await _mint(client, headers)
    for path in _entry_paths(private, public):
        for auth in (_basic(key), {"X-Api-Key": key}, headers):
            resp = await client.get(path, headers=auth)
            assert resp.status_code == 200, (path, resp.text)
        head = await client.head(path, headers=_basic(key))
        assert head.status_code == 200, path

    listed = await client.get("/desktop/collections", headers=_basic(key))
    assert str(private.id) in {c["id"] for c in listed.json()["collections"]}
    items = await client.get(
        f"/desktop/collections/{private.id}/items", headers=_basic(key)
    )
    assert [f["properties"]["name"] for f in items.json()["features"]] == ["seed"]
    feature_id = items.json()["features"][0]["id"]
    feature = await client.get(
        f"/desktop/collections/{private.id}/items/{feature_id}", headers=_basic(key)
    )
    assert feature.status_code == 200, feature.text


async def test_a_reopened_client_without_its_login_is_challenged_at_the_stored_address(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    private = datasets[0]
    key = await _mint(client, headers)
    stored = ["/desktop", "/desktop/openapi.json", "/desktop/collections"]
    stored.append(f"/desktop/collections/{private.id}/items")
    for path in stored:
        assert (await client.get(path, headers=_basic(key))).status_code == 200
    for path in stored:
        resp = await client.get(path)
        assert resp.status_code == 401, path
        assert resp.headers["www-authenticate"] == CHALLENGE, path


async def test_every_link_under_the_entry_stays_there_when_the_entry_serves_it(
    client: AsyncClient, test_db_session, owner, datasets
):
    headers, _ = owner
    private = datasets[0]
    await test_db_session.execute(
        text(
            f"INSERT INTO data.{private.table_name} (geom, geom_4326, name) VALUES "
            "(ST_SetSRID(ST_MakePoint(-73.9, 40.7), 4326), "
            "ST_SetSRID(ST_MakePoint(-73.9, 40.7), 4326), 'second')"
        )
    )
    await test_db_session.commit()
    key = await _mint(client, headers)
    api_base = await _api_base(client)
    entry_base = api_base + "/desktop"

    items = await client.get(
        f"/desktop/collections/{private.id}/items?limit=1", headers=_basic(key)
    )
    assert any(link["rel"] == "next" for link in items.json()["links"])
    feature_id = items.json()["features"][0]["id"]
    documents = [items.json()]
    for path in (
        "/desktop/",
        "/desktop/collections",
        f"/desktop/collections/{private.id}",
        f"/desktop/collections/{private.id}/items/{feature_id}",
    ):
        resp = await client.get(path, headers=_basic(key))
        assert resp.status_code == 200, (path, resp.text)
        documents.append(resp.json())

    served = 0
    for link in _links(documents):
        href = link["href"]
        if not href.startswith(api_base + "/"):
            assert "/desktop" not in href, href
            continue
        path = urlsplit(href).path.removeprefix(urlsplit(api_base).path)
        if path.startswith("/desktop/") or path == "/desktop":
            assert desktop_entry_serves(path.removeprefix("/desktop") or "/"), href
            served += 1
        else:
            assert not desktop_entry_serves(path), href
    assert served > 10

    for rel in ("self", "data", "conformance", "service-desc"):
        landing = documents[1]["links"]
        href = next(link["href"] for link in landing if link["rel"] == rel)
        assert href.startswith(entry_base + "/"), (rel, href)
    for link in items.json()["links"]:
        assert link["href"].startswith(entry_base + "/"), link

    next_href = next(link for link in items.json()["links"] if link["rel"] == "next")
    next_page = await client.get(
        urlsplit(next_href["href"]).path.removeprefix(urlsplit(api_base).path)
        + "?"
        + urlsplit(next_href["href"]).query,
        headers=_basic(key),
    )
    assert [f["properties"]["name"] for f in next_page.json()["features"]] == ["second"]


async def test_the_openapi_document_under_the_entry_describes_the_routes_it_serves(
    client: AsyncClient, owner
):
    headers, _ = owner
    key = await _mint(client, headers)
    document = (await client.get("/desktop/openapi.json", headers=_basic(key))).json()
    published = (await client.get("/openapi.json")).json()

    assert [server["url"] for server in document["servers"]] == [
        server["url"].rstrip("/") + "/desktop" for server in published["servers"]
    ]
    assert document["paths"]
    assert "/collections/{dataset_id}/items" in document["paths"]
    assert all(desktop_entry_serves(path) for path in document["paths"])
    for path in document["paths"]:
        if "{" not in path:
            resp = await client.get("/desktop" + path, headers=_basic(key))
            assert resp.status_code == 200, (path, resp.text)
    assert not any("desktop" in path for path in published["paths"])

    schemes = document["components"]["securitySchemes"]
    assert schemes["HTTPBasic"]["scheme"] == "basic"
    assert "HTTPBasic" not in published["components"]["securitySchemes"]
    for path, item in document["paths"].items():
        assert set(item) & {"get", "head"} and not set(item) & {
            "post",
            "put",
            "patch",
            "delete",
        }, path
        for method in ("get", "head"):
            if method not in item:
                continue
            security = item[method]["security"]
            assert {} not in security and {"HTTPBasic": []} in security, (path, method)
            assert "401" in item[method]["responses"], (path, method)
    assert {} in published["paths"]["/collections"]["get"]["security"]


async def test_the_entry_serves_only_reads_of_the_ogc_routes(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    public = datasets[2]
    key = await _mint(client, headers)
    for path in ("/desktop/datasets", "/desktop/auth/me", "/desktop/desktop"):
        resp = await client.get(path, headers=headers)
        assert resp.status_code == 404, (path, resp.text)
    resp = await client.post(
        f"/desktop/collections/{public.id}/items", json={}, headers=headers
    )
    assert resp.status_code == 405, resp.text
    assert resp.headers["allow"] == "GET, HEAD"
    assert (
        await client.get("/desktop/collections", headers=_basic(key))
    ).status_code == 200


async def test_the_api_root_answers_anonymous_callers_as_before(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    private, _, public = datasets
    key = await _mint(client, headers)
    paths = [
        "/",
        "/conformance",
        "/collections",
        f"/collections/{public.id}",
        f"/collections/{public.id}/items",
    ]

    def stable(resp):
        assert resp.status_code == 200, resp.text
        return {**resp.json(), "timeStamp": None}

    before = [stable(await client.get(path)) for path in paths]
    for path in _entry_paths(private, public):
        await client.get(path, headers=_basic(key))
    after = [stable(await client.get(path)) for path in paths]

    assert before == after
    assert not any("/desktop" in link["href"] for link in _links(after))
    assert (await client.get(f"/collections/{private.id}")).status_code == 404


async def test_the_entry_never_gets_the_anonymous_cors_wildcard(
    client: AsyncClient, owner
):
    headers, _ = owner
    key = await _mint(client, headers)
    origin = {"Origin": "https://elsewhere.example.com"}

    public_answer = await client.get("/collections", headers=origin)
    assert public_answer.headers.get("access-control-allow-origin") == "*"
    for auth in ({}, _basic(key)):
        resp = await client.get("/desktop/collections", headers={**origin, **auth})
        assert resp.headers.get("access-control-allow-origin") is None, auth


def test_the_entry_is_routed_before_the_rate_limiter_and_backstopped_inside_logging():
    """The limiter finds the route a request under the entry names; a backstop refusal is logged."""
    from app.api.main import app
    from app.api.middleware.logging import RequestLoggingMiddleware
    from app.api.middleware.rate_limit import GlobalRateLimitMiddleware
    from app.standards.ogc.desktop import (
        DesktopEntryGateMiddleware,
        DesktopEntryRewriteMiddleware,
    )

    outermost_first = [middleware.cls for middleware in app.user_middleware]
    position = outermost_first.index
    assert position(DesktopEntryRewriteMiddleware) < position(GlobalRateLimitMiddleware)
    assert position(RequestLoggingMiddleware) < position(DesktopEntryGateMiddleware)


async def test_a_refusal_under_the_entry_is_a_problem_document(
    client: AsyncClient, datasets
):
    _, _, public = datasets
    for path in ("/desktop", f"/desktop/collections/{public.id}/items"):
        for auth in ({}, _basic("glk_not-a-real-key"), {"X-Api-Key": "glk_nope"}):
            resp = await client.get(path, headers=auth)
            assert resp.status_code == 401, (path, auth)
            assert resp.headers["content-type"] == "application/problem+json"
            assert resp.headers["cache-control"] == "no-store"
            assert "www-authenticate" in resp.headers
            body = resp.json()
            assert body["status"] == 401 and body["title"] == "Unauthorized", body
            assert {"type", "detail"} <= body.keys(), body
    refused = await client.post(f"/desktop/collections/{public.id}/items", json={})
    assert refused.headers["content-type"] == "application/problem+json"
    assert refused.json()["status"] == 405


async def test_a_dataset_key_is_judged_under_the_entry_as_on_the_api(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    bound, other, _ = datasets
    resp = await client.post(
        f"/datasets/{bound.id}/api-keys",
        json={"name": "Bound", "expires_at": _in_days(30)},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    key = resp.json()["key"]
    feature_id = (
        await client.get(f"/collections/{bound.id}/items", headers=headers)
    ).json()["features"][0]["id"]

    expected = {
        f"/collections/{bound.id}/items": 200,
        f"/collections/{bound.id}/items/": 200,
        f"/collections/{bound.id}/items/{feature_id}": 200,
        f"/collections/{other.id}/items": 401,
        f"/collections/{other.id}/items/": 401,
        "/collections": 401,
    }
    transports = {
        "basic": (_basic(key), ""),
        "header": ({"X-Api-Key": key}, ""),
        "query": ({}, f"?api_key={key}"),
    }
    for path, status_code in expected.items():
        for name, (auth, query) in transports.items():
            for method in ("GET", "HEAD"):
                api = await client.request(method, path + query, headers=auth)
                entry = await client.request(
                    method, "/desktop" + path + query, headers=auth
                )
                assert entry.status_code == api.status_code, (method, name, path)
                if method == "GET":
                    assert api.status_code == status_code, (name, path, api.text)
    # The landing page never reads a key on /api; the entry requires one that resolves.
    assert (await client.get("/desktop/", headers=_basic(key))).status_code == 401


async def test_the_backstop_challenges_an_answer_the_gate_did_not_pass():
    """A route reached through the entry without the gate answers with the challenge."""
    from starlette.responses import PlainTextResponse

    from app.core.public_urls import mark_desktop_entry
    from app.standards.ogc.desktop import DesktopEntryGateMiddleware

    sent: list[dict] = []

    async def ungated(scope, receive, send):
        await PlainTextResponse("private")(scope, receive, send)

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "GET", "path": "/", "headers": []}
    mark_desktop_entry(scope)
    await DesktopEntryGateMiddleware(ungated)(scope, receive, send)

    assert sent[0]["status"] == 401
    assert (b"www-authenticate", CHALLENGE.encode()) in sent[0]["headers"]
    assert b"private" not in b"".join(m.get("body", b"") for m in sent)


async def test_a_database_failure_while_judging_the_credential_is_a_503(
    client: AsyncClient, monkeypatch
):
    """The gate's lookup failing on the database gets the API's 503, not a 500."""
    from sqlalchemy.exc import OperationalError

    import app.standards.ogc.desktop as desktop

    async def unavailable(request, db):
        raise OperationalError("SELECT 1", {}, ConnectionError("connection lost"))

    monkeypatch.setattr(desktop, "get_optional_user_no_security_schema", unavailable)
    resp = await client.get("/desktop/collections", headers=_basic("glk_any"))
    assert resp.status_code == 503, resp.text
    assert resp.headers["content-type"] == "application/problem+json"
