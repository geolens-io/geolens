"""A non-public vector tile is served to a caller with access by API key or bearer, never shared-cached."""

import gzip
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from structlog.testing import capture_logs

from app.core.config import settings
from app.core.tile_scope import tile_signature_scope
from app.modules.auth.models import Role, UserRole
from app.modules.catalog.datasets.domain.models import DatasetGrant
from app.processing.tiles import router as tile_router
from app.processing.tiles.signing import generate_tile_signature
from tests.factories import create_dataset, create_user, get_user_id
from tests.test_tiles import _cleanup_data_table, _create_data_table

pytestmark = pytest.mark.usefixtures("_init_tile_pool_for_tests")

_COLUMNS = [
    {"name": "gid", "type": "integer"},
    {"name": "name", "type": "text"},
    {"name": "value", "type": "integer"},
    {"name": "geom", "type": "geometry"},
    {"name": "geom_4326", "type": "geometry"},
]
_VARY = ("authorization", "x-api-key", "x-embed-token")


def _vector(table: str, z: int = 0, x: int = 0, y: int = 0) -> str:
    return f"/tiles/data.{table}/{z}/{x}/{y}.pbf"


def _cluster(table: str) -> str:
    return f"/tiles/clusters/data.{table}/0/0/0.pbf"


def _assert_private(resp) -> None:
    cache_control = resp.headers["cache-control"]
    assert cache_control.startswith("private"), cache_control
    assert "public" not in cache_control and "s-maxage" not in cache_control
    vary = {v.strip().lower() for v in resp.headers.get("vary", "").split(",")}
    assert set(_VARY) <= vary, resp.headers.get("vary")


@pytest.fixture
async def people(client: AsyncClient, admin_auth_header: dict):
    """An owner and a stranger, both editors."""
    _, owner_id = await create_user(client, admin_auth_header, "editor")
    _, stranger_id = await create_user(client, admin_auth_header, "editor")
    return uuid.UUID(owner_id), uuid.UUID(stranger_id)


