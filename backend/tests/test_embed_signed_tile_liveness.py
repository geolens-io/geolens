"""Tile templates minted through an embed token stop working within a minute of it."""

import hashlib
import time
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text, update

from app.core.tile_scope import split_embed_binding, tile_signature_scope
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.embed_tokens.service import (
    EMBED_TOKEN_LIVENESS_TTL_SECONDS,
    _embed_token_cache_key,
    accepted_embed_token_id,
    create_embed_token,
    embed_token_still_admits,
    revoke_embed_token,
)
from app.platform.cache import provider as cache_provider
from app.platform.cache.provider import get_cache
from app.platform.cache.redis import RedisCacheProvider
from app.processing.raster.models import RasterAsset
from app.processing.tiles.signing import generate_tile_signature, round_expiry

from tests.factories import create_dataset, create_raster_dataset, get_user_id

pytestmark = pytest.mark.usefixtures("_init_tile_pool_for_tests")


@contextmanager
def _cache_clock_advanced(seconds: int):
    """Move the in-process cache stores' clock forward, nothing else's."""
    real = time.monotonic
    with patch(
        "app.platform.cache.memory.time",
        SimpleNamespace(monotonic=lambda: real() + seconds),
    ):
        yield


class _NoDatabase:
    async def execute(self, *args, **kwargs):
        raise AssertionError("liveness reached the database")


async def _make_private_vector(session, admin_id: uuid.UUID) -> Dataset:
    dataset = await create_dataset(
        session,
        created_by=admin_id,
        table_name=f"embed_live_{uuid.uuid4().hex[:10]}",
        geometry_type="Point",
        column_info=[
            {"name": "gid", "type": "integer"},
            {"name": "geom", "type": "geometry"},
        ],
    )
    await session.execute(
        text(
            f"CREATE TABLE data.{dataset.table_name} (gid SERIAL PRIMARY KEY, "
            "geom GEOMETRY(Point, 3857), geom_4326 GEOMETRY(Point, 4326))"
        )
    )
    await session.commit()
    return dataset


