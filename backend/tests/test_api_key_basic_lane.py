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

import pytest
import sqlalchemy
from httpx import AsyncClient
from sqlalchemy import text

from app.core.config import settings
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
# The desktop entry route
# ---------------------------------------------------------------------------


async def _landing_url(client: AsyncClient) -> str:
    links = (await client.get("/")).json()["links"]
    return next(link["href"] for link in links if link["rel"] == "self")


async def test_the_desktop_entry_challenges_without_a_working_credential(
    client: AsyncClient,
):
    for auth in (
        {},
        _basic("glk_not-a-real-key"),
        _basic(ADMIN_PASS, username=ADMIN_USER),
        {"Authorization": "Basic not*base64"},
        {"Authorization": "Bearer not-a-token"},
        {"X-Api-Key": "glk_not-a-real-key"},
    ):
        for method in ("GET", "HEAD"):
            resp = await client.request(method, "/desktop", headers=auth)
            assert resp.status_code == 401, (method, auth, resp.text)
            assert resp.headers["www-authenticate"] == CHALLENGE, (method, auth)
            assert resp.headers["cache-control"] == "no-store", (method, auth)


async def test_the_desktop_entry_redirects_a_signed_in_caller_to_the_landing_page(
    client: AsyncClient, owner
):
    headers, _ = owner
    key = await _mint(client, headers)
    landing = await _landing_url(client)
    assert landing.endswith("/")

    for auth in (_basic(key), {"X-Api-Key": key}, headers):
        for method in ("GET", "HEAD"):
            resp = await client.request(
                method, "/desktop", headers=auth, follow_redirects=False
            )
            assert resp.status_code == 302, (method, resp.text)
            assert resp.headers["location"] == landing
            assert resp.headers["cache-control"] == "no-store"