@pytest.fixture
def mint_key(client: AsyncClient, admin_auth_header: dict):
    async def mint(user_id: uuid.UUID, scope: str = "full") -> tuple[str, str]:
        resp = await client.post(
            "/admin/api-keys/",
            json={"user_id": str(user_id), "name": "tile reader", "scope": scope},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        return body["key"], body["id"]

    return mint


@pytest.fixture
async def make_tiles(test_db_session):
    """Commit a point dataset with a real data table, dropped afterwards."""
    tables: list[str] = []

    async def make(
        owner_id: uuid.UUID,
        *,
        visibility: str = "private",
        record_status: str = "published",
    ):
        table = f"vt_key_{uuid.uuid4().hex[:8]}"
        tables.append(table)
        dataset = await create_dataset(
            test_db_session,
            created_by=owner_id,
            table_name=table,
            visibility=visibility,
            record_status=record_status,
            geometry_type="Point",
            feature_count=1,
            column_info=_COLUMNS,
        )
        await _create_data_table(test_db_session, table)
        return dataset

    yield make
    await test_db_session.rollback()
    for table in tables:
        await _cleanup_data_table(test_db_session, table)


@pytest.fixture
async def grant_holder(client: AsyncClient, admin_auth_header: dict, test_db_session):
    """A user holding a role of their own, which is removed afterwards."""
    _, user_id = await create_user(client, admin_auth_header, "viewer")
    role = Role(name=f"vt-grant-{uuid.uuid4().hex[:8]}")
    test_db_session.add(role)
    await test_db_session.flush()
    test_db_session.add(UserRole(user_id=uuid.UUID(user_id), role_id=role.id))
    role_id = role.id
    await test_db_session.commit()
    yield uuid.UUID(user_id), role_id
    await test_db_session.rollback()
    await test_db_session.execute(
        text("DELETE FROM catalog.roles WHERE id = :id"), {"id": role_id}
    )
    await test_db_session.commit()


async def test_owner_key_opens_private_vector_and_cluster_tiles_by_header(
    client: AsyncClient, people, mint_key, make_tiles
) -> None:
    """The owner's key in X-Api-Key serves MVT bytes on the vector and cluster routes."""
    owner_id, _ = people
    key, _ = await mint_key(owner_id)
    dataset = await make_tiles(owner_id)

    vector = await client.get(_vector(dataset.table_name), headers={"X-Api-Key": key})
    cluster = await client.get(_cluster(dataset.table_name), headers={"X-Api-Key": key})

    assert vector.status_code == 200, vector.text
    assert vector.headers["content-type"] == "application/vnd.mapbox-vector-tile"
    assert vector.content
    assert cluster.status_code == 200, cluster.text


@pytest.mark.parametrize("scope", ["full", "read_only"])
async def test_owner_key_opens_private_tiles_by_query_or_header(
    client: AsyncClient, people, mint_key, make_tiles, scope: str
) -> None:
    """Full and read-only keys both serve a private tile as ?api_key= or as a header."""
    owner_id, _ = people
    key, _ = await mint_key(owner_id, scope)
    dataset = await make_tiles(owner_id)

    by_query = await client.get(_vector(dataset.table_name), params={"api_key": key})
    by_header = await client.get(
        _vector(dataset.table_name), headers={"X-Api-Key": key}
    )

    assert by_query.status_code == by_header.status_code == 200, by_query.text
    assert by_query.content == by_header.content


async def test_bearer_token_opens_a_private_tile(
    client: AsyncClient, admin_auth_header: dict, make_tiles, test_db_session
) -> None:
    """A signed-in session's bearer token is an identity like any other."""
    admin_id = await get_user_id(test_db_session, settings.geolens_admin_username)
    dataset = await make_tiles(admin_id)

    resp = await client.get(_vector(dataset.table_name), headers=admin_auth_header)

    assert resp.status_code == 200, resp.text
    _assert_private(resp)


async def test_a_key_without_access_gets_the_unknown_table_404(
    client: AsyncClient, people, mint_key, make_tiles
) -> None:
    """A stranger's key gets the same 404 body for a private tile as for no table at all."""
    owner_id, stranger_id = people
    key, _ = await mint_key(stranger_id)
    dataset = await make_tiles(owner_id)

    private = await client.get(_vector(dataset.table_name), headers={"X-Api-Key": key})
    cluster = await client.get(_cluster(dataset.table_name), params={"api_key": key})
    missing = await client.get(
        _vector(f"no_such_{uuid.uuid4().hex[:8]}"), headers={"X-Api-Key": key}
    )

    assert private.status_code == cluster.status_code == missing.status_code == 404
    assert private.json() == cluster.json() == missing.json()


async def test_restricted_tiles_follow_grants(
    client: AsyncClient,
    people,
    mint_key,
    make_tiles,
    grant_holder,
    test_db_session,
) -> None:
    """A restricted dataset serves a grant holder's key and 404s a key without the grant."""
    owner_id, stranger_id = people
    holder_id, role_id = grant_holder
    dataset = await make_tiles(owner_id, visibility="restricted")
    test_db_session.add(DatasetGrant(dataset_id=dataset.id, role_id=role_id))
    await test_db_session.commit()
    holder_key, _ = await mint_key(holder_id)
    stranger_key, _ = await mint_key(stranger_id)

    held = await client.get(
        _vector(dataset.table_name), headers={"X-Api-Key": holder_key}
    )
    refused = await client.get(
        _vector(dataset.table_name), headers={"X-Api-Key": stranger_key}
    )

    assert held.status_code == 200, held.text
    assert refused.status_code == 404


async def test_private_draft_serves_owner_and_admin_keys_only(
    client: AsyncClient, people, mint_key, make_tiles, test_db_session
) -> None:
    """An unpublished private dataset serves its owner's and an admin's key, nobody else's."""
    owner_id, stranger_id = people
    admin_id = await get_user_id(test_db_session, settings.geolens_admin_username)
    dataset = await make_tiles(owner_id, record_status="draft")
    owner_key, _ = await mint_key(owner_id)
    admin_key, _ = await mint_key(admin_id)
    stranger_key, _ = await mint_key(stranger_id)

    statuses = [
        (
            await client.get(_vector(dataset.table_name), headers={"X-Api-Key": k})
        ).status_code
        for k in (owner_key, admin_key, stranger_key)
    ]

    assert statuses == [200, 200, 404]


async def test_a_warm_byte_cache_never_answers_before_authorization(
    client: AsyncClient, people, mint_key, make_tiles, monkeypatch
) -> None:
    """Once the owner has warmed a tile, a stranger's key still gets 404 and never reads the cache."""
    owner_id, stranger_id = people
    owner_key, _ = await mint_key(owner_id)
    stranger_key, _ = await mint_key(stranger_id)
    dataset = await make_tiles(owner_id)
    cache = SimpleNamespace(
        get=AsyncMock(return_value=gzip.compress(b"warm-mvt")), set=AsyncMock()
    )
    monkeypatch.setattr(tile_router, "get_tile_cache", lambda: cache)

    for path in (_vector(dataset.table_name), _cluster(dataset.table_name)):
        cache.get.reset_mock()
        warm = await client.get(path, headers={"X-Api-Key": owner_key})
        stranger = await client.get(path, headers={"X-Api-Key": stranger_key})

        assert warm.status_code == 200, warm.text
        assert stranger.status_code == 404
        assert cache.get.await_count == 1


@pytest.mark.parametrize("on_public", [False, True])
async def test_an_unresolvable_key_is_401_never_anonymous(
    client: AsyncClient, people, make_tiles, on_public: bool
) -> None:
    """A key that resolves to nobody is refused with 401 by header and by query."""
    owner_id, _ = people
    dataset = await make_tiles(
        owner_id, visibility="public" if on_public else "private"
    )
    bogus = f"gl_{uuid.uuid4().hex}"

    by_header = await client.get(
        _vector(dataset.table_name), headers={"X-Api-Key": bogus}
    )
    by_query = await client.get(_vector(dataset.table_name), params={"api_key": bogus})

    for resp in (by_header, by_query):
        assert resp.status_code == 401, resp.text
        assert resp.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("dead_by", ["revoked", "expired", "epoch_bumped"])
async def test_a_key_stops_opening_tiles_once_it_is_dead(
    client: AsyncClient,
    admin_auth_header: dict,
    people,
    mint_key,
    make_tiles,
    test_db_session,
    dead_by: str,
) -> None:
    """A key serves a private tile, then gets 401 once revoked, expired or epoch-stale."""
    owner_id, _ = people
    key, key_id = await mint_key(owner_id)
    dataset = await make_tiles(owner_id)
    path = _vector(dataset.table_name)

    before = await client.get(path, headers={"X-Api-Key": key})
    assert before.status_code == 200, before.text

    if dead_by == "revoked":
        revoked = await client.delete(
            f"/admin/api-keys/{key_id}", headers=admin_auth_header
        )
        assert revoked.status_code == 204, revoked.text
    elif dead_by == "expired":
        await test_db_session.execute(
            text(
                "UPDATE catalog.api_keys SET expires_at = now() - interval '1 minute' "
                "WHERE id = :id"
            ),
            {"id": uuid.UUID(key_id)},
        )
        await test_db_session.commit()
    else:
        await test_db_session.execute(
            text("UPDATE catalog.users SET key_epoch = key_epoch + 1 WHERE id = :id"),
            {"id": owner_id},
        )
        await test_db_session.commit()

    after = await client.get(path, headers={"X-Api-Key": key})
    assert after.status_code == 401, after.text


async def test_private_tile_responses_stay_private_and_vary_on_credentials(
    client: AsyncClient, people, mint_key, make_tiles, monkeypatch
) -> None:
    """200, 204 and 304 private responses are private with Vary, even under a hosted public override."""
    owner_id, _ = people
    key, _ = await mint_key(owner_id)
    dataset = await make_tiles(owner_id)
    monkeypatch.setattr(
        tile_router,
        "_get_tile_serving_controls",
        lambda _tid: (None, "public, max-age=60, s-maxage=600"),
    )

    full = await client.get(_vector(dataset.table_name), params={"api_key": key})
    empty = await client.get(
        _vector(dataset.table_name, 18, 100000, 100000), headers={"X-Api-Key": key}
    )
    unchanged = await client.get(
        _vector(dataset.table_name),
        headers={"X-Api-Key": key, "If-None-Match": full.headers["etag"]},
    )

    assert (full.status_code, empty.status_code, unchanged.status_code) == (
        200,
        204,
        304,
    )
    for resp in (full, empty, unchanged):
        _assert_private(resp)


async def test_public_tiles_stay_public_unless_the_key_is_in_the_query(
    client: AsyncClient, people, mint_key, make_tiles
) -> None:
    """A public tile is shared-cacheable anonymously or with a header key, never with ?api_key=."""
    owner_id, _ = people
    key, _ = await mint_key(owner_id)
    dataset = await make_tiles(owner_id, visibility="public")
    path = _vector(dataset.table_name)

    anonymous = await client.get(path)
    header_key = await client.get(path, headers={"X-Api-Key": key})
    query_key = await client.get(path, params={"api_key": key})
    upper_query_key = await client.get(path, params={"API_KEY": key})

    for resp in (anonymous, header_key):
        assert resp.status_code == 200, resp.text
        assert resp.headers["cache-control"].startswith("public, max-age=")
        vary = resp.headers.get("vary", "").lower()
        assert not any(name in vary for name in _VARY), vary
    for resp in (query_key, upper_query_key):
        assert resp.status_code == 200, resp.text
        _assert_private(resp)


async def test_no_key_reaches_the_logs(
    client: AsyncClient, people, mint_key, make_tiles
) -> None:
    """Neither a working query key nor an unresolvable one appears in any log event."""
    owner_id, _ = people
    key, _ = await mint_key(owner_id)
    dataset = await make_tiles(owner_id)
    bogus = f"gl_{uuid.uuid4().hex}"

    with capture_logs() as logs:
        served = await client.get(_vector(dataset.table_name), params={"api_key": key})
        refused = await client.get(
            _vector(dataset.table_name), params={"api_key": bogus}
        )

    assert (served.status_code, refused.status_code) == (200, 401)
    assert logs, "no log events were captured, so this proves nothing"
    captured = repr(logs)
    assert key not in captured
    assert bogus not in captured


async def test_capability_arms_keep_their_order(
    client: AsyncClient, people, mint_key, make_tiles
) -> None:
    """An aged-out signature falls through to the key, a bad embed token still decides alone."""
    owner_id, _ = people
    key, _ = await mint_key(owner_id)
    dataset = await make_tiles(owner_id)
    path = _vector(dataset.table_name)
    stale_scope = tile_signature_scope(dataset.table_name, 99)
    stale = {
        "sig": generate_tile_signature(stale_scope, int(time.time()) + 300),
        "exp": int(time.time()) + 300,
        "scope": stale_scope,
    }
    current_scope = tile_signature_scope(dataset.table_name, 0)
    expired = {
        "sig": generate_tile_signature(current_scope, int(time.time()) - 60),
        "exp": int(time.time()) - 60,
        "scope": current_scope,
    }

    stale_sig = await client.get(path, params=stale, headers={"X-Api-Key": key})
    expired_sig = await client.get(path, params=expired, headers={"X-Api-Key": key})
    bad_embed = await client.get(
        path, headers={"X-Api-Key": key, "X-Embed-Token": "et_not-a-real-token"}
    )
    anonymous = await client.get(path)

    assert stale_sig.status_code == expired_sig.status_code == 200, stale_sig.text
    _assert_private(stale_sig)
    assert bad_embed.status_code == 403
    assert anonymous.status_code == 403
    assert "Signature required" in anonymous.json()["detail"]
