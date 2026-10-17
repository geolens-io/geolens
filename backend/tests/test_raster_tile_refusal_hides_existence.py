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


@pytest.fixture
async def non_raster_ids(test_db_session):
    """Ids whose raster lookup fails with a detail only an existing id produces."""
    owner = await get_user_id(test_db_session, settings.geolens_admin_username)
    private_vector = await create_dataset(
        test_db_session, created_by=owner, visibility="private"
    )
    draft_vector = await create_dataset(
        test_db_session, created_by=owner, record_status="draft"
    )
    private_bare_raster = await create_raster_dataset(
        test_db_session, created_by=owner, visibility="private"
    )
    public_vector = await create_dataset(test_db_session, created_by=owner)
    return {
        "private_vector": private_vector.id,
        "draft_vector": draft_vector.id,
        "private_bare_raster": private_bare_raster.id,
        "public_vector": public_vector.id,
    }


async def test_a_stranger_cannot_tell_an_unreadable_non_raster_from_a_missing_id(
    client: AsyncClient,
    non_raster_ids,
    people,  # noqa: F811
    mint_key,  # noqa: F811
) -> None:
    _, stranger_id = people
    key, _ = await mint_key(stranger_id)
    headers = {"X-Api-Key": key}
    ids = {
        **{k: v for k, v in non_raster_ids.items() if k != "public_vector"},
        "missing": uuid.uuid4(),
    }

    answers = {
        name: _answer(await client.get(_tile_url(dataset_id), headers=headers))
        for name, dataset_id in ids.items()
    }

    assert all(answer == answers["missing"] for answer in answers.values()), answers
    assert answers["missing"][0] == 404, answers
    assert answers["missing"][1]["detail"] == "Dataset not found", answers


async def test_a_reader_keeps_the_specific_lookup_detail(
    client: AsyncClient,
    admin_auth_header: dict,
    non_raster_ids,
    people,  # noqa: F811
    mint_key,  # noqa: F811
) -> None:
    _, stranger_id = people
    key, _ = await mint_key(stranger_id)
    cases = [
        ("public_vector", {"X-Api-Key": key}, "Not a raster dataset"),
        ("private_vector", admin_auth_header, "Not a raster dataset"),
        ("draft_vector", admin_auth_header, "Not a raster dataset"),
        ("private_bare_raster", admin_auth_header, "No raster asset"),
    ]

    for name, headers, detail in cases:
        resp = await client.get(_tile_url(non_raster_ids[name]), headers=headers)
        assert resp.status_code == 404, (name, resp.text)
        assert resp.json()["detail"] == detail, (name, resp.text)


async def test_a_denying_permission_extension_hides_the_lookup_detail(
    client: AsyncClient, admin_auth_header: dict, non_raster_ids, monkeypatch
) -> None:
    """An overlay that denies the caller decides, public datasets included."""
    import app.platform.extensions as extensions

    class _DenyEveryone:
        async def can_access_dataset(self, *args, **kwargs):
            return False

    monkeypatch.setitem(extensions._extensions, "permission", _DenyEveryone())
    ids = {**non_raster_ids, "missing": uuid.uuid4()}

    answers = {
        name: _answer(
            await client.get(_tile_url(dataset_id), headers=admin_auth_header)
        )
        for name, dataset_id in ids.items()
    }

    assert all(answer == answers["missing"] for answer in answers.values()), answers
    assert answers["missing"][1]["detail"] == "Dataset not found", answers


_DEAD_CREDENTIALS = {
    "bearer": {"headers": {"Authorization": "Bearer not-a-real-token"}},
    "key_header": {"headers": {"X-Api-Key": "gl_not-a-real-key"}},
    "key_query": {"params": {"api_key": "gl_not-a-real-key"}},
}


def _with(extra: dict, *, headers: dict | None = None, params: dict | None = None):
    return {
        "headers": {**(headers or {}), **extra.get("headers", {})},
        "params": {**(params or {}), **extra.get("params", {})},
    }


@pytest.mark.parametrize("credential", sorted(_DEAD_CREDENTIALS))
async def test_a_valid_embed_token_gets_the_lookup_answer_despite_a_dead_credential(
    client: AsyncClient, admin_auth_header: dict, test_db_session, credential: str
) -> None:
    """The embed capability authorizes on its own, as on the success path."""
    from tests.test_embed_tokens import _create_map_with_layer

    owner = await get_user_id(test_db_session, settings.geolens_admin_username)
    vector = await create_dataset(
        test_db_session, created_by=owner, visibility="private"
    )
    map_obj, _ = await _create_map_with_layer(
        test_db_session, client, admin_auth_header, vector, created_by=owner
    )
    minted = await client.post(
        f"/maps/{map_obj.id}/embed-tokens/",
        json={"name": "raster lookup"},
        headers=admin_auth_header,
    )
    assert minted.status_code == 201, minted.text
    embed = {"X-Embed-Token": minted.json()["raw_token"]}

    alone = await client.get(_tile_url(vector.id), headers=embed)
    with_dead = await client.get(
        _tile_url(vector.id), **_with(_DEAD_CREDENTIALS[credential], headers=embed)
    )

    assert alone.status_code == 404, alone.text
    assert alone.json()["detail"] == "Not a raster dataset", alone.text
    assert _answer(with_dead) == _answer(alone), with_dead.text


@pytest.fixture
async def bare_rasters(test_db_session):
    """A public, published raster and a private one, both without an image."""
    owner = await get_user_id(test_db_session, settings.geolens_admin_username)
    public = await create_raster_dataset(test_db_session, created_by=owner)
    private = await create_raster_dataset(
        test_db_session, created_by=owner, visibility="private"
    )
    return public, private


@pytest.mark.parametrize("credential", [None, *sorted(_DEAD_CREDENTIALS)])
async def test_a_valid_signature_gets_the_lookup_answer(
    client: AsyncClient, bare_rasters, credential: str | None
) -> None:
    """A signed template authorizes on its own, as on the success path."""
    for raster in bare_rasters:
        signed = _signed(raster.id, publication_version=raster.publication_version)
        extra = _DEAD_CREDENTIALS[credential] if credential else {}

        resp = await client.get(_tile_url(raster.id), **_with(extra, params=signed))

        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"] == "No raster asset", resp.text


async def test_a_forged_signature_on_a_bare_private_raster_is_still_refused(
    client: AsyncClient, bare_rasters
) -> None:
    _, private = bare_rasters
    forged = {**_signed(private.id), "sig": "0" * 64}

    resp = await client.get(_tile_url(private.id), params=forged)

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "Invalid or expired signature", resp.text