async def _embed_map(
    client: AsyncClient, headers: dict, session, dataset: Dataset, admin_id
) -> tuple[uuid.UUID, uuid.UUID, str]:
    """Publish a map holding ``dataset``, mint an embed token, then make it private."""
    map_id = (
        await client.post(
            "/maps/", json={"name": f"Embed {uuid.uuid4().hex[:6]}"}, headers=headers
        )
    ).json()["id"]
    resp = await client.post(
        f"/maps/{map_id}/layers", json={"dataset_id": str(dataset.id)}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    resp = await client.put(
        f"/maps/{map_id}", json={"visibility": "public"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(f"/maps/{map_id}/share/", headers=headers)
    assert resp.status_code in (200, 201), resp.text
    token, raw = await create_embed_token(session, uuid.UUID(map_id), admin_id)
    await session.commit()
    await session.execute(
        update(Record)
        .where(Record.id == dataset.record_id)
        .values(visibility="private")
    )
    await session.commit()
    return uuid.UUID(map_id), token.id, raw


async def _mint(client: AsyncClient, dataset: Dataset, **headers) -> dict:
    resp = await client.post(
        "/tiles/tokens/", json={"dataset_ids": [str(dataset.id)]}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    entry = resp.json()["tokens"][str(dataset.id)]
    assert "error" not in entry, entry
    return entry


def _tile_url(dataset: Dataset) -> str:
    return f"/tiles/data.{dataset.table_name}/0/0/0.pbf"


async def _drop(session, dataset: Dataset) -> None:
    await session.execute(text(f"DROP TABLE IF EXISTS data.{dataset.table_name}"))
    await session.commit()


async def test_vector_template_stops_within_the_liveness_ttl_after_revoke(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _make_private_vector(test_db_session, admin_id)
    try:
        map_id, token_id, raw = await _embed_map(
            client, admin_auth_header, test_db_session, dataset, admin_id
        )
        entry = await _mint(client, dataset, **{"X-Embed-Token": raw})
        unbound, bound_to = split_embed_binding(entry["scope"])
        assert bound_to == token_id
        assert unbound == tile_signature_scope(
            dataset.table_name, dataset.publication_version
        )
        params = {k: entry[k] for k in ("sig", "exp", "scope")}

        assert (await client.get(_tile_url(dataset), params=params)).status_code in (
            200,
            204,
        )
        # Answered from the cache, with no database read.
        assert await embed_token_still_admits(_NoDatabase(), token_id, dataset.id)

        await revoke_embed_token(test_db_session, token_id, map_id)
        await test_db_session.commit()
        # Inside the bound the cached answer still serves.
        assert (await client.get(_tile_url(dataset), params=params)).status_code in (
            200,
            204,
        )
        with _cache_clock_advanced(EMBED_TOKEN_LIVENESS_TTL_SECONDS + 1):
            resp = await client.get(_tile_url(dataset), params=params)
        assert resp.status_code == 403, resp.text
    finally:
        await _drop(test_db_session, dataset)


async def test_binding_cannot_be_stripped_from_a_signed_scope(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _make_private_vector(test_db_session, admin_id)
    try:
        _, _, raw = await _embed_map(
            client, admin_auth_header, test_db_session, dataset, admin_id
        )
        entry = await _mint(client, dataset, **{"X-Embed-Token": raw})
        unbound, _ = split_embed_binding(entry["scope"])
        resp = await client.get(
            _tile_url(dataset),
            params={"sig": entry["sig"], "exp": entry["exp"], "scope": unbound},
        )
        assert resp.status_code == 403
    finally:
        await _drop(test_db_session, dataset)


async def test_previous_release_template_without_a_binding_still_verifies(
    client: AsyncClient, test_db_session
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _make_private_vector(test_db_session, admin_id)
    try:
        await test_db_session.execute(
            update(Record)
            .where(Record.id == dataset.record_id)
            .values(visibility="private")
        )
        await test_db_session.commit()
        scope = tile_signature_scope(dataset.table_name, dataset.publication_version)
        exp = round_expiry()
        resp = await client.get(
            _tile_url(dataset),
            params={
                "sig": generate_tile_signature(scope, exp),
                "exp": exp,
                "scope": scope,
            },
        )
        assert resp.status_code in (200, 204), resp.text
    finally:
        await _drop(test_db_session, dataset)


async def test_signed_in_minter_gets_an_unbound_template(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _make_private_vector(test_db_session, admin_id)
    try:
        _, _, raw = await _embed_map(
            client, admin_auth_header, test_db_session, dataset, admin_id
        )
        entry = await _mint(
            client, dataset, **admin_auth_header, **{"X-Embed-Token": raw}
        )
        assert entry["scope"] == tile_signature_scope(
            dataset.table_name, dataset.publication_version
        )
        single = await client.get(
            f"/tiles/token/{dataset.id}/", headers=admin_auth_header
        )
        assert single.json()["scope"] == entry["scope"]
    finally:
        await _drop(test_db_session, dataset)


async def test_raster_template_stops_within_the_liveness_ttl_after_revoke(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_raster_dataset(
        test_db_session,
        created_by=admin_id,
        table_name=f"embed_live_r_{uuid.uuid4().hex[:8]}",
    )
    test_db_session.add(
        RasterAsset(
            dataset_id=dataset.id,
            asset_uri=f"rasters/{dataset.id}/a/source.cog.tif",
            storage_backend="local",
        )
    )
    await test_db_session.commit()
    map_id, token_id, raw = await _embed_map(
        client, admin_auth_header, test_db_session, dataset, admin_id
    )
    entry = await _mint(client, dataset, **{"X-Embed-Token": raw})
    assert entry["kind"] == "raster"
    assert split_embed_binding(entry["scope"])[1] == token_id
    params = {"dataset_id": str(dataset.id)} | {
        k: entry[k] for k in ("sig", "exp", "scope")
    }

    assert (
        await client.get("/tiles/raster-auth-check/", params=params)
    ).status_code == 200
    await revoke_embed_token(test_db_session, token_id, map_id)
    await test_db_session.commit()
    with _cache_clock_advanced(EMBED_TOKEN_LIVENESS_TTL_SECONDS + 1):
        resp = await client.get("/tiles/raster-auth-check/", params=params)
    assert resp.status_code == 403, resp.text


async def test_cache_outage_refuses_a_revoked_token_after_the_process_ttl(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch: pytest.MonkeyPatch,
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _make_private_vector(test_db_session, admin_id)
    try:
        map_id, token_id, raw = await _embed_map(
            client, admin_auth_header, test_db_session, dataset, admin_id
        )
        down = RedisCacheProvider(url="redis://cache.example.invalid:6379/0")
        down._failure_count = down._max_failures
        down._circuit_open_until = time.monotonic() + 3600
        monkeypatch.setattr(cache_provider, "_cache_provider", down)

        entry = await _mint(client, dataset, **{"X-Embed-Token": raw})
        params = {k: entry[k] for k in ("sig", "exp", "scope")}
        assert (await client.get(_tile_url(dataset), params=params)).status_code in (
            200,
            204,
        )
        # The per-process store answers while the shared one is unreachable.
        assert await embed_token_still_admits(_NoDatabase(), token_id, dataset.id)

        await revoke_embed_token(test_db_session, token_id, map_id)
        await test_db_session.commit()
        with _cache_clock_advanced(EMBED_TOKEN_LIVENESS_TTL_SECONDS + 1):
            resp = await client.get(_tile_url(dataset), params=params)
        assert resp.status_code == 403, resp.text
    finally:
        await _drop(test_db_session, dataset)


async def test_validation_entry_without_a_token_id_is_read_again(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(test_db_session, created_by=admin_id)
    _, token_id, raw = await _embed_map(
        client, admin_auth_header, test_db_session, dataset, admin_id
    )
    assert await accepted_embed_token_id(raw, dataset.id, test_db_session) == token_id
    key = _embed_token_cache_key(hashlib.sha256(raw.encode()).hexdigest())
    cache = get_cache()
    entry = await cache.get(key, security=True)
    entry.pop("token_id")
    await cache.set(key, entry, ttl=60, security=True)

    assert await accepted_embed_token_id(raw, dataset.id, test_db_session) == token_id
