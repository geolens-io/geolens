"""One-dataset write keys: what a ``dataset_write`` key may reach, and how it is refused.

The key is bound to one dataset and authenticates only that dataset's feature
routes. Everywhere else it must look exactly like an invalid key, so a
holder learns nothing about other routes or datasets. It acts as its minting
user, so that user's own access still applies on every request.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy
from httpx import AsyncClient
from sqlalchemy import text

from app.core.config import settings
from app.modules.auth.dependencies import _DATASET_KEY_ROUTES
from app.modules.catalog.datasets.domain.models import Dataset, Record
from tests.factories import create_user, get_user_id

pytestmark = pytest.mark.anyio

POINT = {"type": "Point", "coordinates": [-73.9857, 40.7484]}
POINT_2 = {"type": "Point", "coordinates": [-118.2437, 34.0522]}


@pytest.fixture(autouse=True)
def _remove_keys_minted_by_the_test(request):
    """Minting commits through the app's own sessions, so the test removes its keys.

    An active dataset_write key left behind makes the 0084 downgrade refuse.
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


def _in_days(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


async def _feature_dataset(session, *, owner_id, visibility: str = "private"):
    table_name = f"test_dskey_{uuid.uuid4().hex[:8]}"
    await session.execute(
        text(
            f"CREATE TABLE data.{table_name} (gid SERIAL PRIMARY KEY, "
            "geom geometry(Point, 4326), geom_4326 geometry(Geometry, 4326), "
            "name TEXT)"
        )
    )
    await session.execute(text(f"GRANT SELECT ON data.{table_name} TO geolens_reader"))
    record = Record(
        title=f"Dataset key {table_name}",
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
        feature_count=0,
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
    """Two private point datasets owned by ``owner``: the bound one and another."""
    _, owner_id = owner
    made = [
        await _feature_dataset(test_db_session, owner_id=owner_id) for _ in range(2)
    ]
    ids = [(d.id, d.table_name, d.record_id) for d in made]
    yield made
    for _, table_name, record_id in ids:
        await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table_name}"))
        await test_db_session.execute(
            text("DELETE FROM catalog.records WHERE id = :id"), {"id": record_id}
        )
    await test_db_session.commit()


async def _mint(client: AsyncClient, headers: dict, dataset_id, **body) -> dict:
    resp = await client.post(
        f"/datasets/{dataset_id}/api-keys",
        json={"name": "Webhook", "expires_at": _in_days(30), **body},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _assert_refused_like_an_invalid_key(
    client: AsyncClient, method: str, url: str, raw_key: str, **kwargs
) -> None:
    junk = await client.request(
        method, url, headers={"X-Api-Key": "not-a-real-key"}, **kwargs
    )
    resp = await client.request(method, url, headers={"X-Api-Key": raw_key}, **kwargs)
    assert junk.status_code == 401, (url, junk.text)
    assert (resp.status_code, resp.json(), resp.headers.get("www-authenticate")) == (
        junk.status_code,
        junk.json(),
        junk.headers.get("www-authenticate"),
    ), (method, url)


async def test_a_dataset_key_reads_and_writes_its_own_features(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    bound = datasets[0]
    data = await _mint(client, headers, bound.id)
    assert (data["scope"], data["dataset_id"]) == ("dataset_write", str(bound.id))
    key = {"X-Api-Key": data["key"]}
    base = f"/datasets/{bound.id}/features"

    for create_url in (f"{base}/", base):
        created = await client.post(
            create_url,
            json={"geometry": POINT, "properties": {"name": "made"}},
            headers=key,
        )
        assert created.status_code == 201, created.text
    gid = created.json()["id"]

    replaced = await client.put(
        f"{base}/{gid}",
        json={"geometry": POINT_2, "properties": {"name": "replaced"}},
        headers=key,
    )
    assert replaced.status_code == 200, replaced.text
    patched = await client.patch(
        f"{base}/{gid}", json={"properties": {"name": "patched"}}, headers=key
    )
    assert patched.status_code == 200, patched.text

    for url in (
        f"{base}/",
        base,
        f"{base}/{gid}",
        f"/datasets/{bound.id}/features.geojson",
        f"/collections/{bound.id}/items",
        f"/collections/{bound.id}/items/",
        f"/collections/{bound.id}/items/{gid}",
    ):
        resp = await client.get(url, headers=key)
        assert resp.status_code == 200, (url, resp.text)

    deleted = await client.delete(f"{base}/{gid}", headers=key)
    assert deleted.status_code == 204, deleted.text

    # The bound id still matches when spelled in another valid UUID form.
    resp = await client.get(f"/collections/{str(bound.id).upper()}/items", headers=key)
    assert resp.status_code == 200, resp.text


async def test_a_dataset_key_is_refused_on_another_datasets_feature_routes(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    bound, other = datasets
    raw_key = (await _mint(client, headers, bound.id))["key"]

    # The owner may write the other dataset, so only the key's binding refuses.
    for method, url, kwargs in (
        ("GET", f"/collections/{other.id}/items", {}),
        ("GET", f"/datasets/{other.id}/features/", {}),
        (
            "POST",
            f"/datasets/{other.id}/features/",
            {"json": {"geometry": POINT, "properties": {}}},
        ),
        ("DELETE", f"/datasets/{other.id}/features/1", {}),
        # A dataset that does not exist answers the same, so nothing leaks.
        ("GET", f"/collections/{uuid.uuid4()}/items", {}),
    ):
        await _assert_refused_like_an_invalid_key(
            client, method, url, raw_key, **kwargs
        )


async def test_a_dataset_key_is_refused_off_the_feature_routes(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    bound = datasets[0]
    raw_key = (await _mint(client, headers, bound.id))["key"]

    for method, url, kwargs in (
        ("GET", "/auth/me/", {}),
        ("GET", "/auth/api-keys/", {}),
        ("GET", f"/datasets/{bound.id}", {}),
        ("GET", f"/collections/{bound.id}", {}),
        ("GET", f"/collections/{bound.id}/queryables", {}),
        ("GET", f"/datasets/{bound.id}/api-keys", {}),
        ("PATCH", f"/datasets/{bound.id}", {"json": {"title": "Renamed"}}),
        ("DELETE", f"/datasets/{bound.id}", {}),
        ("POST", "/maps/", {"json": {"name": "Made by a dataset key"}}),
        ("GET", "/admin/users/", {}),
        ("GET", "/admin/api-keys/", {}),
    ):
        await _assert_refused_like_an_invalid_key(
            client, method, url, raw_key, **kwargs
        )


async def test_a_refused_dataset_key_records_no_use(
    client: AsyncClient, owner, datasets, test_db_session
):
    headers, _ = owner
    data = await _mint(client, headers, datasets[0].id)
    resp = await client.get("/auth/me/", headers={"X-Api-Key": data["key"]})
    assert resp.status_code == 401
    await test_db_session.commit()
    last_used = (
        await test_db_session.execute(
            text("SELECT last_used_at FROM catalog.api_keys WHERE id = :id"),
            {"id": data["id"]},
        )
    ).scalar_one()
    assert last_used is None


async def test_minting_requires_write_access_to_the_dataset(
    client: AsyncClient, owner, datasets, admin_auth_header, test_db_session
):
    bound = datasets[0]
    peer_headers, _ = await create_user(client, admin_auth_header, "editor")
    body = {"name": "Not mine", "expires_at": _in_days(30)}

    # A private dataset the caller cannot see is a 404, not a 403.
    resp = await client.post(
        f"/datasets/{bound.id}/api-keys", json=body, headers=peer_headers
    )
    assert resp.status_code == 404, resp.text

    await test_db_session.execute(
        text("UPDATE catalog.records SET visibility = 'public' WHERE id = :id"),
        {"id": bound.record_id},
    )
    await test_db_session.commit()
    resp = await client.post(
        f"/datasets/{bound.id}/api-keys", json=body, headers=peer_headers
    )
    assert resp.status_code == 403, resp.text
    resp = await client.get(f"/datasets/{bound.id}/api-keys", headers=peer_headers)
    assert resp.status_code == 403, resp.text

    # An admin may write any dataset, so may mint for it.
    await _mint(client, admin_auth_header, bound.id)

    count = (
        await test_db_session.execute(
            text("SELECT count(*) FROM catalog.api_keys WHERE dataset_id = :id"),
            {"id": bound.id},
        )
    ).scalar_one()
    assert count == 1


async def test_a_dataset_key_cannot_be_minted_with_an_api_key(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    bound = datasets[0]
    full = await client.post("/auth/api-keys/", json={"name": "Full"}, headers=headers)
    assert full.status_code == 201, full.text
    resp = await client.post(
        f"/datasets/{bound.id}/api-keys",
        json={"name": "Child", "expires_at": _in_days(30)},
        headers={**headers, "X-Api-Key": full.json()["key"]},
    )
    assert resp.status_code == 403, resp.text


async def test_the_mint_request_is_validated(client: AsyncClient, owner, datasets):
    headers, _ = owner
    bound = datasets[0]
    for body in (
        {"name": "No expiry"},
        {"name": "Too long", "expires_at": _in_days(366)},
        {"name": "Past", "expires_at": _in_days(-1)},
    ):
        resp = await client.post(
            f"/datasets/{bound.id}/api-keys", json=body, headers=headers
        )
        assert resp.status_code == 422, (body, resp.text)

    # The generic mint endpoint offers no way to bind a key to a dataset.
    resp = await client.post(
        "/auth/api-keys/",
        json={"name": "Sneaky", "scope": "dataset_write"},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


async def test_a_raster_dataset_cannot_have_a_dataset_key(
    client: AsyncClient, owner, test_db_session
):
    from tests.factories import create_raster_dataset

    headers, owner_id = owner
    raster = await create_raster_dataset(test_db_session, created_by=owner_id)
    resp = await client.post(
        f"/datasets/{raster.id}/api-keys",
        json={"name": "Raster", "expires_at": _in_days(30)},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


async def test_the_key_stops_writing_when_its_user_loses_edit_rights(
    client: AsyncClient, owner, datasets, test_db_session
):
    headers, _ = owner
    bound = datasets[0]
    key = {"X-Api-Key": (await _mint(client, headers, bound.id))["key"]}
    admin_id = await get_user_id(test_db_session, "admin")

    await test_db_session.execute(
        text(
            "UPDATE catalog.records SET created_by = :admin, visibility = 'public' "
            "WHERE id = :id"
        ),
        {"admin": admin_id, "id": bound.record_id},
    )
    await test_db_session.commit()

    resp = await client.post(
        f"/datasets/{bound.id}/features/",
        json={"geometry": POINT, "properties": {}},
        headers=key,
    )
    assert resp.status_code == 403, resp.text
    # Reading a public dataset is still within what the user may do.
    resp = await client.get(f"/collections/{bound.id}/items", headers=key)
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize(
    "revoke",
    [
        pytest.param(
            "UPDATE catalog.api_keys SET expires_at = now() - interval '1 second' "
            "WHERE id = :key",
            id="expired",
        ),
        pytest.param(
            "UPDATE catalog.users SET key_epoch = key_epoch + 1 WHERE id = :user",
            id="key-epoch-bumped",
        ),
        pytest.param(
            "UPDATE catalog.api_keys SET is_active = false WHERE id = :key",
            id="revoked",
        ),
    ],
)
async def test_expiry_epoch_and_revocation_still_stop_the_key(
    client: AsyncClient, owner, datasets, test_db_session, revoke
):
    headers, owner_id = owner
    bound = datasets[0]
    data = await _mint(client, headers, bound.id)
    url = f"/collections/{bound.id}/items"
    assert (
        await client.get(url, headers={"X-Api-Key": data["key"]})
    ).status_code == 200

    await test_db_session.execute(text(revoke), {"key": data["id"], "user": owner_id})
    await test_db_session.commit()
    await _assert_refused_like_an_invalid_key(client, "GET", url, data["key"])


async def test_revoking_through_the_generic_endpoint_stops_the_key(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    bound = datasets[0]
    data = await _mint(client, headers, bound.id)
    resp = await client.delete(f"/auth/api-keys/{data['id']}", headers=headers)
    assert resp.status_code == 204, resp.text
    listed = await client.get(f"/datasets/{bound.id}/api-keys", headers=headers)
    assert listed.json() == {"items": [], "total": 0}
    await _assert_refused_like_an_invalid_key(
        client, "GET", f"/collections/{bound.id}/items", data["key"]
    )


async def test_listings_show_the_bound_dataset(
    client: AsyncClient, owner, datasets, admin_auth_header
):
    headers, _ = owner
    bound, other = datasets
    data = await _mint(client, headers, bound.id)
    await _mint(client, headers, other.id)

    listed = (
        await client.get(f"/datasets/{bound.id}/api-keys", headers=headers)
    ).json()
    assert [item["id"] for item in listed["items"]] == [data["id"]]
    assert listed["items"][0]["dataset_id"] == str(bound.id)

    mine = (await client.get("/auth/api-keys/", headers=headers)).json()["items"]
    assert {(k["id"], k["scope"], k["dataset_id"]) for k in mine} >= {
        (data["id"], "dataset_write", str(bound.id))
    }
    admin = (await client.get("/admin/api-keys/", headers=admin_auth_header)).json()[
        "items"
    ]
    assert {(k["id"], k["scope"], k["dataset_id"]) for k in admin} >= {
        (data["id"], "dataset_write", str(bound.id))
    }


async def test_deleting_the_dataset_deletes_its_keys(
    client: AsyncClient, owner, datasets, test_db_session
):
    headers, _ = owner
    bound = datasets[0]
    data = await _mint(client, headers, bound.id)
    await test_db_session.execute(
        text("DELETE FROM catalog.datasets WHERE id = :id"), {"id": bound.id}
    )
    await test_db_session.commit()
    remaining = (
        await test_db_session.execute(
            text("SELECT count(*) FROM catalog.api_keys WHERE id = :id"),
            {"id": data["id"]},
        )
    ).scalar_one()
    assert remaining == 0


async def _editing_off(monkeypatch) -> None:
    import app.core.persistent_config as pc

    class _AlwaysOff:
        async def get(self, _db):
            return False

    monkeypatch.setattr(pc, "ENABLE_DATASET_EDITING", _AlwaysOff())


async def test_a_dataset_key_writes_while_site_wide_editing_is_off(
    client: AsyncClient, owner, datasets, monkeypatch
):
    headers, _ = owner
    bound = datasets[0]
    dataset_key = (await _mint(client, headers, bound.id))["key"]
    full = await client.post("/auth/api-keys/", json={"name": "Full"}, headers=headers)
    assert full.status_code == 201, full.text
    await _editing_off(monkeypatch)

    body = {"geometry": POINT, "properties": {"name": "webhook"}}
    url = f"/datasets/{bound.id}/features/"
    resp = await client.post(url, json=body, headers={"X-Api-Key": dataset_key})
    assert resp.status_code == 201, resp.text
    gid = resp.json()["id"]
    resp = await client.patch(
        f"/datasets/{bound.id}/features/{gid}",
        json={"properties": {"name": "edited"}},
        headers={"X-Api-Key": dataset_key},
    )
    assert resp.status_code == 200, resp.text

    for caller in ({"X-Api-Key": full.json()["key"]}, headers):
        resp = await client.post(url, json=body, headers=caller)
        assert resp.status_code == 403, resp.text
        assert "disabled by the administrator" in resp.json()["detail"]


async def test_writes_through_a_key_are_attributed_to_it(
    client: AsyncClient, owner, datasets, test_db_session
):
    from sqlalchemy import select

    from app.modules.audit.models import AuditLog

    headers, _ = owner
    bound = datasets[0]
    data = await _mint(client, headers, bound.id)
    body = {"geometry": POINT, "properties": {"name": "x"}}
    url = f"/datasets/{bound.id}/features/"
    by_key = await client.post(url, json=body, headers={"X-Api-Key": data["key"]})
    by_session = await client.post(url, json=body, headers=headers)
    assert (by_key.status_code, by_session.status_code) == (201, 201)

    await test_db_session.commit()
    rows = (
        (
            await test_db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "feature.insert",
                    AuditLog.resource_id == bound.id,
                )
            )
        )
        .scalars()
        .all()
    )
    by_gid = {row.details["gid"]: row.details for row in rows}
    assert by_gid[by_key.json()["id"]]["api_key_id"] == data["id"]
    assert "api_key_id" not in by_gid[by_session.json()["id"]]


def _collection(*names: str) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": POINT, "properties": {"name": n}}
            for n in names
        ],
    }


async def test_a_dataset_key_bulk_inserts_with_editing_off_and_is_attributed(
    client: AsyncClient, owner, datasets, test_db_session, monkeypatch
):
    from sqlalchemy import select

    from app.modules.audit.models import AuditLog

    headers, _ = owner
    bound = datasets[0]
    data = await _mint(client, headers, bound.id)
    await _editing_off(monkeypatch)

    resp = await client.post(
        f"/datasets/{bound.id}/features/",
        json=_collection("a", "b"),
        headers={"X-Api-Key": data["key"]},
    )
    assert resp.status_code == 201, resp.text
    assert len(resp.json()["features"]) == 2

    await test_db_session.commit()
    row = (
        await test_db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "feature.bulk_insert",
                AuditLog.resource_id == bound.id,
            )
        )
    ).scalar_one()
    assert row.details["api_key_id"] == data["id"]
    assert row.details["count"] == 2

    # A session caller is still held to the switch on the same path.
    resp = await client.post(
        f"/datasets/{bound.id}/features/", json=_collection("c"), headers=headers
    )
    assert resp.status_code == 403, resp.text


async def test_a_bulk_insert_into_another_dataset_is_refused(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    bound, other = datasets
    raw_key = (await _mint(client, headers, bound.id))["key"]
    await _assert_refused_like_an_invalid_key(
        client,
        "POST",
        f"/datasets/{other.id}/features/",
        raw_key,
        json=_collection("x"),
    )


async def test_the_owner_sees_and_revokes_every_key_on_the_dataset(
    client: AsyncClient, owner, datasets, admin_auth_header
):
    headers, owner_id = owner
    bound = datasets[0]
    own = await _mint(client, headers, bound.id)
    admins = await _mint(client, admin_auth_header, bound.id)

    listed = (
        await client.get(f"/datasets/{bound.id}/api-keys", headers=headers)
    ).json()
    creators = {item["id"]: item for item in listed["items"]}
    assert set(creators) == {own["id"], admins["id"]}
    assert creators[own["id"]]["user_id"] == str(owner_id)
    assert creators[admins["id"]]["username"] == settings.geolens_admin_username

    resp = await client.delete(
        f"/datasets/{bound.id}/api-keys/{admins['id']}", headers=headers
    )
    assert resp.status_code == 204, resp.text
    await _assert_refused_like_an_invalid_key(
        client, "GET", f"/collections/{bound.id}/items", admins["key"]
    )
    resp = await client.delete(
        f"/datasets/{bound.id}/api-keys/{admins['id']}", headers=headers
    )
    assert resp.status_code == 404, resp.text


async def test_who_may_revoke_through_the_dataset(
    client: AsyncClient, owner, datasets, admin_auth_header, test_db_session
):
    headers, _ = owner
    bound, other = datasets
    data = await _mint(client, headers, bound.id)
    peer_headers, _ = await create_user(client, admin_auth_header, "editor")
    admin_id = await get_user_id(test_db_session, "admin")
    await test_db_session.execute(
        text(
            "UPDATE catalog.records SET created_by = :admin, visibility = 'public' "
            "WHERE id = :id"
        ),
        {"admin": admin_id, "id": bound.record_id},
    )
    await test_db_session.commit()

    # Someone who neither made the key nor may write the dataset cannot.
    url = f"/datasets/{bound.id}/api-keys/{data['id']}"
    resp = await client.delete(url, headers=peer_headers)
    assert resp.status_code == 403, resp.text
    # A key is revoked only through the dataset it is bound to.
    resp = await client.delete(
        f"/datasets/{other.id}/api-keys/{data['id']}", headers=headers
    )
    assert resp.status_code == 404, resp.text
    # Its creator still can after losing write access to the dataset.
    resp = await client.delete(url, headers=headers)
    assert resp.status_code == 204, resp.text


async def test_a_refused_dataset_key_falls_back_to_a_bearer_like_an_invalid_key(
    client: AsyncClient, owner, datasets, admin_auth_header
):
    headers, _ = owner
    raw_key = (await _mint(client, headers, datasets[0].id))["key"]
    admin = (await client.get("/auth/me/", headers=admin_auth_header)).json()["id"]
    for key in (raw_key, "not-a-real-key"):
        resp = await client.get(
            "/auth/me/", headers={**admin_auth_header, "X-Api-Key": key}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == admin


async def test_the_query_lane_reads_but_never_writes(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    bound = datasets[0]
    raw_key = (await _mint(client, headers, bound.id))["key"]
    resp = await client.get(f"/collections/{bound.id}/items?api_key={raw_key}")
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"/datasets/{bound.id}/features/?api_key={raw_key}",
        json={"geometry": POINT, "properties": {}},
    )
    assert resp.status_code == 401, resp.text


async def test_other_feature_routes_of_another_dataset_are_refused(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    bound, other = datasets
    raw_key = (await _mint(client, headers, bound.id))["key"]
    write = {"json": {"geometry": POINT, "properties": {}}}
    for method, url, kwargs in (
        ("GET", f"/datasets/{other.id}/features.geojson", {}),
        ("PUT", f"/datasets/{other.id}/features/1", write),
        ("PATCH", f"/datasets/{other.id}/features/1", {"json": {"properties": {}}}),
    ):
        await _assert_refused_like_an_invalid_key(
            client, method, url, raw_key, **kwargs
        )


@pytest.mark.parametrize(
    "status_sql",
    [
        pytest.param("status = 'suspended', is_active = false", id="suspended"),
        pytest.param("status = 'deactivated', is_active = false", id="deactivated"),
    ],
)
async def test_the_key_stops_when_its_user_is_not_active(
    client: AsyncClient, owner, datasets, test_db_session, status_sql
):
    headers, owner_id = owner
    bound = datasets[0]
    raw_key = (await _mint(client, headers, bound.id))["key"]
    await test_db_session.execute(
        text(f"UPDATE catalog.users SET {status_sql} WHERE id = :id"),
        {"id": owner_id},
    )
    await test_db_session.commit()
    await _assert_refused_like_an_invalid_key(
        client, "GET", f"/collections/{bound.id}/items", raw_key
    )


async def test_minting_is_rate_limited(client: AsyncClient, owner, datasets):
    from app.platform.ratelimit import limiter

    headers, _ = owner
    bound = datasets[0]
    body = {"name": "Burst", "expires_at": _in_days(30)}
    original = limiter.enabled
    limiter.enabled = True
    limiter._storage.reset()
    try:
        codes = [
            (
                await client.post(
                    f"/datasets/{bound.id}/api-keys", json=body, headers=headers
                )
            ).status_code
            for _ in range(31)
        ]
    finally:
        limiter.enabled = original
        limiter._storage.reset()
    assert codes[:30] == [201] * 30
    assert codes[30] == 429


def _mounted_route_pairs() -> set[tuple[str, str]]:
    from fastapi.routing import APIRoute, iter_route_contexts

    from app.api.main import app

    return {
        (method, ctx.path)
        for ctx in iter_route_contexts(app.routes)
        if isinstance(ctx.route, APIRoute)
        for method in (ctx.route.methods or set())
    }


def test_every_allowed_route_is_mounted_and_names_its_dataset():
    mounted = _mounted_route_pairs()
    assert _DATASET_KEY_ROUTES <= mounted, _DATASET_KEY_ROUTES - mounted
    for _, template in _DATASET_KEY_ROUTES:
        assert "{dataset_id}" in template


def test_every_feature_route_is_classified():
    """A new feature route has to be added to the allowlist or listed here as refused."""
    refused_on_purpose = {
        # Answers with features of the related dataset, which is not the key's.
        ("GET", "/datasets/{dataset_id}/features/{gid}/related/{relationship_id}"),
        ("GET", "/datasets/{dataset_id}/features/{gid}/related/{relationship_id}/"),
        # The standards layer serves HEAD on items; a key client has no use for it.
        ("HEAD", "/collections/{dataset_id}/items"),
        ("HEAD", "/collections/{dataset_id}/items/"),
        ("HEAD", "/collections/{dataset_id}/items/{feature_id}"),
    }
    feature_routes = {
        (method, path)
        for method, path in _mounted_route_pairs()
        if path.startswith(
            ("/datasets/{dataset_id}/features", "/collections/{dataset_id}/items")
        )
    }
    assert feature_routes - refused_on_purpose == set(_DATASET_KEY_ROUTES)
