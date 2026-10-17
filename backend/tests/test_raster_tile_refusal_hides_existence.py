"""A raster tile or tile token refused to a caller who cannot see the dataset reads as a missing one."""

import time
import uuid

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.tile_scope import tile_signature_scope
from app.processing.tiles.signing import generate_tile_signature
from tests.factories import create_dataset, create_raster_dataset, get_user_id
from tests.test_vector_tile_identity_2543 import mint_key, people  # noqa: F401


def _tile_url(dataset_id) -> str:
    return f"/tiles/raster-proxy/{dataset_id}/0/0/0.png"


def _signed(dataset_id, *, publication_version: int = 0, exp_offset: int = 300):
    exp = int(time.time()) + exp_offset
    scope = tile_signature_scope(str(dataset_id), publication_version)
    return {"sig": generate_tile_signature(scope, exp), "exp": exp, "scope": scope}


def _answer(resp) -> tuple[int, object, str | None]:
    return resp.status_code, resp.json(), resp.headers.get("www-authenticate")


@pytest.fixture
async def unseen_ids(test_db_session):
    """A private raster, a public raster draft, a private vector and an unused id."""
    owner = await get_user_id(test_db_session, settings.geolens_admin_username)
    private = await create_raster_dataset(
        test_db_session,
        created_by=owner,
        visibility="private",
        create_raster_asset=True,
    )
    draft = await create_raster_dataset(
        test_db_session,
        created_by=owner,
        record_status="draft",
        create_raster_asset=True,
    )
    private_vector = await create_dataset(
        test_db_session, created_by=owner, visibility="private"
    )
    return private.id, draft.id, private_vector.id, uuid.uuid4()


@pytest.mark.parametrize(
    ("shape", "expected_status"),
    [
        ("bare", 404),
        ("wrong_scope", 403),
        ("current_scope_expired", 403),
        ("forged_sig", 403),
        ("embed_token", 403),
    ],
)
async def test_anonymous_raster_refusals_match_a_missing_dataset(
    client: AsyncClient, unseen_ids, shape: str, expected_status: int
) -> None:
    *unseen, missing = unseen_ids

    def request_for(dataset_id) -> dict:
        if shape == "bare":
            return {}
        if shape == "wrong_scope":
            return {"params": _signed(dataset_id, publication_version=7)}
        if shape == "current_scope_expired":
            return {"params": _signed(dataset_id, exp_offset=-60)}
        if shape == "forged_sig":
            return {"params": {**_signed(dataset_id), "sig": "0" * 64}}
        return {"headers": {"X-Embed-Token": "et_not-a-real-token"}}

    answers = {
        dataset_id: _answer(
            await client.get(_tile_url(dataset_id), **request_for(dataset_id))
        )
        for dataset_id in (*unseen, missing)
    }

    assert all(answer == answers[missing] for answer in answers.values()), answers
    assert answers[missing][0] == expected_status, answers


async def test_anonymous_tile_token_refusals_match_a_missing_dataset(
    client: AsyncClient, unseen_ids
) -> None:
    *unseen, missing = unseen_ids

    single = {
        dataset_id: _answer(await client.get(f"/tiles/token/{dataset_id}/"))
        for dataset_id in (*unseen, missing)
    }
    batch = await client.post(
        "/tiles/tokens/",
        json={"dataset_ids": [str(dataset_id) for dataset_id in (*unseen, missing)]},
    )

    assert all(answer == single[missing] for answer in single.values()), single
    assert single[missing][0] == 404, single
    assert batch.status_code == 200, batch.text
    errors = batch.json()["tokens"]
    assert all(entry == errors[str(missing)] for entry in errors.values()), errors
    assert errors[str(missing)] == {"error": "Dataset not found"}, errors


async def test_a_stranger_with_a_key_is_still_refused_with_404(
    client: AsyncClient,
    unseen_ids,
    people,  # noqa: F811
    mint_key,  # noqa: F811
) -> None:
    private, _, _, missing = unseen_ids
    _, stranger_id = people
    key, _ = await mint_key(stranger_id)
    headers = {"X-Api-Key": key}

    for dataset_id in (private, missing):
        tile = await client.get(_tile_url(dataset_id), headers=headers)
        token = await client.get(f"/tiles/token/{dataset_id}/", headers=headers)
        assert tile.status_code == 404, tile.text
        assert token.status_code == 404, token.text


async def test_the_owner_still_gets_a_raster_token(
    client: AsyncClient, admin_auth_header: dict, unseen_ids
) -> None:
    private, draft, _, _ = unseen_ids

    for dataset_id in (private, draft):
        resp = await client.get(
            f"/tiles/token/{dataset_id}/", headers=admin_auth_header
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["kind"] == "raster"


async def test_a_dead_credential_is_refused_with_401_alike(
    client: AsyncClient, unseen_ids
) -> None:
    """An unresolvable credential never degrades to the anonymous answer."""
    private, _, _, missing = unseen_ids
    headers = {"Authorization": "Bearer not-a-real-token"}

    for url in (_tile_url, lambda dataset_id: f"/tiles/token/{dataset_id}/"):
        answers = {
            dataset_id: _answer(await client.get(url(dataset_id), headers=headers))
            for dataset_id in (private, missing)
        }
        assert answers[private] == answers[missing], answers
        assert answers[missing][0] == 401, answers
        assert answers[missing][2] == "Bearer", answers
